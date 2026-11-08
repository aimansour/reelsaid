"""Exercise fencing from two independent Apify runs against the state service."""

import asyncio
import os

from apify import Actor
from curl_cffi.requests import AsyncSession

from reelsaid.contracts import Outcome, TranscriptOptions
from reelsaid.state import Checkpoint, D1Backend, State


OPTIONS = TranscriptOptions()


async def note(state, key, name):
    return await state.record_answer(state.tenant_id, key, name, Outcome("success"))


async def wait_for_note(state, key, name, *, keep_alive=None):
    async with asyncio.timeout(25):
        while not (await state.lookup_answer(state.tenant_id, key, name)).answered:
            if keep_alive:
                assert await state.renew(keep_alive)
            await asyncio.sleep(0.25)


async def hold(state, key):
    lease = (await state.acquire(key, state.run_id)).value
    assert lease and await state.stage(lease, OPTIONS, {"transcript": "staged"})
    await note(state, key, "ready")
    await wait_for_note(state, key, "blocked", keep_alive=lease)
    await wait_for_note(state, key, "committed")
    assert not await state.stage(lease, OPTIONS, {"transcript": "stale"})
    assert not await state.commit(lease, OPTIONS, "success", {"transcript": "stale"})
    assert not await state.release(lease)
    result = await state.lookup(state.tenant_id, key, OPTIONS)
    assert result.reusable and result.result.payload == {"transcript": "winner"}
    checkpoint = await state.load_checkpoint(state.tenant_id, key)
    assert checkpoint and checkpoint.completed[0]["videoId"] == key
    return {"role": "holder", "staleFenced": True, "checkpointRecovered": True}


async def contend(state, key):
    await wait_for_note(state, key, "ready")
    first = await state.acquire(key, state.run_id)
    assert first.error_code == "VIDEO_IN_PROGRESS" and not first.value
    await note(state, key, "blocked")
    async with asyncio.timeout(15):
        while not (lease := (await state.acquire(key, state.run_id)).value):
            await asyncio.sleep(0.25)
    payload = {"transcript": "winner"}
    assert await state.stage(lease, OPTIONS, payload)
    assert await state.commit(lease, OPTIONS, "success", payload)
    await state.save_checkpoint(state.tenant_id, key, Checkpoint(completed=({"videoId": key},)))
    await note(state, key, "committed")
    await state.release(lease)
    return {"role": "contender", "blockedWhileOwned": True, "tookOverAfterExpiry": True}


async def main():
    async with Actor, AsyncSession(trust_env=False) as session:
        env = Actor.get_env()
        raw = await Actor.get_input()
        role, key = raw["role"], raw["key"]
        backend = D1Backend(session, os.environ["REELSAID_STATE_URL"], os.environ["REELSAID_STATE_SECRET"])
        state = State(backend, env["user_id"], env["run_id"], lease_ms=3500)
        operation = {"holder": hold, "contender": contend}[role]
        result = await operation(state, key)
        await Actor.push_data(result)


if __name__ == "__main__":
    asyncio.run(main())
