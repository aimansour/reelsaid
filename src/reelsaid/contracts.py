from dataclasses import dataclass
from datetime import date
from typing import Generic, Literal, TypeVar


JsonObject = dict[str, object]
Status = Literal["success", "partial", "skipped", "failed", "deferred"]
SourceKind = Literal["post", "cdn", "profile", "shortcode", "dataset", "dataset_item"]
T = TypeVar("T")


@dataclass(frozen=True)
class InputRef:
    field: str
    index: int | None = None


@dataclass(frozen=True)
class Outcome(Generic[T]):
    status: Status
    error_code: str | None = None
    retryable: bool = False
    value: T | None = None
    input_ref: InputRef | None = None


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    value: str | JsonObject
    ref: InputRef


@dataclass(frozen=True)
class FilterOptions:
    date_from: date | None = None
    date_to: date | None = None
    last_days: int | None = None
    min_views: int | None = None
    min_likes: int | None = None
    min_duration_seconds: float | None = None
    max_duration_seconds: float | None = None
    skip_pinned: bool = False
    sort: Literal["newest", "mostViewed"] = "newest"


@dataclass(frozen=True)
class TranscriptOptions:
    language: str = "auto"
    prefer_captions: bool = True
    word_level_timestamps: bool = False
    include_srt: bool = True
    include_vtt: bool = True


@dataclass(frozen=True)
class RunOptions:
    transcript: TranscriptOptions
    max_results: int | None = None
    watchlist_id: str | None = None
    new_reels_only: bool = False
    force_refresh: bool = False
    resume_from_dataset_id: str | None = None


@dataclass(frozen=True)
class InputPlan:
    sources: tuple[Source, ...]
    outcomes: tuple[Outcome[None], ...]
    filters: FilterOptions
    options: RunOptions
    valid_options: bool = True
