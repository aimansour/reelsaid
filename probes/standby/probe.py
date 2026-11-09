"""Private diagnostic for the Apify Standby gateway and billing context."""

import asyncio
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import signal

from aiohttp import web
from apify import Actor, Event
from apify_client.errors import ApifyApiError


EVENT_NAME = "probe-result"
PRICE = Decimal("0.001")
STORE_KEY = "STANDBY_PROBE"
READINESS = "X-Apify-Container-Server-Readiness-Probe"
FORGED = "reelsaid-forged-probe-value"


def create_app(environment):
    app = web.Application(client_max_size=4096)
    ready = False
    at_home = environment["is_at_home"]
    runtime_user = environment["user_id"]
    run_id = environment["run_id"]
    context = sha256(runtime_user.encode()).hexdigest()[:16] if runtime_user else None
    platform_budget = environment["max_total_charge_usd"]
    client = Actor.apify_client if at_home else None
    run = client.run(run_id) if client else None

    async def health(request):
        nonlocal ready
        if READINESS in request.headers:
            ready = True
            return web.Response(text="OK")
        return web.json_response({"status": "ready"})

    async def observe(request):
        if request.content_type != "application/json":
            return web.json_response({"error": "JSON_REQUIRED"}, status=415)
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            return web.json_response({"error": "INVALID_JSON"}, status=400)
        if not isinstance(payload, dict) or payload.get("mode") not in ("observe", "charge", "store", "zero"):
            return web.json_response({"error": "INVALID_MODE"}, status=400)

        request_id = request.headers.get("X-Actor-Request-ID")
        result = {
            "origin": Actor.configuration.meta_origin,
            "port": Actor.configuration.web_server_port,
            "readinessSeen": ready,
            "runId": run_id,
            "callerContext": context,
            "platformBudget": str(platform_budget) if platform_budget is not None else None,
            "authorizationForwarded": "Authorization" in request.headers,
            "apifyAuthorizationForwarded": "X-Apify-Authorization" in request.headers,
            "apifyHeaders": sorted({key.lower() for key in request.headers
                                    if key.lower().startswith(("x-actor-", "x-apify-"))
                                    and "authorization" not in key.lower()}),
            "forgedHeadersForwarded": sorted({key.lower() for key, value in request.headers.items() if value == FORGED}),
            "requestIdPresent": bool(request_id),
            "settlement": "no-event",
        }
        if payload["mode"] == "charge":
            try:
                limit = Decimal(str(payload.get("maxTotalChargeUsd")))
            except InvalidOperation:
                return web.json_response({"error": "INVALID_BUDGET"}, status=400)
            if not limit.is_finite() or limit < 0:
                return web.json_response({"error": "INVALID_BUDGET"}, status=400)
            if limit < PRICE:
                result["settlement"] = "budget-rejected"
            elif run:
                attribution = request_id if payload.get("usePlatformRequestId") is True and request_id != FORGED else None
                key = f"reelsaid-standby-probe-{run_id}"
                try:
                    for _ in range(2):
                        await run.charge(EVENT_NAME, idempotency_key=key, request_id=attribution)
                    result["settlement"] = "acknowledged"
                except ApifyApiError as error:
                    result.update(settlement="rejected", chargeStatus=error.status_code, chargeError=error.type)
            else:
                result["settlement"] = "local-only"
        elif payload["mode"] == "store" and client:
            store = client.key_value_store(environment["default_key_value_store_id"])
            info = await store.get()
            if not info or info.user_id != runtime_user:
                return web.json_response({"error": "STORAGE_SCOPE_MISMATCH"}, status=503)
            if info.general_access != "RESTRICTED":
                info = await store.update(general_access="RESTRICTED")
            if info.general_access != "RESTRICTED":
                return web.json_response({"error": "STORAGE_PRIVACY_UNCONFIRMED"}, status=503)
            await store.set_record(STORE_KEY, {"callerContext": context}, content_type="application/json")
            result["storageId"] = info.id

        if run:
            details = await run.get()
            result["eventsObserved"] = details.charged_event_counts if details else None
        Actor.log.info("Standby probe request completed.")
        return web.json_response(result)

    app.router.add_get("/", health, allow_head=False)
    app.router.add_post("/probe", observe)
    return app


async def main():
    async with Actor:
        if Actor.configuration.meta_origin != "STANDBY":
            Actor.log.info("Standby probe standard run completed.")
            return
        stop = asyncio.Event()
        Actor.on(Event.ABORTING, stop.set)
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        runner = web.AppRunner(create_app(Actor.get_env()), access_log=None)
        try:
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", Actor.configuration.web_server_port).start()
            Actor.log.info("Standby probe is listening.")
            await stop.wait()
        finally:
            await runner.cleanup()
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    asyncio.run(main())
