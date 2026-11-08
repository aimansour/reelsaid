import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from apify_client.errors import ApifyClientError

from reelsaid.actor import ActorContext, run
from reelsaid.billing import PROPOSED_BASE, PROPOSED_MINUTE, RunBudget, RunPricing
from reelsaid.contracts import Outcome
from reelsaid.groq import Segment, Word
from reelsaid.instagram import InstagramError, ProfilePage
from reelsaid.media import MediaAsset, MediaPlan
from reelsaid.quality import Assessment, TranscriptResult

from test_billing import Provider
from test_state import FakeAccount


NOW = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)
SHORT, LONG, NEXT, CAROUSEL, PRIVATE = "DS46KJNjva9", "CsuFa_Mga41", "Dfax6SllBLR", "Ddm6E9OGt5D", "AbcDEF12345"
PREFILL = json.loads((Path(__file__).resolve().parents[1] / ".actor/input_schema.json").read_text())["properties"]["startUrls"]["prefill"]


class Output:
    def __init__(self, dataset_id):
        self.dataset_id = dataset_id
        self.store_id = f"storage-{dataset_id}"
        self.rows = []
        self.records = {}

    async def existing(self):
        return list(self.rows)

    async def push(self, row):
        self.rows.append(row)

    async def put(self, key, value, content_type="application/json"):
        self.records[key] = value


def video(code, *, duration=8, position=0):
    url = f"https://scontent.cdninstagram.com/{code}-{position}.mp4"
    return {"pk": f"{position}", "media_type": 2, "video_url": url, "video_duration": duration}


class Instagram:
    def __init__(self):
        self.posts = {}
        self.calls = []
        for offset, (code, duration) in enumerate(((SHORT, 8), (LONG, 181), (NEXT, 8), (CAROUSEL, 8))):
            self.posts[code] = {
                **video(code, duration=duration),
                "taken_at": (NOW - timedelta(days=offset)).timestamp(),
                "user": {"username": "public.personal"},
            }
        self.posts[CAROUSEL]["carousel_media"] = [video(CAROUSEL), {"media_type": 1}, video(CAROUSEL, position=2)]

    async def post(self, code):
        self.calls.append(code)
        if code not in self.posts:
            raise InstagramError("CONTENT_UNAVAILABLE")
        return self.posts[code]

    async def profile(self, username, cursor):
        return ProfilePage("1", tuple({"code": code} for code in (SHORT, LONG, NEXT)))


class Case:
    def __init__(self):
        self.instagram = Instagram()
        self.account = FakeAccount("account")
        self.inspect_calls = []
        self.asr_calls = []
        self.outcomes = {}
        self.known_durations = {}
        self.expired = False
        self.pause = asyncio.Event()
        self.pause.set()

    def context(self, run_id, *, cap=None, output=None):
        provider = Provider()
        return ActorContext(
            instagram=self.instagram, apify=None, now=NOW, expired=lambda: self.expired,
            output=output or Output(run_id), state=self.account.state(run_id), provider=provider,
            pricing=RunPricing(RunBudget(cap), PROPOSED_BASE["FREE"], PROPOSED_MINUTE, True),
            inspect=self.inspect, evaluate=self.evaluate,
        )

    async def inspect(self, ref, context):
        code = ref.metadata.shortcode or ref.video_id
        self.inspect_calls.append(code)
        seconds = Decimal(self.known_durations.get(code, ref.metadata.duration_seconds or 8))
        asset = MediaAsset(ref.video_url, seconds, True, True, 1)
        return Outcome("success", value=MediaPlan(ref.video_id, ref, seconds, asset, asset, ()))

    async def evaluate(self, media, options, context):
        code = media.ref.metadata.shortcode or media.video_id
        self.asr_calls.append(code)
        await self.pause.wait()
        outcome = self.outcomes.get(code, "success")
        if outcome == "failure":
            return Outcome("failed", "PROVIDER_UNAVAILABLE", True)
        if outcome == "time":
            self.expired = True
            return Outcome("deferred", "TIME_LIMIT", True)
        if outcome == "silence":
            return Outcome("skipped", "SILENCE", value=TranscriptResult(
                "", None, media.duration_seconds, (), (), None, "silence", 0.99, Assessment(), False,
            ))
        return Outcome("success", value=TranscriptResult(
            "One good sentence.", "English", media.duration_seconds,
            (Segment("One good sentence.", 0.1, 2.5),),
            (Word("One", 0.1, 0.2), Word("good", 0.3, 0.5), Word("sentence.", 0.6, 2.5)),
            "asr", "speech", None, Assessment(0), True,
        ))


def test_api_input_and_store_prefill():
    async def check():
        case = Case()
        for index, payload in enumerate(({}, {"startURL": PREFILL}, {"startUrls": ["https://example.org"]})):
            context = case.context(str(index))
            result = await run(payload, context)
            assert result.input_errors == 1 and not context.provider.calls
        assert not case.asr_calls and not case.instagram.calls
        context = case.context("prefill")
        result = await run({"startUrls": ["https://example.org", *PREFILL], "wordLevelTimestamps": True}, context)
        assert result.successful == result.billed == result.input_errors == 1
        row = next(row for row in context.output.rows if row["kind"] == "video")
        assert row["transcript"] == "One good sentence." and len(row["wordLevelTimestamps"]) == 3
        assert row["subtitles"]["vtt"]["key"] in context.output.records
    asyncio.run(check())


def test_ordered_budget_stop_and_resume():
    async def check():
        case = Case()
        initial = replace(case.context("first", cap=Decimal("0.024")), concurrency=3)
        summary = await run({"shortcodes": [SHORT, LONG, NEXT]}, initial)
        assert summary.stop_reason == "SPEND_LIMIT"
        assert case.asr_calls == [SHORT]
        assert initial.output.rows[0]["charged"] is True
        assert summary.continuation.remaining == 2
        resumed = case.context("second", cap=Decimal("0.027"))
        done = await run({"resumeFromDatasetId": "first"}, resumed)
        assert [row["videoId"] for row in resumed.output.rows] == [LONG, NEXT]
        assert done.billed == 2 and case.asr_calls == [SHORT, LONG, NEXT]
        assert done.completed_dataset_ids == ("first",)
        assert len(initial.provider.calls) == 1 and len(resumed.provider.calls) == 3
    asyncio.run(check())


def test_batch_overlaps_transcription_with_ordered_delivery():
    async def check():
        case = Case()
        both_admitted = asyncio.Event()
        started = []

        async def evaluate(media, options, context):
            started.append(media.video_id)
            if len(started) == 2:
                both_admitted.set()
            await asyncio.wait_for(both_admitted.wait(), timeout=1)
            if media.video_id == SHORT:
                await asyncio.sleep(0.02)
            return await case.evaluate(media, options, context)

        context = replace(case.context("overlap", cap=Decimal("0.027")), concurrency=2, evaluate=evaluate)
        result = await run({"shortcodes": [SHORT, LONG]}, context)
        assert result.successful == result.billed == 2
        assert started == [SHORT, LONG]
        assert [row["videoId"] for row in context.output.rows] == [SHORT, LONG]
    asyncio.run(check())


def test_watchlist_first_and_later_runs():
    async def check():
        case = Case()
        case.outcomes.update({LONG: "silence", NEXT: "failure"})
        first = case.context("first")
        opts = {"profiles": ["public.personal"], "watchlistId": "original", "newReelsOnly": True}
        summary = await run(opts, first)
        assert (summary.successful, summary.new_answers, summary.failed, summary.billed) == (1, 2, 1, 1)
        assert all(row["isNew"] is True for row in first.output.rows if row["videoId"] in (SHORT, LONG))
        assert summary.continuation
        case.inspect_calls.clear()
        case.outcomes.pop(NEXT)
        second = case.context("second")
        result = await run({**opts, "watchlistId": "new-name"}, second)
        assert result.previously_answered == 2 and result.new_answers == 1
        assert case.inspect_calls == [NEXT]
        answered = next(row for row in second.output.rows if row["videoId"] == SHORT)
        assert answered["isNew"] is False and answered["firstSeenRunId"] == "first"
    asyncio.run(check())


def test_bounded_newest_profile_defers_older_pages_for_resume():
    async def check():
        case = Case()
        pages = []

        async def profile(username, cursor):
            pages.append(cursor)
            if cursor:
                return ProfilePage("1", ({"code": NEXT, "clips_tab_pinned_user_ids": []},))
            return ProfilePage("1", tuple(
                {"code": code, "clips_tab_pinned_user_ids": []} for code in (SHORT, LONG)
            ), ("profile", "next"))

        case.instagram.profile = profile
        first = case.context("first")
        summary = await run({"profiles": ["public.personal"], "maxResults": 2}, first)
        assert pages == [None]
        assert summary.stop_reason == "RESULT_LIMIT" and summary.continuation.remaining is None
        assert [row["videoId"] for row in first.output.rows] == [SHORT, LONG]
        second = case.context("second")
        resumed = await run({"resumeFromDatasetId": "first"}, second)
        assert pages == [None, ("profile", "next")]
        assert resumed.successful == 1 and resumed.continuation is None
        assert [row["videoId"] for row in second.output.rows] == [NEXT]
    asyncio.run(check())


def test_batch_keeps_completed_results():
    async def check():
        case = Case()
        context = case.context("batch")
        result = await run({"shortcodes": [SHORT, CAROUSEL, PRIVATE]}, context)
        assert result.successful == result.billed == 3 and result.input_errors == 1
        children = [row for row in context.output.rows if row["videoId"] and row["videoId"].startswith(CAROUSEL)]
        assert sorted(row["metadata"]["carouselPosition"] for row in children) == [0, 2]
        assert len(context.provider.calls) == 3
    asyncio.run(check())


def test_cache_hit_and_refresh():
    async def check():
        case = Case()
        payload = {"shortcodes": [SHORT]}
        await run(payload, case.context("initial"))
        cached = case.context("cached")
        summary = await run({**payload, "includeSrt": False}, cached)
        assert summary.cached == 1 and not cached.provider.calls and case.asr_calls == [SHORT]
        assert cached.output.rows[0]["subtitles"]["srt"] is None
        assert cached.output.rows[0]["subtitles"]["vtt"]["key"] in cached.output.records
        case.pause.clear()
        first, second = case.context("refresh-a"), case.context("refresh-b")
        first_task = asyncio.create_task(run({**payload, "forceRefresh": True}, first))
        while len(case.asr_calls) < 2:
            await asyncio.sleep(0)
        second_task = asyncio.create_task(run({**payload, "forceRefresh": True}, second))
        await asyncio.sleep(0.05)
        case.pause.set()
        await asyncio.gather(first_task, second_task)
        assert case.asr_calls == [SHORT, SHORT]
        assert len(first.provider.calls) == 1 and not second.provider.calls
        assert second.output.rows[0]["cached"] is True
    asyncio.run(check())


def test_duration_and_time_stops():
    async def check():
        case = Case()
        case.known_durations[SHORT] = 181
        case.outcomes[LONG] = "time"
        context = case.context("timed")
        summary = await run({"shortcodes": [SHORT, LONG, NEXT], "maxDurationSeconds": 181}, context)
        assert summary.stop_reason == "TIME_LIMIT" and case.asr_calls == [SHORT, LONG]
        assert summary.continuation.remaining == 2
        case.expired = False
        case.asr_calls.clear()
        single = case.context("duration")
        result = await run({"shortcodes": [SHORT], "maxDurationSeconds": 180, "forceRefresh": True}, single)
        assert result.skipped == 1 and not case.asr_calls
        assert single.output.rows[0]["errorCode"] == "DURATION_LIMIT"
    asyncio.run(check())


def test_dataset_response_loss_does_not_repeat_billing_or_paid_rows():
    class InterruptedOutput(Output):
        async def push(self, row):
            await super().push(row)
            if row["kind"] == "video":
                raise ApifyClientError("Response unavailable after dataset write")

    async def check():
        case = Case()
        first = case.context("first", output=InterruptedOutput("first"))
        paused = await run({"shortcodes": [SHORT, NEXT]}, first)
        assert paused.stop_reason == "DELIVERY_INTERRUPTED"
        assert len(first.provider.calls) == 1 and len(first.output.rows) == 1

        async def read_previous(dataset_id):
            assert dataset_id == "first"
            return await first.output.existing()

        resumed = replace(case.context("later"), read_previous=read_previous)
        done = await run({"resumeFromDatasetId": "first"}, resumed)
        assert done.completed_dataset_ids == ("first",)
        assert [row["videoId"] for row in resumed.output.rows] == [NEXT]
        assert case.asr_calls == [SHORT, NEXT]
        assert len(resumed.provider.calls) == 1
    asyncio.run(check())
