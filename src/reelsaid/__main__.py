"""Apify runtime entry point."""

import asyncio
from datetime import UTC, datetime
from os import environ

from apify import Actor, Event
from apify_client import ApifyClientAsync
from apify_client.errors import ApifyClientError
from curl_cffi.requests import AsyncSession

from .actor import ActorContext, run
from .billing import ApifyCharges, BillingError, PROPOSED_BASE, PROPOSED_MINUTE, RunBudget, RunPricing
from .groq import GroqAdapter, GroqPool, GroqTransport, load_accounts
from .input import parse_input
from .instagram import InstagramClient
from .media import MediaClient
from .state import State, StateAccessError, StateUnavailable


class ApifyOutput:
    def __init__(self, client: ApifyClientAsync, dataset_id: str, store_id: str):
        self.client = client
        self.dataset_id = dataset_id
        self.store_id = store_id

    async def read(self, dataset_id: str) -> list[dict]:
        dataset = self.client.dataset(dataset_id)
        rows = []
        while True:
            page = await dataset.list_items(offset=len(rows), limit=250, timeout="short")
            rows.extend(page.items)
            if not page.items or len(rows) >= page.total:
                return rows

    async def existing(self) -> list[dict]:
        return await self.read(self.dataset_id)

    async def push(self, row: dict) -> None:
        await self.client.dataset(self.dataset_id).push_items(row, timeout="short")

    async def put(self, key: str, value: object, content_type: str = "application/json") -> None:
        await self.client.key_value_store(self.store_id).set_record(key, value, content_type=content_type, timeout="short")


async def main() -> None:
    async with Actor, AsyncSession(impersonate="chrome", trust_env=False) as web, AsyncSession(trust_env=False) as provider_http:
        env = Actor.get_env()
        raw = await Actor.get_input() or {}
        if not isinstance(raw, dict):
            raw = {"input": raw}
        plan = parse_input(raw)
        cloud = env["is_at_home"]
        state, provider, groq = None, None, None
        concurrency = 1
        measure = environ.get("REELSAID_BENCHMARK") == "1"
        pricing = RunPricing(RunBudget(env["max_total_charge_usd"]), PROPOSED_BASE["FREE"], PROPOSED_MINUTE, False)
        client = ApifyClientAsync(token=env["token"], api_url=env["api_base_url"], max_retries=0)
        if not cloud:
            await Actor.fail(status_message="Use Apify to run this Actor. Local verification is available in the test suite.")
            return
        output = ApifyOutput(client, env["default_dataset_id"], env["default_key_value_store_id"])
        if plan.valid_options and (plan.sources or plan.options.resume_from_dataset_id):
            try:
                scoped_run = client.run(env["run_id"])
                details, state = await asyncio.gather(
                    scoped_run.get(timeout="short"),
                    State.open(Actor.apify_client, env["user_id"], env["run_id"]),
                )
                if details is None:
                    raise BillingError("Run pricing is unavailable")
                pricing = RunPricing.from_run(details, environ.get("APIFY_USER_PRICING_TIER"), env["max_total_charge_usd"])
                provider = ApifyCharges(scoped_run) if pricing.charges_enabled else None
                memory = details.options.memory_mbytes
                concurrency = 4 if memory >= 512 else 2 if memory >= 256 else 1
                if keys := environ.get("REELSAID_GROQ_KEYS"):
                    accounts = load_accounts(keys, environ.get("REELSAID_GROQ_LIMITS", "{}"))
                    groq = GroqAdapter(
                        GroqTransport(provider_http), GroqPool(accounts, rotation_seed=env["run_id"], measure=measure),
                    )
            except (ApifyClientError, BillingError, StateUnavailable, StateAccessError, ValueError):
                await Actor.fail(status_message="Run configuration could not be verified.")
                return

        stopping = asyncio.Event()

        def request_stop() -> None:
            stopping.set()

        def remaining_seconds() -> float | None:
            if stopping.is_set():
                return 0
            timeout_at = env["timeout_at"]
            return max(0, (timeout_at - datetime.now(UTC)).total_seconds() - 10) if timeout_at else None

        Actor.on(Event.ABORTING, request_stop)
        Actor.on(Event.MIGRATING, request_stop)
        summary = await run(raw, ActorContext(
            instagram=InstagramClient(web), apify=Actor.apify_client, now=datetime.now(UTC),
            expired=lambda: remaining_seconds() == 0, remaining_seconds=remaining_seconds,
            media_client=MediaClient(web), groq=groq, state=state, output=output, pricing=pricing,
            provider=provider, read_previous=output.read, concurrency=concurrency, discovery_concurrency=concurrency,
        ))
        if measure and groq is not None:
            await output.put("REELSAID_METRICS", {"models": groq.pool.measurements, "workers": concurrency})
        message = f"{summary.successful} transcribed, {summary.partial} partial, {summary.failed + summary.input_errors} failed"
        if summary.stop_reason:
            message += f". {summary.stop_reason}"
        await Actor.set_status_message(message, is_terminal=True)


if __name__ == "__main__":
    asyncio.run(main())
