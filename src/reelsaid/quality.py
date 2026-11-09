"""Transcription quality, speech verification, and bounded repair."""

import html
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal

from curl_cffi.requests import AsyncSession

from .audio_quality import Interval, SpeechClass, SpeechEvidence, verified_audio
from .contracts import Outcome, RunContext, TranscriptOptions
from .groq import LARGE, Segment, TranscriptDraft, Word, prepare_upload, transcribe
from .media import MediaClient, MediaError, MediaPlan


MAX_BILLABLE_DEFECT = 0.20
MIN_DEFECT_SECONDS = 0.12
TRAILING_SPEECH_MARGIN = 0.55
TranscriptSource = Literal["captions", "asr"]
FREE_SPEECH_ERRORS = {
    "silence": "SILENCE", "music_only": "MUSIC_ONLY", "no_speech": "NO_SPEECH", "no_audio": "NO_AUDIO",
}


@dataclass(frozen=True)
class Defect:
    start: float
    end: float
    reason: str


@dataclass(frozen=True)
class Assessment:
    affected_fraction: float | None = None
    defects: tuple[Defect, ...] = ()
    missing_start: bool = False
    missing_end: bool = False
    missing_internal: bool = False

    @property
    def needs_repair(self) -> bool:
        return self.affected_fraction is not None and self.affected_fraction > MAX_BILLABLE_DEFECT + 1e-9


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str | None
    duration_seconds: Decimal
    segments: tuple[Segment, ...]
    words: tuple[Word, ...]
    source: TranscriptSource | None
    speech_classification: SpeechClass
    speech_confidence: float | None
    assessment: Assessment
    billable: bool

    @property
    def affected_fraction(self) -> float | None:
        return self.assessment.affected_fraction


def _usable(draft: TranscriptDraft) -> bool:
    return any(character.isalnum() for character in draft.text)


def _merge(intervals, timeline: float, *, gap: float = 0) -> tuple[Interval, ...]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        left, right = max(0, start), min(timeline, end)
        if right <= left:
            continue
        if merged and left <= merged[-1][1] + gap:
            merged[-1] = merged[-1][0], max(right, merged[-1][1])
        else:
            merged.append((left, right))
    return tuple(merged)


def _overlap(start: float, end: float, spans: tuple[Interval, ...]) -> float:
    return sum(max(0, min(end, right) - max(start, left)) for left, right in spans)


def _subtract(voiced: tuple[Interval, ...], covered: tuple[Interval, ...]) -> list[Interval]:
    missing = []
    for left, right in voiced:
        start = left
        for begin, end in covered:
            if end <= start:
                continue
            if begin >= right:
                break
            if begin > start:
                missing.append((start, begin))
            start = max(start, end)
            if start >= right:
                break
        if start < right:
            missing.append((start, right))
    return [(start, end) for start, end in missing if end - start >= MIN_DEFECT_SECONDS]


def _words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def _repeated_phrase(tokens: tuple[str, ...]) -> bool:
    return any(tokens[index:index + size] * 3 == tokens[index:index + 3 * size]
               for size in range(3, min(8, len(tokens) // 3) + 1)
               for index in range(len(tokens) - 3 * size + 1))


def assess(draft: TranscriptDraft, evidence: SpeechEvidence, duration: Decimal) -> Assessment:
    timeline = float(duration)
    if evidence.classification != "speech" or timeline <= 0:
        return Assessment()
    voiced = _merge(evidence.voiced, timeline)
    if not voiced:
        return Assessment()
    alignment = draft.words or draft.segments
    covered = _merge(((entry.start, entry.end) for entry in alignment), timeline, gap=0.28 if draft.words else 0)
    missing = _subtract(voiced, covered)
    defects = [Defect(start, end, "missing_speech") for start, end in missing]
    previous = None
    for segment in draft.segments:
        left, right = max(0, segment.start), min(timeline, segment.end)
        if right - left < MIN_DEFECT_SECONDS:
            continue
        supported = _overlap(left - 0.1, right + 0.1, voiced) >= min(0.12, (right - left) * .2)
        tokens = _words(segment.text)
        duplicate = previous and len(tokens) >= 3 and tokens == previous[0] and (
            not supported or left < previous[1] - 0.15
        )
        compressed = (segment.compression_ratio or 0) >= 2.5 and _repeated_phrase(tokens)
        if not supported or duplicate or compressed:
            claimed = _merge(
                ((max(left, word.start), min(right, word.end)) for word in draft.words), timeline, gap=0.28,
            ) or ((left, right),)
            if not supported:
                defects.extend(Defect(start, end, "unsupported_speech") for start, end in claimed)
            if duplicate or compressed:
                defects.extend(Defect(start, end, "repeated_text") for start, end in claimed)
        previous = tokens, right
    union = _merge(((defect.start, defect.end) for defect in defects), timeline)
    affected = sum(end - start for start, end in union) / timeline
    first, last = voiced[0][0], voiced[-1][1]
    return Assessment(
        affected, tuple(sorted(defects, key=lambda defect: (defect.start, defect.end, defect.reason))),
        any(start <= first + 0.001 for start, _ in missing),
        any(end >= last - 0.001 for _, end in missing),
        any(start > first + 0.001 and end < last - 0.001 for start, end in missing),
    )


def _suspect(draft: TranscriptDraft, media: MediaPlan) -> bool:
    duration = float(media.audio.duration_seconds)
    if not _usable(draft) or not draft.segments:
        return True
    audio = media.ref.metadata.audio or {}
    if audio.get("isOriginal") is False or media.audio.file:
        return True
    spans = _merge(((segment.start, segment.end) for segment in draft.segments), duration)
    edge = min(.9, max(.2, duration * .10))
    if not spans or spans[0][0] > edge or duration - spans[-1][1] > edge:
        return True
    if draft.words:
        first_word = min(word.start for word in draft.words)
        last_word = max(word.end for word in draft.words)
        if first_word > min(.45, edge) or duration - last_word > min(TRAILING_SPEECH_MARGIN, edge):
            return True
    if sum(end - start for start, end in spans) < duration * .60:
        return True
    if sum(character.isalnum() for character in draft.text) < duration * 1.5:
        return True
    tokens = tuple(_words(segment.text) for segment in draft.segments)
    if any(len(left) >= 3 and left == right for left, right in zip(tokens, tokens[1:])):
        return True
    return any(
        (segment.no_speech_prob or 0) >= .55 or (segment.avg_logprob or 0) <= -.85
        or (segment.compression_ratio or 0) >= 2.5 or _repeated_phrase(_words(segment.text))
        for segment in draft.segments
    )


_CUE = re.compile(
    r"^((?:\d+:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+((?:\d+:)?\d{2}:\d{2}[.,]\d{3})(?:\s|$)",
)


def _cue_time(value: str) -> float:
    total = 0.0
    for field in value.replace(",", ".").split(":"):
        total = total * 60 + float(field)
    return total


def parse_captions(text: str, language: str, duration: Decimal) -> TranscriptDraft | None:
    segments = []
    timeline = float(duration)
    for block in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").lstrip("\ufeff")):
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION", "WEBVTT")):
            continue
        for index, line in enumerate(lines[:2]):
            if match := _CUE.match(line):
                start, end = map(_cue_time, match.groups())
                cue = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[index + 1:]))).strip()
                if 0 <= start < min(timeline, end) and end <= timeline + .2 and any(character.isalnum() for character in cue):
                    segments.append(Segment(cue, start, min(timeline, end)))
                break
    if not segments or any(right.start < left.end for left, right in zip(segments, segments[1:])):
        return None
    return TranscriptDraft(" ".join(segment.text for segment in segments), language, tuple(segments), (), None)


async def read_captions(media: MediaPlan, context: RunContext) -> TranscriptDraft | None:
    async def read(client):
        for track in media.captions:
            try:
                contents = await client.read_text(track.url, context.now)
            except (MediaError, UnicodeError):
                continue
            if caption := parse_captions(contents, track.language, media.duration_seconds):
                return caption
        return None

    if context.media_client:
        return await read(context.media_client)
    async with AsyncSession(impersonate="chrome", trust_env=False) as session:
        return await read(MediaClient(session))


def _shift(entry, offset: float):
    return replace(entry, start=entry.start + offset, end=entry.end + offset)


async def _repair(media, options, context, draft, assessment, asr):
    audio = media.audio
    timeline = float(audio.duration_seconds)
    affected = _merge(((item.start, item.end) for item in assessment.defects), timeline)
    if audio.file and len(affected) == 1:
        start, end = max(0, affected[0][0] - .3), min(timeline, affected[0][1] + .3)
        for segment in draft.segments:
            if segment.start < end and segment.end > start:
                start, end = max(0, min(start, segment.start)), min(timeline, max(end, segment.end))
        if 0 < end - start < timeline * .75:
            try:
                async with prepare_upload(media, context, start=start, duration=end - start) as path:
                    window = replace(media, audio=replace(audio, duration_seconds=Decimal(str(end - start))))
                    response = await asr(window, options, context, models=(LARGE,), prepared_file=path)
                if response.value and _usable(response.value):
                    updated = response.value
                    segments = [entry for entry in draft.segments if entry.end <= start or entry.start >= end]
                    segments += [_shift(entry, start) for entry in updated.segments]
                    words = [entry for entry in draft.words if entry.end <= start or entry.start >= end]
                    words += [_shift(entry, start) for entry in updated.words]
                    segments.sort(key=lambda entry: entry.start)
                    words.sort(key=lambda entry: entry.start)
                    return Outcome("success", value=TranscriptDraft(
                        " ".join(entry.text.strip() for entry in segments),
                        draft.language or updated.language, tuple(segments), tuple(words), draft.provider_duration,
                    ))
                return response
            except MediaError:
                pass
    return await asr(media, options, context, models=(LARGE,))


def _clip(entries, duration: Decimal):
    timeline = float(duration)
    return tuple(
        replace(entry, start=max(0, entry.start), end=min(timeline, entry.end))
        for entry in sorted(entries, key=lambda entry: entry.start)
        if min(timeline, entry.end) > max(0, entry.start)
    )


def _assess_draft(draft, evidence, duration, source):
    assessment = assess(draft, evidence, duration)
    unsupported = tuple((defect.start, defect.end) for defect in assessment.defects
                        if defect.reason == "unsupported_speech")
    if source != "asr" or not unsupported:
        return draft, assessment
    boundary = max(end for _, end in evidence.voiced) + TRAILING_SPEECH_MARGIN
    text = draft.text.rstrip()
    retained = len(draft.segments)
    for segment in reversed(draft.segments):
        suffix = segment.text.strip()
        if (segment.start < boundary or not suffix or not text.endswith(suffix)
                or not _overlap(segment.start, segment.end, unsupported)):
            break
        text = text.removesuffix(suffix).rstrip()
        retained -= 1
    if not retained or not text or retained == len(draft.segments):
        return draft, assessment
    tail_start = min(entry.start for entry in draft.segments[retained:])
    cleaned = replace(draft, text=text, segments=draft.segments[:retained],
                      words=tuple(word for word in draft.words if word.end <= tail_start))
    return cleaned, assess(cleaned, evidence, duration)


def _result(media, draft, source, evidence, assessment, billable) -> TranscriptResult:
    return TranscriptResult(
        draft.text if draft else "", draft.language if draft else None, media.duration_seconds,
        _clip(draft.segments, media.duration_seconds) if draft else (),
        _clip(draft.words, media.duration_seconds) if draft else (),
        source, evidence.classification, evidence.confidence, assessment, billable,
    )


async def evaluate_video(
    media: MediaPlan, options: TranscriptOptions, context: RunContext, *,
    speech_probe=verified_audio, asr=transcribe, caption_reader=read_captions,
) -> Outcome[TranscriptResult]:
    if media.audio is None:
        return Outcome("skipped", "NO_AUDIO", value=_result(
            media, None, None, SpeechEvidence("no_audio"), Assessment(), False,
        ))
    if context.expired():
        return Outcome("deferred", "TIME_LIMIT", True)

    eligible = tuple(track for track in media.captions if track.is_original and track.language and (
        options.language == "auto" or track.language.casefold() == options.language
    ))
    draft, source = None, "asr"
    if options.prefer_captions and not options.word_level_timestamps and eligible:
        draft = await caption_reader(replace(media, captions=eligible), context)
        if draft and _usable(draft):
            source = "captions"
        else:
            draft = None
    audio_metadata = media.ref.metadata.audio or {}
    licensed_track = media.ref.dash_audio_url and audio_metadata.get("isOriginal") is False
    if draft is None and not (media.audio.file or licensed_track):
        initial = await asr(media, options, context)
        if initial.value is None:
            return Outcome(initial.status, initial.error_code, initial.retryable)
        draft = initial.value
        if not _suspect(draft, media):
            return Outcome("success", value=_result(
                media, draft, source, SpeechEvidence("speech"), Assessment(), True,
            ))

    async with speech_probe(media, context) as (evidence, inspected):
        if code := FREE_SPEECH_ERRORS.get(evidence.classification):
            return Outcome("skipped", code, value=_result(media, None, None, evidence, Assessment(), False))
        if draft is None:
            initial = await asr(inspected, options, context)
            if initial.value is None:
                return Outcome(initial.status, initial.error_code, initial.retryable)
            draft = initial.value
        draft, quality = _assess_draft(draft, evidence, media.duration_seconds, source)
        if source == "captions" and (quality.affected_fraction is None or quality.needs_repair):
            fallback = await asr(inspected, options, context)
            if fallback.value:
                draft, source = fallback.value, "asr"
                draft, quality = _assess_draft(draft, evidence, media.duration_seconds, source)
        retryable = False
        if quality.needs_repair and not context.expired():
            repair = await _repair(inspected, options, context, draft, quality, asr)
            retryable = repair.retryable
            if repair.value and _usable(repair.value):
                repaired, reassessed = _assess_draft(repair.value, evidence, media.duration_seconds, "asr")
                if reassessed.affected_fraction is not None and (
                    not _usable(draft) or reassessed.affected_fraction < quality.affected_fraction
                ):
                    draft, source, quality = repaired, "asr", reassessed
        if not _usable(draft):
            return Outcome("failed", "TRANSCRIPTION_FAILED", retryable, _result(
                media, None, None, evidence, quality, False,
            ))
        verified = quality.affected_fraction is not None
        billable = verified and not quality.needs_repair
        result = _result(media, draft, source, evidence, quality, billable)
        if not verified:
            return Outcome("partial", "QUALITY_UNVERIFIED", value=result)
        if quality.needs_repair:
            return Outcome("partial", "QUALITY_LIMIT_EXCEEDED", retryable, result)
        if quality.defects:
            return Outcome("partial", "TRANSCRIPT_PARTIAL", value=result)
        return Outcome("success", value=result)
