"""Versioned dataset rows, timed subtitles, and a separate run receipt."""

import hashlib
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from urllib.parse import quote

import pycountry
import regex

from .contracts import InputRef, JsonObject, Outcome, VideoRef
from .groq import Segment, Word
from .quality import TranscriptResult


SCHEMA_VERSION = 1
SUMMARY_KEY = "SUMMARY"
DatasetRow = JsonObject
_SENTENCE_END = regex.compile(r'\p{Sentence_Terminal}+[\p{Pe}\p{Pf}"\']*')
_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "sr", "jr", "vs", "e.g", "i.e"}


@dataclass(frozen=True)
class BillingFields:
    charged: bool | None = False
    billed_minutes: int | None = 0
    charged_events: dict[str, int] | None = field(default_factory=dict)
    confirmed_charge_usd: Decimal | None = Decimal(0)
    cached: bool = False


@dataclass(frozen=True)
class SubtitleFiles:
    srt: str | None
    vtt: str | None


@dataclass(frozen=True)
class SubtitleRecord:
    format: str
    key: str
    content_type: str
    content: str
    store_id: str

    @property
    def reference(self) -> JsonObject:
        store = quote(self.store_id, safe="")
        key = quote(self.key, safe="")
        return {
            "key": self.key,
            "contentType": self.content_type,
            "url": f"https://api.apify.com/v2/key-value-stores/{store}/records/{key}",
        }


@dataclass(frozen=True)
class Continuation:
    dataset_id: str
    remaining: int | None
    reason: str

    def to_dict(self) -> JsonObject:
        return {"resumeFromDatasetId": self.dataset_id, "remaining": self.remaining, "reason": self.reason}


@dataclass(frozen=True)
class RunSummary:
    submitted: int
    unique: int
    duplicate: int
    successful: int
    partial: int
    failed: int
    skipped: int
    deferred: int
    input_errors: int
    cached: int
    billed: int
    unresolved_charges: int
    billed_minutes: int
    confirmed_charge_usd: Decimal
    charged_events: dict[str, int]
    reason_counts: dict[str, int]
    watchlist_id: str | None
    new_answers: int
    previously_answered: int
    stop_reason: str | None
    continuation: Continuation | None
    completed_dataset_ids: tuple[str, ...] = ()

    def to_dict(self) -> JsonObject:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "submitted": self.submitted,
            "discovered": self.unique + self.duplicate,
            "unique": self.unique,
            "duplicate": self.duplicate,
            "successful": self.successful,
            "partial": self.partial,
            "failed": self.failed,
            "skipped": self.skipped,
            "deferred": self.deferred,
            "inputErrors": self.input_errors,
            "cached": self.cached,
            "billed": self.billed,
            "unresolvedCharges": self.unresolved_charges,
            "billedMinutes": self.billed_minutes,
            "confirmedChargeUsd": float(self.confirmed_charge_usd),
            "chargedEvents": self.charged_events,
            "reasonCounts": self.reason_counts,
            "watchlistId": self.watchlist_id,
            "newAnswers": self.new_answers,
            "previouslyAnswered": self.previously_answered,
            "stopReason": self.stop_reason,
            "continuation": self.continuation.to_dict() if self.continuation else None,
            "completedDatasetIds": list(self.completed_dataset_ids),
        }


@lru_cache(maxsize=128)
def _language(value: str | None) -> str | None:
    if not value or not (value := value.strip().casefold()):
        return None
    try:
        match = pycountry.languages.lookup(value)
        return getattr(match, "alpha_2", None) or match.alpha_3
    except LookupError:
        return value


def _offsets(text: str, words: tuple[Word, ...]) -> list[tuple[int, int]] | None:
    cursor = 0
    offsets = []
    for word in words:
        part = word.text.strip()
        start = text.find(part, cursor)
        if start < 0:
            return None
        cursor = start + len(part)
        offsets.append((start, cursor))
    return offsets


def _sentence_ranges(text: str):
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        if match.group().startswith("."):
            previous = text[:match.start()]
            word = previous.split()[-1].casefold() if previous.split() else ""
            if word in _ABBREVIATIONS:
                continue
            if previous and end < len(text) and previous[-1].isdigit() and text[end].isdigit():
                continue
        if text[start:end].strip():
            yield start, end
        start = end
    if text[start:].strip():
        yield start, len(text)


def _segments(result: TranscriptResult) -> tuple[tuple[Segment, ...], str | None]:
    if result.words and (offsets := _offsets(result.text, result.words)) is not None:
        sentences = []
        cursor = 0
        for start, end in _sentence_ranges(result.text):
            selected = []
            while cursor < len(offsets) and offsets[cursor][0] < end:
                if offsets[cursor][1] > start:
                    selected.append(result.words[cursor])
                cursor += 1
            if not selected:
                break
            sentences.append(Segment(
                result.text[start:end].strip(), min(word.start for word in selected), max(word.end for word in selected),
            ))
        else:
            if sentences:
                return tuple(sentences), "sentence"
    if result.segments:
        return result.segments, "cue" if result.source == "captions" else "segment"
    return (), None


def _word_text(words: list[Word]) -> str:
    text = ""
    for word in words:
        part = word.text.strip()
        if not part:
            continue
        if text and regex.match(r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}]", part) and regex.search(
            r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}]$", text,
        ):
            text += part
        elif not text or regex.match(r"^\p{P}", part):
            text += part
        else:
            text += " " + part
    return text


def _hook(result: TranscriptResult) -> JsonObject | None:
    if result.words:
        selected = [index for index, word in enumerate(result.words) if word.start < 3 and word.end > 0]
        if not selected:
            return None
        words = [result.words[index] for index in selected]
        offsets = _offsets(result.text, result.words)
        if offsets is not None and selected == list(range(selected[0], selected[-1] + 1)):
            text = result.text[offsets[selected[0]][0]:offsets[selected[-1]][1]].strip()
        else:
            text = _word_text(words)
        return {
            "text": text, "startSeconds": max(0, min(word.start for word in words)),
            "endSeconds": min(3, max(word.end for word in words)), "timingGranularity": "word",
        }
    cues = [segment for segment in result.segments if 0 <= segment.start < segment.end <= 3]
    if not cues:
        return None
    return {
        "text": " ".join(cue.text.strip() for cue in cues), "startSeconds": min(cue.start for cue in cues),
        "endSeconds": max(cue.end for cue in cues), "timingGranularity": "cue" if result.source == "captions" else "segment",
    }


def _timed(entry: Segment | Word) -> JsonObject:
    return {"text": entry.text.strip(), "startSeconds": entry.start, "endSeconds": entry.end}


def _word_count(result: TranscriptResult) -> int:
    if result.words:
        return sum(any(character.isalnum() for character in word.text) for word in result.words)
    return sum(any(character.isalnum() for character in piece) for piece in regex.split(r"\b", result.text, flags=regex.WORD))


def _reference(ref: InputRef) -> JsonObject:
    return {"field": ref.field, "index": ref.index, "itemIndex": ref.item_index}


def _metadata(ref: VideoRef, result: TranscriptResult | None) -> JsonObject:
    metadata = ref.metadata
    return {
        "postUrl": metadata.post_url,
        "shortcode": metadata.shortcode,
        "mediaId": metadata.media_id,
        "publisher": metadata.publisher,
        "discoveryProfiles": list(metadata.discovery_profiles) if metadata.discovery_profiles else None,
        "coauthors": list(metadata.coauthors) if metadata.coauthors else None,
        "caption": metadata.caption,
        "publishedAt": metadata.published_at.isoformat() if metadata.published_at else None,
        "durationSeconds": float(result.duration_seconds) if result else metadata.duration_seconds,
        "coverUrl": metadata.cover_url,
        "audio": metadata.audio,
        "videoUrl": ref.video_url,
        "audioUrl": ref.audio_url,
        "viewCount": metadata.view_count,
        "playCount": metadata.play_count,
        "likeCount": metadata.like_count,
        "commentCount": metadata.comment_count,
        "carouselPosition": metadata.carousel_position,
        "pinned": metadata.pinned,
    }


def _quality(result: TranscriptResult | None, outcome: Outcome) -> JsonObject | None:
    if result is None:
        return None
    assessment = result.assessment
    known = assessment.affected_fraction is not None
    return {
        "speechClassification": result.speech_classification,
        "speechConfidence": result.speech_confidence,
        "affectedFraction": assessment.affected_fraction,
        "missingStart": assessment.missing_start if known else None,
        "missingEnd": assessment.missing_end if known else None,
        "missingInternal": assessment.missing_internal if known else None,
        "defects": [
            {"startSeconds": defect.start, "endSeconds": defect.end, "reason": defect.reason}
            for defect in assessment.defects
        ],
        "stopReason": outcome.error_code if outcome.status == "partial" else None,
    }


def to_row(
    ref: VideoRef | InputRef, outcome: Outcome[TranscriptResult], billing: BillingFields,
    *, include_word_timestamps: bool = False, subtitles: dict[str, JsonObject] | None = None,
    is_new: bool | None = None, first_seen_at: datetime | None = None, first_seen_run_id: str | None = None,
) -> DatasetRow:
    video = ref if isinstance(ref, VideoRef) else None
    value = outcome.value
    segments, timing = _segments(value) if value else ((), None)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "video" if video else "input",
        "videoId": video.video_id if video else None,
        "status": outcome.status,
        "errorCode": outcome.error_code,
        "retryable": outcome.retryable,
        "provenance": [_reference(item) for item in (video.provenance if video else (ref,))],
        "transcript": value.text if value else None,
        "language": _language(value.language) if value else None,
        "durationSeconds": float(value.duration_seconds) if value else video.metadata.duration_seconds if video else None,
        "wordCount": _word_count(value) if value else None,
        "segments": [_timed(segment) for segment in segments],
        "timingGranularity": timing,
        "wordLevelTimestamps": [_timed(word) for word in value.words] if value and value.words and include_word_timestamps else None,
        "hook": _hook(value) if value else None,
        "transcriptSource": value.source if value else None,
        "metadata": _metadata(video, value) if video else None,
        "quality": _quality(value, outcome),
        "subtitles": {kind: (subtitles or {}).get(kind) for kind in ("srt", "vtt")},
        "charged": billing.charged,
        "billedMinutes": billing.billed_minutes,
        "chargedEvents": billing.charged_events,
        "confirmedChargeUsd": float(billing.confirmed_charge_usd) if billing.confirmed_charge_usd is not None else None,
        "cached": billing.cached,
        "isNew": is_new,
        "firstSeenAt": first_seen_at.isoformat() if first_seen_at else None,
        "firstSeenRunId": first_seen_run_id,
    }


def _milliseconds(seconds: float) -> int:
    return int((Decimal(str(max(0, seconds))) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def _timecode(milliseconds: int, separator: str) -> str:
    seconds, remainder = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{remainder:03d}"


def subtitle_files(result: TranscriptResult, *, include_srt: bool = True, include_vtt: bool = True) -> SubtitleFiles:
    segments, _ = _segments(result)
    srt, vtt = [], []
    for index, segment in enumerate(segments, 1):
        start = _milliseconds(segment.start)
        end = max(start + 1, _milliseconds(segment.end))
        text = re.sub(r"\n[ \t]*\n+", "\n", segment.text.strip())
        if include_srt:
            srt.append(f"{index}\n{_timecode(start, ',')} --> {_timecode(end, ',')}\n{text}")
        if include_vtt:
            vtt.append(f"{_timecode(start, '.')} --> {_timecode(end, '.')}\n{html.escape(text, quote=False)}")
    return SubtitleFiles(
        "\n\n".join(srt) + "\n" if srt else None,
        "WEBVTT\n\n" + "\n\n".join(vtt) + "\n" if vtt else None,
    )


def subtitle_records(files: SubtitleFiles, video_id: str, store_id: str) -> tuple[SubtitleRecord, ...]:
    identity = hashlib.sha256(video_id.encode()).hexdigest()[:24]
    return tuple(
        SubtitleRecord(kind, f"subtitle-{kind}-{identity}.{kind}", content_type, content, store_id)
        for kind, content, content_type in (
            ("srt", files.srt, "application/x-subrip"), ("vtt", files.vtt, "text/vtt"),
        ) if content is not None
    )


def summarize(
    rows: list[DatasetRow], *, submitted: int, unique: int, duplicates: int,
    watchlist_id: str | None = None, previously_answered: int = 0, stop_reason: str | None = None,
    continuation: Continuation | None = None,
    completed_dataset_ids: tuple[str, ...] = (),
) -> RunSummary:
    videos = [row for row in rows if row["kind"] == "video"]
    statuses = Counter(row["status"] for row in videos)
    events = Counter()
    total = Decimal(0)
    for row in videos:
        events.update(row["chargedEvents"] or {})
        if row["confirmedChargeUsd"] is not None:
            total += Decimal(str(row["confirmedChargeUsd"]))
    return RunSummary(
        submitted=submitted, unique=unique, duplicate=duplicates,
        successful=statuses["success"], partial=statuses["partial"], failed=statuses["failed"],
        skipped=statuses["skipped"], deferred=statuses["deferred"], input_errors=len(rows) - len(videos),
        cached=sum(bool(row["cached"]) for row in videos), billed=sum(row["charged"] is True for row in videos),
        unresolved_charges=sum(row["charged"] is None for row in videos),
        billed_minutes=sum(row["billedMinutes"] or 0 for row in videos), confirmed_charge_usd=total,
        charged_events=dict(events), reason_counts=dict(Counter(row["errorCode"] for row in rows if row["errorCode"])),
        watchlist_id=watchlist_id, new_answers=sum(row["isNew"] is True for row in videos),
        previously_answered=previously_answered, stop_reason=stop_reason, continuation=continuation,
        completed_dataset_ids=completed_dataset_ids,
    )
