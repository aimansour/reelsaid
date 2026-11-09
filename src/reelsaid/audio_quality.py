"""Independent speech evidence for uncertain transcripts."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from curl_cffi.requests import AsyncSession

from .contracts import RunContext
from .media import LOCAL_MEDIA_FORMATS, MediaAsset, MediaClient, MediaError, MediaPlan

if TYPE_CHECKING:
    import numpy as np


RATE = 16000
FRAME = 512
FRAME_SECONDS = FRAME / RATE
SpeechClass = Literal["speech", "silence", "music_only", "no_speech", "no_audio", "unknown"]
Interval = tuple[float, float]


@dataclass(frozen=True)
class SpeechEvidence:
    classification: SpeechClass
    voiced: tuple[Interval, ...] = ()
    confidence: float | None = None


def _model_directory() -> Path:
    configured = os.environ.get("REELSAID_MODEL_DIR")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / ".quality-models"


@lru_cache(maxsize=1)
def _silero_model(path: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def _voice_scores(samples: np.ndarray) -> list[float]:
    import numpy as np

    model = _silero_model(_model_directory() / "silero_vad.onnx")
    state = np.zeros((2, 1, 128), dtype=np.float32)
    data = np.zeros((1, FRAME + 64), dtype=np.float32)
    rate = np.array(RATE, dtype=np.int64)
    result = []
    for offset in range(0, len(samples), FRAME):
        block = samples[offset:offset + FRAME]
        data[0, 64:] = 0
        data[0, 64:64 + len(block)] = block
        score, state = model.run(None, {"input": data, "state": state, "sr": rate})
        result.append(float(score.item()))
        data[0, :64] = data[0, -64:]
    return result


def _voiced_spans(scores: list[float], duration: float) -> tuple[Interval, ...]:
    voiced: list[Interval] = []
    start = None
    for index, score in enumerate((*scores, 0.0)):
        if score >= 0.5:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= 2:
                left, right = start * FRAME_SECONDS, min(duration, index * FRAME_SECONDS)
                if voiced and left - voiced[-1][1] <= 0.16:
                    voiced[-1] = (voiced[-1][0], right)
                elif right > left:
                    voiced.append((left, right))
            start = None
    return tuple(voiced)


def _music_score(samples: np.ndarray) -> float:
    import numpy as np
    from ai_edge_litert.interpreter import Interpreter

    model = Interpreter(model_path=str(_model_directory() / "yamnet.tflite"), num_threads=1)
    model.allocate_tensors()
    input_index = model.get_input_details()[0]["index"]
    output_index = model.get_output_details()[0]["index"]
    scores = []
    for offset in range(0, max(1, len(samples) - 15599), 7680):
        block = samples[offset:offset + 15600]
        if len(block) < 15600:
            block = np.pad(block, (0, 15600 - len(block)))
        model.set_tensor(input_index, block)
        model.invoke()
        scores.append(float(model.get_tensor(output_index)[0, 132]))
    return float(np.mean(scores))


def analyze_pcm(raw: bytes) -> SpeechEvidence:
    import numpy as np

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    if not samples.size:
        return SpeechEvidence("unknown")
    if float(np.abs(samples).max()) <= 4 / 32768:
        return SpeechEvidence("silence", confidence=1.0)
    scores = _voice_scores(samples)
    spans = _voiced_spans(scores, len(samples) / RATE)
    if spans:
        confidence = round(float(np.median([score for score in scores if score >= 0.5])), 3)
        return SpeechEvidence("speech", spans, confidence)
    peak = max(scores)
    music = _music_score(samples)
    isolated_weak_voice = 0.5 <= peak < 0.55 and sum(score >= 0.5 for score in scores) == 1
    if (music >= 0.65 and peak < 0.5) or (music >= 0.90 and isolated_weak_voice):
        return SpeechEvidence("music_only", confidence=round(min(1, music), 3))
    if peak < 0.35:
        return SpeechEvidence("no_speech", confidence=round(1 - peak, 3))
    return SpeechEvidence("unknown")


async def _decode_audio(path: Path) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file",
        "-format_whitelist", LOCAL_MEDIA_FORMATS, "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(45):
            data, _ = await process.communicate()
    except (TimeoutError, asyncio.CancelledError):
        with suppress(ProcessLookupError):
            process.kill()
        await process.communicate()
        raise
    if process.returncode != 0:
        raise MediaError("AUDIO_PREPARATION_FAILED")
    return data


def _aligned_audio(primary: MediaAsset, alternate: MediaAsset) -> bool:
    if primary.audio_span and alternate.audio_span:
        start, end = primary.audio_span
        other_start, other_end = alternate.audio_span
        return abs(start - other_start) <= Decimal("0.05") and abs(end - other_end) <= Decimal("0.35")
    return abs(primary.duration_seconds - alternate.duration_seconds) <= Decimal("0.35")


async def _speech_asset(media: MediaPlan, client: MediaClient, context: RunContext):
    asset = media.audio
    sidecar = media.ref.dash_audio_url
    if not asset.file and sidecar and sidecar != asset.url:
        candidate = None
        try:
            candidate = await client.inspect(sidecar, context.now)
            if candidate.has_audio and not candidate.has_video and _aligned_audio(asset, candidate):
                return candidate, await client.materialize(candidate)
        except MediaError:
            pass
        if candidate and candidate.file:
            candidate.file.unlink(missing_ok=True)
    return asset, await client.materialize(asset)


@asynccontextmanager
async def verified_audio(media: MediaPlan, context: RunContext):
    asset = media.audio
    if asset is None or context.expired():
        yield SpeechEvidence("no_audio" if asset is None else "unknown"), media
        return
    path = None
    try:
        try:
            if context.media_client:
                inspected, path = await _speech_asset(media, context.media_client, context)
            else:
                async with AsyncSession(impersonate="chrome", trust_env=False) as session:
                    inspected, path = await _speech_asset(media, MediaClient(session), context)
            evidence = await asyncio.to_thread(analyze_pcm, await _decode_audio(path))
        except (MediaError, OSError, RuntimeError, TimeoutError, ValueError):
            evidence = SpeechEvidence("unknown")
        yield evidence, replace(media, audio=replace(inspected, file=path)) if path else media
    finally:
        if path and path != asset.file:
            path.unlink(missing_ok=True)
