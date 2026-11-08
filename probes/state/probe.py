"""Measure native claim and recovery primitives from two scoped Apify runs."""

import asyncio
from time import monotonic

from apify import Actor
from apify_client.errors import ApifyApiError


TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


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
        queue = client.request_queue(queue_info.id)
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
        assert existing and existing.user_data["runId"] in {peer["runId"], run_id}
        won = not registration.was_already_present
        if won:
            assert existing.user_data["runId"] == run_id
            await store.set_record("winner", {"runId": run_id})
        else:
            assert existing.user_data["runId"] == peer["runId"]
            await wait_for_record(store, "winner")
        run_api = None
        if not won:
            try:
                async with asyncio.timeout(15):
                    while True:
                        owner = await client.run(peer["runId"]).get()
                        if not owner:
                            run_api = "not-found"
                            break
                        if owner.status in TERMINAL:
                            run_api = "terminal-visible"
                            break
                        await asyncio.sleep(0.25)
            except ApifyApiError as error:
                run_api = error.status_code
            if run_api == "terminal-visible":
                next_request = {**request, "uniqueKey": "after-terminal"}
                replacement = await queue.add_request(next_request)
                assert not replacement.was_already_present
        await Actor.push_data({
            "role": role,
            "won": won,
            "restricted": restrictions,
            "runApi": run_api,
            "permissionLevel": env["permission_level"],
            "milliseconds": round((monotonic() - start) * 1000),
        })


if __name__ == "__main__":
    asyncio.run(main())
