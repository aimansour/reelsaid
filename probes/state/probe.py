"""Measure native claim and recovery primitives from two scoped Apify runs."""

import asyncio
from datetime import timedelta
from time import monotonic

from apify import Actor
from apify_client.errors import ApifyApiError


TTL = timedelta(seconds=4)


async def wait_for_record(store, key):
    async with asyncio.timeout(24):
        while not (record := await store.get_record(key)):
            await asyncio.sleep(0.25)
    return record["value"]


async def main():
    async with Actor:
        client = Actor.apify_client
        env = Actor.get_env()
        run_id, user_id = env["run_id"], env["user_id"]
        raw = await Actor.get_input()
        role, key = raw["role"], raw["key"]
        start = monotonic()
        queue_info, store_info = await asyncio.gather(
            client.request_queues().get_or_create(name=f"reelsaid-claim-{key}"),
            client.key_value_stores().get_or_create(name=f"reelsaid-state-{key}"),
        )
        queue = client.request_queue(queue_info.id, client_key=run_id)
        store = client.key_value_store(store_info.id)
        assert queue_info.user_id == store_info.user_id == user_id
        restrictions = {}
        for name, resource, metadata in (("queue", queue, queue_info), ("store", store, store_info)):
            try:
                restricted = metadata if metadata.general_access == "RESTRICTED" else await resource.update(
                    general_access="RESTRICTED",
                )
                restrictions[name] = restricted.general_access == "RESTRICTED"
            except ApifyApiError as error:
                restrictions[name] = error.status_code
        request = {"url": "https://reelsaid.invalid/claim", "uniqueKey": "claim", "userData": {"runId": run_id}}
        await store.set_record(role, {"runId": run_id})
        peer = await wait_for_record(store, "holder" if role == "contender" else "contender")
        registration = await queue.add_request(request)
        existing = await queue.get_request(registration.request_id)
        assert existing and existing.user_data
        owner_id = existing.user_data.model_dump().get("runId")
        assert owner_id in {peer["runId"], run_id}
        initial = await queue.list_and_lock_head(lock_duration=TTL, limit=1)
        won = bool(initial.items)
        stale_rejected = None
        replacement_acquired = False
        if won:
            await store.set_record("winner", {"runId": run_id})
            await wait_for_record(store, "replacement")
            try:
                await queue.prolong_request_lock(registration.request_id, lock_duration=TTL)
                stale_rejected = False
            except ApifyApiError as error:
                stale_rejected = error.status_code
            assert stale_rejected
            await store.set_record("stale-checked", {"rejected": stale_rejected})
        else:
            await wait_for_record(store, "winner")
            try:
                async with asyncio.timeout(15):
                    while True:
                        replacement = await queue.list_and_lock_head(lock_duration=TTL, limit=1)
                        if replacement.items:
                            assert replacement.items[0].id == registration.request_id
                            replacement_acquired = True
                            break
                        await asyncio.sleep(0.25)
            except TimeoutError as error:
                raise RuntimeError("Apify lock did not become available") from error
            await queue.prolong_request_lock(registration.request_id, lock_duration=timedelta(seconds=10))
            await store.set_record("replacement", {"runId": run_id})
            await wait_for_record(store, "stale-checked")
            await queue.delete_request_lock(registration.request_id)
        await Actor.push_data({
            "role": role,
            "won": won,
            "registeredFirst": not registration.was_already_present,
            "restricted": restrictions,
            "staleRejected": stale_rejected,
            "replacementAcquired": replacement_acquired,
            "permissionLevel": env["permission_level"],
            "milliseconds": round((monotonic() - start) * 1000),
        })


if __name__ == "__main__":
    asyncio.run(main())
