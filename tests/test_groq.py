import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from reelsaid.contracts import RunContext, TranscriptOptions, VideoMetadata, VideoRef
from reelsaid.groq import (
    LARGE,
    TURBO,
    GroqAccount,
    GroqAdapter,
    GroqPool,
    ProviderResponse,
    Quota,
    transcribe,
)
from reelsaid.media import MediaAsset, MediaPlan


URL = "https://video.cdninstagram.com/sample.mp4?oe=FFFFFFFF&oh=signed"


def asset():
    ref = VideoRef("sample", VideoMetadata(), (), video_url=URL)
    source = MediaAsset(URL, Decimal("8.9"), True, True, 2200000)
    return MediaPlan(ref.video_id, ref, source.duration_seconds, source, source, ())


def transcript(text="Hola mundo."):
    return {
        "text": text,
        "language": "spanish",
        "duration": 8.9,
        "segments": [{"start": 0.3, "end": 1.3, "text": text, "no_speech_prob": 0.01, "avg_logprob": -0.2}],
        "words": [{"start": 0.3, "end": 0.7, "word": "Hola"}, {"start": 0.7, "end": 1.3, "word": "mundo."}],
    }


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def send(self, account, model, *, url, file, language):
        self.calls.append((account.name, model, url, file, language))
        return next(self.responses)


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    async def sleep(self, delay):
        self.value += delay


def setup(responses, accounts, uploads=None, clock=None):
    transport = Transport(responses)
    clock = clock or Clock()
    pool = GroqPool(accounts, clock=clock)

    @asynccontextmanager
    async def prepare(media, context):
        assert uploads is not None
        uploads.append(media.video_id)
        yield Path("speech.flac")

    adapter = GroqAdapter(transport, pool, upload=prepare, sleep=clock.sleep)
    context = RunContext(None, None, datetime.now(UTC), lambda: False, groq=adapter)
    return transport, context


def test_url_first_and_upload_recovery():
    uploads = []
    calls, context = setup(
        [ProviderResponse(200, {}, transcript())], [GroqAccount("one", "fake")], uploads,
    )
    result = asyncio.run(transcribe(asset(), TranscriptOptions(), context))
    assert result.status == "success"
    assert calls.calls == [("one", TURBO, URL, None, None)] and not uploads

    calls, context = setup([
        ProviderResponse(400, {}, {"error": {"code": "media_fetch_failed"}}),
        ProviderResponse(200, {}, transcript()),
    ], [GroqAccount("one", "fake")], uploads)
    result = asyncio.run(transcribe(asset(), TranscriptOptions(), context))
    assert result.status == "success"
    assert uploads == ["sample"]
    assert calls.calls[1] == ("one", TURBO, None, Path("speech.flac"), None)


def test_model_and_account_quota():
    async def check():
        one = GroqAccount("one", "fake-1", {TURBO: Quota(requests_per_minute=1), LARGE: Quota()},
                          shared=Quota(requests_per_minute=2))
        two = GroqAccount("two", "fake-2", {TURBO: Quota(audio_seconds_per_hour=11)})
        clock = Clock()
        pool = GroqPool([one, two], clock=clock)
        reservations = [(await pool.reserve((TURBO, LARGE), 10))[0] for _ in range(3)]
        assert [(entry.account.name, entry.model) for entry in reservations] == [
            ("one", TURBO), ("two", TURBO), ("one", LARGE),
        ]
        unavailable, ready_in = await pool.reserve((TURBO, LARGE), 10)
        assert unavailable is None and ready_in == 60
        await clock.sleep(60)
        resumed, _ = await pool.reserve((TURBO, LARGE), 10)
        assert (resumed.account.name, resumed.model) == ("one", TURBO)

    asyncio.run(check())


def test_rate_limit_cooldown():
    async def check():
        clock = Clock()
        transport, context = setup([
            ProviderResponse(429, {"retry-after": "3"}, {"error": {"code": "rate_limit_exceeded"}}),
            ProviderResponse(200, {}, transcript()),
            ProviderResponse(200, {}, transcript()),
        ], [GroqAccount("one", "fake", {TURBO: Quota(), LARGE: Quota()})], clock=clock)
        first = await transcribe(asset(), TranscriptOptions(), context)
        assert first.status == "success"
        assert [call[1] for call in transport.calls] == [TURBO, LARGE]
        assert clock.value == 0
        second = await transcribe(asset(), TranscriptOptions(), context, models=(TURBO,))
        assert second.status == "success"
        assert clock.value == 3 and transport.calls[-1][1] == TURBO

    asyncio.run(check())


def test_timestamps_and_language_hint():
    calls, context = setup(
        [ProviderResponse(200, {}, transcript())], [GroqAccount("one", "fake")],
    )
    result = asyncio.run(transcribe(asset(), TranscriptOptions(language="es", word_level_timestamps=True), context))
    draft = result.value
    assert calls.calls[0][-1] == "es"
    assert draft.text == "Hola mundo." and draft.language == "spanish"
    assert draft.segments[0].start == 0.3 and draft.segments[0].no_speech_prob == 0.01
    assert [word.text for word in draft.words] == ["Hola", "mundo."]


def test_invalid_key_is_disabled_for_both_models():
    calls, context = setup([
        ProviderResponse(401, {}, {"error": {"code": "invalid_api_key"}}),
        ProviderResponse(200, {}, transcript()),
    ], [GroqAccount("old", "invalid"), GroqAccount("healthy", "fake")])
    result = asyncio.run(transcribe(asset(), TranscriptOptions(), context))
    assert result.status == "success"
    assert [call[0] for call in calls.calls] == ["old", "healthy"]
    another, _ = asyncio.run(context.groq.pool.reserve((LARGE,), 10))
    assert another.account.name == "healthy"
