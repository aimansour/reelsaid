"""Instrumentation copied into a disposable, private timing build."""

from contextlib import contextmanager
from functools import wraps
from time import perf_counter, time


START = perf_counter()
START_UNIX_MS = round(time() * 1000)
spans = []


@contextmanager
def stage(name):
    start = round((perf_counter() - START) * 1000, 1)
    span = {"stage": name, "startMs": start}
    try:
        yield span
    except Exception as error:
        span["error"] = type(error).__name__
        if type(error).__name__ == "MediaError":
            span["errorCode"] = error.code
        raise
    finally:
        span["endMs"] = round((perf_counter() - START) * 1000, 1)
        spans.append(span)


def timed(name, call):
    @wraps(call)
    async def traced(*args, **kwargs):
        with stage(name):
            return await call(*args, **kwargs)
    return traced


def wrap_methods(owner, names):
    for method, label in names.items():
        setattr(owner, method, timed(label, getattr(owner, method)))


def instrument(output):
    from . import actor, audio_quality, groq, quality, state

    actor.discover = timed("discovery", actor.discover)
    wrap_methods(actor._Run, {"_restore": "restore", "_checkpoint": "checkpoint", "_deliver": "delivery"})
    wrap_methods(actor._Batch, {"reserve": "admission"})
    wrap_methods(output, {"push": "datasetWrite", "put": "recordWrite"})
    wrap_methods(state.State, {"lookup": "cacheLookup", "lookup_answer": "answerLookup", "acquire": "lease",
                               "stage": "durableStage", "commit": "durableCommit", "release": "release"})
    wrap_methods(audio_quality, {"_speech_asset": "verificationMedia", "_decode_audio": "decode"})
    inspect = timed("preflight", actor.inspect_media)
    original_analyze = audio_quality.analyze_pcm

    def analyze(data):
        with stage("classify") as details:
            evidence = original_analyze(data)
            details["verdict"] = evidence.classification
            return evidence

    audio_quality.analyze_pcm = analyze

    async def asr(media, options, context, **kwargs):
        with stage("repair" if kwargs.get("models") else "asr") as details:
            details["upload"] = bool(kwargs.get("prepared_file") or media.audio.file)
            return await groq.transcribe(media, options, context, **kwargs)

    async def evaluate(media, options, context):
        with stage("quality"):
            return await quality.evaluate_video(media, options, context, asr=asr)

    return inspect, evaluate


def snapshot():
    return {"startUnixMs": START_UNIX_MS, "spans": spans.copy()}
