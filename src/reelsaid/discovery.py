"""Resolve submitted sources to unique, ordered video work."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlsplit

from apify_client.errors import ApifyApiError, ApifyClientError

from .contracts import FilterOptions, InputPlan, InputRef, JsonObject, Outcome, RunContext, VideoMetadata, VideoRef
from .input import classify_url
from .instagram import BASE, CODE, InstagramError, object_value, post_shortcode, records


DATASET_PAGE_SIZE = 250


@dataclass(frozen=True)
class DiscoveryCursor:
    source_index: int
    profile_cursor: tuple[str, str] | None = None
    dataset_offset: int = 0
    profile_offset: int = 0


@dataclass(frozen=True)
class Discovery:
    videos: tuple[VideoRef, ...]
    input_outcomes: tuple[Outcome[None], ...]
    video_outcomes: tuple[Outcome[VideoRef], ...]
    duplicates: int
    continuation: DiscoveryCursor | None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _id(value: object) -> str | None:
    return str(value) if type(value) is int else _text(value)


def _count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _duration(value: object) -> float | None:
    return float(value) if type(value) in (int, float) and 0 < value < float("inf") else None


def _published(value: object) -> datetime | None:
    if type(value) in (int, float):
        try:
            return datetime.fromtimestamp(value, UTC)
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _cdn(value: object) -> str | None:
    classified = classify_url(value)
    return classified[1] if classified and classified[0] == "cdn" else None


def _asset_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}{parts.path}"


def _variant(value: object) -> str | None:
    return next((url for entry in records(value) if (url := _cdn(entry.get("url")))), None)


def _audio_url(node: JsonObject) -> str | None:
    clips = object_value(node.get("clips_metadata"))
    original = object_value(clips.get("original_sound_info"))
    # Music-preview URLs describe a soundtrack. Only use an explicit media audio track.
    return _cdn(node.get("audio_url")) or _cdn(node.get("audioUrl")) or _cdn(original.get("audio_url"))


def _audio_metadata(node: JsonObject) -> JsonObject | None:
    clips = object_value(node.get("clips_metadata"))
    asset = object_value(object_value(clips.get("music_info")).get("music_asset_info"))
    original = object_value(clips.get("original_sound_info"))
    if not (asset or original):
        return None
    return {
        "title": _text(asset.get("title")) or _text(original.get("original_audio_title")),
        "artist": _text(asset.get("display_artist")),
        "id": _id(asset.get("audio_cluster_id") or original.get("audio_asset_id")),
        "isOriginal": not bool(asset),
    }


def _canonical(parent: JsonObject, shortcode: str) -> str:
    product = parent.get("product_type")
    route = "reel" if product == "clips" else "tv" if product == "igtv" else "p"
    return f"{BASE}/{route}/{shortcode}/"


def _videos_from_post(
    node: JsonObject, code: str, ref: InputRef, *, profile: str | None = None,
    listing: JsonObject | None = None, profile_id: str | None = None,
) -> list[VideoRef]:
    listing = listing or {}
    carousel = node.get("carousel_media")
    entries = enumerate(carousel) if isinstance(carousel, list) else [(None, node)]
    owner = object_value(node.get("user") or node.get("owner"))
    parent_image = _variant(object_value(node.get("image_versions2")).get("candidates"))
    pinned_users = listing.get("clips_tab_pinned_user_ids")
    pinned = (profile_id in {str(user) for user in pinned_users}) if profile_id and isinstance(pinned_users, list) else None

    def count(field: str) -> int | None:
        value = _count(node.get(field))
        return value if value is not None else _count(listing.get(field))

    videos = []
    for position, child in entries:
        if not isinstance(child, dict):
            continue
        variants = tuple(dict.fromkeys(
            url for variant in records(child.get("video_versions")) if (url := _cdn(variant.get("url")))
        ))
        video_url = variants[0] if variants else _cdn(child.get("video_url"))
        audio_url = _audio_url(child)
        if not video_url and not audio_url and child.get("media_type") != 2 and child.get("is_video") is not True:
            continue
        child_id = _id(child.get("pk") or child.get("id"))
        identity = code if position is None else f"{code}:{child_id or position}"
        videos.append(VideoRef(identity, VideoMetadata(
            post_url=_canonical(node, code),
            shortcode=code,
            media_id=child_id,
            publisher=_text(owner.get("username")),
            discovery_profiles=(profile,) if profile else (),
            coauthors=tuple(name for author in records(node.get("coauthor_producers")) if (name := _text(author.get("username")))),
            caption=_text(object_value(node.get("caption")).get("text")) or _text(node.get("caption")),
            published_at=_published(node.get("taken_at")),
            duration_seconds=_duration(child.get("video_duration")),
            cover_url=_variant(object_value(child.get("image_versions2")).get("candidates")) or parent_image,
            audio=_audio_metadata(child) or _audio_metadata(node),
            view_count=count("view_count"),
            play_count=count("play_count"),
            like_count=count("like_count"),
            comment_count=count("comment_count"),
            carousel_position=position,
            pinned=pinned,
        ), (ref,), video_url, audio_url, variants[1:]))
    return videos


def _merge(first: VideoRef, second: VideoRef) -> VideoRef:
    left, right = first.metadata, second.metadata
    pinned = True if True in (left.pinned, right.pinned) else left.pinned if left.pinned is not None else right.pinned
    return replace(
        first,
        provenance=tuple(dict.fromkeys((*first.provenance, *second.provenance))),
        video_url=first.video_url or second.video_url,
        audio_url=first.audio_url or second.audio_url,
        metadata=replace(
            left,
            discovery_profiles=tuple(dict.fromkeys((*left.discovery_profiles, *right.discovery_profiles))),
            view_count=left.view_count if left.view_count is not None else right.view_count,
            play_count=left.play_count if left.play_count is not None else right.play_count,
            like_count=left.like_count if left.like_count is not None else right.like_count,
            comment_count=left.comment_count if left.comment_count is not None else right.comment_count,
            pinned=pinned,
        ),
    )


def _views(meta: VideoMetadata) -> int | None:
    return meta.view_count if meta.view_count is not None else meta.play_count


def _filter(video: VideoRef, filters: FilterOptions, now: datetime) -> str | None:
    meta = video.metadata
    if filters.skip_pinned and meta.discovery_profiles:
        if meta.pinned is None:
            return "FILTER_METADATA_MISSING"
        if meta.pinned:
            return "PINNED"
    if filters.date_from or filters.date_to or filters.last_days:
        if meta.published_at is None:
            return "FILTER_METADATA_MISSING"
        published_date = meta.published_at.date()
        if (
            (filters.date_from and published_date < filters.date_from)
            or (filters.date_to and published_date > filters.date_to)
            or (filters.last_days and (now - meta.published_at).total_seconds() > filters.last_days * 86400)
        ):
            return "OUTSIDE_DATE_RANGE"
    for minimum, value, code in (
        (filters.min_views, _views(meta), "BELOW_MIN_VIEWS"),
        (filters.min_likes, meta.like_count, "BELOW_MIN_LIKES"),
    ):
        if minimum is not None:
            if value is None:
                return "FILTER_METADATA_MISSING"
            if value < minimum:
                return code
    if meta.duration_seconds is not None:
        if filters.min_duration_seconds is not None and meta.duration_seconds < filters.min_duration_seconds:
            return "BELOW_MIN_DURATION"
        if filters.max_duration_seconds is not None and meta.duration_seconds > filters.max_duration_seconds:
            return "DURATION_LIMIT"
    return None


def _sort_key(video: VideoRef, order: str) -> tuple:
    meta = video.metadata
    date = -meta.published_at.timestamp() if meta.published_at else float("inf")
    views = _views(meta)
    identity = (meta.shortcode or video.video_id, meta.carousel_position if meta.carousel_position is not None else -1)
    if order == "mostViewed":
        return (-views if views is not None else float("inf"), date, *identity)
    return date, *identity


class _DiscoveryRun:
    def __init__(self, context: RunContext, outcomes: tuple[Outcome[None], ...]):
        self.context = context
        self.outcomes = list(outcomes)
        self.posts: dict[str, JsonObject | InstagramError] = {}
        self.videos: dict[str, VideoRef] = {}
        self.assets: dict[str, str] = {}
        self.duplicates = 0

    def error(self, ref: InputRef, code: str, retryable: bool = False) -> None:
        self.outcomes.append(Outcome("failed", code, retryable, input_ref=ref))

    def add(self, video: VideoRef, *extra_assets: str) -> None:
        identity = video.video_id
        urls = {
            url for url in (video.video_url, video.audio_url, *video.alternate_video_urls, *extra_assets) if url
        }
        assets = {_asset_key(url) for url in urls}
        for asset in assets:
            prior_identity = self.assets.get(asset)
            if prior_identity is None or prior_identity == identity:
                continue
            if prior_identity.startswith("cdn:"):
                prior = self.videos.pop(prior_identity, None)
                if prior:
                    video = _merge(video, prior)
                    self.duplicates += 1
                    for key, mapped in self.assets.items():
                        if mapped == prior_identity:
                            self.assets[key] = identity
        if identity in self.videos:
            self.duplicates += 1
            video = _merge(self.videos[identity], video)
        self.videos[identity] = video
        for asset in assets:
            self.assets.setdefault(asset, identity)

    def standalone(self, url: str, ref: InputRef, *, audio: bool = False) -> None:
        asset = _asset_key(url)
        identity = self.assets.get(asset) or f"cdn:{sha256(asset.encode()).hexdigest()}"
        if video := self.videos.get(identity):
            self.duplicates += 1
            self.videos[identity] = replace(video, provenance=tuple(dict.fromkeys((*video.provenance, ref))))
        else:
            self.add(VideoRef(
                identity, VideoMetadata(), (ref,), audio_url=url if audio else None, video_url=None if audio else url,
            ))

    async def _post(
        self, code: str, ref: InputRef, *, profile: str | None = None,
        listing: JsonObject | None = None, profile_id: str | None = None,
    ) -> list[VideoRef]:
        if not CODE.fullmatch(code):
            raise InstagramError("INVALID_SHORTCODE")
        if code not in self.posts:
            try:
                self.posts[code] = await self.context.instagram.post(code)
            except InstagramError as error:
                self.posts[code] = error
        result = self.posts[code]
        if isinstance(result, InstagramError):
            raise result
        videos = _videos_from_post(result, code, ref, profile=profile, listing=listing, profile_id=profile_id)
        if not videos:
            raise InstagramError("NO_VIDEO")
        return videos

    async def add_post(
        self, value: str, ref: InputRef, *, is_url: bool = False, profile: str | None = None,
        listing: JsonObject | None = None, profile_id: str | None = None,
    ) -> None:
        try:
            code = await self._code(value) if is_url else value
            for video in await self._post(code, ref, profile=profile, listing=listing, profile_id=profile_id):
                self.add(video)
        except InstagramError as error:
            self.error(ref, error.code, error.retryable)

    async def _code(self, url: str) -> str:
        return post_shortcode(url) or await self.context.instagram.resolve_share(url)

    async def dataset_item(self, item: JsonObject, ref: InputRef) -> None:
        meta = object_value(item.get("metadata"))
        code = _text(meta.get("shortcode")) or _text(item.get("shortcode") or item.get("shortCode"))
        post_url = None
        video_url = _cdn(item.get("videoUrl") or item.get("video_url") or item.get("webVideoUrl"))
        audio_url = _cdn(item.get("audioUrl") or item.get("audio_url"))
        for key in ("postUrl", "reelUrl", "canonicalUrl", "url", "inputUrl"):
            url = classify_url(item.get(key) or meta.get(key))
            if url and url[0] == "post":
                post_url = post_url or url[1]
            elif url and url[0] == "cdn":
                video_url = video_url or url[1]
        post_error = None
        videos = []
        try:
            if post_url:
                code = await self._code(post_url)
            if code:
                videos = await self._post(code, ref)
        except InstagramError as error:
            post_error = error

        if videos:
            media_id = _id(meta.get("mediaId") or item.get("mediaId"))
            position = meta.get("carouselPosition", item.get("carouselPosition"))
            selected = [
                video for video in videos if
                (media_id is not None and media_id == video.metadata.media_id)
                or (type(position) is int and position == video.metadata.carousel_position)
            ]
            matched = selected[0] if len(selected) == 1 else videos[0] if len(videos) == 1 else None
            if matched is None and video_url:
                asset = _asset_key(video_url)
                matching_assets = [
                    video for video in videos if any(
                        _asset_key(candidate) == asset
                        for candidate in (video.video_url, *video.alternate_video_urls) if candidate
                    )
                ]
                if len(matching_assets) == 1:
                    matched = matching_assets[0]
            for video in videos:
                if video == matched:
                    self.add(replace(video, video_url=video.video_url or video_url, audio_url=video.audio_url or audio_url),
                             *(url for url in (video_url, audio_url) if url))
                else:
                    self.add(video)
            return

        asset_url = video_url or audio_url
        if asset_url and (not post_error or post_error.code in {
            "TEMPORARILY_BLOCKED", "INSTAGRAM_UNAVAILABLE", "CONTENT_UNAVAILABLE",
        }):
            asset = _asset_key(asset_url)
            identity = self.assets.get(asset) or f"cdn:{sha256(asset.encode()).hexdigest()}"
            existing = self.videos.get(identity)
            metadata = existing.metadata if existing else VideoMetadata(post_url=post_url, shortcode=code)
            self.add(VideoRef(identity, metadata, (ref,), video_url, audio_url))
        elif post_error:
            self.error(ref, post_error.code, post_error.retryable)
        else:
            self.error(ref, "INVALID_DATASET_ITEM")

    async def dataset(self, identifier: str, ref: InputRef, offset: int) -> int | None:
        dataset = self.context.apify.dataset(identifier)
        while True:
            if self.context.expired():
                return offset
            try:
                page = await dataset.list_items(offset=offset, limit=DATASET_PAGE_SIZE)
            except ApifyApiError as error:
                code = {
                    401: "DATASET_ACCESS_DENIED", 403: "DATASET_ACCESS_DENIED", 404: "DATASET_UNAVAILABLE",
                }.get(error.status_code, "DATASET_READ_FAILED")
                self.error(ref, code, error.status_code == 429 or error.status_code >= 500)
                return None
            except ApifyClientError:
                self.error(ref, "DATASET_READ_FAILED", True)
                return None
            if not page.items:
                if offset == 0:
                    self.error(ref, "EMPTY_DATASET")
                return None
            for item in page.items:
                if self.context.expired():
                    return offset
                item_ref = replace(ref, item_index=offset)
                if isinstance(item, dict):
                    await self.dataset_item(item, item_ref)
                else:
                    self.error(item_ref, "INVALID_DATASET_ITEM")
                offset += 1
            if offset >= page.total:
                return None

    async def profile(
        self, name: str, ref: InputRef, cursor: tuple[str, str] | None, offset: int,
    ) -> tuple[tuple[str, str] | None, int] | None:
        seen_cursors = set()
        while True:
            if self.context.expired():
                return cursor, offset
            if cursor in seen_cursors:
                self.error(ref, "PROFILE_PAGINATION_UNAVAILABLE", True)
                return None
            seen_cursors.add(cursor)
            try:
                page = await self.context.instagram.profile(name, cursor)
            except InstagramError as error:
                self.error(ref, error.code, error.retryable)
                return None
            if not page.entries and cursor is None and not page.cursor:
                self.error(ref, "EMPTY_PROFILE")
            for entry in page.entries[offset:]:
                if self.context.expired():
                    return cursor, offset
                entry_ref = replace(ref, item_index=offset) if cursor is None else ref
                code = entry["code"]
                await self.add_post(code, entry_ref, profile=name, listing=entry, profile_id=page.profile_id)
                offset += 1
            if not page.cursor:
                return None
            cursor, offset = page.cursor, 0


async def discover(
    plan: InputPlan, context: RunContext, *, continuation: DiscoveryCursor | None = None,
) -> Discovery:
    run = _DiscoveryRun(context, plan.outcomes)
    cursor = None
    start = continuation.source_index if continuation else 0
    if not plan.valid_options:
        return Discovery((), plan.outcomes, (), 0, None)
    for index, source in enumerate(plan.sources[start:], start):
        position = continuation if index == start and continuation else DiscoveryCursor(index)
        if context.expired():
            cursor = position
            break
        ref, value = source.ref, source.value
        if source.kind == "profile":
            pending = await run.profile(value, ref, position.profile_cursor, position.profile_offset)
            if pending is not None:
                cursor = DiscoveryCursor(index, profile_cursor=pending[0], profile_offset=pending[1])
                break
        elif source.kind == "dataset":
            pending = await run.dataset(value, ref, position.dataset_offset)
            if pending is not None:
                cursor = DiscoveryCursor(index, dataset_offset=pending)
                break
        elif source.kind == "dataset_item":
            await run.dataset_item(value, ref)
        elif source.kind == "cdn":
            run.standalone(value, ref)
        else:
            await run.add_post(value, ref, is_url=source.kind == "post")

    videos, skipped = [], []
    for video in sorted(run.videos.values(), key=lambda video: _sort_key(video, plan.filters.sort)):
        if reason := _filter(video, plan.filters, context.now):
            skipped.append(Outcome("skipped", reason, value=video))
        else:
            videos.append(video)
    return Discovery(tuple(videos), tuple(run.outcomes), tuple(skipped), run.duplicates, cursor)
