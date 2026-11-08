import asyncio
import json
from os import environ

from apify import Actor
from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError

from reelsaid.billing import RunPricing


async def observed_counts(run, event, count):
    for _ in range(15):
        details = await run.get()
        counts = details.charged_event_counts or {}
        if counts.get(event, 0) >= count:
            return counts
        await asyncio.sleep(0.2)
    return counts

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
        if request.get("charge") is True:
            try:
                settings = RunPricing.from_run(
                    details, environ.get("APIFY_USER_PRICING_TIER"), settings["max_total_charge_usd"],
                )
                quote = settings.quote(241)
                result["quote"] = {"total": str(quote.total), "admission": settings.budget.reserve(quote).status,
                                   "chargesEnabled": settings.charges_enabled}
                await run.charge("reel-transcript", idempotency_key="reelsaid-test-base", timeout="short")
                result["first"] = await observed_counts(run, "reel-transcript", 1)
                await run.charge("reel-transcript", idempotency_key="reelsaid-test-base", timeout="short")
                result["replayed"] = await observed_counts(run, "reel-transcript", 1)
                await run.charge("additional-minute", count=2, idempotency_key="reelsaid-test-minute", timeout="short")
                result["final"] = await observed_counts(run, "additional-minute", 2)
            except ApifyApiError as error:
                result["chargeError"] = {"status": error.status_code, "type": error.type}
        await Actor.set_value("RESULT", result)


asyncio.run(main())
