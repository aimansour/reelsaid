import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from apify_client.errors import ApifyApiError

from reelsaid.contracts import RunContext
from reelsaid.discovery import discover
from reelsaid.input import parse_input
from reelsaid.instagram import InstagramError, ProfilePage, parse_post


CLOUD = json.loads(Path("tests/fixtures/instagram/cloud-retrieval-summary.json").read_text())
EXAMPLE = "DS46KJNjva9"
CAROUSEL = "Ddm6E9OGt5D"
COLLAB = "DfaaAP7BvIu"
PERSONAL = "CsuFa_Mga41"
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def cdn(code, signature="fresh"):
    return f"https://test.cdninstagram.com/v/{code}.mp4?oh={signature}"


def post(code, *, owner="original", **fields):
    return {
        "code": code,
        "product_type": "clips",
        "media_type": 2,
        "video_versions": [{"url": cdn(code)}],
        "video_duration": 8.5,
        "user": {"username": owner},
        **fields,
    }


class FakeInstagram:
    def __init__(self, posts, pages=None):
        self.posts = posts
        self.pages = pages or {}
        self.requests = []

    async def post(self, code):
        self.requests.append(code)
        value = self.posts[code]
        if isinstance(value, InstagramError):
            raise value
        return value

    async def profile(self, username, cursor=None):
        return self.pages[username, cursor]


class FakeApify:
    def __init__(self, pages=None):
        self.pages = pages or {}

    def dataset(self, dataset_id):
        async def list_items(*, offset, limit):
            result = self.pages[dataset_id, offset]
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(items=result, total=len(result) + offset)

        return SimpleNamespace(list_items=list_items)


def resolve(raw, instagram, datasets=None, *, expired=lambda: False, continuation=None):
    return asyncio.run(discover(
        parse_input(raw), RunContext(instagram, FakeApify(datasets), NOW, expired), continuation=continuation
    ))


def test_mixed_sources_converge():
    ig = FakeInstagram({EXAMPLE: post(EXAMPLE)})
    input_data = {
        "startUrls": [
            f"https://www.instagram.com/reel/{EXAMPLE}/?igsh=share",
            f"https://www.instagram.com/p/{EXAMPLE}/",
            f"https://www.instagram.com/tv/{EXAMPLE}/",
            cdn(EXAMPLE, "older"),
        ],
        "shortcodes": [EXAMPLE],
        "datasetId": "sourceDataset",
        "datasetItems": [{"postUrl": f"https://www.instagram.com/p/{EXAMPLE}/", "audioUrl": cdn("audio")}],
    }
    result = resolve(input_data, ig, {("sourceDataset", 0): [{"shortcode": EXAMPLE}]})
    video, = result.videos
    assert video.video_id == EXAMPLE
    assert video.video_url == cdn(EXAMPLE)
    assert video.audio_url == cdn("audio")
    assert video.metadata.post_url == f"https://www.instagram.com/reel/{EXAMPLE}/"
    assert len(video.provenance) == 7 and result.duplicates == 6
    assert ig.requests == [EXAMPLE]


def test_media_dash_audio_keeps_signed_url_and_excludes_video_and_other_hosts():
    manifest = """<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
        <AdaptationSet contentType="video"><Representation bandwidth="999999">
            <BaseURL>https://test.cdninstagram.com/video.mp4</BaseURL>
        </Representation></AdaptationSet>
        <AdaptationSet mimeType="audio/mp4">
            <Representation bandwidth="100000"><BaseURL>https://example.org/high.m4a</BaseURL></Representation>
            <Representation bandwidth="32000"><BaseURL>https://test.cdninstagram.com/low.m4a</BaseURL></Representation>
            <Representation bandwidth="64000"><BaseURL>https://test.cdninstagram.com/high.m4a?oh=abc&amp;oe=abc</BaseURL></Representation>
        </AdaptationSet>
    </Period></MPD>"""
    result = resolve({"shortcodes": [EXAMPLE]}, FakeInstagram({EXAMPLE: post(EXAMPLE, video_dash_manifest=manifest)}))
    video, = result.videos
    assert video.dash_audio_url == "https://test.cdninstagram.com/high.m4a?oh=abc&oe=abc"
    assert video.audio_url is None


def test_profile_and_carousel():
    expected = CLOUD[f"post-graphql-{CAROUSEL}"]["targetChildChecks"]
    child_by_position = {row["position"]: row["id"] for row in expected}
    raw_carousel = post(CAROUSEL, owner="publisher", product_type="carousel", media_type=8, video_versions=[],
                        carousel_media=[
                            {"pk": child_by_position.get(i, str(i)), "media_type": 1, "video_versions": []}
                            if i not in child_by_position
                            else post(f"child{i}", pk=child_by_position[i])
                            for i in range(11)
                        ])
    listing = CLOUD["guest-clips-first-nasa"]
    first = ProfilePage(listing["profilePk"], ({"code": CAROUSEL},), ("relay", "page2"))
    second = ProfilePage(listing["profilePk"], ({"code": COLLAB, "play_count": 34},))
    ig = FakeInstagram({
        CAROUSEL: raw_carousel,
        COLLAB: post(COLLAB, owner=CLOUD[f"post-graphql-{COLLAB}"]["targetPublisher"],
                     coauthor_producers=[{"username": "nasa"}]),
        PERSONAL: post(PERSONAL, owner="astro_kjell"),
    }, {("nasa", None): first, ("nasa", first.cursor): second,
        ("astro_kjell", None): ProfilePage("2074163374", ({"code": PERSONAL},))})
    result = resolve({"profiles": ["nasa", "astro_kjell"]}, ig)
    children = [video for video in result.videos if video.metadata.shortcode == CAROUSEL]
    assert [(video.metadata.carousel_position, video.metadata.media_id) for video in children] == [
        (entry["position"], entry["id"]) for entry in expected
    ]
    assert {video.metadata.publisher for video in children} == {"publisher"}
    collab = next(video for video in result.videos if video.video_id == COLLAB)
    assert collab.metadata.publisher == "nasajohnson"
    assert collab.metadata.discovery_profiles == ("nasa",)
    assert collab.metadata.coauthors == ("nasa",)
    assert collab.metadata.play_count == 34 and collab.metadata.view_count is None
    assert any(video.metadata.publisher == "astro_kjell" for video in result.videos)


def test_filters_and_order():
    def time(day):
        return int(datetime(2026, 11, day, tzinfo=UTC).timestamp())

    posts = {
        "B": post("B", taken_at=time(7), view_count=80, like_count=6),
        "A": post("A", taken_at=time(7), view_count=80, like_count=6),
        "C": post("C", taken_at=time(6), view_count=90, like_count=6),
        "D": post("D", taken_at=time(7), view_count=95, like_count=6),
        "old": post("old", taken_at=time(2), view_count=100, like_count=6),
        "future": post("future", taken_at=time(8), view_count=100, like_count=6),
        "views": post("views", taken_at=time(7), view_count=3, like_count=6),
        "likes": post("likes", taken_at=time(7), view_count=100, like_count=1),
        "duration": post("duration", taken_at=time(7), view_count=100, like_count=6, video_duration=99),
        "unknown": post("unknown", taken_at=time(7), like_count=6),
        "inspect": post("inspect", taken_at=time(7), view_count=60, like_count=6, video_duration=None),
    }
    rows = tuple({"code": code, "clips_tab_pinned_user_ids": ["owner"] if code == "D" else []} for code in posts)
    ig = FakeInstagram(posts, {("nasa", None): ProfilePage("owner", rows)})
    raw = {"profiles": ["nasa"], "dateFrom": "2026-11-05", "dateTo": "2026-11-07", "lastDays": 3,
           "minViews": 20, "minLikes": 5, "minDurationSeconds": 2, "maxDurationSeconds": 15, "skipPinned": True}

    newest = resolve(raw, ig)
    popular = resolve({**raw, "sort": "mostViewed"}, ig)
    assert [v.video_id for v in newest.videos] == ["A", "B", "inspect", "C"]
    assert [v.video_id for v in popular.videos] == ["C", "A", "B", "inspect"]
    assert [v.value.video_id for v in newest.video_outcomes if v.error_code == "FILTER_METADATA_MISSING"] == ["unknown"]
    assert len(newest.video_outcomes) == 7
    assert next(v for v in newest.videos if v.video_id == "inspect").metadata.duration_seconds is None


def test_discovery_errors_are_rows():
    ig = FakeInstagram({
        "blocked": InstagramError("TEMPORARILY_BLOCKED", retryable=True),
        "private": InstagramError("CONTENT_PRIVATE"),
        "removed": InstagramError("CONTENT_REMOVED"),
        "unknown": post("unknown"),
    })
    response = SimpleNamespace(status_code=403, text='{"error":{"type":"forbidden","message":"denied"}}', url="test", json=lambda: {"error": {"type": "forbidden", "message": "denied"}})
    result = resolve({"shortcodes": list(ig.posts), "datasetId": "privateDataset"}, ig,
                     {("privateDataset", 0): ApifyApiError(response, 1)})
    assert {err.error_code: err.retryable for err in result.input_outcomes} == {
        "TEMPORARILY_BLOCKED": True, "CONTENT_PRIVATE": False, "CONTENT_REMOVED": False,
        "DATASET_ACCESS_DENIED": False,
    }
    assert result.videos[0].metadata.view_count is None
    assert result.videos[0].metadata.like_count is None


def test_continuation_replays_only_the_interrupted_profile_page():
    ig = FakeInstagram({"A": post("A"), "B": post("B")}, {
        ("nasa", None): ProfilePage("owner", ({"code": "A"},), ("relay", "second")),
        ("nasa", ("relay", "second")): ProfilePage("owner", ({"code": "B"},)),
    })
    raw = {"profiles": ["nasa"]}
    expired = lambda: bool(ig.requests)
    first = resolve(raw, ig, expired=expired)
    second = resolve(raw, ig, continuation=first.continuation)
    assert [v.video_id for v in first.videos] == ["A"]
    assert [v.video_id for v in second.videos] == ["B"]
    assert second.continuation is None


def test_post_parser_resolves_the_exact_child_on_both_routes():
    carousel = post(CAROUSEL, media_type=8, video_versions=[], carousel_media=[post("video", pk="42")])
    payload = {"data": {"items": [post("unrelated"), carousel]}}
    text = json.dumps(payload)
    embedded = f'<script type="application/json">{text}</script>'
    assert parse_post(text, CAROUSEL) == parse_post(embedded, CAROUSEL) == carousel
    assert parse_post(text, "unknown") is None


def test_cdn_alias_and_failed_post_hydration_keep_single_outcomes():
    ig = FakeInstagram({
        EXAMPLE: post(EXAMPLE, video_versions=[{"url": cdn(EXAMPLE)}, {"url": cdn("alternate")}]),
        "blocked": InstagramError("TEMPORARILY_BLOCKED", retryable=True),
    })
    raw = {
        "startUrls": [cdn("alternate", "old")],
        "shortcodes": [EXAMPLE],
        "datasetItems": [{"postUrl": "https://www.instagram.com/reel/blocked/", "videoUrl": cdn("dataset")}],
    }
    result = resolve(raw, ig)
    assert result.duplicates == 1
    assert len(result.videos) == 2
    assert result.videos[0].video_id == EXAMPLE
    assert result.videos[0].video_url == cdn(EXAMPLE)
    assert any(v.metadata.post_url == "https://www.instagram.com/reel/blocked/" for v in result.videos)
    assert not result.input_outcomes


def test_empty_pinned_ids_are_known_unpinned_without_profile_id():
    ig = FakeInstagram({"B": post("B")}, {
        ("nasa", None): ProfilePage("owner", (), ("relay", "second")),
        ("nasa", ("relay", "second")): ProfilePage(None, ({"code": "B", "clips_tab_pinned_user_ids": []},)),
    })
    result = resolve({"profiles": ["nasa"], "skipPinned": True}, ig)
    assert len(result.videos) == 1 and result.videos[0].metadata.pinned is False
