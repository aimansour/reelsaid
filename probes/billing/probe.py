import asyncio
import json
from os import environ

from apify import Actor
from apify_client import ApifyClientAsync
from apify_client.errors import ApifyApiError


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
                await run.charge("reel-transcript", idempotency_key="reelsaid-test-base", timeout="short")
                result["first"] = (await run.get()).charged_event_counts
                await run.charge("reel-transcript", idempotency_key="reelsaid-test-base", timeout="short")
                result["replayed"] = (await run.get()).charged_event_counts
                await run.charge("additional-minute", count=2, idempotency_key="reelsaid-test-minute", timeout="short")
                result["final"] = (await run.get()).charged_event_counts
            except ApifyApiError as error:
                result["chargeError"] = {"status": error.status_code, "type": error.type}
        await Actor.set_value("RESULT", result)


asyncio.run(main())
