from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Generic, Literal, TypeVar

if TYPE_CHECKING:
    from apify_client import ApifyClientAsync

    from .groq import GroqAdapter
    from .instagram import InstagramClient
    from .media import MediaClient


JsonObject = dict[str, object]
Status = Literal["success", "partial", "skipped", "failed", "deferred"]
SourceKind = Literal["post", "cdn", "profile", "shortcode", "dataset", "dataset_item"]
T = TypeVar("T")


@dataclass(frozen=True)
class InputRef:
    field: str
    index: int | None = None
    item_index: int | None = None


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


@dataclass(frozen=True)
class VideoMetadata:
    post_url: str | None = None
    shortcode: str | None = None
    media_id: str | None = None
    publisher: str | None = None
    discovery_profiles: tuple[str, ...] = ()
    coauthors: tuple[str, ...] = ()
    caption: str | None = None
    published_at: datetime | None = None
    duration_seconds: float | None = None
    cover_url: str | None = None
    audio: JsonObject | None = None
    view_count: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    carousel_position: int | None = None
    pinned: bool | None = None


@dataclass(frozen=True)
class CaptionCandidate:
    url: str
    language: str | None = None
    is_original: bool = False


@dataclass(frozen=True)
class VideoRef:
    video_id: str
    metadata: VideoMetadata
    provenance: tuple[InputRef, ...]
    video_url: str | None = None
    audio_url: str | None = None
    alternate_video_urls: tuple[str, ...] = ()
    caption_candidates: tuple[CaptionCandidate, ...] = ()
    dash_audio_url: str | None = None


@dataclass(frozen=True)
class RunContext:
    instagram: InstagramClient
    apify: ApifyClientAsync
    now: datetime
    expired: Callable[[], bool]
    media_client: MediaClient | None = None
    groq: GroqAdapter | None = None
    discovery_concurrency: int = 1
