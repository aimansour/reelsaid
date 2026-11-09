"""Account-scoped results and ownership backed by native Apify storage."""

import asyncio
import base64
import hashlib
import json
import zlib
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError, ApifyClientError

from .contracts import JsonObject, Outcome, Status, TranscriptOptions


CHECKPOINT_PART_SIZE = 512 * 1024
CLAIM_SHARDS = 64
DEFINITIVE_FREE = frozenset({"NO_AUDIO", "NO_SPEECH", "SILENCE", "MUSIC_ONLY"})
LOCK_REJECTED = frozenset({400, 403, 404, 409})
SHARED_REQUEST = {"url": "https://reelsaid.invalid/work", "uniqueKey": "reelsaid-work"}


class StateAccessError(ValueError):
    pass


class StateUnavailable(RuntimeError):
    pass


def _key(prefix: str, *identity: str) -> str:
    value = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return f"{prefix}-{value}"


def _result_key(video_id: str, options: TranscriptOptions) -> str:
    return _key("result-v1", video_id, options.language, str(options.prefer_captions), str(options.word_level_timestamps))


def claim_slot(video_id: str) -> int:
    return hashlib.sha256(video_id.encode()).digest()[0] % CLAIM_SHARDS


@dataclass(frozen=True)
class Lease:
    video_id: str
    tenant_id: str
    run_id: str
    claim_id: str
    slot: int
    request_id: str


@dataclass(frozen=True)
class CachedResult:
    revision: str
    status: Status
    payload: JsonObject


@dataclass(frozen=True)
class CacheLookup:
    result: CachedResult | None = None
    successful: CachedResult | None = None

    @property
    def revision(self) -> str | None:
        return self.result.revision if self.result else None

    @property
    def reusable(self) -> bool:
        return self.successful is not None

    def changed_since(self, baseline: "CacheLookup") -> bool:
        return self.result is not None and self.revision != baseline.revision


@dataclass(frozen=True)
class AnswerState:
    answered: bool = False
    first_seen_at: datetime | None = None
    is_new: bool = False
    first_seen_run_id: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    pending: tuple[JsonObject, ...] = ()
    completed: tuple[JsonObject, ...] = ()
    cursor: JsonObject | None = None
    filters: JsonObject | None = None
    stop_reason: str | None = None


class State:
    def __init__(
        self, client: ApifyClientAsync, store, tenant_id: str, run_id: str, *,
        namespace: str = "reelsaid-v1", lock_seconds: int = 90, storage_owner_id: str | None = None,
    ):
        if not tenant_id or not run_id:
            raise StateAccessError("State requires an authenticated account and run")
        self._client = client
        self._store = store
        self.tenant_id = tenant_id
        self.run_id = run_id
        self._namespace = namespace
        self._storage_owner_id = storage_owner_id or tenant_id
        self._client_key = uuid4().hex
        self.lock_duration = timedelta(seconds=lock_seconds)
        self._queues = {}
        self._guards: dict[int, asyncio.Lock] = {}
        self._active: dict[int, Lease] = {}
        self._staged: set[str] = set()

    @classmethod
    async def open(
        cls, client: ApifyClientAsync, tenant_id: str, run_id: str, *,
        namespace: str = "reelsaid-v1", lock_seconds: int = 90, storage_owner_id: str | None = None,
    ):
        try:
            store_info = await client.key_value_stores().get_or_create(name=f"{namespace}-state")
            store = client.key_value_store(store_info.id)
            await cls._restrict(store, store_info, storage_owner_id or tenant_id)
        except ApifyClientError as error:
            raise StateUnavailable("Account state is unavailable") from error
        return cls(client, store, tenant_id, run_id, namespace=namespace, lock_seconds=lock_seconds,
                   storage_owner_id=storage_owner_id)

    @staticmethod
    async def _restrict(resource, info, tenant_id: str) -> None:
        if info.user_id != tenant_id:
            raise StateAccessError("Storage belongs to a different account")
        if info.general_access != "RESTRICTED":
            updated = await resource.update(general_access="RESTRICTED")
            if updated.general_access != "RESTRICTED":
                raise StateUnavailable("Private storage access could not be confirmed")

    async def _queue_for(self, slot: int):
        if slot not in self._queues:
            info = await self._client.request_queues().get_or_create(name=f"{self._namespace}-work-{slot:02x}")
            queue = self._client.request_queue(info.id, client_key=self._client_key)
            await self._restrict(queue, info, self._storage_owner_id)
            registration = await queue.add_request(SHARED_REQUEST)
            self._queues[slot] = (queue, registration.request_id)
        return self._queues[slot]

    def _check_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_id:
            raise StateAccessError("State belongs to a different account")

    def _owns(self, lease: Lease) -> bool:
        return self._active.get(lease.slot) == lease

    async def _get(self, key: str) -> JsonObject | None:
        try:
            record = await self._store.get_record(key)
        except ApifyClientError as error:
            raise StateUnavailable("Account state could not be read") from error
        if record is None:
            return None
        value = record["value"]
        if not isinstance(value, dict):
            raise StateUnavailable("Account state record has an invalid shape")
        return value

    async def _set(self, key: str, value: JsonObject) -> None:
        try:
            await self._store.set_record(key, value, content_type="application/json")
        except ApifyClientError as error:
            raise StateUnavailable("Account state could not be saved") from error

    async def lookup(self, tenant_id: str, video_id: str, options: TranscriptOptions) -> CacheLookup:
        self._check_tenant(tenant_id)
        record = await self._get(_result_key(video_id, options))
        if not record:
            return CacheLookup()
        latest = CachedResult(**record["latest"])
        saved = record.get("successful")
        return CacheLookup(latest, latest if latest.status == "success" else CachedResult(**saved) if saved else None)

    async def acquire(
        self, video_id: str, run_id: str, *, options: TranscriptOptions | None = None,
        baseline: CacheLookup | None = None,
    ) -> Outcome[Lease]:
        if run_id != self.run_id:
            raise StateAccessError("State belongs to a different run")
        if baseline is not None and options is None:
            raise ValueError("Refresh coordination requires transcript options")
        slot = claim_slot(video_id)
        guard = self._guards.setdefault(slot, asyncio.Lock())
        try:
            async with guard:
                if slot in self._active:
                    return Outcome("deferred", "VIDEO_IN_PROGRESS", True)
                queue, expected_request_id = await self._queue_for(slot)
                head = await queue.list_and_lock_head(lock_duration=self.lock_duration, limit=1)
                if not head.items:
                    return Outcome("deferred", "VIDEO_IN_PROGRESS", True)
                if baseline is not None:
                    try:
                        changed = (await self.lookup(self.tenant_id, video_id, options)).changed_since(baseline)
                    except BaseException:
                        with suppress(ApifyClientError):
                            await queue.delete_request_lock(head.items[0].id)
                        raise
                    if changed:
                        await queue.delete_request_lock(head.items[0].id)
                        return Outcome("skipped", "RESULT_AVAILABLE")
                request_id = head.items[0].id
                if request_id != expected_request_id:
                    await queue.delete_request_lock(request_id)
                    raise StateUnavailable("Work queue contains an unexpected record")
                lease = Lease(video_id, self.tenant_id, run_id, uuid4().hex, slot, request_id)
                self._active[slot] = lease
                return Outcome("success", value=lease)
        except ApifyClientError as error:
            raise StateUnavailable("Work ownership could not be established") from error

    async def _renew_active(self, lease: Lease) -> bool:
        if not self._owns(lease):
            return False
        try:
            queue, _ = self._queues[lease.slot]
            refreshed = await queue.prolong_request_lock(
                lease.request_id, lock_duration=self.lock_duration,
            )
            if refreshed is not None:
                return True
        except ApifyApiError as error:
            if error.status_code not in LOCK_REJECTED:
                raise StateUnavailable("Work ownership could not be renewed") from error
        except ApifyClientError as error:
            raise StateUnavailable("Work ownership could not be renewed") from error
        del self._active[lease.slot]
        self._staged.discard(lease.claim_id)
        return False

    async def renew(self, lease: Lease) -> bool:
        if not self._owns(lease):
            return False
        async with self._guards[lease.slot]:
            return await self._renew_active(lease)

    async def release(self, lease: Lease) -> bool:
        if not self._owns(lease):
            return False
        async with self._guards[lease.slot]:
            if not self._owns(lease):
                return False
            del self._active[lease.slot]
            self._staged.discard(lease.claim_id)
            try:
                queue, _ = self._queues[lease.slot]
                await queue.delete_request_lock(lease.request_id)
            except ApifyApiError as error:
                if error.status_code in LOCK_REJECTED:
                    return False
                raise StateUnavailable("Work release could not be confirmed") from error
            except ApifyClientError as error:
                raise StateUnavailable("Work release could not be confirmed") from error
            return True

    async def stage(self, lease: Lease, options: TranscriptOptions, payload: JsonObject) -> bool:
        if not self._owns(lease):
            return False
        async with self._guards[lease.slot]:
            if not await self._renew_active(lease):
                return False
            key = _key("staged", _result_key(lease.video_id, options))
            record = {
                "resultKey": _result_key(lease.video_id, options), "runId": self.run_id,
                "claimId": lease.claim_id, "payload": payload,
            }
            if lease.claim_id in self._staged:
                return await self._get(key) == record
            await self._set(key, record)
            self._staged.add(lease.claim_id)
            return True

    async def load_stage(self, lease: Lease, options: TranscriptOptions = TranscriptOptions()) -> JsonObject | None:
        if not self._owns(lease):
            return None
        return await self._get(_key("staged", _result_key(lease.video_id, options)))

    async def load_settlement(self, lease: Lease, claim_id: str) -> JsonObject | None:
        if not self._owns(lease):
            return None
        return await self._get(_key("settlement", lease.video_id, claim_id))

    async def save_settlement(self, lease: Lease, claim_id: str, record: JsonObject) -> None:
        if not self._owns(lease):
            raise StateUnavailable("Billing ownership was lost")
        async with self._guards[lease.slot]:
            if not await self._renew_active(lease):
                raise StateUnavailable("Billing ownership was lost")
            await self._set(_key("settlement", lease.video_id, claim_id), record)

    async def load_run_billing(self) -> JsonObject | None:
        return await self._get(_key("run-billing", self.run_id))

    async def save_run_billing(self, lease: Lease, record: JsonObject) -> None:
        if not self._owns(lease):
            raise StateUnavailable("Billing ownership was lost")
        async with self._guards[lease.slot]:
            if not await self._renew_active(lease):
                raise StateUnavailable("Billing ownership was lost")
            await self._set(_key("run-billing", self.run_id), record)

    async def commit(
        self, lease: Lease, options: TranscriptOptions, status: Status, payload: JsonObject, *, recovered_claim: str | None = None,
    ) -> bool:
        if not self._owns(lease) or status not in {"success", "partial", "skipped"}:
            return False
        async with self._guards[lease.slot]:
            if not await self._renew_active(lease):
                return False
            if recovered_claim is not None:
                staged = await self.load_stage(lease, options)
                if not staged or staged["claimId"] != recovered_claim:
                    return False
            elif lease.claim_id not in self._staged:
                return False
            result = asdict(CachedResult(recovered_claim or lease.claim_id, status, payload))
            record = {"latest": result}
            if status != "success":
                previous = await self.lookup(self.tenant_id, lease.video_id, options)
                if previous.successful:
                    record["successful"] = asdict(previous.successful)
            await self._set(_result_key(lease.video_id, options), record)
            return True

    async def lookup_answer(self, tenant_id: str, watchlist_id: str | None, video_id: str) -> AnswerState:
        self._check_tenant(tenant_id)
        record = await self._get(_key("answer", video_id))
        if not record:
            return AnswerState()
        return AnswerState(True, datetime.fromisoformat(record["firstSeenAt"]), first_seen_run_id=record["firstSeenRunId"])

    async def record_answer(
        self, tenant_id: str, watchlist_id: str | None, video_id: str, outcome: Outcome[object],
        *, seen_at: datetime | None = None,
    ) -> AnswerState:
        current = await self.lookup_answer(tenant_id, watchlist_id, video_id)
        if current.answered or outcome.retryable or (
            outcome.status != "success" and (outcome.status != "skipped" or outcome.error_code not in DEFINITIVE_FREE)
        ):
            return current
        seen = seen_at or datetime.now(UTC)
        await self._set(_key("answer", video_id), {
            "firstSeenAt": seen.isoformat(), "firstSeenRunId": self.run_id, "watchlistId": watchlist_id,
        })
        return AnswerState(True, seen, True, self.run_id)

    async def save_checkpoint(self, tenant_id: str, dataset_id: str, checkpoint: Checkpoint) -> None:
        self._check_tenant(tenant_id)
        key = _key("checkpoint", dataset_id)
        payload = json.dumps(asdict(checkpoint), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        encoded = base64.b64encode(zlib.compress(payload.encode())).decode("ascii")
        if len(encoded) <= CHECKPOINT_PART_SIZE:
            await self._set(key, {"data": encoded})
            return
        generation = uuid4().hex
        offsets = range(0, len(encoded), CHECKPOINT_PART_SIZE)
        for index, start in enumerate(offsets):
            await self._set(_key("checkpoint-part", dataset_id, generation, str(index)), {
                "data": encoded[start:start + CHECKPOINT_PART_SIZE],
            })
        await self._set(key, {"generation": generation, "count": len(offsets)})

    async def load_checkpoint(self, tenant_id: str, dataset_id: str) -> Checkpoint | None:
        self._check_tenant(tenant_id)
        record = await self._get(_key("checkpoint", dataset_id))
        if not record:
            return None
        try:
            encoded = record.get("data")
            if encoded is None:
                parts = []
                for index in range(record["count"]):
                    part = await self._get(_key("checkpoint-part", dataset_id, record["generation"], str(index)))
                    if part is None:
                        raise StateUnavailable("Checkpoint is incomplete")
                    parts.append(part["data"])
                encoded = "".join(parts)
            payload = json.loads(zlib.decompress(base64.b64decode(encoded)))
            return Checkpoint(
                tuple(payload["pending"]), tuple(payload["completed"]), payload["cursor"], payload["filters"],
                payload["stop_reason"],
            )
        except (ValueError, KeyError, TypeError, zlib.error) as error:
            raise StateUnavailable("Checkpoint could not be read") from error


class LocalState(State):
    """Reuse state records with local SDK storage and process-scoped leases."""

    async def _get(self, key: str) -> JsonObject | None:
        value = await self._store.get_value(key)
        if value is not None and not isinstance(value, dict):
            raise StateUnavailable("Local state record has an invalid shape")
        return value

    async def _set(self, key: str, value: JsonObject) -> None:
        await self._store.set_value(key, value)

    async def acquire(
        self, video_id: str, run_id: str, *, options: TranscriptOptions | None = None,
        baseline: CacheLookup | None = None,
    ) -> Outcome[Lease]:
        if run_id != self.run_id:
            raise StateAccessError("State belongs to a different run")
        slot = claim_slot(video_id)
        async with self._guards.setdefault(slot, asyncio.Lock()):
            if slot in self._active:
                return Outcome("deferred", "VIDEO_IN_PROGRESS", True)
            if baseline is not None:
                if options is None:
                    raise ValueError("Refresh coordination requires transcript options")
                if (await self.lookup(self.tenant_id, video_id, options)).changed_since(baseline):
                    return Outcome("skipped", "RESULT_AVAILABLE")
            claim_id = uuid4().hex
            lease = Lease(video_id, self.tenant_id, run_id, claim_id, slot, claim_id)
            self._active[slot] = lease
            return Outcome("success", value=lease)

    async def _renew_active(self, lease: Lease) -> bool:
        return self._owns(lease)

    async def release(self, lease: Lease) -> bool:
        async with self._guards[lease.slot]:
            if not self._owns(lease):
                return False
            del self._active[lease.slot]
            self._staged.discard(lease.claim_id)
            return True
