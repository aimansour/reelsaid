"""Exercise the account state contract from two independent scoped Apify runs."""

import asyncio
from time import monotonic

from apify import Actor

from reelsaid.contracts import Outcome, TranscriptOptions
from reelsaid.state import Checkpoint, State


OPTIONS = TranscriptOptions()
VIDEO = "matched-video"


async def wait_for_record(store, key):
    async with asyncio.timeout(24):
        while not (record := await store.get_record(key)):
            await asyncio.sleep(0.2)
    return record["value"]


async def hold(state, store):
    lease = (await state.acquire(VIDEO, state.run_id)).value
    assert lease and await state.stage(lease, OPTIONS, {"transcript": "staged"})
    await store.set_record("probe-holder", {"ready": True})
    await wait_for_record(store, "probe-replacement")
    assert not await state.commit(lease, OPTIONS, "success", {"transcript": "stale"})
    assert not await state.release(lease)
    await store.set_record("probe-stale-checked", {"rejected": True})
    result = await state.lookup(state.tenant_id, VIDEO, OPTIONS)
    assert result.reusable and result.successful.payload == {"transcript": "delivered"}
    checkpoint = await state.load_checkpoint(state.tenant_id, "probe")
    assert checkpoint and checkpoint.completed == ({"videoId": VIDEO},)
    assert (await state.lookup_answer(state.tenant_id, "different-list", VIDEO)).answered
    return {"role": "holder", "staleFenced": True, "checkpointRecovered": True, "otherListAnswered": True}


async def contend(state, store):
    await wait_for_record(store, "probe-holder")
    baseline = await state.lookup(state.tenant_id, VIDEO, OPTIONS)
    first = await state.acquire(VIDEO, state.run_id)
    assert first.error_code == "VIDEO_IN_PROGRESS" and not first.value
    async with asyncio.timeout(18):
        while not (lease := (await state.acquire(VIDEO, state.run_id)).value):
            await asyncio.sleep(0.25)
    recovered = await state.load_stage(lease)
    assert recovered and recovered["payload"] == {"transcript": "staged"}
    payload = {"transcript": "delivered"}
    assert await state.stage(lease, OPTIONS, payload)
    assert await state.commit(lease, OPTIONS, "success", payload)
    assert (await state.record_answer(state.tenant_id, "original-list", VIDEO, Outcome("success"))).is_new
    await state.save_checkpoint(state.tenant_id, "probe", Checkpoint(completed=({"videoId": VIDEO},)))
    await store.set_record("probe-replacement", {"ready": True})
    await wait_for_record(store, "probe-stale-checked")
    assert await state.release(lease)
    repeat = await state.acquire(VIDEO, state.run_id, options=OPTIONS, baseline=baseline)
    assert repeat.error_code == "RESULT_AVAILABLE" and not repeat.value
    return {"role": "contender", "blockedWhileOwned": True, "tookOverAfterExpiry": True, "reusedResult": True}


async def main():
    async with Actor:
        env, client = Actor.get_env(), Actor.apify_client
        raw = await Actor.get_input()
        role, namespace = raw["role"], f"reelsaid-{raw['key']}"
        start = monotonic()
        state = await State.open(client, env["user_id"], env["run_id"], namespace=namespace, lock_seconds=5)
        info = await client.key_value_stores().get_or_create(name=f"{namespace}-state")
        assert info.general_access == "RESTRICTED"
        operation = {"holder": hold, "contender": contend}[role]
        result = await operation(state, client.key_value_store(info.id))
        await Actor.push_data({
            **result,
            "permissionLevel": env["permission_level"],
            "milliseconds": round((monotonic() - start) * 1000),
        })


if __name__ == "__main__":
    asyncio.run(main())
