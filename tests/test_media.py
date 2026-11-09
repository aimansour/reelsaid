import asyncio
import subprocess
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from reelsaid import media as media_module
from reelsaid.audio_quality import verified_audio
from reelsaid.contracts import InputRef, RunContext, VideoMetadata, VideoRef
from reelsaid.discovery import discover
from reelsaid.input import parse_input
from reelsaid.media import MediaClient, inspect_media


BASE = "https://video.cdninstagram.com"
VIDEO = BASE + "/a.mp4?oh=fresh&oe=FFFFFFFF"
EXPIRED = BASE + "/a.mp4?oh=old&oe=1"
AUDIO = BASE + "/audio.m4a?oh=sidecar"
CAROUSEL = "Ddm6E9OGt5D"


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    video, audio = root / "video.mp4", root / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x120:r=25:d=4",
        "-c:v", "mpeg4", "-q:v", "2", "-movflags", "+faststart", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:a", "aac", "-movflags", "+faststart", str(audio),
    ], check=True)
    return video.read_bytes(), audio.read_bytes()


class Response:
    def __init__(self, status, body=b"", **headers):
        self.status_code = status
        self.body = body
        self.headers = headers

    async def aiter_content(self):
        yield self.body


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    @asynccontextmanager
    async def stream(self, method, url, *, headers, **kwargs):
        self.requests.append((url, headers.get("Range")))
        assert kwargs["allow_redirects"] is False
        value = self.responses[url]
        if isinstance(value, bytes):
            if header := headers.get("Range"):
                start, end = map(int, header.removeprefix("bytes=").split("-"))
                end = min(end, len(value) - 1)
                yield Response(206, value[start:end+1], **{"content-range": f"bytes {start}-{end}/{len(value)}"})
            else:
                yield Response(200, value)
        else:
            yield value


def context(session, posts=None, tmp_path=None):
    async def post(code):
        assert code in posts
        return posts[code]

    instagram = SimpleNamespace(post=post)
    return RunContext(
        instagram, None, datetime.now(UTC), lambda: False, media_client=MediaClient(session, directory=tmp_path),
    )


def ref(video_url=None, audio_url=None, **metadata):
    return VideoRef("original-id", VideoMetadata(**metadata), (InputRef("startUrls", 0),), video_url, audio_url)


def test_expired_carousel_sidecar(samples, tmp_path):
    video, audio = samples
    session = Session({EXPIRED: Response(403), VIDEO: video, AUDIO: audio})
    post = {
        "code": CAROUSEL,
        "carousel_media": [
            {"pk": "other", "video_versions": [{"url": BASE + "/wrong.mp4"}]},
            {"pk": "original-child", "video_versions": [{"url": VIDEO}]},
        ],
    }
    result = asyncio.run(inspect_media(ref(
        EXPIRED, AUDIO, shortcode=CAROUSEL, media_id="original-child", carousel_position=0,
    ), context(session, {CAROUSEL: post}, tmp_path)))
    assert result.status == "success"
    plan = result.value
    try:
        assert plan.video_id == "original-id"
        assert plan.ref.metadata.media_id == "original-child"
        assert plan.ref.metadata.carousel_position == 1
        assert plan.video.url == VIDEO
        assert plan.audio.url == AUDIO
        assert plan.duration_seconds == Decimal(4)
    finally:
        plan.close()
    assert not list(tmp_path.iterdir())


def test_signed_url_preserved_and_expiry_is_explicit_without_origin(tmp_path):
    session = Session({EXPIRED: Response(403)})
    outcome = asyncio.run(inspect_media(ref(EXPIRED), context(session, tmp_path=tmp_path)))
    assert [url for url, _ in session.requests] == [EXPIRED]
    assert outcome.status == "failed"
    assert outcome.error_code == "MEDIA_URL_EXPIRED"
    assert outcome.retryable


def test_large_fast_start_index_extends_range_without_downloading_video(samples, tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "PROBE_BYTES", 128)
    session = Session({VIDEO: samples[0]})
    result = asyncio.run(inspect_media(ref(VIDEO), context(session, tmp_path=tmp_path)))
    assert result.value.duration_seconds == Decimal(4)
    assert result.value.video.file is None
    assert len(session.requests) == 2 and all(header for _, header in session.requests)
    assert not list(tmp_path.iterdir())


def test_shorter_audio_sidecar_uses_the_audio_timeline_and_preserves_video_duration(samples, tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    audio = tmp_path / "sound.m4a"
    combined = tmp_path / "combined.mp4"
    video.write_bytes(samples[0])
    audio.write_bytes(samples[1])
    subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(video), "-i", str(audio),
        "-c", "copy", "-movflags", "+faststart", str(combined),
    ], check=True)
    monkeypatch.setattr(media_module, "PROBE_BYTES", 8192)
    session = Session({VIDEO: combined.read_bytes(), AUDIO: samples[1]})
    ctx = context(session, tmp_path=tmp_path)

    async def check():
        outcome = await inspect_media(replace(ref(VIDEO), dash_audio_url=AUDIO), ctx)
        plan = outcome.value
        try:
            assert plan.duration_seconds == Decimal(4)
            assert plan.audio.file is None
            async with verified_audio(plan, ctx) as (_, inspected):
                assert inspected.audio.url == AUDIO
                assert inspected.duration_seconds == Decimal(4)
            assert (VIDEO, None) not in session.requests
        finally:
            plan.close()

    asyncio.run(check())


def test_stable_cdn_identity():
    posts = {CAROUSEL: {
        "code": CAROUSEL,
        "carousel_media": [
            {"pk": "one", "video_versions": [{"url": VIDEO}]},
            {"pk": "two", "video_versions": [{"url": BASE + "/different.mp4"}]},
        ],
    }}
    ctx = context(Session({}), posts)
    a = asyncio.run(discover(parse_input({"startUrls": [VIDEO]}), ctx))
    b = asyncio.run(discover(parse_input({"startUrls": [EXPIRED]}), ctx))
    assert a.videos[0].video_id == b.videos[0].video_id
    joined = asyncio.run(discover(parse_input({"startUrls": [EXPIRED], "shortcodes": [CAROUSEL]}), ctx))
    assert [video.video_id for video in joined.videos] == [f"{CAROUSEL}:one", f"{CAROUSEL}:two"]
    assert joined.duplicates == 1


def test_media_destination_validation(tmp_path):
    forbidden = "https://video.cdninstagram.com.evil.example/a.mp4"
    session = Session({VIDEO: Response(302, location=forbidden)})
    outcome = asyncio.run(inspect_media(ref(VIDEO), context(session, tmp_path=tmp_path)))
    assert outcome.error_code == "INVALID_MEDIA_DESTINATION"
    assert [url for url, _ in session.requests] == [VIDEO]
    session.requests.clear()
    outcome = asyncio.run(inspect_media(ref(forbidden), context(session, tmp_path=tmp_path)))
    assert outcome.error_code == "INVALID_MEDIA_DESTINATION" and not session.requests


def test_track_and_duration(samples, tmp_path):
    video, audio = samples
    session = Session({VIDEO: video, AUDIO: audio})
    ctx = context(session, tmp_path=tmp_path)
    no_audio = asyncio.run(inspect_media(ref(VIDEO), ctx))
    assert no_audio.status == "skipped"
    assert no_audio.error_code == "NO_AUDIO"
    assert no_audio.value.duration_seconds == Decimal(4)
    no_audio.value.close()
    audio_only = asyncio.run(inspect_media(ref(AUDIO), ctx))
    try:
        assert audio_only.status == "success"
        assert audio_only.value.video is None
        assert audio_only.value.audio.url == AUDIO
        assert audio_only.value.duration_seconds == Decimal(2)
    finally:
        audio_only.value.close()
    assert all(header is not None for _, header in session.requests)
    assert not list(tmp_path.iterdir())


def test_complete_download_is_reused(samples, tmp_path):
    _, audio = samples
    session = Session({AUDIO: Response(200, audio)})
    ctx = context(session, tmp_path=tmp_path)
    outcome = asyncio.run(inspect_media(ref(audio_url=AUDIO), ctx))
    assert outcome.status == "success"
    plan = outcome.value
    try:
        local_file = asyncio.run(ctx.media_client.materialize(plan.audio))
        assert isinstance(local_file, Path) and local_file.read_bytes() == audio
        assert len(session.requests) == 1
    finally:
        plan.close()
    assert not list(tmp_path.iterdir())
