import sys
import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from .contracts import FilterOptions, InputPlan, InputRef, JsonObject, Outcome, RunOptions, Source, SourceKind, TranscriptOptions


_INSTAGRAM = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"}
_SHORT_LINKS = {"ig.me", "www.ig.me"}
_SHORTCODE = re.compile(r"[A-Za-z0-9_-]+")
_USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}")
_RESERVED = {"accounts", "about", "api", "challenge", "direct", "explore", "legal", "p", "reel", "reels", "share", "stories", "tv", "web"}
_SOURCE_FIELDS = ("startUrls", "profiles", "shortcodes", "datasetId", "datasetItems")
_OPTION_FIELDS = {
    "language", "preferCaptions", "wordLevelTimestamps", "includeSrt", "includeVtt",
    "dateFrom", "dateTo", "lastDays", "minViews", "minLikes", "minDurationSeconds", "maxDurationSeconds",
    "skipPinned", "sort", "maxResults", "watchlistId", "newReelsOnly", "forceRefresh", "resumeFromDatasetId",
}


def _string(value: object) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        if value and not any(character.isspace() or ord(character) < 32 for character in value):
            return value
    return None


def classify_url(value: object) -> tuple[SourceKind, str] | None:
    url = _string(value)
    if not url or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username is not None or parts.port not in (None, 443):
            return None
        host = parts.hostname or ""
    except ValueError:
        return None

    if host.endswith((".cdninstagram.com", ".fbcdn.net")) and parts.path not in ("", "/"):
        return "cdn", urlunsplit(parts._replace(fragment=""))

    path = parts.path.strip("/").split("/")
    if host in _SHORT_LINKS and parts.path not in ("", "/"):
        return "post", urlunsplit(parts._replace(fragment=""))
    if host not in _INSTAGRAM:
        return None
    if path[0] == "share" and (
        len(path) == 2 or (len(path) == 3 and path[1] in {"reel", "reels", "p", "tv"})
    ) and _SHORTCODE.fullmatch(path[-1]):
        return "post", urlunsplit(parts._replace(query="", fragment=""))
    if len(path) == 2 and path[0] in {"reel", "reels", "p", "tv"} and _SHORTCODE.fullmatch(path[1]):
        route = "reel" if path[0] == "reels" else path[0]
        return "post", f"https://www.instagram.com/{route}/{path[1]}/"
    handle = path[0].casefold()
    if handle not in _RESERVED and _USERNAME.fullmatch(handle) and (len(path) == 1 or path[1:] == ["reels"]):
        return "profile", handle
    return None


def _profile(value: object) -> str | None:
    handle = _string(value)
    if not handle:
        return None
    if "://" in handle:
        classified = classify_url(handle)
        return classified[1] if classified and classified[0] == "profile" else None
    handle = handle.removeprefix("@").casefold()
    if _USERNAME.fullmatch(handle) and handle not in _RESERVED:
        return handle
    return None


def parse_input(raw: JsonObject) -> InputPlan:
    sources: list[Source] = []
    outcomes: list[Outcome[None]] = []
    valid_options = True

    def error(field: str, code: str, index: int | None = None) -> None:
        outcomes.append(Outcome("failed", code, input_ref=InputRef(field, index)))

    for field in sorted(raw.keys() - set(_SOURCE_FIELDS) - _OPTION_FIELDS):
        error(field, "UNKNOWN_INPUT")

    for field in _SOURCE_FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field == "datasetId":
            if dataset := _string(value):
                sources.append(Source("dataset", dataset, InputRef(field)))
            else:
                error(field, "INVALID_DATASET_ID")
            continue

        if field in {"startUrls", "profiles", "shortcodes"} and isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            error(field, "INVALID_INPUT")
            continue
        for index, item in enumerate(value):
            ref = InputRef(field, index)
            if field == "startUrls":
                url = classify_url(item.get("url") if isinstance(item, dict) else item)
                if url:
                    sources.append(Source(url[0], url[1], ref))
                else:
                    error(field, "INVALID_URL", index)
            elif field == "profiles":
                if handle := _profile(item):
                    sources.append(Source("profile", handle, ref))
                else:
                    error(field, "INVALID_PROFILE", index)
            elif field == "shortcodes":
                code = _string(item)
                if code and _SHORTCODE.fullmatch(code):
                    sources.append(Source("shortcode", code, ref))
                else:
                    error(field, "INVALID_SHORTCODE", index)
            elif isinstance(item, dict) and item:
                sources.append(Source("dataset_item", item, ref))
            else:
                error(field, "INVALID_DATASET_ITEM", index)

    def invalid_option(field: str) -> None:
        nonlocal valid_options
        valid_options = False
        error(field, "INVALID_OPTION")

    def boolean(field: str, default: bool = False) -> bool:
        value = raw.get(field, default)
        if isinstance(value, bool):
            return value
        invalid_option(field)
        return default

    def identifier(field: str) -> str | None:
        value = _string(raw.get(field))
        if value is None and field in raw:
            invalid_option(field)
        return value

    def integer(field: str, minimum: int = 0) -> int | None:
        if field not in raw:
            return None
        value = raw[field]
        if type(value) is int and value >= minimum:
            return value
        invalid_option(field)
        return None

    def duration(field: str) -> float | None:
        if field not in raw:
            return None
        value = raw[field]
        if type(value) in (int, float) and 0 <= value <= sys.float_info.max:
            return float(value)
        invalid_option(field)
        return None

    def day(field: str) -> date | None:
        if field not in raw:
            return None
        value = raw[field]
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
        invalid_option(field)
        return None

    language = raw.get("language", "auto")
    language = language.strip().lower() if isinstance(language, str) else ""
    if not re.fullmatch(r"auto|[a-z]{2,3}", language):
        invalid_option("language")
        language = "auto"
    sort = raw.get("sort", "newest")
    if sort not in ("newest", "mostViewed"):
        invalid_option("sort")
        sort = "newest"
    filters = FilterOptions(
        date_from=day("dateFrom"),
        date_to=day("dateTo"),
        last_days=integer("lastDays", 1),
        min_views=integer("minViews"),
        min_likes=integer("minLikes"),
        min_duration_seconds=duration("minDurationSeconds"),
        max_duration_seconds=duration("maxDurationSeconds"),
        skip_pinned=boolean("skipPinned"),
        sort=sort,
    )
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        invalid_option("dateTo")
    if (
        filters.min_duration_seconds is not None and filters.max_duration_seconds is not None
        and filters.min_duration_seconds > filters.max_duration_seconds
    ):
        invalid_option("maxDurationSeconds")

    options = RunOptions(
        transcript=TranscriptOptions(
            language=language,
            prefer_captions=boolean("preferCaptions", True),
            word_level_timestamps=boolean("wordLevelTimestamps"),
            include_srt=boolean("includeSrt", True),
            include_vtt=boolean("includeVtt", True),
        ),
        max_results=integer("maxResults", 1),
        watchlist_id=identifier("watchlistId"),
        new_reels_only=boolean("newReelsOnly"),
        force_refresh=boolean("forceRefresh"),
        resume_from_dataset_id=identifier("resumeFromDatasetId"),
    )
    if not sources and not options.resume_from_dataset_id and not outcomes:
        error("input", "NO_SOURCE")
    return InputPlan(tuple(sources), tuple(outcomes), filters, options, valid_options)
