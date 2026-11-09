"""Instrumentation copied into a disposable, private timing build."""

from contextlib import contextmanager
from functools import wraps
from time import perf_counter, time


START = perf_counter()
START_UNIX_MS = round(time() * 1000)
spans = []
policy = "conditional"


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


def mark(name):
    with stage(name):
        pass


def wrap_methods(owner, names):
    for method, label in names.items():
        setattr(owner, method, timed(label, getattr(owner, method)))


def instrument(output):
    from . import actor, audio_quality, groq, instagram, quality, state

    actor.discover = timed("discovery", actor.discover)
    wrap_methods(instagram.InstagramClient, {"_bootstrap": "guestBootstrap", "_graphql": "instagramGraph",
                                             "_get": "instagramPage"})
    wrap_methods(actor._Run, {"_restore": "restore", "_checkpoint": "checkpoint", "_deliver": "delivery"})
    wrap_methods(actor._Batch, {"reserve": "admission"})
    wrap_methods(output, {"push": "datasetWrite", "put": "recordWrite"})
    wrap_methods(state.State, {"lookup": "cacheLookup", "lookup_answer": "answerLookup", "acquire": "lease",
                               "stage": "durableStage", "commit": "durableCommit", "release": "release"})
    wrap_methods(audio_quality, {"_decode_audio": "decode"})
    inspect = timed("preflight", actor.inspect_media)
    original_analyze = audio_quality.analyze_pcm
    original_asset = audio_quality._speech_asset
    original_voice = audio_quality._voice_scores
    original_music = audio_quality._music_score

    async def speech_asset(*args, **kwargs):
        with stage("verificationMedia") as details:
            asset, path = await original_asset(*args, **kwargs)
            details.update(video=asset.has_video, sourceBytes=asset.source_bytes,
                           audioSpan=[float(value) for value in asset.audio_span] if asset.audio_span else None)
            return asset, path

    def voice(data):
        with stage("voiceScores") as details:
            scores = original_voice(data)
            details.update(peak=round(max(scores), 4), aboveThreshold=sum(score >= .5 for score in scores))
            return scores

    def music(data):
        with stage("musicScore") as details:
            score = original_music(data)
            details["score"] = round(score, 4)
            return score

    def analyze(data):
        with stage("classify") as details:
            evidence = original_analyze(data)
            details["verdict"] = evidence.classification
            return evidence

    audio_quality.analyze_pcm = analyze
    audio_quality._speech_asset = speech_asset
    audio_quality._voice_scores = voice
    audio_quality._music_score = music

    async def asr(media, options, context, **kwargs):
        with stage("repair" if kwargs.get("models") else "asr") as details:
            details["preparedUpload"] = bool(kwargs.get("prepared_file"))
            return await groq.transcribe(media, options, context, **kwargs)

    async def evaluate(media, options, context):
        with stage("quality"):
            return await quality.evaluate_video(media, options, context, asr=asr)

    return inspect, evaluate


def snapshot():
    return {"startUnixMs": START_UNIX_MS, "spans": spans.copy()}
