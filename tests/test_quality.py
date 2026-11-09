import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from reelsaid import audio_quality
from reelsaid.audio_quality import SpeechEvidence, verified_audio
from reelsaid.contracts import CaptionCandidate, Outcome, RunContext, TranscriptOptions, VideoMetadata, VideoRef
from reelsaid.groq import LARGE, Segment, TranscriptDraft, Word
from reelsaid.media import MediaAsset, MediaPlan
from reelsaid.quality import assess, evaluate_video


URL = "https://media.cdninstagram.com/example.mp4"


def media(*, audio=True, captions=()):
    ref = VideoRef("video", VideoMetadata(), (), video_url=URL, caption_candidates=captions)
    asset = MediaAsset(URL, Decimal(10), audio, True, 1000)
    return MediaPlan(ref.video_id, ref, asset.duration_seconds, asset, asset if audio else None, captions)


def draft(*spans, text="Some real spoken text."):
    segments = tuple(Segment(label if label else text, start, end) for start, end, label in spans)
    return TranscriptDraft(text, "es", segments, (), 10)


def evaluate(plan, evidence, initial, *, captions=None, repaired=None, options=None):
    calls = []
    ctx = RunContext(None, None, datetime.now(UTC), lambda: False)

    @asynccontextmanager
    async def verify(candidate, context):
        yield evidence, candidate

    async def caption_reader(candidate, context):
        return captions

    async def asr(candidate, options, context, **kwargs):
        models = kwargs.get("models")
        calls.append(models)
        answer = repaired if models == (LARGE,) else initial
        return Outcome("success", value=answer) if answer else Outcome("failed", "TRANSCRIPTION_FAILED", True)

    outcome = asyncio.run(evaluate_video(
        plan, options or TranscriptOptions(), ctx, speech_probe=verify, asr=asr, caption_reader=caption_reader,
    ))
    return outcome, calls


def test_music_silence_and_speech():
    hallucination = draft((0, 2, "Thanks for watching!"), text="Thanks for watching!")
    for kind, code in (("music_only", "MUSIC_ONLY"), ("silence", "SILENCE")):
        result, _ = evaluate(media(), SpeechEvidence(kind, (), .98), hallucination)
        assert result.status == "skipped" and result.error_code == code
        assert not result.value.billable and not result.value.text
        assert result.value.speech_classification == kind and result.value.speech_confidence == .98
    missing, calls = evaluate(media(audio=False), SpeechEvidence("unknown"), None)
    assert missing.error_code == "NO_AUDIO" and not calls and not missing.value.billable
    spoken, _ = evaluate(
        media(), SpeechEvidence("speech", ((0, 9),), .96),
        draft((0, 9, "La voz se escucha sobre la música."), text="La voz se escucha sobre la música."),
    )
    assert spoken.value.billable and "música" in spoken.value.text


def test_verified_unsupported_tail_is_removed_from_text_and_timestamps():
    initial = TranscriptDraft(
        "Real ending. Thank you.", "en",
        (Segment("Real ending.", 0, 4), Segment("Thank you.", 9.8, 10)),
        (Word("Real", 0, 2), Word("ending.", 2, 4), Word("Thank", 9.8, 9.9), Word("you.", 9.9, 10)), 10,
    )
    outcome, calls = evaluate(media(), SpeechEvidence("speech", ((0, 4),), .99), initial)
    assert outcome.status == "success" and outcome.value.billable
    assert outcome.value.text == "Real ending."
    assert [entry.text for entry in outcome.value.segments] == ["Real ending."]
    assert [entry.text for entry in outcome.value.words] == ["Real", "ending."]
    assert calls == [None]
    audible, _ = evaluate(media(), SpeechEvidence("speech", ((0, 4), (9.8, 10)), .99), initial)
    assert audible.value.text == initial.text


def test_overlapping_segments_are_ordered_by_start_without_reordering_transcript():
    initial = draft((0, 4, "First sentence."), (4.54, 4.68, "Yes."),
                    (4.3, 10, "The speaker continues."),
                    text="First sentence. Yes. The speaker continues.")
    outcome, _ = evaluate(media(), SpeechEvidence("speech", ((0, 4), (4.3, 10)), .99), initial)
    assert outcome.value.text == initial.text
    assert [entry.start for entry in outcome.value.segments] == [0, 4.3, 4.54]


def test_verified_licensed_music_avoids_asr_while_mixed_speech_is_transcribed():
    plan = media()
    plan = replace(plan, ref=replace(
        plan.ref, metadata=VideoMetadata(audio={"isOriginal": False}),
        dash_audio_url="https://media.cdninstagram.com/audio.m4a",
    ))
    initial = draft((0, 9, "Audible mixed speech."), text="Audible mixed speech.")
    music, calls = evaluate(plan, SpeechEvidence("music_only", confidence=.98), initial)
    assert music.error_code == "MUSIC_ONLY" and calls == []
    mixed, calls = evaluate(plan, SpeechEvidence("speech", ((0, 9),), .94), initial)
    assert mixed.value.billable and calls == [None]


def test_verification_uses_aligned_dash_track_and_rejects_unaligned_track(tmp_path, monkeypatch):
    async def check():
        sidecar = "https://media.cdninstagram.com/audio.m4a"
        plan = media()
        plan = replace(plan, ref=replace(plan.ref, dash_audio_url=sidecar))
        seen = []

        class Client:
            duration = Decimal("10.1")

            async def inspect(self, url, now):
                assert url == sidecar
                return MediaAsset(url, self.duration, True, False, 100)

            async def materialize(self, asset):
                seen.append(asset.url)
                path = tmp_path / "asset"
                path.write_bytes(b"fixture")
                return path

        async def decode(path):
            return b"audio"

        monkeypatch.setattr(audio_quality, "_decode_audio", decode)
        monkeypatch.setattr(audio_quality, "analyze_pcm", lambda _: SpeechEvidence("speech"))
        client = Client()
        ctx = RunContext(None, None, datetime.now(UTC), lambda: False, media_client=client)
        async with verified_audio(plan, ctx) as (evidence, inspected):
            assert evidence.classification == "speech" and inspected.audio.url == sidecar
        assert not list(tmp_path.iterdir())
        client.duration = Decimal(4)
        async with verified_audio(plan, ctx) as (_, inspected):
            assert inspected.audio.url == URL
        assert seen == [sidecar, URL]
    asyncio.run(check())


def test_unsupported_speech_uses_word_times_inside_coarse_segment():
    candidate = TranscriptDraft(
        "Good morning. Extra phrase. Welcome back.", "en",
        (Segment("Good morning.", 0, 18), Segment("Extra phrase.", 20, 80),
         Segment("Welcome back.", 83, 100)),
        (Word("Good", 0, 9), Word("morning.", 9, 18), Word("Extra", 55, 55.5),
         Word("phrase.", 55.5, 56), Word("Welcome", 83, 92), Word("back.", 92, 100)),
        100,
    )
    result = assess(candidate, SpeechEvidence("speech", ((0, 18), (83, 100)), 0.97), Decimal(100))
    assert result.affected_fraction == pytest.approx(.01)
    assert [(d.start, d.end, d.reason) for d in result.defects] == [(55, 56, "unsupported_speech")]


def test_captions_and_asr_provenance():
    evidence = SpeechEvidence("speech", ((0, 8),), .94)
    track = CaptionCandidate("https://media.cdninstagram.com/caption.vtt", "es", True)
    exact = draft((0, 8, "Una frase en español."), text="Una frase en español.")
    accepted, calls = evaluate(media(captions=(track,)), evidence, None, captions=exact)
    assert accepted.value.source == "captions" and not calls and accepted.value.billable
    fallback, calls = evaluate(media(captions=(track,)), evidence, exact)
    assert fallback.value.source == "asr" and calls == [None]
    translated = CaptionCandidate(track.url, "en", False)
    fallback, calls = evaluate(media(captions=(translated,)), evidence, exact, captions=exact)
    assert fallback.value.source == "asr" and calls == [None]


def test_defect_boundary_and_repair():
    evidence = SpeechEvidence("speech", ((0, 10),), .99)
    exact = draft((2, 10, "We begin after the missing words."))
    result, calls = evaluate(media(), evidence, exact)
    assert result.status == "partial" and result.value.billable
    assert result.value.affected_fraction == pytest.approx(.20) and calls == [None]

    wrong = draft((2.1, 10, "We begin after the missing words."))
    unresolved, calls = evaluate(media(), evidence, wrong, repaired=wrong)
    assert unresolved.status == "partial" and not unresolved.value.billable
    assert unresolved.value.affected_fraction == pytest.approx(.21)
    assert calls == [None, (LARGE,)]

    corrected = draft((0, 10, "The opening words are present."))
    recovered, calls = evaluate(media(), evidence, wrong, repaired=corrected)
    assert recovered.status == "success" and recovered.value.billable
    assert recovered.value.affected_fraction == 0 and calls == [None, (LARGE,)]


def test_partial_coverage_edges():
    spoken = SpeechEvidence("speech", ((0, 2), (3, 5), (7, 10)), .95)
    bad = draft(
        (1, 2, "The opening starts late."),
        (5, 6, "This sentence is invented."),
        (5.2, 6.2, "This sentence is invented."),
        (7, 9, "The last phrase stops early."),
    )
    quality = assess(bad, spoken, Decimal(10))
    assert quality.missing_start and quality.missing_end and quality.missing_internal
    assert quality.affected_fraction == pytest.approx(.52)
    assert {"missing_speech", "unsupported_speech", "repeated_text"} <= {item.reason for item in quality.defects}


def test_suspect_result_without_independent_evidence_stays_free():
    initial = TranscriptDraft("Thanks.", "es", (Segment("Thanks.", 8, 9),), (Word("Thanks.", 8, 9),), 10)
    outcome, calls = evaluate(media(), SpeechEvidence("unknown"), initial)
    assert outcome.status == "partial" and outcome.error_code == "QUALITY_UNVERIFIED"
    assert outcome.value.text == "Thanks." and not outcome.value.billable
    assert calls == [None]


def test_word_edges_trigger_verification_even_when_segment_spans_whole_video():
    raw = draft((0, 10, "The transcript lost a word at each end."))
    timed = replace(raw, words=(Word("The transcript lost a word at each end.", .55, 9.35),))
    result, calls = evaluate(media(), SpeechEvidence("speech", ((0, 10),), .97), timed)
    assert result.status == "partial" and result.value.billable
    assert result.value.assessment.missing_start and result.value.assessment.missing_end
    assert result.value.affected_fraction == pytest.approx(.12) and calls == [None]


def test_targeted_repair_keeps_unaffected_timeline(monkeypatch):
    import reelsaid.quality as quality_module

    plan = media()
    plan = replace(plan, audio=replace(plan.audio, file=Path("existing.media")))
    prepared = []
    asr_calls = []

    @asynccontextmanager
    async def verify(candidate, context):
        yield SpeechEvidence("speech", ((0, 4), (5, 8), (9, 10)), .95), candidate

    @asynccontextmanager
    async def trim(candidate, context, *, start, duration):
        assert candidate.audio.file == Path("existing.media")
        prepared.append((start, duration))
        yield Path("slice.flac")

    async def asr(candidate, options, context, **kwargs):
        asr_calls.append(kwargs)
        if kwargs:
            assert candidate.audio.duration_seconds < plan.audio.duration_seconds
            return Outcome("success", value=draft((.3, 3.3, "Restored middle."), text="Restored middle."))
        return Outcome("success", value=draft(
            (0, 4, "Original start."), (9, 10, "Original ending."), text="Original start. Original ending.",
        ))

    monkeypatch.setattr(quality_module, "prepare_upload", trim)
    ctx = RunContext(None, None, datetime.now(UTC), lambda: False)
    outcome = asyncio.run(evaluate_video(plan, TranscriptOptions(), ctx, speech_probe=verify, asr=asr))
    assert outcome.status == "success" and outcome.value.billable
    assert outcome.value.text == "Original start. Restored middle. Original ending."
    assert [(segment.start, segment.end) for segment in outcome.value.segments] == [(0, 4), (5, 8), (9, 10)]
    assert prepared[0] == pytest.approx((4.7, 3.6))
    assert asr_calls == [{}, {"models": (LARGE,), "prepared_file": Path("slice.flac")}]
