import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from reelsaid.contracts import Outcome, TranscriptOptions
from reelsaid.state import Checkpoint, State, StateAccessError, StateUnavailable


OPTIONS = TranscriptOptions()


class FakeStore:
    def __init__(self):
        self.records = {}
        self.fail_at = None

    async def get_record(self, key):
        return {"value": deepcopy(self.records[key])} if key in self.records else None

    async def set_record(self, key, value, **kwargs):
        if self.fail_at and key.startswith(self.fail_at):
            raise StateUnavailable("Interrupted write")
        self.records[key] = deepcopy(value)


class FakeQueue:
    def __init__(self, queue, client_key):
        self.queue = queue
        self.client_key = client_key

    async def add_request(self, data):
        return SimpleNamespace(request_id=data["uniqueKey"])

    async def list_and_lock_head(self, **kwargs):
        await asyncio.sleep(0)
        if self.queue.owner:
            return SimpleNamespace(items=[])
        self.queue.owner = self.client_key
        return SimpleNamespace(items=[SimpleNamespace(id="reelsaid-work")])

    async def prolong_request_lock(self, request_id, **kwargs):
        return object() if self.queue.owner == self.client_key else None

    async def delete_request_lock(self, request_id):
        assert self.queue.owner == self.client_key
        self.queue.owner = None


class FakeAccount:
    def __init__(self, user_id):
        self.store = FakeStore()
        self.queues = {}
        self.user_id = user_id

    def state(self, run_id):
        return State(self, self.store, self.user_id, run_id)

    def request_queues(self):
        async def get_or_create(*, name):
            self.queues.setdefault(name, SimpleNamespace(owner=None))
            return SimpleNamespace(id=name, user_id=self.user_id, general_access="RESTRICTED")

        return SimpleNamespace(get_or_create=get_or_create)

    def request_queue(self, queue_id, *, client_key):
        return FakeQueue(self.queues[queue_id], client_key)


def test_expired_owner_allows_recovery():
    async def check():
        account = FakeAccount("account")
        original = account.state("original")
        contenders = [account.state(f"run-{index}") for index in range(12)]
        first = (await original.acquire("reel", "original")).value
        assert first and await original.stage(first, OPTIONS, {"transcript": "staged"})
        assert not (await contenders[0].acquire("reel", contenders[0].run_id)).value
        account.queues[f"reelsaid-v1-work-{first.slot:02x}"].owner = None
        outcomes = await asyncio.gather(*(state.acquire("reel", state.run_id) for state in contenders))
        active = [outcome.value for outcome in outcomes if outcome.status == "success"]
        assert len(active) == 1
        assert all(outcome.retryable for outcome in outcomes if outcome.status != "success")
        assert not await original.stage(first, OPTIONS, {"transcript": "late"})
        assert not await original.commit(first, OPTIONS, "success", {"transcript": "late"})
        winner = next(state for state in contenders if state.run_id == active[0].run_id)
        staged = await winner.load_stage(active[0])
        assert staged["runId"] == "original" and staged["payload"]["transcript"] == "staged"
        assert await winner.release(active[0])

    asyncio.run(check())


def test_tenant_isolation():
    async def check():
        alice = FakeAccount("alice").state("one")
        bob = FakeAccount("bob").state("two")
        lease = (await alice.acquire("reel", "one")).value
        assert await alice.stage(lease, OPTIONS, {"transcript": "Alice's result"})
        assert await alice.commit(lease, OPTIONS, "success", {"transcript": "Alice's result"})
        await alice.record_answer("alice", "watch", "reel", Outcome("success"))
        await alice.save_checkpoint("alice", "dataset", Checkpoint(pending=({"videoId": "reel"},)))

        assert (await bob.acquire("reel", "two")).value
        assert not (await bob.lookup("bob", "reel", OPTIONS)).result
        assert not (await bob.lookup_answer("bob", "watch", "reel")).answered
        assert await bob.load_checkpoint("bob", "dataset") is None
        assert not await bob.commit(lease, OPTIONS, "success", {"transcript": "wrong account"})
        with pytest.raises(StateAccessError):
            await bob.lookup("alice", "reel", OPTIONS)

    asyncio.run(check())


def test_overlapping_refresh_coalesces():
    async def check():
        account = FakeAccount("account")
        first, second = account.state("first"), account.state("second")
        baseline = await second.lookup("account", "video", OPTIONS)
        before = (await first.acquire("video", "first")).value
        assert not (await second.acquire("video", "second")).value
        assert await first.stage(before, OPTIONS, {"transcript": "new"})
        assert await first.commit(before, OPTIONS, "success", {"transcript": "new"})
        assert await first.release(before)
        visible = await second.lookup("account", "video", OPTIONS)
        assert visible.changed_since(baseline) and visible.reusable
        coalesced = await second.acquire("video", "second", options=OPTIONS, baseline=baseline)
        assert coalesced.error_code == "RESULT_AVAILABLE" and not coalesced.value
        assert not (await second.lookup("account", "video", TranscriptOptions(language="es"))).result
        later = await second.acquire("video", "second", options=OPTIONS, baseline=visible)
        assert later.status == "success"

    asyncio.run(check())


def test_checkpoint_preserves_completed_work():
    async def check():
        account = FakeAccount("account")
        owner, resume = account.state("owner"), account.state("resume")
        saved = Checkpoint(
            pending=({"videoId": "second"}, {"videoId": "third"}),
            completed=({"videoId": "first", "datasetId": "last", "charged": True},),
            cursor={"sourceIndex": 3, "profileCursor": ["relay", "next"]},
            filters={"maxDurationSeconds": 60},
            stop_reason="BUDGET_LIMIT",
        )
        await owner.save_checkpoint("account", "last", saved)
        assert await resume.load_checkpoint("account", "last") == saved
        account.store.fail_at = "checkpoint-"
        with pytest.raises(StateUnavailable):
            await resume.save_checkpoint("account", "last", Checkpoint(pending=({"videoId": "different"},)))
        assert await owner.load_checkpoint("account", "last") == saved

    asyncio.run(check())


def test_new_watchlist_uses_account_answers():
    async def check():
        account = FakeAccount("account")
        first, second = account.state("one"), account.state("two")
        for outcome in (Outcome("failed", "TEMPORARILY_BLOCKED", True), Outcome("partial"), Outcome("skipped", "PINNED")):
            assert not (await first.record_answer("account", "daily", "reel", outcome)).answered
        answer = await first.record_answer("account", "daily", "reel", Outcome("skipped", "MUSIC_ONLY"))
        assert answer.is_new
        other = await second.lookup_answer("account", "a-new-list", "reel")
        assert other.answered and not other.is_new and other.first_seen_at == answer.first_seen_at

    asyncio.run(check())
