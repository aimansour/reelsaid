"""Run the selected quality checks on labeled audio and real Instagram media."""

import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from curl_cffi.requests import AsyncSession

from instagram import emit
from reelsaid.contracts import RunContext, TranscriptOptions, VideoMetadata, VideoRef
from reelsaid.discovery import discover
from reelsaid.groq import GroqAdapter, GroqPool, GroqTransport, load_accounts, transcribe
from reelsaid.input import parse_input
from reelsaid.instagram import InstagramClient
from reelsaid.media import MediaAsset, MediaClient, MediaPlan, inspect_media
from reelsaid.quality import evaluate_video


SHORT = "DS46KJNjva9"
SPANISH = "Dfax6SllBLR"
QUIET = "DfaaAP7BvIu"


def emit_quality(case, result, elapsed):
    value = result.value
    emit({
        "case": case, "status": result.status, "errorCode": result.error_code,
        "speech": value.speech_classification if value else None,
        "confidence": value.speech_confidence if value else None,
        "billable": value.billable if value else False,
        "language": value.language if value else None,
        "usableText": bool(value and value.text),
        "defectFraction": value.affected_fraction if value else None,
        "milliseconds": round(elapsed * 1000),
    })


def render(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True, timeout=25)


def fixture(name, path, seconds):
    ref = VideoRef(name, VideoMetadata(), ())
    audio = MediaAsset("https://media.cdninstagram.com/fixture", Decimal(str(seconds)), True, False,
                       path.stat().st_size, path)
    return MediaPlan(name, ref, audio.duration_seconds, None, audio, ())


async def main():
    accounts = load_accounts(os.environ["REELSAID_GROQ_KEYS"])
    async with AsyncSession(impersonate="chrome", trust_env=False) as session, \
               AsyncSession(impersonate="chrome", trust_env=False) as asr_session:
        media_client = MediaClient(session)
        context = RunContext(
            InstagramClient(session), None, datetime.now(UTC), lambda: False, media_client,
            GroqAdapter(GroqTransport(asr_session), GroqPool(accounts)),
        )
        options = TranscriptOptions(word_level_timestamps=True)
        result = await discover(parse_input({"shortcodes": [SHORT, SPANISH, QUIET]}), context)
        refs = {video.metadata.shortcode: video for video in result.videos}
        inputs = {}
        for code in (SHORT, SPANISH, QUIET):
            inspected = await inspect_media(refs[code], context)
            assert inspected.status == "success", inspected.error_code
            inputs[code] = inspected.value
        retained = {}
        try:
            for code, language in ((SHORT, "english"), (SPANISH, "spanish")):
                media = inputs[code]
                retained[code] = await media_client.materialize(media.audio)
                complete = replace(media, audio=replace(media.audio, file=retained[code]))
                start = monotonic()
                spoken = await evaluate_video(complete, options, context)
                emit_quality(language, spoken, monotonic() - start)
                assert spoken.value and spoken.value.billable and spoken.value.language.casefold() == language
                assert spoken.value.speech_classification == "speech" and spoken.value.words

            with TemporaryDirectory() as directory:
                workspace = Path(directory)
                silent, mixture = workspace / "silent.flac", workspace / "speech-music.flac"
                render("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", 9, silent)
                render("-i", retained[SHORT], "-i", "piano.flac", "-filter_complex",
                       "amix=inputs=2:duration=first:weights=1 0.45", "-ar", 16000, "-ac", 1, mixture)

                async def upload(media, options, context, **kwargs):
                    return await transcribe(media, options, context, prepared_file=media.audio.file, **kwargs)

                async def no_asr(*args, **kwargs):
                    raise AssertionError("A verified non-speech fixture reached ASR")

                for name, path, seconds, code in (
                    ("silence", silent, 9, "SILENCE"), ("piano", Path("piano.flac"), 12, "MUSIC_ONLY"),
                ):
                    start = monotonic()
                    quiet = await evaluate_video(fixture(name, path, seconds), options, context, asr=no_asr)
                    emit_quality(name, quiet, monotonic() - start)
                    assert quiet.error_code == code and not quiet.value.billable and not quiet.value.text
                    assert quiet.value.speech_confidence >= 0.85

                start = monotonic()
                mixed = await evaluate_video(fixture("mixed", mixture, inputs[SHORT].duration_seconds),
                                             options, context, asr=upload)
                emit_quality("speech-over-music", mixed, monotonic() - start)
                assert mixed.value and mixed.value.billable and mixed.value.speech_classification == "speech"

            start = monotonic()
            candidate = await evaluate_video(inputs[QUIET], options, context)
            emit_quality("instagram-no-speech-candidate", candidate, monotonic() - start)
        finally:
            for code, path in retained.items():
                if inputs[code].audio.file != path:
                    path.unlink(missing_ok=True)
            for media in inputs.values():
                media.close()
