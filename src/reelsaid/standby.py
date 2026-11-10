"""Interactive Reel transcription on the Apify Standby gateway."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from os import environ
import re
import signal
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web
from apify import Actor, Event
from apify_client import ApifyClientAsync
from apify_client.errors import ApifyClientError
from curl_cffi.requests import AsyncSession

from .actor import ActorContext, MultipleVideos, run
from .billing import ApifyCharges, BillingError, RunPricing, money
from .groq import GroqAdapter, GroqPool, GroqTransport, load_accounts
from .input import parse_input
from .instagram import InstagramClient
from .media import MediaClient
from .state import LocalState, State, StateAccessError, StateUnavailable


READINESS = "X-Apify-Container-Server-Readiness-Probe"
NATIVE_RUN = "https://api.apify.com/v2/acts/aimansour~reelsaid/runs"
_BATCH_FIELDS = {"profiles", "datasetId", "datasetItems", "watchlistId", "newReelsOnly", "resumeFromDatasetId"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    request_id: str


ContextResolver = Callable[[RequestIdentity, Decimal | None], Awaitable[ActorContext]]


def _identity(request: web.Request, gateway_host: str | None) -> RequestIdentity | None:
    if gateway_host is None:
        return RequestIdentity("local", uuid4().hex)
    if request.headers.getall("Host", []) != [gateway_host]:
        return None
    fields = tuple(request.headers.getall(key, []) for key in (
        "X-Apify-User-ID", "X-Actor-Request-ID", "X-Apify-Standby-Caller-Type",
    ))
    if not all(len(values) == 1 and _IDENTIFIER.fullmatch(values[0]) for values in fields):
        return None
    return RequestIdentity(fields[0][0], fields[1][0])


def _error(status: int, code: str, identity: RequestIdentity | None = None, *, retryable: bool = False):
    body = {"status": "failed", "errorCode": code, "retryable": retryable}
    if identity:
        body["requestId"] = identity.request_id
        Actor.log.info("Standby request %s rejected with %s.", identity.request_id, code)
    else:
        Actor.log.info("Standby request rejected with %s.", code)
    if code == "USE_NATIVE_RUN":
        body["nativeRunUrl"] = NATIVE_RUN
    return web.json_response(body, status=status)


def _input(payload):
    if not isinstance(payload, dict) or not payload:
        return None, None, "INVALID_INPUT"
    if _BATCH_FIELDS.intersection(payload):
        return None, None, "USE_NATIVE_RUN"
    options = dict(payload)
    budget = options.pop("maxTotalChargeUsd", None)
    if budget is not None:
        try:
            if type(budget) not in (int, float):
                raise BillingError("A numeric request budget is required")
            budget = money(budget)
        except BillingError:
            return None, None, "INVALID_BUDGET"
    if "reelUrl" in options:
        if "startUrls" in options or "shortcodes" in options:
            return None, None, "USE_NATIVE_RUN"
        url = options.pop("reelUrl")
        if not isinstance(url, str):
            return None, None, "INVALID_URL"
        options["startUrls"] = [url]
    plan = parse_input(options)
    if plan.outcomes:
        return None, None, plan.outcomes[0].error_code
    if len(plan.sources) > 1 or any(source.kind == "profile" for source in plan.sources):
        return None, None, "USE_NATIVE_RUN"
    if len(plan.sources) != 1:
        return None, None, "INVALID_INPUT"
    return options, budget, None


class StandbyOutput:
    def __init__(self, request_id: str):
        self.dataset_id = request_id
        self.store_id = request_id
        self.rows = []
        self.records = {}

    async def existing(self):
        return list(self.rows)

    async def push(self, row):
        self.rows.append(row)

    async def put(self, key, value, content_type="application/json"):
        self.records[key] = value


def _http_rows(output):
    rows = []
    for original in output.rows:
        row = dict(original)
        row["subtitles"] = subtitles = dict(row["subtitles"])
        for format_, item in subtitles.items():
            if item and (data := output.records.get(item["key"])) is not None:
                subtitles[format_] = {
                    "key": item["key"], "contentType": item["contentType"],
                    "content": data.decode("utf-8") if isinstance(data, bytes) else data,
                }
        rows.append(row)
    return rows


def create_app(resolve_context: ContextResolver, *, gateway_host: str | None = None) -> web.Application:
    app = web.Application(client_max_size=32_768)

    async def readiness(request):
        if READINESS in request.headers:
            return web.Response(text="OK")
        return web.json_response({"status": "ready"})

    async def transcribe(request):
        started = monotonic()
        identity = _identity(request, gateway_host)
        if identity is None:
            return _error(403, "STANDBY_AUTH_REQUIRED")
        if request.content_type != "application/json":
            return _error(415, "JSON_REQUIRED", identity)
        try:
            payload = await request.json()
        except web.HTTPRequestEntityTooLarge:
            return _error(413, "INPUT_TOO_LARGE", identity)
        except (ValueError, UnicodeError):
            return _error(400, "INVALID_JSON", identity)
        options, budget, issue = _input(payload)
        if issue:
            return _error(400, issue, identity)
        try:
            context = await resolve_context(identity, budget)
            summary = await run(options, replace(context, single_video=True))
        except MultipleVideos:
            return _error(400, "USE_NATIVE_RUN", identity)
        except (ApifyClientError, BillingError, StateAccessError, StateUnavailable):
            Actor.log.warning("Standby request finished with SERVICE_UNAVAILABLE.")
            return _error(503, "SERVICE_UNAVAILABLE", identity, retryable=True)
        outcome = "SUCCESS" if summary.successful else next(iter(summary.reason_counts), "PARTIAL")
        Actor.log.info("Standby request %s finished with %s in %.3f seconds.",
                       identity.request_id, outcome, monotonic() - started)
        receipt = summary.to_dict()
        receipt["continuation"] = None
        rows = _http_rows(context.output)
        if not context.pricing.amount_is_exact and summary.charged_events:
            receipt["confirmedChargeUsd"] = None
            for row in rows:
                if row["charged"]:
                    row["confirmedChargeUsd"] = None
        return web.json_response({
            "requestId": identity.request_id, "rows": rows, "summary": receipt,
            "delivered": summary.successful + summary.partial,
            "charged": summary.charged_events, "notes": [],
        })

    app.router.add_get("/", readiness, allow_head=False)
    app.router.add_post("/", transcribe)
    return app


async def serve_standby() -> None:
    """Serve HTTP inside the initialized Actor SDK lifecycle."""
    env = Actor.get_env()
    client = Actor.apify_client
    cloud = env["is_at_home"]
    run_id = env["run_id"]
    owner = env["user_id"]
    gateway_host, charge_run, active_pricing, local_store = None, None, None, None
    if cloud:
        configuration = Actor.configuration
        gateway_host = urlsplit(configuration.standby_url).hostname
        if not gateway_host or not gateway_host.endswith(".apify.actor") or not owner or not run_id or not configuration.actor_id:
            raise StateAccessError("The Standby gateway configuration could not be verified")
        scoped = ApifyClientAsync(token=env["token"], api_url=env["api_base_url"], max_retries=0)
        charge_run = scoped.run(run_id)
        actor = await client.actor(configuration.actor_id).get()
        if actor is None:
            raise BillingError("The Actor pricing configuration is unavailable")
        now = datetime.now(UTC)
        available = [price for price in (actor.pricing_infos or ())
                     if price.started_at is not None and price.started_at <= now]
        active_pricing = max(available, key=lambda price: price.started_at, default=None)
    else:
        local_store = await Actor.open_key_value_store(name="reelsaid-local-standby-state")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    Actor.on(Event.ABORTING, stopped.set)
    loop.add_signal_handler(signal.SIGTERM, stopped.set)
    try:
        async with AsyncSession(impersonate="chrome", trust_env=False) as instagram_http, AsyncSession(trust_env=False) as provider_http:
            instagram, media = InstagramClient(instagram_http), MediaClient(instagram_http)
            groq = None
            if keys := environ.get("REELSAID_GROQ_KEYS"):
                accounts = load_accounts(keys, environ.get("REELSAID_GROQ_LIMITS", "{}"))
                groq = GroqAdapter(GroqTransport(provider_http), GroqPool(accounts, rotation_seed=run_id or "standby-local"))

            async def resolve(identity: RequestIdentity, budget: Decimal | None) -> ActorContext:
                pricing = RunPricing.from_standby(active_pricing, budget)
                provider = ApifyCharges(charge_run, request_id=identity.request_id) if pricing.charges_enabled else None
                if cloud:
                    namespace = f"reelsaid-http-{sha256(identity.user_id.encode()).hexdigest()[:24]}"
                    state = await State.open(client, identity.user_id, identity.request_id,
                                             namespace=namespace, storage_owner_id=owner)
                else:
                    state = LocalState(client, local_store, identity.user_id, identity.request_id)
                return ActorContext(
                    instagram=instagram, media_client=media, groq=groq, apify=client, now=datetime.now(UTC),
                    expired=stopped.is_set, output=StandbyOutput(identity.request_id), state=state,
                    pricing=pricing, provider=provider,
                )

            runner = web.AppRunner(create_app(resolve, gateway_host=gateway_host), access_log=None)
            try:
                await runner.setup()
                await web.TCPSite(runner, "0.0.0.0", Actor.configuration.web_server_port).start()
                Actor.log.info("ReelSaid Standby server is listening.")
                await stopped.wait()
            finally:
                await runner.cleanup()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
