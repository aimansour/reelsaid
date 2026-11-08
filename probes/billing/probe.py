import asyncio
import json
from os import environ

from apify import Actor
from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError

from reelsaid.billing import ApifyCharges, RunPricing, Settlement
from reelsaid.contracts import TranscriptOptions
from reelsaid.state import State


async def observed_counts(run, event, count):
    for _ in range(15):
        details = await run.get()
        counts = details.charged_event_counts or {}
        if counts.get(event, 0) >= count:
            return counts
        await asyncio.sleep(0.2)
    return counts

async def settle_real_events(client, env, details, pricing):
    class LostResponse(ApifyCharges):
        def __init__(self, run):
            super().__init__(run)
            self.calls = []

        async def charge(self, event, count, key):
            acknowledged = await super().charge(event, count, key)
            self.calls.append(key)
            return acknowledged and len(self.calls) != 2

    state = await State.open(client, env["user_id"], env["run_id"], namespace="reelsaid-account-qa")
    provider = LostResponse(client.run(details.id))
    settlement = Settlement(state, provider, pricing.budget)
    confirmed = []
    for number in range(2):
        video = f"{details.id}-test-{number}"
        lease = (await state.acquire(video, state.run_id)).value
        assert lease and await state.stage(lease, TranscriptOptions(), {"transcript": "Billing verification fixture."})
        reservation = pricing.budget.reserve(pricing.quote(8)).reservation
        assert reservation
        receipt = await settlement.settle(lease, reservation)
        confirmed.append({"state": receipt.state, "amount": str(receipt.confirmed_usd), "events": receipt.events})
        await state.release(lease)
    return {
        "receipts": confirmed,
        "distinctKeys": len(set(provider.calls)),
        "journal": await state.load_run_billing(),
    }


async def main():
    async with Actor:
        settings = Actor.get_env()
        client = ApifyClientAsync(token=settings["token"], max_retries=0)
        run = client.run(settings["run_id"])
        details = await run.get()
        request = await Actor.get_input() or {}
        result = {
            "pricingEnv": settings["actor_pricing_info"],
            "chargeEnv": settings["charged_actor_event_counts"],
            "maxChargeEnv": settings["max_total_charge_usd"],
            "maxChargeRun": details.options.max_total_charge_usd,
            "countsBefore": details.charged_event_counts,
            "tierEnvironmentNames": sorted(key for key in environ if key.startswith("APIFY_") and "TIER" in key),
        }
        for key in result["tierEnvironmentNames"]:
            result[key] = environ[key]
        try:
            user = await client.user().get()
            result["selfUserPlan"] = json.loads(user.model_dump_json()).get("plan")
        except ApifyApiError as error:
            result["selfUserError"] = error.status_code
        if request.get("settle") is True:
            pricing = RunPricing.from_run(
                details, environ.get("APIFY_USER_PRICING_TIER"), settings["max_total_charge_usd"],
            )
            result.update(await settle_real_events(client, settings, details, pricing))
        elif request.get("charge") is True:
            try:
                settings = RunPricing.from_run(
                    details, environ.get("APIFY_USER_PRICING_TIER"), settings["max_total_charge_usd"],
                )
                quote = settings.quote(241)
                result["quote"] = {"total": str(quote.total), "admission": settings.budget.reserve(quote).status,
                                   "chargesEnabled": settings.charges_enabled}
                base_key = f"reelsaid-test-base-{details.id}"
                await run.charge("reel-transcript", idempotency_key=base_key, timeout="short")
                result["first"] = await observed_counts(run, "reel-transcript", 1)
                await run.charge("reel-transcript", idempotency_key=base_key, timeout="short")
                result["replayed"] = await observed_counts(run, "reel-transcript", 1)
                await run.charge("additional-minute", count=2, idempotency_key=f"reelsaid-test-minute-{details.id}", timeout="short")
                result["final"] = await observed_counts(run, "additional-minute", 2)
            except ApifyApiError as error:
                result["chargeError"] = {"status": error.status_code, "type": error.type}
        await Actor.set_value("RESULT", result)


asyncio.run(main())
