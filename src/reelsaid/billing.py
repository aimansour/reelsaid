"""Full-price admission and recoverable settlement for Apify event charges."""

import asyncio
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Literal, Protocol
from uuid import uuid4

from apify_client.errors import ApifyClientError

from .contracts import TranscriptOptions
from .state import Lease, State


BASE_EVENT = "reel-transcript"
MINUTE_EVENT = "additional-minute"
PROPOSED_BASE = {
    "FREE": Decimal("0.012"),
    "BRONZE": Decimal("0.011"),
    "SILVER": Decimal("0.010"),
    "GOLD": Decimal("0.009"),
    "PLATINUM": Decimal("0.0085"),
    "DIAMOND": Decimal("0.0085"),
}
PROPOSED_MINUTE = Decimal("0.003")
RETRY_WINDOW = 150  # Leave time for an in-flight request before the 180-second expiry.
ZERO = Decimal(0)


class BillingError(RuntimeError):
    pass


def money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise BillingError("Invalid billing amount") from error
    if not amount.is_finite() or amount < 0:
        raise BillingError("Invalid billing amount")
    return amount


@dataclass(frozen=True)
class ChargeQuote:
    base: Decimal
    minute: Decimal
    included_minutes: int
    extra_minutes: int

    @property
    def billed_minutes(self) -> int:
        return self.included_minutes + self.extra_minutes

    @property
    def total(self) -> Decimal:
        return self.base + self.minute * self.extra_minutes

    @property
    def events(self) -> dict[str, int]:
        return {BASE_EVENT: 1, MINUTE_EVENT: self.extra_minutes} if self.extra_minutes else {BASE_EVENT: 1}

    def amount_for(self, events: dict[str, int]) -> Decimal:
        return self.base * events.get(BASE_EVENT, 0) + self.minute * events.get(MINUTE_EVENT, 0)

    def record(self) -> dict:
        return {**asdict(self), "base": str(self.base), "minute": str(self.minute)}

    @classmethod
    def from_record(cls, record: dict) -> "ChargeQuote":
        return cls(**{**record, "base": money(record["base"]), "minute": money(record["minute"])})


def quote(
    duration_seconds: float, tier: str, *, base_prices=PROPOSED_BASE, minute_price=PROPOSED_MINUTE,
) -> ChargeQuote:
    seconds = money(duration_seconds)
    if not seconds or tier not in base_prices:
        raise BillingError("Billing requires a positive duration and a known price tier")
    minutes = ceil(seconds / 60)
    return ChargeQuote(money(base_prices[tier]), money(minute_price), min(minutes, 3), max(0, minutes - 3))


@dataclass(frozen=True)
class Reservation:
    id: str
    quote: ChargeQuote


@dataclass(frozen=True)
class ReservationDecision:
    status: Literal["admitted", "waiting", "deferred"]
    reservation: Reservation | None = None


@dataclass(frozen=True)
class ChargeReceipt:
    state: Literal["free", "settled", "incomplete", "unknown"]
    events: dict[str, int]
    confirmed_usd: Decimal
    billed_minutes: int | None

    @property
    def charged(self) -> bool | None:
        return None if self.state == "unknown" else bool(self.events)


def free_receipt() -> ChargeReceipt:
    return ChargeReceipt("free", {}, ZERO, 0)


class RunBudget:
    def __init__(self, cap: Decimal | None, *, spent: Decimal = ZERO):
        self.cap = None if cap is None else money(cap)
        self.spent = money(spent)
        self.blocked = False
        self.settlement_lock = asyncio.Lock()
        self._active: dict[str, Reservation] = {}

    def reserve(self, cost: ChargeQuote) -> ReservationDecision:
        if self.blocked or self.cap is not None and self.spent + cost.total > self.cap:
            return ReservationDecision("deferred")
        reserved = sum((item.quote.total for item in self._active.values()), ZERO)
        if self.cap is not None and self.spent + reserved + cost.total > self.cap:
            return ReservationDecision("waiting")
        reservation = Reservation(uuid4().hex, cost)
        self._active[reservation.id] = reservation
        return ReservationDecision("admitted", reservation)

    def require(self, reservation: Reservation) -> None:
        if self._active.get(reservation.id) != reservation:
            raise BillingError("Settlement requires an active run reservation")

    def complete(self, reservation: Reservation, receipt: ChargeReceipt) -> ChargeReceipt:
        self.require(reservation)
        del self._active[reservation.id]
        self.spent += receipt.confirmed_usd
        if receipt.state in {"unknown", "incomplete"}:
            self.blocked = True
        return receipt

    def release(self, reservation: Reservation) -> ChargeReceipt:
        return self.complete(reservation, free_receipt())


@dataclass(frozen=True)
class RunPricing:
    budget: RunBudget
    base: Decimal
    minute: Decimal
    charges_enabled: bool

    def quote(self, duration_seconds: float) -> ChargeQuote:
        return quote(duration_seconds, "effective", base_prices={"effective": self.base}, minute_price=self.minute)

    @classmethod
    def from_run(cls, run, tier: str | None, cap_environment: Decimal | str | None) -> "RunPricing":
        caps = [money(value) for value in (run.options.max_total_charge_usd, cap_environment) if value is not None]
        cap = min(caps) if caps else None
        pricing = run.pricing_info
        if pricing is None or pricing.pricing_model == "FREE":
            return cls(RunBudget(cap), PROPOSED_BASE.get(tier, PROPOSED_BASE["FREE"]), PROPOSED_MINUTE, False)
        if pricing.pricing_model != "PAY_PER_EVENT" or pricing.is_ppe_platform_usage_paid_by_user:
            raise BillingError("Run pricing must cover all platform usage through transcript events")
        events = pricing.pricing_per_event.actor_charge_events
        if set(events) != {BASE_EVENT, MINUTE_EVENT} or any(item.is_one_time_event for item in events.values()):
            raise BillingError("Unexpected transcript event configuration")

        def price(event: str) -> Decimal:
            item = events[event]
            if item.event_price_usd is not None:
                return money(item.event_price_usd)
            entry = (item.event_tiered_pricing_usd or {}).get(tier)
            if entry is None:
                raise BillingError("The effective tier price could not be confirmed")
            return money(entry.tiered_event_price_usd)

        base, minute = price(BASE_EVENT), price(MINUTE_EVENT)
        counts = run.charged_event_counts or {}
        spent = base * counts.get(BASE_EVENT, 0) + minute * counts.get(MINUTE_EVENT, 0)
        return cls(RunBudget(cap, spent=spent), base, minute, True)


class ChargeProvider(Protocol):
    async def counts(self) -> dict[str, int] | None: ...
    async def charge(self, event: str, count: int, key: str) -> bool: ...


class ApifyCharges:
    """The caller supplies the original run client with automatic retries disabled."""

    def __init__(self, run):
        self._run = run

    async def counts(self) -> dict[str, int] | None:
        try:
            details = await self._run.get(timeout="short")
        except ApifyClientError:
            return None
        return details.charged_event_counts if details is not None else None

    async def charge(self, event: str, count: int, key: str) -> bool:
        try:
            await self._run.charge(event, count=count, idempotency_key=key, timeout="short")
        except ApifyClientError:
            return False
        return True


class Settlement:
    def __init__(
        self, state: State, provider: ChargeProvider | None, budget: RunBudget, *,
        options: TranscriptOptions = TranscriptOptions(), clock=time.time,
    ):
        self._state = state
        self._provider = provider
        self._budget = budget
        self._options = options
        self._clock = clock

    async def settle(self, lease: Lease, reservation: Reservation) -> ChargeReceipt:
        async with self._budget.settlement_lock:
            self._budget.require(reservation)
            staged = await self._state.load_stage(lease, self._options)
            if not staged or staged["claimId"] != lease.claim_id or staged["runId"] != lease.run_id:
                raise BillingError("A durable result must exist before settlement")
            if self._budget.blocked:
                raise BillingError("A previous charge is awaiting reconciliation")
            if self._provider is None:
                return self._budget.release(reservation)
            record = await self._state.load_settlement(lease, lease.claim_id)
            if record is None:
                record = {
                    "quote": reservation.quote.record(),
                    "cap": str(self._budget.cap) if self._budget.cap is not None else None,
                    "confirmed": {},
                    "pending": None,
                    "finished": False,
                }
                await self._state.save_settlement(lease, lease.claim_id, record)
            elif ChargeQuote.from_record(record["quote"]) != reservation.quote:
                raise BillingError("The original authorized price must be preserved")
            receipt = await self._advance(lease, lease.claim_id, record, allow_new=True)
            return self._budget.complete(reservation, receipt)

    async def recover(self, lease: Lease) -> ChargeReceipt | None:
        async with self._budget.settlement_lock:
            staged = await self._state.load_stage(lease, self._options)
            if not staged:
                return None
            claim_id = staged["claimId"]
            record = await self._state.load_settlement(lease, claim_id)
            if record is None:
                return free_receipt()
            if staged["runId"] == lease.run_id and self._provider is not None:
                receipt = await self._advance(lease, claim_id, record, allow_new=False)
                if receipt.state in {"unknown", "incomplete"}:
                    self._budget.blocked = True
                return receipt
            return self._receipt(record)

    async def _advance(self, lease: Lease, claim_id: str, record: dict, *, allow_new: bool) -> ChargeReceipt:
        if record["finished"]:
            return self._receipt(record)
        cost = ChargeQuote.from_record(record["quote"])
        for event, count in cost.events.items():
            if event in record["confirmed"]:
                continue
            pending = record["pending"]
            if pending is None:
                if not allow_new:
                    break
                counts = await self._provider.counts()
                if counts is None:
                    break
                pending = {"event": event, "before": counts.get(event, 0), "started": self._clock()}
                record["pending"] = pending
                await self._state.save_settlement(lease, claim_id, record)
            if pending["event"] != event:
                raise BillingError("The pending event does not match its authorized price")
            accepted = await self._confirm(lease, claim_id, event, count, pending)
            if accepted is None:
                return self._receipt(record)
            record["confirmed"][event] = accepted
            record["pending"] = None
            await self._state.save_settlement(lease, claim_id, record)
            if accepted != count:
                break
        record["finished"] = True
        await self._state.save_settlement(lease, claim_id, record)
        return self._receipt(record)

    async def _confirm(self, lease: Lease, claim_id: str, event: str, count: int, pending: dict) -> int | None:
        for attempt in range(3):
            counts = await self._provider.counts()
            if counts is not None:
                difference = counts.get(event, 0) - pending["before"]
                if difference:
                    return difference if 0 < difference <= count else None
            if attempt == 2 or not 0 <= self._clock() - pending["started"] < RETRY_WINDOW:
                break
            if not await self._state.renew(lease):
                raise BillingError("Billing ownership was lost")
            if await self._provider.charge(event, count, f"reelsaid-{claim_id}-{event}"):
                return count
        return None

    @staticmethod
    def _receipt(record: dict) -> ChargeReceipt:
        cost = ChargeQuote.from_record(record["quote"])
        events = dict(record["confirmed"])
        minutes = cost.included_minutes * events.get(BASE_EVENT, 0) + events.get(MINUTE_EVENT, 0)
        if record["pending"] is not None:
            state = "unknown"
        elif events == cost.events:
            state = "settled"
        else:
            state = "incomplete"
        return ChargeReceipt(state, events, cost.amount_for(events), minutes if state != "unknown" else None)
