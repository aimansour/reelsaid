import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from apify_client.errors import ApifyClientError

from reelsaid.actor import ActorContext, run
from reelsaid.audio_quality import SpeechEvidence
from reelsaid.billing import BASE_EVENT, PROPOSED_BASE, PROPOSED_MINUTE, RunBudget, RunPricing
from reelsaid.contracts import Outcome
from reelsaid.groq import LARGE, Segment, TranscriptDraft, Word
from reelsaid.instagram import InstagramError, ProfilePage
from reelsaid.media import MediaAsset, MediaPlan
from reelsaid.quality import Assessment, TranscriptResult, evaluate_video

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


def test_cache_and_charges_are_independent_between_accounts():
    async def check():
        alice, bob = Case(), Case()
        alice.account, bob.account = FakeAccount("alice"), FakeAccount("bob")
        request = {"startUrls": [f"https://www.instagram.com/reel/{SHORT}/"]}
        alice_first = alice.context("alice-first", cap=Decimal("0.012"))
        alice_retry = alice.context("alice-retry", cap=Decimal("0"))
        bob_first = bob.context("bob-first", cap=Decimal("0.012"))

        await run(request, alice_first)
        await run(request, alice_retry)
        await run(request, bob_first)

        assert alice_first.provider.events == bob_first.provider.events == {BASE_EVENT: 1}
        assert not alice_retry.provider.calls
        assert alice.asr_calls == bob.asr_calls == [SHORT]
        assert alice_retry.output.rows[0]["cached"] is True
        assert bob_first.output.rows[0]["cached"] is False
        assert alice_first.output.rows[0]["subtitles"]["vtt"]["key"] in alice_first.output.records
        assert bob_first.output.rows[0]["subtitles"]["vtt"]["key"] in bob_first.output.records
        assert alice_first.output.store_id != bob_first.output.store_id

    asyncio.run(check())


def test_audio_policy_preserves_free_and_mixed_speech_outcomes():
    async def check():
        case = Case()
        silence, music, mixed, boundary, unresolved = SHORT, LONG, NEXT, "AbcDEF12340", "AbcDEF12341"
        codes = [silence, music, mixed, boundary, unresolved]
        for code in codes:
            case.instagram.posts[code] = video(code, duration=10)
        classifications = {
            silence: SpeechEvidence("silence", confidence=1.0),
            music: SpeechEvidence("music_only", confidence=.95),
            mixed: SpeechEvidence("speech", ((0, 4), (6, 10)), .98),
            boundary: SpeechEvidence("speech", ((0, 10),), .98),
            unresolved: SpeechEvidence("speech", ((0, 10),), .98),
        }
        segments = {
            silence: (Segment("Invented words.", 0, 2),),
            music: (Segment("Invented words.", 0, 2),),
            mixed: (Segment("Voz real.", 0, 4), Segment("Con música.", 6, 10)),
            boundary: (Segment("Voz válida.", 2, 10),),
            unresolved: (Segment("Texto incompleto.", 2.1, 10),),
        }
        calls = []

        @asynccontextmanager
        async def probe(media, context):
            yield classifications[media.video_id], media

        async def asr(media, options, context, **kwargs):
            calls.append((media.video_id, kwargs.get("models")))
            timing = segments[media.video_id]
            return Outcome("success", value=TranscriptDraft(
                " ".join(segment.text for segment in timing), "es", timing, (), 10,
            ))

        async def evaluate(media, options, context):
            return await evaluate_video(media, options, context, speech_probe=probe, asr=asr)

        context = replace(case.context("audio-policy"), evaluate=evaluate)
        await run({"shortcodes": codes}, context)
        rows = {row["videoId"]: row for row in context.output.rows}
        for code, error in ((silence, "SILENCE"), (music, "MUSIC_ONLY")):
            assert rows[code]["errorCode"] == error
            assert not rows[code]["transcript"] and rows[code]["chargedEvents"] == {}
        assert rows[mixed]["transcript"] == "Voz real. Con música." and rows[mixed]["charged"] is True
        assert rows[boundary]["quality"]["affectedFraction"] == .20 and rows[boundary]["charged"] is True
        assert rows[unresolved]["errorCode"] == "QUALITY_LIMIT_EXCEEDED"
        assert rows[unresolved]["charged"] is False and rows[unresolved]["chargedEvents"] == {}
        assert (boundary, (LARGE,)) not in calls and (unresolved, (LARGE,)) in calls
        assert context.provider.events == {BASE_EVENT: 2}

    asyncio.run(check())


def test_subtitle_records_write_concurrently_before_delivering_the_row():
    class CoordinatedOutput(Output):
        def __init__(self):
            super().__init__("subtitle-order")
            self.writes = set()
            self.both_started = asyncio.Event()

        async def put(self, key, value, content_type="application/json"):
            if key.startswith("subtitle-"):
                self.writes.add(key)
                if len(self.writes) == 2:
                    self.both_started.set()
                await asyncio.wait_for(self.both_started.wait(), timeout=.5)
            await super().put(key, value, content_type)

        async def push(self, row):
            assert self.writes <= self.records.keys()
            await super().push(row)

    async def check():
        case = Case()
        output = CoordinatedOutput()
        context = case.context("subtitle-order", output=output)
        await run({"shortcodes": [SHORT]}, context)
        assert len(output.writes) == 2
        assert len(output.rows) == 1 and all(output.rows[0]["subtitles"].values())
        assert context.provider.events == {BASE_EVENT: 1}

    asyncio.run(check())


def test_interrupted_subtitle_write_resumes_without_charging_again():
    class InterruptedOutput(Output):
        async def put(self, key, value, content_type="application/json"):
            if key.startswith("subtitle-vtt-"):
                raise ApifyClientError("Subtitle write unavailable")
            await super().put(key, value, content_type)

    async def check():
        case = Case()
        first = case.context("subtitles-interrupted", output=InterruptedOutput("subtitles-interrupted"))
        paused = await run({"shortcodes": [SHORT]}, first)
        assert paused.stop_reason == "DELIVERY_INTERRUPTED"
        assert first.output.rows == []
        assert first.provider.events == {BASE_EVENT: 1}

        resumed = case.context("subtitles-resumed")
        await run({"resumeFromDatasetId": "subtitles-interrupted"}, resumed)
        assert case.asr_calls == [SHORT]
        assert resumed.provider.events == {}
        assert len(resumed.output.rows) == 1
        assert all(resumed.output.rows[0]["subtitles"].values())

    asyncio.run(check())


def test_committed_paid_result_keeps_billing_origin_across_interrupted_delivery():
    class InterruptedOutput(Output):
        async def push(self, row):
            raise ApifyClientError("Dataset write unavailable")

    async def check(force_refresh):
        case = Case()
        first = case.context("paying-run", output=InterruptedOutput("first-dataset"))
        paused = await run({"shortcodes": [SHORT], "forceRefresh": force_refresh}, first)
        assert paused.stop_reason == "DELIVERY_INTERRUPTED" and not first.output.rows
        assert first.provider.events == {BASE_EVENT: 1}

        second = case.context("interrupted-resume", output=InterruptedOutput("second-dataset"))
        paused_again = await run({"resumeFromDatasetId": "first-dataset"}, second)
        assert paused_again.stop_reason == "DELIVERY_INTERRUPTED" and second.provider.events == {}

        if force_refresh:
            async def newer_transcript(media, options, context):
                evaluated = await case.evaluate(media, options, context)
                return replace(evaluated, value=replace(evaluated.value, text="A newer transcript."))

            independent = replace(case.context("independent-refresh"), evaluate=newer_transcript)
            refreshed = await run({"shortcodes": [SHORT], "forceRefresh": True}, independent)
            assert refreshed.billed == 1 and independent.output.rows[0]["transcript"] == "A newer transcript."

        resumed = case.context("completed-resume")
        summary = await run({"resumeFromDatasetId": "second-dataset"}, resumed)
        assert summary.successful == 1 and not summary.charged_events
        assert case.asr_calls == ([SHORT, SHORT] if force_refresh else [SHORT]) and resumed.provider.events == {}
        row, = resumed.output.rows
        assert row["billingOriginRunId"] == "paying-run"
        assert row["charged"] is False and row["chargedEvents"] == {}
        assert row["transcript"] == "One good sentence."

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_canonical_delivery_resume_handles_expired_source_and_ambiguous_prior_read():
    async def check(delivered):
        class InterruptedOutput(Output):
            async def push(self, row):
                if delivered:
                    await super().push(row)
                raise ApifyClientError("Dataset acknowledgement unavailable")

        case = Case()

        async def canonical_inspect(ref, context):
            resolved = replace(ref, video_id=SHORT, metadata=replace(ref.metadata, shortcode=SHORT))
            return await case.inspect(resolved, context)

        async def unavailable_inspect(ref, context):
            return Outcome("failed", "MEDIA_URL_EXPIRED", True)

        async def unavailable_read(dataset_id):
            raise ApifyClientError("Prior dataset unavailable")

        async def read_previous(dataset_id):
            assert dataset_id == "paid-dataset"
            return first.output.rows

        first = replace(case.context("paying-run", output=InterruptedOutput("paid-dataset")), inspect=canonical_inspect)
        summary = await run({"startUrls": ["https://scontent.cdninstagram.com/video.mp4"]}, first)
        assert summary.stop_reason == "DELIVERY_INTERRUPTED" and first.provider.events == {BASE_EVENT: 1}
        source = {"resumeFromDatasetId": "paid-dataset"}
        failed_read = replace(case.context("read-interrupted"), inspect=unavailable_inspect, read_previous=unavailable_read)
        summary = await run(source, failed_read)
        assert summary.stop_reason == "DELIVERY_INTERRUPTED" and summary.continuation.dataset_id == "paid-dataset"
        assert not failed_read.output.rows and not failed_read.provider.events

        resumed = replace(case.context("resumed"), inspect=unavailable_inspect, read_previous=read_previous)
        summary = await run(source, resumed)
        assert case.asr_calls == [SHORT] and not resumed.provider.events
        if delivered:
            assert not resumed.output.rows and summary.completed_dataset_ids == ("paid-dataset",)
        else:
            row, = resumed.output.rows
            assert row["status"] == "success" and row["billingOriginRunId"] == "paying-run"

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_resume_reconciles_delivery_even_when_another_item_sets_the_stop_reason():
    class InterruptedOutput(Output):
        async def push(self, row):
            await super().push(row)
            raise ApifyClientError("Dataset acknowledgement unavailable")

    async def check():
        case = Case()

        async def evaluate(media, options, context):
            if media.ref.video_id == SHORT:
                return Outcome("deferred", "TIME_LIMIT", True)
            return await case.evaluate(media, options, context)

        first = replace(case.context("parallel", output=InterruptedOutput("parallel")), evaluate=evaluate, concurrency=2)
        summary = await run({"shortcodes": [SHORT, NEXT]}, first)
        assert summary.stop_reason == "TIME_LIMIT" and first.provider.events == {BASE_EVENT: 1}
        assert [row["videoId"] for row in first.output.rows] == [NEXT]

        async def read_previous(dataset_id):
            assert dataset_id == "parallel"
            return first.output.rows

        resumed = replace(case.context("resumed"), read_previous=read_previous)
        summary = await run({"resumeFromDatasetId": "parallel"}, resumed)
        assert summary.completed_dataset_ids == ("parallel",)
        assert [row["videoId"] for row in resumed.output.rows] == [SHORT]
        assert resumed.provider.events == {BASE_EVENT: 1}

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


def test_qualifying_partial_is_reused_and_counts_as_an_answer():
    async def check():
        case = Case()

        async def at_threshold(media, options, context):
            evaluated = await case.evaluate(media, options, context)
            return Outcome("partial", "TRANSCRIPT_PARTIAL", value=replace(evaluated.value, assessment=Assessment(0.20)))

        first = replace(case.context("partial-original"), evaluate=at_threshold)
        inputs = {"shortcodes": [SHORT]}
        watched = {**inputs, "newReelsOnly": True}
        summary = await run(watched, first)
        assert summary.partial == summary.billed == 1 and first.output.rows[0]["isNew"] is True

        scheduled = replace(case.context("partial-next-schedule"), evaluate=at_threshold)
        summary = await run(watched, scheduled)
        assert summary.previously_answered == 1 and not scheduled.provider.calls
        assert scheduled.output.rows[0]["errorCode"] == "ALREADY_ANSWERED"

        cached = replace(case.context("partial-cache"), evaluate=at_threshold)
        summary = await run(inputs, cached)
        assert summary.partial == 1 and cached.output.rows[0]["cached"] is True
        assert case.asr_calls == [SHORT] and not cached.provider.calls

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


def test_bounded_watchlist_fetches_more_only_when_recent_videos_were_answered():
    async def check():
        case = Case()
        pages = []
        older = ("profile", "older")

        async def profile(username, cursor):
            pages.append(cursor)
            codes = (NEXT,) if cursor else (SHORT, LONG)
            entries = tuple({"code": code, "clips_tab_pinned_user_ids": []} for code in codes)
            return ProfilePage("1", entries, None if cursor else older)

        case.instagram.profile = profile
        options = {"profiles": ["public.personal"], "newReelsOnly": True, "maxResults": 2}
        first = case.context("first")
        result = await run(options, first)
        assert pages == [None]
        assert result.successful == 2 and result.continuation

        pages.clear()
        second = case.context("second")
        result = await run(options, second)
        assert pages == [None, older]
        assert result.previously_answered == 2 and result.successful == 1
        assert [row["videoId"] for row in second.output.rows if row["status"] == "success"] == [NEXT]
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


def test_cached_results_use_measured_duration_for_new_run_filters():
    async def check(duration, filters, reason):
        case = Case()
        case.known_durations[SHORT] = duration
        input_ = {"shortcodes": [SHORT]}
        assert (await run(input_, case.context("original"))).successful == 1
        cached = case.context("filtered-cache")
        result = await run({**input_, **filters}, cached)
        assert result.skipped == 1 and case.asr_calls == [SHORT] and not cached.provider.calls
        row, = cached.output.rows
        assert row["durationSeconds"] == duration and row["errorCode"] == reason and row["transcript"] is None

    asyncio.run(check(181, {"maxDurationSeconds": 180}, "DURATION_LIMIT"))
    asyncio.run(check(4, {"minDurationSeconds": 6}, "BELOW_MIN_DURATION"))


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
