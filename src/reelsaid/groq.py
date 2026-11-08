"""Groq transcription transport and organization/model quota admission."""

import asyncio
import hashlib
import json
import math
import re
from collections import deque
from contextlib import asynccontextmanager, closing, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from curl_cffi import CurlMime
from curl_cffi.requests import AsyncSession, RequestsError

from .contracts import JsonObject, Outcome, RunContext, TranscriptOptions
from .input import classify_url
from .instagram import object_value, records
from .media import LOCAL_MEDIA_FORMATS, MediaClient, MediaError, MediaPlan, inspect_media


TURBO = "whisper-large-v3-turbo"
LARGE = "whisper-large-v3"
MODELS = (TURBO, LARGE)
ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


@dataclass(frozen=True)
class Quota:
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    audio_seconds_per_hour: int | None = None
    audio_seconds_per_day: int | None = None

    def __post_init__(self):
        if any(value is not None and (type(value) is not int or value <= 0) for value in (
            self.requests_per_minute, self.requests_per_day, self.audio_seconds_per_hour, self.audio_seconds_per_day,
        )):
            raise ValueError("Groq limits must be positive integers")


FREE_QUOTA = Quota(20, 2000, 7200, 28800)


@dataclass(frozen=True)
class GroqAccount:
    name: str
    key: str = field(repr=False)
    models: dict[str, Quota] = field(default_factory=lambda: dict.fromkeys(MODELS, FREE_QUOTA))
    shared: Quota | None = None


def load_accounts(keys_json: str, limits_json: str = "{}") -> list[GroqAccount]:
    try:
        keys, limits = json.loads(keys_json), json.loads(limits_json)
        if not isinstance(keys, dict) or not keys or not isinstance(limits, dict):
            raise ValueError
        if any(not name or not isinstance(key, str) or not key for name, key in keys.items()):
            raise ValueError
        if len(set(keys.values())) != len(keys) or not limits.keys() <= keys.keys():
            raise ValueError
        accounts = []
        for name, key in keys.items():
            config = limits.get(name, {})
            if not isinstance(config, dict) or not config.keys() <= {*MODELS, "shared"}:
                raise ValueError
            models = {
                model: Quota(**config[model]) if model in config else FREE_QUOTA
                for model in MODELS if model not in config or config[model] is not None
            }
            shared = Quota(**config["shared"]) if config.get("shared") is not None else None
            accounts.append(GroqAccount(name, key, models, shared))
        return accounts
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid Groq account or quota configuration") from None


@dataclass
class _Usage:
    time: float
    seconds: int


@dataclass
class _Bucket:
    quota: Quota
    usage: deque[_Usage] = field(default_factory=deque)
    cooldown_until: float = 0
    remaining: int | None = None
    reset: float = 0

    def _wait(self, now: float, window: int, limit: int | None, amount: int, *, audio: bool = False) -> float:
        if limit is None:
            return 0
        if amount > limit:
            return math.inf
        recent = [event for event in self.usage if event.time + window > now]
        used = sum(event.seconds for event in recent) if audio else len(recent)
        for event in recent:
            if used + amount <= limit:
                return 0
            used -= event.seconds if audio else 1
            if used + amount <= limit:
                return event.time + window - now
        return 0

    def wait(self, now: float, seconds: int) -> float:
        while self.usage and self.usage[0].time + 86400 <= now:
            self.usage.popleft()
        if self.reset <= now:
            self.remaining = None
        return max(
            self.cooldown_until - now,
            self.reset - now if self.remaining == 0 else 0,
            self._wait(now, 60, self.quota.requests_per_minute, 1),
            self._wait(now, 86400, self.quota.requests_per_day, 1),
            self._wait(now, 3600, self.quota.audio_seconds_per_hour, seconds, audio=True),
            self._wait(now, 86400, self.quota.audio_seconds_per_day, seconds, audio=True),
        )


@dataclass(frozen=True)
class Reservation:
    account: GroqAccount
    model: str
    usage: _Usage = field(repr=False)


@dataclass(frozen=True)
class ProviderResponse:
    status: int
    headers: dict[str, str]
    payload: JsonObject


_TIME_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")


def _delay(raw: str | None) -> float | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        seconds = float(raw)
        return max(0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        pass
    parts = list(_TIME_PART.finditer(raw))
    if parts and "".join(part.group() for part in parts) == raw:
        multipliers = {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}
        return sum(float(part[1]) * multipliers[part[2]] for part in parts)
    try:
        return max(0, (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class GroqPool:
    def __init__(self, accounts: list[GroqAccount], *, clock=monotonic, rotation_seed: str = ""):
        self.accounts = tuple(accounts)
        self.clock = clock
        self._lock = asyncio.Lock()
        self._models = {(a.name, model): _Bucket(quota) for a in accounts for model, quota in a.models.items()}
        self._shared = {account.name: _Bucket(account.shared) for account in accounts if account.shared}
        first = 0
        if accounts and rotation_seed:
            digest = hashlib.blake2s(rotation_seed.encode(), digest_size=4).digest()
            first = int.from_bytes(digest) % len(accounts)
        self._next = dict.fromkeys(MODELS, first)
        self._disabled: set[str] = set()

    async def reserve(
        self, models: tuple[str, ...], seconds: int, *, exclude: set[tuple[str, str]] | None = None,
    ) -> tuple[Reservation | None, float]:
        async with self._lock:
            now = self.clock()
            next_wait = math.inf
            for model in models:
                start = self._next[model]
                for offset in range(len(self.accounts)):
                    index = (start + offset) % len(self.accounts)
                    account = self.accounts[index]
                    pair = account.name, model
                    bucket = self._models.get(pair)
                    if bucket is None or account.name in self._disabled or (exclude and pair in exclude):
                        continue
                    shared = self._shared.get(account.name)
                    wait = max(bucket.wait(now, seconds), shared.wait(now, seconds) if shared else 0)
                    if wait > 0:
                        next_wait = min(next_wait, wait)
                        continue
                    usage = _Usage(now, seconds)
                    bucket.usage.append(usage)
                    if shared:
                        shared.usage.append(usage)
                    if bucket.remaining is not None:
                        bucket.remaining = max(0, bucket.remaining - 1)
                    self._next[model] = (index + 1) % len(self.accounts)
                    return Reservation(account, model, usage), 0
            return None, next_wait

    async def observe(self, reservation: Reservation, response: ProviderResponse) -> None:
        async with self._lock:
            now = self.clock()
            account = reservation.account.name
            bucket = self._models[account, reservation.model]
            if response.status == 401:
                self._disabled.add(account)
            if response.status in {400, 401, 403, 413, 422, 429}:
                reservation.usage.seconds = 0
            reset = _delay(response.headers.get("x-ratelimit-reset-requests"))
            remaining = response.headers.get("x-ratelimit-remaining-requests", "")
            if reset is not None and remaining.isdecimal():
                reported = int(remaining)
                if bucket.remaining is None or bucket.reset <= now:
                    bucket.remaining, bucket.reset = reported, now + reset
                else:
                    bucket.remaining = min(bucket.remaining, reported)
                    bucket.reset = max(bucket.reset, now + reset)
            if response.status == 429:
                delay = _delay(response.headers.get("retry-after"))
                if delay is None:
                    delay = reset if reset and remaining == "0" else 1
                bucket.cooldown_until = max(bucket.cooldown_until, now + max(0.1, delay))


class GroqTransport:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def send(
        self, account: GroqAccount, model: str, *, url: str | None, file: Path | None, language: str | None,
    ) -> ProviderResponse:
        fields = [
            ("model", model), ("response_format", "verbose_json"), ("temperature", "0"),
            ("timestamp_granularities[]", "segment"), ("timestamp_granularities[]", "word"),
        ]
        if url is not None:
            fields.append(("url", url))
        if language is not None:
            fields.append(("language", language))
        try:
            with closing(CurlMime()) as multipart:
                for key, value in fields:
                    multipart.addpart(key, data=value.encode())
                if file is not None:
                    multipart.addpart("file", filename=file.name, local_path=file)
                response = await self._session.post(
                    ENDPOINT, multipart=multipart, headers={"Authorization": f"Bearer {account.key}"},
                    timeout=40, allow_redirects=False,
                )
            try:
                payload = object_value(response.json())
            except ValueError:
                payload = {}
            return ProviderResponse(response.status_code, dict(response.headers), payload)
        except (RequestsError, OSError):
            return ProviderResponse(503, {}, {})


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float
    no_speech_prob: float | None = None
    avg_logprob: float | None = None
    compression_ratio: float | None = None


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class TranscriptDraft:
    text: str
    language: str | None
    segments: tuple[Segment, ...]
    words: tuple[Word, ...]
    provider_duration: float | None


def _number(value: object) -> float | None:
    if type(value) in (int, float):
        try:
            return float(value) if math.isfinite(value) else None
        except OverflowError:
            pass
    return None


def _timing(item: JsonObject, key: str) -> tuple[str, float, float] | None:
    text, start, end = item.get(key), _number(item.get("start")), _number(item.get("end"))
    if isinstance(text, str) and text.strip() and start is not None and end is not None and end >= start:
        return text, start, end
    return None


def _draft(payload: JsonObject, hint: str | None) -> TranscriptDraft | None:
    text = payload.get("text")
    if not isinstance(text, str):
        return None
    segments = tuple(
        Segment(*timing, _number(item.get("no_speech_prob")), _number(item.get("avg_logprob")),
                _number(item.get("compression_ratio")))
        for item in records(payload.get("segments")) if (timing := _timing(item, "text"))
    )
    words = tuple(
        Word(*timing) for item in records(payload.get("words")) if (timing := _timing(item, "word"))
    )
    language = payload.get("language")
    return TranscriptDraft(
        text.strip(), language if isinstance(language, str) and language else hint,
        segments, words, _number(payload.get("duration")),
    )


@asynccontextmanager
async def _prepare_upload(media: MediaPlan, context: RunContext):
    source = media.audio
    if source is None:
        raise MediaError("NO_AUDIO")
    path, upload = None, None
    try:
        if context.media_client:
            path = await context.media_client.materialize(source)
        else:
            async with AsyncSession(impersonate="chrome", trust_env=False) as session:
                path = await MediaClient(session).materialize(source)
        with NamedTemporaryFile(suffix=".flac", delete=False) as output:
            upload = Path(output.name)
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file",
            "-format_whitelist", LOCAL_MEDIA_FORMATS, "-i", str(path),
            "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(upload),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(45):
                await process.wait()
        except (TimeoutError, asyncio.CancelledError):
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        if process.returncode or not upload.stat().st_size:
            raise MediaError("AUDIO_PREPARATION_FAILED")
        yield upload
    except (OSError, TimeoutError) as error:
        raise MediaError("AUDIO_PREPARATION_FAILED", retryable=True) from error
    finally:
        if upload:
            upload.unlink(missing_ok=True)
        if path and source.file != path:
            path.unlink(missing_ok=True)


class GroqAdapter:
    def __init__(self, transport: GroqTransport, pool: GroqPool, *, upload=_prepare_upload, sleep=asyncio.sleep,
                 max_wait_seconds: float = 10):
        self.transport = transport
        self.pool = pool
        self._upload = upload
        self._sleep = sleep
        self._max_wait = max_wait_seconds

    async def _request(
        self, media: MediaPlan, options: TranscriptOptions, context: RunContext, models: tuple[str, ...],
        *, url: str | None = None, file: Path | None = None,
    ) -> Outcome[TranscriptDraft]:
        seconds = max(10, math.ceil(media.audio.duration_seconds))
        language = None if options.language == "auto" else options.language
        deadline = self.pool.clock() + self._max_wait
        exclude: set[tuple[str, str]] = set()
        transient = False
        for _ in range(max(2, len(self.pool.accounts) * len(models) + 1)):
            reservation = None
            while not context.expired():
                reservation, wait = await self.pool.reserve(models, seconds, exclude=exclude)
                if reservation:
                    break
                if self.pool.clock() + wait > deadline:
                    return Outcome("deferred", "PROVIDER_UNAVAILABLE" if transient else "PROVIDER_RATE_LIMITED", True)
                await self._sleep(min(max(0.01, wait), 1))
            if reservation is None:
                return Outcome("deferred", "TIME_LIMIT", True)
            response = await self.transport.send(
                reservation.account, reservation.model, url=url, file=file, language=language,
            )
            await self.pool.observe(reservation, response)
            if response.status == 200 and (draft := _draft(response.payload, language)) is not None:
                return Outcome("success", value=draft)
            if response.status == 429:
                continue
            if response.status in {401, 403, 408, 425} or response.status >= 500 or response.status == 200:
                transient = True
                exclude.add((reservation.account.name, reservation.model))
                continue
            error = object_value(response.payload.get("error"))
            code = error.get("code") or error.get("type")
            message = str(error.get("message") or "").casefold()
            if url and (
                response.status == 413 or code in {"media_fetch_failed", "invalid_audio_url", "file_too_large"}
                or "could not fetch" in message or "failed to fetch" in message
            ):
                return Outcome("failed", "PROVIDER_MEDIA_FETCH_FAILED", True)
            if language and ("language" in message or code == "invalid_language"):
                return Outcome("failed", "UNSUPPORTED_LANGUAGE")
            return Outcome("failed", "TRANSCRIPTION_FAILED")
        return Outcome("deferred", "PROVIDER_UNAVAILABLE" if transient else "PROVIDER_RATE_LIMITED", True)

    async def transcribe(
        self, media: MediaPlan, options: TranscriptOptions, context: RunContext, models: tuple[str, ...],
        *, prepared_file: Path | None = None,
    ) -> Outcome[TranscriptDraft]:
        if not media.audio:
            return Outcome("skipped", "NO_AUDIO")
        if prepared_file:
            return await self._request(media, options, context, models, file=prepared_file)
        safe = classify_url(media.audio.url)
        if not safe or safe[0] != "cdn":
            return Outcome("failed", "INVALID_MEDIA_DESTINATION")
        direct = await self._request(media, options, context, models, url=safe[1])
        if direct.error_code != "PROVIDER_MEDIA_FETCH_FAILED":
            return direct
        try:
            async with self._upload(media, context) as path:
                return await self._request(media, options, context, models, file=path)
        except MediaError as error:
            if error.code != "MEDIA_URL_EXPIRED" or not media.ref.metadata.shortcode or context.expired():
                return Outcome("failed", error.code, error.retryable)
        refreshed = await inspect_media(media.ref, context)
        if refreshed.status != "success":
            if refreshed.value:
                refreshed.value.close()
            return Outcome(refreshed.status, refreshed.error_code, refreshed.retryable)
        replacement = refreshed.value
        try:
            return await self._request(replacement, options, context, models, url=replacement.audio.url)
        finally:
            replacement.close()


async def transcribe(
    media: MediaPlan, options: TranscriptOptions, context: RunContext, *, models: tuple[str, ...] = MODELS,
    prepared_file: Path | None = None,
) -> Outcome[TranscriptDraft]:
    if context.groq is None:
        return Outcome("failed", "PROVIDER_UNAVAILABLE", True)
    return await context.groq.transcribe(media, options, context, models, prepared_file=prepared_file)
