"""Inspect Instagram CDN assets with validated redirects and local stream metadata."""

import asyncio
import json
import re
from collections.abc import Iterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qs, urljoin, urlsplit

from curl_cffi.requests import AsyncSession, RequestsError, Response

from .contracts import CaptionCandidate, InputRef, Outcome, RunContext, VideoRef
from .discovery import videos_from_post
from .input import classify_url
from .instagram import InstagramError


PROBE_BYTES = 64 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
LOCAL_MEDIA_FORMATS = "mov,mp3,aac,wav,flac,ogg,matroska,webm"
REDIRECTS = {301, 302, 303, 307, 308}


class MediaError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class MediaAsset:
    url: str
    duration_seconds: Decimal
    has_audio: bool
    has_video: bool
    source_bytes: int
    file: Path | None = None


@dataclass(frozen=True)
class MediaPlan:
    video_id: str
    ref: VideoRef
    duration_seconds: Decimal
    video: MediaAsset | None
    audio: MediaAsset | None
    captions: tuple[CaptionCandidate, ...]

    def close(self) -> None:
        for path in {asset.file for asset in (self.video, self.audio) if asset and asset.file}:
            path.unlink(missing_ok=True)


def _mp4_headers(data: bytes) -> Iterator[tuple[bytes, int, int]]:
    offset = 0
    while len(data) - offset >= 8:
        length = int.from_bytes(data[offset:offset + 4])
        name = data[offset + 4:offset + 8]
        header = 8
        if length == 1:
            if len(data) - offset < 16:
                return
            length = int.from_bytes(data[offset + 8:offset + 16])
            header = 16
        if length < header:
            return
        yield name, offset + header, offset + length
        offset += length


def _mp4_boxes(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    for name, start, end in _mp4_headers(data):
        if end > len(data):
            return
        yield name, data[start:end]


def _mp4_index_end(data: bytes) -> int | None:
    if data[4:8] != b"ftyp":
        return None
    return next((end for name, _, end in _mp4_headers(data) if name == b"moov"), None)


def _contains_complete_mp4_index(data: bytes) -> bool:
    if data[4:8] != b"ftyp":
        return False
    for name, body in _mp4_boxes(data):
        if name == b"moov":
            boxes = {name for name, _ in _mp4_boxes(body)}
            return {b"mvhd", b"trak"}.issubset(boxes) and b"mvex" not in boxes
    return False


async def _probe(path: Path) -> tuple[Decimal, bool, bool]:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", LOCAL_MEDIA_FORMATS,
            "-show_entries", "format=duration:stream=codec_type:stream_disposition=attached_pic",
            "-of", "json", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        raise MediaError("MEDIA_INSPECTION_FAILED", retryable=True) from error
    try:
        async with asyncio.timeout(10):
            data, _ = await process.communicate()
    except (TimeoutError, asyncio.CancelledError) as error:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            raise MediaError("MEDIA_INSPECTION_FAILED", retryable=True) from error
        raise
    if process.returncode == 0:
        try:
            info = json.loads(data)
            duration = Decimal(info.get("format", {}).get("duration", "NaN"))
            streams = info.get("streams", [])
            audio = any(stream.get("codec_type") == "audio" for stream in streams)
            video = any(
                stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
                for stream in streams
            )
            if duration.is_finite() and duration > 0 and (audio or video):
                return duration, audio, video
        except (ValueError, InvalidOperation):
            pass
    raise MediaError("MEDIA_DURATION_UNAVAILABLE")


def _expiry_error(url: str, status: int, now: datetime) -> MediaError:
    if status in {403, 404, 410}:
        expiry = parse_qs(urlsplit(url).query).get("oe", [None])[0]
        if expiry and re.fullmatch(r"[0-9a-fA-F]{1,16}", expiry) and int(expiry, 16) <= now.timestamp():
            return MediaError("MEDIA_URL_EXPIRED", retryable=True)
    if status in {401, 403}:
        return MediaError("MEDIA_ACCESS_DENIED", retryable=True)
    if status in {404, 410}:
        return MediaError("MEDIA_NOT_FOUND")
    if status == 429:
        return MediaError("TEMPORARILY_BLOCKED", retryable=True)
    return MediaError("MEDIA_FETCH_FAILED", retryable=status >= 500)


class MediaClient:
    def __init__(self, session: AsyncSession, *, directory: Path | None = None):
        self._session = session
        self._directory = directory

    @asynccontextmanager
    async def _open(self, url: str, now: datetime, *, range_header: str | None = None):
        headers = {"Accept-Encoding": "identity"}
        if range_header:
            headers["Range"] = range_header
        try:
            for _ in range(5):
                classified = classify_url(url)
                if not classified or classified[0] != "cdn":
                    raise MediaError("INVALID_MEDIA_DESTINATION")
                url = classified[1]
                async with self._session.stream(
                    "GET", url, headers=headers, allow_redirects=False, timeout=15,
                ) as response:
                    if response.status_code in REDIRECTS:
                        if location := response.headers.get("location"):
                            url = urljoin(url, location)
                            continue
                    if response.status_code not in {200, 206}:
                        raise _expiry_error(url, response.status_code, now)
                    yield response, url
                    return
        except (RequestsError, TimeoutError) as error:
            raise MediaError("MEDIA_FETCH_FAILED", retryable=True) from error
        raise MediaError("MEDIA_FETCH_FAILED", retryable=True)

    async def _spool(self, response: Response, *, expected_size: int | None = None) -> tuple[Path, int]:
        size = 0
        with NamedTemporaryFile(dir=self._directory, suffix=".media", delete=False) as output:
            path = Path(output.name)
            try:
                async for chunk in response.aiter_content():
                    size += len(chunk)
                    if expected_size is not None and size > expected_size:
                        raise MediaError("INVALID_MEDIA_RESPONSE", retryable=True)
                    output.write(chunk)
                if not size or (expected_size is not None and size != expected_size):
                    raise MediaError("INVALID_MEDIA_RESPONSE", retryable=True)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return path, size

    async def _download(self, url: str, now: datetime) -> tuple[Path, str, int]:
        path = None
        try:
            async with self._open(url, now) as (response, resolved):
                if response.status_code != 200:
                    raise MediaError("INVALID_MEDIA_RESPONSE", retryable=True)
                length = response.headers.get("content-length")
                path, size = await self._spool(
                    response, expected_size=int(length) if length and length.isdecimal() else None,
                )
        except BaseException:
            if path:
                path.unlink(missing_ok=True)
            raise
        return path, resolved, size

    async def _prefix(self, url: str, now: datetime, limit: int) -> tuple[Path, str, int, bool]:
        async with self._open(url, now, range_header=f"bytes=0-{limit - 1}") as (response, resolved):
            expected = total = None
            if response.status_code == 206:
                match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", response.headers.get("content-range", ""))
                if not match:
                    raise MediaError("INVALID_MEDIA_RESPONSE", retryable=True)
                expected, total = int(match[1]) + 1, int(match[2])
                if expected > min(total, limit):
                    raise MediaError("INVALID_MEDIA_RESPONSE", retryable=True)
            path, size = await self._spool(response, expected_size=expected)
        total = size if total is None else total
        return path, resolved, total, size == total

    async def inspect(self, url: str, now: datetime) -> MediaAsset:
        path = None
        keep = False
        try:
            path, resolved, total, complete = await self._prefix(url, now, PROBE_BYTES)
            index = path.read_bytes() if not complete else b""
            index_end = _mp4_index_end(index)
            if index_end is not None and len(index) < index_end <= min(total, MAX_INDEX_BYTES):
                path.unlink()
                path, resolved, total, complete = await self._prefix(resolved, now, index_end)
                index = path.read_bytes() if not complete else b""
            if not complete and _contains_complete_mp4_index(index):
                try:
                    duration, audio, video = await _probe(path)
                    return MediaAsset(resolved, duration, audio, video, total)
                except MediaError:
                    pass
            if not complete:
                path.unlink(missing_ok=True)
                path, resolved, total = await self._download(resolved, now)
            duration, audio, video = await _probe(path)
            keep = True
            return MediaAsset(resolved, duration, audio, video, total, path)
        except OSError as error:
            raise MediaError("MEDIA_INSPECTION_FAILED", retryable=True) from error
        finally:
            if path and not keep:
                path.unlink(missing_ok=True)

    async def materialize(self, asset: MediaAsset, *, now: datetime | None = None) -> Path:
        """Reuse a completed inspection download. The caller owns any newly fetched file."""
        if asset.file:
            return asset.file
        path, _, _ = await self._download(asset.url, now or datetime.now(UTC))
        return path

    async def read_text(self, url: str, now: datetime) -> str:
        data = bytearray()
        async with self._open(url, now) as (response, _):
            async for chunk in response.aiter_content():
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise MediaError("CAPTIONS_TOO_LARGE")
        return data.decode("utf-8-sig")


async def _refresh(ref: VideoRef, context: RunContext) -> VideoRef:
    if not ref.metadata.shortcode:
        raise MediaError("MEDIA_NOT_FOUND")
    try:
        post = await context.instagram.post(ref.metadata.shortcode)
    except InstagramError as error:
        raise MediaError(error.code, retryable=error.retryable) from error
    candidates = videos_from_post(post, ref.metadata.shortcode, InputRef("refresh"))
    if ref.metadata.media_id:
        matched = next((item for item in candidates if item.metadata.media_id == ref.metadata.media_id), None)
    elif ref.metadata.carousel_position is not None:
        matched = next((item for item in candidates if item.metadata.carousel_position == ref.metadata.carousel_position), None)
    else:
        matched = candidates[0] if len(candidates) == 1 else None
    if not matched:
        raise MediaError("MEDIA_IDENTITY_CHANGED")
    return replace(
        ref,
        video_id=matched.video_id if ref.video_id.startswith("cdn:") else ref.video_id,
        video_url=matched.video_url,
        alternate_video_urls=matched.alternate_video_urls,
        audio_url=matched.audio_url or ref.audio_url,
        dash_audio_url=matched.dash_audio_url,
        metadata=replace(
            ref.metadata,
            post_url=matched.metadata.post_url,
            media_id=matched.metadata.media_id,
            carousel_position=matched.metadata.carousel_position,
        ),
    )


async def _inspect(ref: VideoRef, context: RunContext, client: MediaClient) -> Outcome[MediaPlan]:
    attempts: dict[str, MediaAsset | MediaError] = {}
    plan = None

    async def fetch(url: str) -> MediaAsset:
        if url not in attempts:
            try:
                attempts[url] = await client.inspect(url, context.now)
            except MediaError as error:
                attempts[url] = error
        result = attempts[url]
        if isinstance(result, MediaError):
            raise result
        return result

    async def resolve(candidate: VideoRef) -> MediaPlan:
        first_error = None
        source = None
        for url in (candidate.video_url, *candidate.alternate_video_urls):
            if url:
                try:
                    source = await fetch(url)
                    break
                except MediaError as error:
                    first_error = first_error or error
        if first_error and source is None:
            raise first_error
        audio = source if source and source.has_audio else None
        audio_error = None
        if audio is None and candidate.audio_url:
            try:
                track = await fetch(candidate.audio_url)
                if track.has_audio:
                    audio = track
            except MediaError as error:
                audio_error = error
        if audio is None and candidate.dash_audio_url:
            try:
                track = await fetch(candidate.dash_audio_url)
            except MediaError:
                track = None
            if track and track.has_audio and not track.has_video:
                audio = track
        if audio is None and audio_error:
            raise audio_error
        video = source if source and source.has_video else None
        timeline = video or audio
        if timeline is None:
            raise MediaError("MEDIA_NOT_FOUND")
        return MediaPlan(candidate.video_id, candidate, timeline.duration_seconds, video, audio, candidate.caption_candidates)

    try:
        try:
            plan = await resolve(ref)
        except MediaError as initial:
            error = initial
            if ref.metadata.shortcode and initial.code in {
                "MEDIA_URL_EXPIRED", "MEDIA_ACCESS_DENIED", "MEDIA_NOT_FOUND", "MEDIA_FETCH_FAILED",
            } and not context.expired():
                try:
                    plan = await resolve(await _refresh(ref, context))
                except MediaError as refreshed:
                    if initial.code != "MEDIA_URL_EXPIRED" or not refreshed.retryable:
                        error = refreshed
            if plan is None:
                return Outcome("failed", error.code, error.retryable)
        if plan.audio is None:
            return Outcome("skipped", "NO_AUDIO", value=plan)
        return Outcome("success", value=plan)
    finally:
        keep = {asset.file for asset in (plan.video, plan.audio) if asset and asset.file} if plan else set()
        for asset in attempts.values():
            if isinstance(asset, MediaAsset) and asset.file and asset.file not in keep:
                asset.file.unlink(missing_ok=True)


async def inspect_media(ref: VideoRef, context: RunContext) -> Outcome[MediaPlan]:
    if context.expired():
        return Outcome("deferred", "TIME_LIMIT", True)
    if context.media_client:
        return await _inspect(ref, context, context.media_client)
    async with AsyncSession(impersonate="chrome", trust_env=False) as session:
        return await _inspect(ref, context, MediaClient(session))
