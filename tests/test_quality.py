import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reelsaid.audio_quality import SpeechEvidence
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
