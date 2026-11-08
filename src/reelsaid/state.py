"""Account-scoped results and checkpoint state with fenced, cross-run video leases."""

import base64
import hashlib
import json
import zlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from curl_cffi.requests import AsyncSession, RequestsError

from .contracts import JsonObject, Outcome, Status, TranscriptOptions


CHECKPOINT_PART_SIZE = 128 * 1024
DEFINITIVE_FREE = frozenset({"NO_AUDIO", "NO_SPEECH", "SILENCE", "MUSIC_ONLY"})
Parameter = str | int | None


class StateAccessError(ValueError):
    pass


class StateUnavailable(RuntimeError):
    pass


class StateBackend(Protocol):
    async def query(self, operation: str, *parameters: Parameter) -> list[JsonObject]: ...


class D1Backend:
    """Client for the private, allowlisted state API."""

    def __init__(self, session: AsyncSession, origin: str, secret: str):
        url = urlsplit(origin)
        if url.scheme != "https" or not url.hostname or url.username or url.path not in ("", "/") or url.query or url.fragment:
            raise StateAccessError("Invalid state service origin")
        if not secret:
            raise StateAccessError("Missing state service credential")
        self._session = session
        self._url = origin.rstrip("/") + "/v1/query"
        self._headers = {"Authorization": f"Bearer {secret}"}

    async def query(self, operation: str, *parameters: Parameter) -> list[JsonObject]:
        try:
            response = await self._session.post(
                self._url,
                headers=self._headers,
                json={"operation": operation, "parameters": parameters},
                allow_redirects=False,
                timeout=8,
            )
            if response.status_code == 200:
                records = response.json()
                if isinstance(records, list) and all(isinstance(row, dict) for row in records):
                    return records
        except (RequestsError, ValueError):
            pass
        raise StateUnavailable("State service could not complete the operation")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _fingerprint(options: TranscriptOptions) -> str:
    identity = (1, options.language, options.prefer_captions, options.word_level_timestamps)
    return hashlib.sha256(_json(identity).encode()).hexdigest()


@dataclass(frozen=True)
class Lease:
    video_id: str
    tenant_id: str
    run_id: str
    fence: str
    expires_ms: int

    def parameters(self) -> tuple[str, str, str, str]:
        return self.video_id, self.tenant_id, self.run_id, self.fence


@dataclass(frozen=True)
class CachedResult:
    revision: str
    status: Status
    payload: JsonObject


@dataclass(frozen=True)
class CacheLookup:
    result: CachedResult | None = None

    @property
    def revision(self) -> str | None:
        return self.result.revision if self.result else None

    @property
    def reusable(self) -> bool:
        return self.result is not None and self.result.status == "success"

    def changed_since(self, baseline: "CacheLookup") -> bool:
        return self.result is not None and self.revision != baseline.revision


@dataclass(frozen=True)
class AnswerState:
    answered: bool = False
    first_seen_at: datetime | None = None
    is_new: bool = False


@dataclass(frozen=True)
class Checkpoint:
    pending: tuple[JsonObject, ...] = ()
    completed: tuple[JsonObject, ...] = ()
    cursor: JsonObject | None = None
    filters: JsonObject | None = None
    stop_reason: str | None = None


class State:
    def __init__(self, backend: StateBackend, tenant_id: str, run_id: str, *, lease_ms: int = 90_000):
        if not tenant_id or not run_id or lease_ms <= 0:
            raise StateAccessError("State requires an authenticated account and run")
        self._backend = backend
        self.tenant_id = tenant_id
        self.run_id = run_id
        self._lease_ms = lease_ms

    def _check_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_id:
            raise StateAccessError("State belongs to a different account")

    def _owns(self, lease: Lease) -> bool:
        return lease.tenant_id == self.tenant_id and lease.run_id == self.run_id

    async def lookup(self, tenant_id: str, video_id: str, options: TranscriptOptions) -> CacheLookup:
        self._check_tenant(tenant_id)
        rows = await self._backend.query("lookup", tenant_id, video_id, _fingerprint(options))
        if not rows:
            return CacheLookup()
        row = rows[0]
        return CacheLookup(CachedResult(row["revision"], row["status"], json.loads(row["payload"])))

    async def acquire(
        self, video_id: str, run_id: str, *, options: TranscriptOptions | None = None,
        baseline: CacheLookup | None = None,
    ) -> Outcome[Lease]:
        if run_id != self.run_id:
            raise StateAccessError("State belongs to a different run")
        if baseline is not None and options is None:
            raise ValueError("Refresh coordination requires transcript options")
        fence = uuid4().hex
        rows = await self._backend.query(
            "acquire", video_id, self.tenant_id, run_id, fence, self._lease_ms,
            _fingerprint(options) if baseline is not None else None,
            baseline.revision if baseline is not None else None,
        )
        if rows:
            return Outcome("success", value=Lease(video_id, self.tenant_id, run_id, fence, rows[0]["expires_ms"]))
        if baseline is not None and (await self.lookup(self.tenant_id, video_id, options)).changed_since(baseline):
            return Outcome("skipped", "RESULT_AVAILABLE")
        return Outcome("deferred", "VIDEO_IN_PROGRESS", True)

    async def renew(self, lease: Lease) -> Lease | None:
        if not self._owns(lease):
            return None
        rows = await self._backend.query("renew", *lease.parameters(), self._lease_ms)
        return Lease(*lease.parameters(), rows[0]["expires_ms"]) if rows else None

    async def release(self, lease: Lease) -> bool:
        return self._owns(lease) and bool(await self._backend.query("release", *lease.parameters()))

    async def stage(self, lease: Lease, options: TranscriptOptions, payload: JsonObject) -> bool:
        if not self._owns(lease):
            return False
        return bool(await self._backend.query("stage", *lease.parameters(), _fingerprint(options), _json(payload)))

    async def commit(self, lease: Lease, options: TranscriptOptions, status: Status, payload: JsonObject) -> bool:
        if not self._owns(lease) or status not in {"success", "partial", "skipped"}:
            return False
        return bool(await self._backend.query(
            "commit", *lease.parameters(), _fingerprint(options), status, _json(payload),
        ))

    async def lookup_answer(self, tenant_id: str, watchlist_id: str, video_id: str) -> AnswerState:
        self._check_tenant(tenant_id)
        rows = await self._backend.query("lookup_answer", tenant_id, watchlist_id, video_id)
        if not rows:
            return AnswerState()
        return AnswerState(True, datetime.fromtimestamp(rows[0]["first_seen_ms"] / 1000, UTC))

    async def record_answer(
        self, tenant_id: str, watchlist_id: str, video_id: str, outcome: Outcome[object],
    ) -> AnswerState:
        self._check_tenant(tenant_id)
        if outcome.retryable or (
            outcome.status != "success" and (outcome.status != "skipped" or outcome.error_code not in DEFINITIVE_FREE)
        ):
            return await self.lookup_answer(tenant_id, watchlist_id, video_id)
        rows = await self._backend.query("record_answer", tenant_id, watchlist_id, video_id)
        if rows:
            return AnswerState(True, datetime.fromtimestamp(rows[0]["first_seen_ms"] / 1000, UTC), True)
        return await self.lookup_answer(tenant_id, watchlist_id, video_id)

    async def save_checkpoint(self, tenant_id: str, dataset_id: str, checkpoint: Checkpoint) -> None:
        self._check_tenant(tenant_id)
        payload = base64.b64encode(zlib.compress(_json(asdict(checkpoint)).encode())).decode("ascii")
        generation = uuid4().hex
        parts = range(0, len(payload), CHECKPOINT_PART_SIZE)
        for index, start in enumerate(parts):
            await self._backend.query(
                "put_checkpoint_part", tenant_id, dataset_id, generation, index,
                payload[start:start + CHECKPOINT_PART_SIZE],
            )
        saved = await self._backend.query("publish_checkpoint", tenant_id, dataset_id, generation, len(parts))
        if not saved:
            raise StateUnavailable("Checkpoint publication was not confirmed")
        if previous := saved[0]["previous_generation"]:
            await self._backend.query("delete_checkpoint_parts", tenant_id, dataset_id, previous)

    async def load_checkpoint(self, tenant_id: str, dataset_id: str) -> Checkpoint | None:
        self._check_tenant(tenant_id)
        rows = await self._backend.query("load_checkpoint", tenant_id, dataset_id)
        if not rows:
            return None
        if rows[0]["chunk_count"] != len(rows) or any(index != row["part"] for index, row in enumerate(rows)):
            raise StateUnavailable("Checkpoint is incomplete")
        try:
            payload = json.loads(zlib.decompress(base64.b64decode("".join(row["payload"] for row in rows))))
            return Checkpoint(
                tuple(payload["pending"]), tuple(payload["completed"]), payload["cursor"], payload["filters"],
                payload["stop_reason"],
            )
        except (ValueError, KeyError, TypeError, zlib.error) as error:
            raise StateUnavailable("Checkpoint could not be read") from error
