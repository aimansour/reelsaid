import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import reelsaid.state as state_module
from reelsaid.contracts import Outcome, TranscriptOptions
from reelsaid.state import Checkpoint, State, StateAccessError, StateUnavailable


DIRECTORY = Path("services/state")
OPTIONS = TranscriptOptions()


class SQLiteBackend:
    """Run the service's exact statements using separate database connections."""

    def __init__(self, path):
        self.path = path
        self.statements = json.loads((DIRECTORY / "statements.json").read_text())
        with sqlite3.connect(path) as database:
            database.executescript((DIRECTORY / "schema.sql").read_text())

    def execute(self, operation, parameters):
        with sqlite3.connect(self.path) as database:
            database.row_factory = sqlite3.Row
            return [dict(row) for row in database.execute(self.statements[operation], parameters)]

    async def query(self, operation, *parameters):
        return await asyncio.to_thread(self.execute, operation, parameters)


@pytest.fixture
def backend(tmp_path):
    return SQLiteBackend(tmp_path / "state.sqlite")


def test_expired_lease_fences_owner(backend):
    async def check():
        owner = State(backend, "account-a", "run-a", lease_ms=35)
        contenders = [State(backend, "account-b", f"run-{index}") for index in range(12)]
        first = (await owner.acquire("shared-reel", "run-a")).value
        assert first
        assert await owner.stage(first, OPTIONS, {"transcript": "original staged"})
        await asyncio.sleep(0.06)
        outcomes = await asyncio.gather(*(state.acquire("shared-reel", state.run_id) for state in contenders))
        active = [outcome.value for outcome in outcomes if outcome.status == "success"]
        assert len(active) == 1
        assert all(outcome.retryable for outcome in outcomes if outcome.status != "success")
        assert not await owner.stage(first, OPTIONS, {"transcript": "stale"})
        assert not await owner.commit(first, OPTIONS, "success", {"transcript": "stale"})
        assert not await owner.release(first)
        assert not await owner.renew(first)
        assert not (await owner.lookup("account-a", "shared-reel", OPTIONS)).result
        winner = next(state for state in contenders if state.run_id == active[0].run_id)
        assert await winner.stage(active[0], OPTIONS, {"transcript": "winning"})
        assert await winner.commit(active[0], OPTIONS, "success", {"transcript": "winning"})
        assert (await winner.lookup("account-b", "shared-reel", OPTIONS)).result.payload["transcript"] == "winning"

    asyncio.run(check())


def test_tenant_isolation(backend):
    async def check():
        alice = State(backend, "alice", "one")
        bob = State(backend, "bob", "two")
        lease = (await alice.acquire("reel", "one")).value
        assert await alice.stage(lease, OPTIONS, {"transcript": "Alice's result"})
        assert await alice.commit(lease, OPTIONS, "success", {"transcript": "Alice's result"})
        await alice.record_answer("alice", "watch", "reel", Outcome("success"))
        await alice.save_checkpoint("alice", "dataset", Checkpoint(pending=({"videoId": "reel"},)))

        assert not (await bob.lookup("bob", "reel", OPTIONS)).result
        assert not (await bob.lookup_answer("bob", "watch", "reel")).answered
        assert await bob.load_checkpoint("bob", "dataset") is None
        assert not await bob.commit(lease, OPTIONS, "success", {"transcript": "wrong account"})
        with pytest.raises(StateAccessError):
            await bob.lookup("alice", "reel", OPTIONS)

    asyncio.run(check())


def test_overlapping_refresh_coalesces(backend):
    async def check():
        first = State(backend, "account", "first")
        second = State(backend, "account", "second")
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


def test_checkpoint_preserves_completed_work(backend):
    async def check():
        owner = State(backend, "account", "run-a")
        resume = State(backend, "account", "run-b")
        saved = Checkpoint(
            pending=({"videoId": "second"}, {"videoId": "third"}),
            completed=({"videoId": "first", "datasetId": "last", "charged": True},),
            cursor={"sourceIndex": 3, "profileCursor": ["relay", "next"]},
            filters={"maxDurationSeconds": 60},
            stop_reason="BUDGET_LIMIT",
        )
        await owner.save_checkpoint("account", "last", saved)
        assert await resume.load_checkpoint("account", "last") == saved
        updated = Checkpoint(pending=({"videoId": "third"},), completed=saved.completed)
        await resume.save_checkpoint("account", "last", updated)
        assert await owner.load_checkpoint("account", "last") == updated

    asyncio.run(check())


def test_watchlist_records_only_definitive_answers_once(backend):
    async def check():
        first, second = [State(backend, "account", run_id) for run_id in ("one", "two")]
        for outcome in (Outcome("failed", "TEMPORARILY_BLOCKED", True), Outcome("partial"), Outcome("skipped", "PINNED")):
            assert not (await first.record_answer("account", "daily", "reel", outcome)).answered
        answers = await asyncio.gather(*(
            state.record_answer("account", "daily", "reel", Outcome("skipped", "MUSIC_ONLY"))
            for state in (first, second)
        ))
        assert sum(answer.is_new for answer in answers) == 1
        assert answers[0].first_seen_at == answers[1].first_seen_at
        assert (await second.lookup_answer("account", "daily", "reel")).answered

    asyncio.run(check())


def test_interrupted_checkpoint_save_leaves_last_complete_generation(backend, monkeypatch):
    monkeypatch.setattr(state_module, "CHECKPOINT_PART_SIZE", 32)

    class InterruptedBackend:
        async def query(self, operation, *parameters):
            if operation == "publish_checkpoint":
                raise StateUnavailable("Connection interrupted")
            return await backend.query(operation, *parameters)

    async def check():
        first = State(backend, "account", "first")
        staged = State(InterruptedBackend(), "account", "staged")
        last = Checkpoint(pending=({"videoId": "unfinished"},))
        await first.save_checkpoint("account", "dataset", last)
        with pytest.raises(StateUnavailable):
            await staged.save_checkpoint("account", "dataset", Checkpoint(pending=({"videoId": "replacement"},)))
        assert await first.load_checkpoint("account", "dataset") == last

    asyncio.run(check())
