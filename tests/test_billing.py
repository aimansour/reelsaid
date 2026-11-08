import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from apify_client._models import PayPerEventActorPricingInfo

from reelsaid.billing import (
    BASE_EVENT,
    MINUTE_EVENT,
    BillingError,
    RunPricing,
    RunBudget,
    Settlement,
    quote,
)
from reelsaid.contracts import TranscriptOptions

from test_state import FakeAccount


OPTIONS = TranscriptOptions()


class Provider:
    def __init__(self):
        self.events = {}
        self.keys = set()
        self.calls = []
        self.lose_response = False
        self.counts_visible = True
        self.interrupt = False

    async def counts(self):
        return dict(self.events) if self.counts_visible else None

    async def charge(self, event, count, key):
        self.calls.append((event, count, key))
        if key not in self.keys:
            self.events[event] = self.events.get(event, 0) + count
            self.keys.add(key)
        if self.interrupt:
            raise asyncio.CancelledError
        return not self.lose_response


def test_quote_tiers_and_started_minutes():
    assert [quote(duration, "BRONZE").total for duration in (180, 180.001, 181, 241)] == [
        Decimal("0.011"), Decimal("0.014"), Decimal("0.014"), Decimal("0.017"),
    ]
    assert quote(180, "PLATINUM").total == quote(180, "DIAMOND").total == Decimal("0.0085")
    assert quote(8.892, "FREE").billed_minutes == 1
    assert quote(181, "FREE").billed_minutes == 4
    for duration in (0, -1, float("nan"), float("inf")):
        with pytest.raises(BillingError):
            quote(duration, "FREE")


def test_base_only_budget_defers_before_asr():
    cost = quote(181, "BRONZE")
    assert RunBudget(Decimal("0.011")).reserve(cost).status == "deferred"
    budget = RunBudget(Decimal("0.014"))
    assert budget.reserve(cost).status == "admitted"
    assert budget.reserve(cost).status == "waiting"


def test_free_result_releases_budget():
    cost = quote(181, "BRONZE")
    budget = RunBudget(Decimal("0.014"))
    reservation = budget.reserve(cost).reservation
    assert budget.release(reservation).charged is False
    assert budget.spent == 0
    assert budget.reserve(cost).status == "admitted"


def test_uses_effective_platform_event_rates_and_previous_counts():
    pricing = SimpleNamespace(
        pricing_model="PAY_PER_EVENT",
        is_ppe_platform_usage_paid_by_user=False,
        pricing_per_event=SimpleNamespace(actor_charge_events={
            BASE_EVENT: SimpleNamespace(
                event_price_usd=None,
                event_tiered_pricing_usd={"GOLD": SimpleNamespace(tiered_event_price_usd=0.009)},
                is_one_time_event=False,
            ),
            MINUTE_EVENT: SimpleNamespace(
                event_price_usd=0.004, event_tiered_pricing_usd=None, is_one_time_event=False,
            ),
        }),
    )
    run = SimpleNamespace(
        pricing_info=pricing,
        options=SimpleNamespace(max_total_charge_usd=0.03),
        charged_event_counts={BASE_EVENT: 1, MINUTE_EVENT: 2},
    )
    settings = RunPricing.from_run(run, "GOLD", "0.030")
    assert settings.quote(181).total == Decimal("0.013")
    assert settings.budget.spent == Decimal("0.017")
    assert settings.budget.reserve(settings.quote(181)).status == "admitted"
    with pytest.raises(BillingError):
        RunPricing.from_run(run, "BRONZE", "0.030")
    pricing.is_ppe_platform_usage_paid_by_user = True
    with pytest.raises(BillingError):
        RunPricing.from_run(run, "GOLD", "0.030")


def test_live_run_pricing_snapshot_omits_the_platform_usage_switch():
    pricing = PayPerEventActorPricingInfo.model_validate({
        "pricingModel": "PAY_PER_EVENT",
        "apifyMarginPercentage": 0.2,
        "createdAt": "2026-11-08T12:00:00Z",
        "startedAt": "2026-11-08T12:00:00Z",
        "pricingPerEvent": {"actorChargeEvents": {
            BASE_EVENT: {"eventTitle": "Transcript", "eventDescription": "Transcript",
                         "eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": 0.012}}},
            MINUTE_EVENT: {"eventTitle": "Minute", "eventDescription": "Minute", "eventPriceUsd": 0.003},
        }},
    })
    run = SimpleNamespace(pricing_info=pricing, options=SimpleNamespace(max_total_charge_usd=0.018),
                          charged_event_counts={BASE_EVENT: 0, MINUTE_EVENT: 0})
    settings = RunPricing.from_run(run, "FREE", "0.018")
    assert settings.charges_enabled and settings.quote(241).total == Decimal("0.018")


def test_settlement_response_lost():
    async def check():
        provider = Provider()
        provider.lose_response = True
        account = FakeAccount("account")
        state = account.state("original")
        lease = (await state.acquire("reel", state.run_id)).value
        assert await state.stage(lease, OPTIONS, {"transcript": "durable"})
        budget = RunBudget(Decimal("0.014"))
        reservation = budget.reserve(quote(181, "BRONZE")).reservation
        settlement = Settlement(state, provider, budget, clock=lambda: 1000)
        receipt = await settlement.settle(lease, reservation)
        assert receipt.charged is True and receipt.state == "settled"
        assert receipt.events == {BASE_EVENT: 1, MINUTE_EVENT: 1}
        assert receipt.confirmed_usd == budget.spent == Decimal("0.014")
        assert len(provider.calls) == 2
        assert await state.release(lease)

        other = account.state("later")
        next_lease = (await other.acquire("reel", other.run_id)).value
        recovered = Settlement(other, provider, RunBudget(None), clock=lambda: 1300)
        assert await recovered.recover(next_lease) == receipt
        assert (await other.load_stage(next_lease))["payload"]["transcript"] == "durable"
        assert len(provider.calls) == 2

    asyncio.run(check())


def test_interrupted_debit_is_never_replayed_by_a_sibling_or_after_expiry():
    async def check():
        account = FakeAccount("account")
        original = account.state("original")
        lease = (await original.acquire("reel", original.run_id)).value
        assert await original.stage(lease, OPTIONS, {"transcript": "durable"})
        budget = RunBudget(Decimal("0.012"))
        reservation = budget.reserve(quote(8, "FREE")).reservation
        provider = Provider()
        provider.interrupt = True
        with pytest.raises(asyncio.CancelledError):
            await Settlement(original, provider, budget, clock=lambda: 1000).settle(lease, reservation)

        provider.interrupt = False
        provider.counts_visible = False
        assert (await Settlement(original, provider, budget, clock=lambda: 1300).recover(lease)).charged is None
        assert len(provider.calls) == 1
        assert await original.release(lease)

        sibling = account.state("sibling")
        sibling_lease = (await sibling.acquire("reel", sibling.run_id)).value
        sibling_provider = Provider()
        recovered = await Settlement(sibling, sibling_provider, RunBudget(None)).recover(sibling_lease)
        assert recovered.charged is None and not sibling_provider.calls
        assert await sibling.release(sibling_lease)

        provider.counts_visible = True
        lease = (await original.acquire("reel", original.run_id)).value
        recovered = await Settlement(original, provider, budget, clock=lambda: 1400).recover(lease)
        assert recovered.charged is True and recovered.events == {BASE_EVENT: 1}
        assert len(provider.calls) == 1

    asyncio.run(check())


def test_lagging_counter_retries_only_with_the_original_key():
    class LaggingProvider(Provider):
        async def counts(self):
            return {}

        async def charge(self, event, count, key):
            self.lose_response = not self.calls
            return await super().charge(event, count, key)

    async def check():
        state = FakeAccount("account").state("run")
        lease = (await state.acquire("reel", state.run_id)).value
        budget = RunBudget(Decimal("0.012"))
        reservation = budget.reserve(quote(8, "FREE")).reservation
        provider = LaggingProvider()
        settlement = Settlement(state, provider, budget)
        with pytest.raises(BillingError, match="durable result"):
            await settlement.settle(lease, reservation)
        assert not provider.calls
        assert await state.stage(lease, OPTIONS, {"transcript": "durable"})
        assert (await settlement.settle(lease, reservation)).state == "settled"
        assert len(provider.calls) == 2 and provider.calls[0] == provider.calls[1]
        assert provider.events == {BASE_EVENT: 1}

    asyncio.run(check())
