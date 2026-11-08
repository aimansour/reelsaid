"""Run ReelSaid from validated input through durable delivery."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import Protocol

from apify_client.errors import ApifyClientError

from .billing import BillingError, ChargeProvider, ChargeReceipt, RunPricing, Settlement, free_receipt
from .contracts import CaptionCandidate, InputRef, JsonObject, Outcome, RunContext, TranscriptOptions, VideoMetadata, VideoRef
from .discovery import DiscoveryCursor, discover
from .input import parse_input
from .media import MediaPlan, inspect_media
from .output import (
    SUMMARY_KEY, BillingFields, Continuation, RunSummary, SubtitleFiles, subtitle_files, subtitle_records, summarize, to_row,
)
from .quality import TranscriptResult, evaluate_video
from .state import DEFINITIVE_FREE, AnswerState, Checkpoint, Lease, State, StateUnavailable


class Output(Protocol):
    dataset_id: str
    store_id: str

    async def existing(self) -> list[JsonObject]: ...
    async def push(self, row: JsonObject) -> None: ...
    async def put(self, key: str, value: object, content_type: str = "application/json") -> None: ...


@dataclass(frozen=True, kw_only=True)
class ActorContext(RunContext):
    output: Output
    state: State | None
    pricing: RunPricing
    provider: ChargeProvider | None = None
    inspect: Callable[[VideoRef, RunContext], Awaitable[Outcome[MediaPlan]]] = inspect_media
    evaluate: Callable[[MediaPlan, TranscriptOptions, RunContext], Awaitable[Outcome[TranscriptResult]]] = evaluate_video
    remaining_seconds: Callable[[], float | None] = lambda: None
    read_previous: Callable[[str], Awaitable[list[JsonObject]]] | None = None
    claim_wait_seconds: float = 3.0


def _encode_video(video: VideoRef) -> JsonObject:
    data = asdict(video)
    if video.metadata.published_at:
        data["metadata"]["published_at"] = video.metadata.published_at.isoformat()
    return data


def _decode_video(data: JsonObject) -> VideoRef:
    metadata = dict(data["metadata"])
    if metadata["published_at"]:
        metadata["published_at"] = datetime.fromisoformat(metadata["published_at"])
    for key in ("discovery_profiles", "coauthors"):
        metadata[key] = tuple(metadata[key])
    return VideoRef(
        data["video_id"], VideoMetadata(**metadata), tuple(InputRef(**item) for item in data["provenance"]),
        data["video_url"], data["audio_url"], tuple(data["alternate_video_urls"]),
        tuple(CaptionCandidate(**item) for item in data["caption_candidates"]),
    )


def _payload(ref, outcome, options) -> JsonObject:
    files = subtitle_files(outcome.value) if outcome.value else SubtitleFiles(None, None)
    return {"row": to_row(ref, outcome, BillingFields(), include_word_timestamps=options.word_level_timestamps),
            "files": asdict(files)}


def _definitive(row: JsonObject) -> bool:
    return row["status"] == "success" or row["status"] == "skipped" and row["errorCode"] in DEFINITIVE_FREE


class _Run:
    def __init__(self, raw: JsonObject, context: ActorContext):
        self.raw = raw
        self.context = context
        self.output = context.output
        self.state = context.state
        self.plan = parse_input(raw)
        self.options = self.plan.options
        self.rows: list[JsonObject] = []
        self.completed: dict[str, JsonObject] = {}
        self.known: set[str] = set()
        self.duplicates = 0
        self.previous = 0
        self.remaining: list[VideoRef] = []
        self.retry: list[VideoRef] = []
        self.source_cursor: DiscoveryCursor | None = None
        self.retry_sources: set[int] = set()
        self.stop_reason: str | None = None
        self.filter_time = context.now
        self.restored = False

    async def _push(self, row: JsonObject) -> None:
        await self.output.push(row)
        self.rows.append(row)

    async def _input_row(self, outcome) -> None:
        row = to_row(outcome.input_ref, outcome, BillingFields())
        if row not in self.rows:
            await self._push(row)

    async def _checkpoint(self) -> None:
        if self.state is None:
            return
        cursor = {"next": asdict(self.source_cursor) if self.source_cursor else None,
                  "retrySources": sorted(self.retry_sources)}
        await self.state.save_checkpoint(
            self.state.tenant_id, self.output.dataset_id, Checkpoint(
                tuple(_encode_video(item) for item in [*self.retry, *self.remaining]),
                tuple(self.completed.values()), cursor, {"input": self.raw, "now": self.filter_time.isoformat()},
                self.stop_reason,
            ),
        )

    async def _restore(self) -> bool:
        resume_id = self.options.resume_from_dataset_id
        if self.state is None:
            if self.plan.sources or resume_id:
                await self._input_row(Outcome("failed", "STATE_UNAVAILABLE", True, input_ref=InputRef("input")))
                return False
            return True
        target = resume_id or self.output.dataset_id
        saved = await self.state.load_checkpoint(self.state.tenant_id, target)
        if not saved:
            if resume_id:
                await self._input_row(Outcome("failed", "CHECKPOINT_NOT_FOUND", input_ref=InputRef("resumeFromDatasetId")))
                return False
            return True
        self.raw = saved.filters["input"]
        self.restored = True
        self.filter_time = datetime.fromisoformat(saved.filters["now"])
        self.plan = parse_input(self.raw)
        self.options = self.plan.options
        self.remaining = [_decode_video(item) for item in saved.pending]
        self.completed = {item["videoId"]: item for item in saved.completed}
        position = saved.cursor.get("next")
        if position and position["profile_cursor"] is not None:
            position["profile_cursor"] = tuple(position["profile_cursor"])
        self.source_cursor = DiscoveryCursor(**position) if position else None
        self.retry_sources = set(saved.cursor.get("retrySources", ()))
        if not resume_id or self.context.read_previous and saved.stop_reason in {None, "DELIVERY_INTERRUPTED"}:
            if resume_id:
                try:
                    prior = await self.context.read_previous(resume_id)
                except ApifyClientError:
                    prior = []
            else:
                self.rows = await self.output.existing()
                prior = self.rows
            current = {row["videoId"]: row for row in prior if row["videoId"]}
            for video in self.remaining:
                row = current.get(video.video_id)
                if row and row["retryable"] and not resume_id:
                    self.retry.append(video)
                elif row and not row["retryable"]:
                    self._mark_completed(row, dataset_id=target)
                    if _definitive(row):
                        seen = datetime.fromisoformat(row["firstSeenAt"]) if row["firstSeenAt"] else None
                        await self._record_answer(row, seen)
            self.remaining = [
                video for video in self.remaining if video.video_id not in self.completed
                and (resume_id or video.video_id not in current)
            ]
        self.known.update(self.completed)
        self.known.update(video.video_id for video in self.remaining)
        return True

    async def _discovery(self) -> None:
        plan = replace(self.plan, outcomes=())
        positions = {source.ref: index for index, source in enumerate(plan.sources)}
        lookup = replace(self.context, now=self.filter_time)
        batches = []
        if not self.restored or self.source_cursor:
            batches.append(await discover(plan, lookup, continuation=self.source_cursor))
            self.source_cursor = batches[-1].continuation
        retried = set(self.retry_sources)
        if retried and not self.context.expired():
            subset = tuple(source for index, source in enumerate(plan.sources) if index in retried)
            retries = await discover(replace(plan, sources=subset), lookup)
            batches.append(retries)
            self.retry_sources.clear()
            if retries.continuation:
                self.retry_sources.update(sorted(retried)[retries.continuation.source_index:])
        for found in batches:
            self.duplicates += found.duplicates
            for outcome in found.input_outcomes:
                await self._input_row(outcome)
                if outcome.retryable:
                    index = positions.get(replace(outcome.input_ref, item_index=None))
                    if index is not None:
                        self.retry_sources.add(index)
            for outcome in found.video_outcomes:
                ref = outcome.value
                if ref.video_id not in self.known:
                    self.known.add(ref.video_id)
                    row = to_row(ref, Outcome("skipped", outcome.error_code), BillingFields())
                    await self._push(row)
                    self._mark_completed(row)
            for ref in found.videos:
                if ref.video_id not in self.known:
                    self.known.add(ref.video_id)
                    self.remaining.append(ref)

    def _mark_completed(self, row: JsonObject, *, dataset_id: str | None = None) -> None:
        self.completed[row["videoId"]] = {
            "videoId": row["videoId"], "datasetId": dataset_id or self.output.dataset_id, "status": row["status"],
        }

    async def _record_answer(self, row: JsonObject, when: datetime | None) -> None:
        await self.state.record_answer(
            self.state.tenant_id, self.options.watchlist_id, row["videoId"],
            Outcome(row["status"], row["errorCode"], row["retryable"]), seen_at=when,
        )

    async def _render(
        self, ref: VideoRef, payload: JsonObject, receipt: ChargeReceipt, answer: AnswerState, *, cached: bool = False,
    ) -> JsonObject:
        row = dict(payload["row"])
        current = to_row(ref, Outcome(row["status"]), BillingFields())
        metadata = dict(row["metadata"])
        for field, value in current["metadata"].items():
            if value is not None and (value != [] or field == "discoveryProfiles"):
                metadata[field] = value
        metadata["durationSeconds"] = row["durationSeconds"]
        files = SubtitleFiles(
            payload["files"]["srt"] if self.options.transcript.include_srt else None,
            payload["files"]["vtt"] if self.options.transcript.include_vtt else None,
        )
        links = dict.fromkeys(("srt", "vtt"))
        for file in subtitle_records(files, ref.video_id, self.output.store_id):
            await self.output.put(file.key, file.content.encode(), file.content_type)
            links[file.format] = file.reference
        row.update(
            metadata=metadata, provenance=current["provenance"], subtitles=links, cached=cached,
            charged=receipt.charged, billedMinutes=receipt.billed_minutes, chargedEvents=receipt.events,
            confirmedChargeUsd=float(receipt.confirmed_usd),
        )
        if self.options.watchlist_id or self.options.new_reels_only:
            if answer.answered:
                row.update(isNew=False, firstSeenAt=answer.first_seen_at.isoformat(), firstSeenRunId=answer.first_seen_run_id)
            elif _definitive(row):
                row.update(isNew=True, firstSeenAt=datetime.now(UTC).isoformat(), firstSeenRunId=self.state.run_id)
        return row

    async def _heartbeat(self, lease: Lease) -> None:
        while True:
            await asyncio.sleep(self.state.lock_duration.total_seconds() / 3)
            if not await self.state.renew(lease):
                return

    async def _work(self, ref: VideoRef, media: MediaPlan | None = None) -> JsonObject | None:
        state, options = self.state, self.options.transcript
        answer = await state.lookup_answer(state.tenant_id, self.options.watchlist_id, ref.video_id)
        if self.options.new_reels_only and answer.answered and not self.options.force_refresh:
            self.previous += 1
            return to_row(ref, Outcome("skipped", "ALREADY_ANSWERED"), BillingFields(), is_new=False,
                          first_seen_at=answer.first_seen_at, first_seen_run_id=answer.first_seen_run_id)
        baseline = await state.lookup(state.tenant_id, ref.video_id, options)
        if baseline.reusable and not self.options.force_refresh and baseline.successful.payload.get("runId") != state.run_id:
            return await self._render(ref, baseline.successful.payload, free_receipt(), answer, cached=True)
        wait_until = monotonic() + self.context.claim_wait_seconds
        while True:
            claim = await state.acquire(ref.video_id, state.run_id, options=options, baseline=baseline)
            if claim.error_code == "RESULT_AVAILABLE":
                result = (await state.lookup(state.tenant_id, ref.video_id, options)).result
                return await self._render(ref, result.payload, free_receipt(), answer, cached=result.status == "success")
            if claim.value or monotonic() >= wait_until or self.context.expired():
                break
            await asyncio.sleep(0.1)
        if not claim.value:
            return to_row(ref, claim, BillingFields())
        lease = claim.value
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        actual = None
        owns_media = media is None
        try:
            settlement = Settlement(state, self.context.provider, self.context.pricing.budget, options=options)
            staged = await state.load_stage(lease, options)
            if staged and (staged["claimId"] != baseline.revision or staged["runId"] == state.run_id):
                receipt = await settlement.recover(lease)
                payload = staged["payload"]
                if not await state.commit(lease, options, payload["row"]["status"], payload, recovered_claim=staged["claimId"]):
                    raise StateUnavailable("Recovered result ownership was lost")
                if staged["runId"] != state.run_id and receipt.charged is not None:
                    receipt = free_receipt()
                return await self._render(ref, payload, receipt, answer)
            if media is None:
                try:
                    async with asyncio.timeout(self.context.remaining_seconds()):
                        inspected = await self.context.inspect(ref, self.context)
                except TimeoutError:
                    inspected = Outcome("deferred", "TIME_LIMIT", True)
                media = inspected.value
                if media is None:
                    return to_row(ref, inspected, BillingFields())
            actual = replace(media.ref, metadata=replace(media.ref.metadata, duration_seconds=float(media.duration_seconds)))
            if actual.video_id == lease.video_id:
                return await self._evaluate(actual, media, lease, settlement, answer)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, StateUnavailable):
                await heartbeat
            with suppress(StateUnavailable):
                await state.release(lease)
            if media and owns_media and (actual is None or actual.video_id == lease.video_id):
                media.close()
        try:
            if actual.video_id in self.completed:
                self.duplicates += 1
                return None
            return await self._work(actual, media)
        finally:
            if owns_media:
                media.close()

    async def _evaluate(self, ref, media, lease, settlement, answer) -> JsonObject:
        duration = media.duration_seconds
        filters, options = self.plan.filters, self.options.transcript
        if filters.max_duration_seconds is not None and duration > Decimal(str(filters.max_duration_seconds)):
            return to_row(ref, Outcome("skipped", "DURATION_LIMIT"), BillingFields())
        if filters.min_duration_seconds is not None and duration < Decimal(str(filters.min_duration_seconds)):
            return to_row(ref, Outcome("skipped", "BELOW_MIN_DURATION"), BillingFields())
        reservation = None
        budget = self.context.pricing.budget
        if media.audio:
            decision = budget.reserve(self.context.pricing.quote(duration))
            if not decision.reservation:
                code = "BILLING_UNRESOLVED" if budget.blocked else "SPEND_LIMIT"
                return to_row(ref, Outcome("deferred", code, True), BillingFields())
            reservation = decision.reservation
        try:
            async with asyncio.timeout(self.context.remaining_seconds()):
                outcome = await self.context.evaluate(media, options, self.context)
        except TimeoutError:
            outcome = Outcome("deferred", "TIME_LIMIT", True)
        payload = {**_payload(ref, outcome, options), "runId": self.state.run_id}
        receipt = free_receipt()
        if outcome.status not in {"success", "partial", "skipped"}:
            if reservation:
                budget.release(reservation)
            return payload["row"]
        if not await self.state.stage(lease, options, payload):
            raise StateUnavailable("Result ownership was lost before delivery")
        if reservation:
            if outcome.value and outcome.value.billable:
                receipt = await settlement.settle(lease, reservation)
            else:
                budget.release(reservation)
        row = await self._render(ref, payload, receipt, answer)
        if not await self.state.commit(lease, options, outcome.status, payload):
            raise StateUnavailable("Result ownership was lost before delivery")
        return row

    async def execute(self) -> RunSummary:
        requested = self.options.resume_from_dataset_id
        fresh = not requested and bool(self.plan.sources)
        original_outcomes = self.plan.outcomes
        can_run = self.plan.valid_options and await self._restore()
        for outcome in original_outcomes:
            await self._input_row(outcome)
        if can_run:
            if self.plan.sources:
                await self._discovery()
            if self.remaining or self.source_cursor or self.retry_sources:
                await self._checkpoint()
            selected = 0
            while self.remaining:
                if self.context.expired():
                    self.stop_reason = "TIME_LIMIT"
                    break
                if self.options.max_results is not None and selected >= self.options.max_results:
                    self.stop_reason = "RESULT_LIMIT"
                    break
                ref = self.remaining[0]
                try:
                    row = await self._work(ref)
                    if row and row["errorCode"] in {"SPEND_LIMIT", "TIME_LIMIT", "BILLING_UNRESOLVED"}:
                        self.stop_reason = row["errorCode"]
                        break
                    if row:
                        await self._push(row)
                        if _definitive(row):
                            seen = datetime.fromisoformat(row["firstSeenAt"]) if row["firstSeenAt"] else None
                            await self._record_answer(row, seen)
                        if row["retryable"]:
                            self.retry.append(ref)
                        else:
                            self._mark_completed(row)
                            if ref.video_id != row["videoId"]:
                                self.completed[ref.video_id] = self.completed[row["videoId"]]
                        selected += row["errorCode"] != "ALREADY_ANSWERED"
                except (ApifyClientError, BillingError, StateUnavailable):
                    self.stop_reason = "DELIVERY_INTERRUPTED"
                    break
                self.remaining.pop(0)
                await self._checkpoint()
        continuation = None
        if self.remaining or self.retry or self.retry_sources or self.source_cursor:
            self.stop_reason = self.stop_reason or ("TIME_LIMIT" if self.context.expired() else "RETRYABLE_ITEMS")
            remaining = None if self.source_cursor or self.retry_sources else len(self.remaining) + len(self.retry)
            continuation = Continuation(self.output.dataset_id, remaining, self.stop_reason)
        if continuation or fresh or requested:
            await self._checkpoint()
        prior = tuple(dict.fromkeys(
            item["datasetId"] for item in self.completed.values() if item["datasetId"] != self.output.dataset_id
        ))
        summary = summarize(
            self.rows, submitted=len(self.plan.sources), unique=len(self.known), duplicates=self.duplicates,
            watchlist_id=self.options.watchlist_id, previously_answered=self.previous,
            stop_reason=self.stop_reason, continuation=continuation, completed_dataset_ids=prior,
        )
        await self.output.put(SUMMARY_KEY, summary.to_dict())
        return summary


async def run(raw: JsonObject, context: ActorContext) -> RunSummary:
    return await _Run(raw, context).execute()
