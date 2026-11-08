import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, Draft7Validator

from reelsaid.contracts import InputRef, Outcome, VideoMetadata, VideoRef
from reelsaid.groq import Segment, Word
from reelsaid.output import BillingFields, Continuation, subtitle_files, subtitle_records, summarize, to_row
from reelsaid.quality import Assessment, TranscriptResult


def result(text, segments, words=(), *, language="English", seconds="8.892"):
    return TranscriptResult(
        text, language, Decimal(seconds), tuple(segments), tuple(words), "asr", "speech", .96,
        Assessment(0), True,
    )


def ref(video_id="A", *, position=None):
    return VideoRef(video_id, VideoMetadata(
        post_url="https://www.instagram.com/p/Example/",
        shortcode="Example",
        media_id=video_id,
        publisher="original",
        discovery_profiles=("profile",),
        carousel_position=position,
        like_count=0,
    ), (InputRef("startUrls", 0), InputRef("profiles", 0)))


def test_hook_three_seconds():
    text = "Open with these words. Then continue."
    spoken = result(text, [Segment(text, .01234, 5.01)], [
        Word("Open", .01234, .75), Word("with", .75, 1.32), Word("these", 1.32, 2.65),
        Word("words.", 2.65, 3.14), Word("Then", 3.0, 3.7), Word("continue.", 3.7, 5.01),
    ])
    row = to_row(ref(), Outcome("success", value=spoken), BillingFields(), include_word_timestamps=True)
    assert row["hook"] == {
        "text": "Open with these words.", "startSeconds": .01234, "endSeconds": 3.0, "timingGranularity": "word",
    }
    assert [segment["text"] for segment in row["segments"]] == ["Open with these words.", "Then continue."]
    assert row["wordLevelTimestamps"][0]["startSeconds"] == .01234
    assert row["wordLevelTimestamps"][3]["endSeconds"] == 3.14


def test_original_script_subtitles_and_file_references():
    text = "おはようございます。今日は晴れです。"
    spoken = result(text, [Segment(text, .12345, 5.3333)], [
        Word("おはようございます。", .12345, 1.5555), Word("今日は晴れです。", 2.0134, 5.3333),
    ], language="Japanese")
    files = subtitle_files(spoken)
    assert files.srt.startswith("1\n00:00:00,123 --> 00:00:01,556\nおはようございます。\n")
    assert "00:00:02,013 --> 00:00:05,333\n今日は晴れです。" in files.srt
    assert files.vtt.startswith("WEBVTT\n\n00:00:00.123 --> 00:00:01.556\nおはようございます。")
    records = subtitle_records(files, "Example:123", "privateStore")
    links = {record.format: record.reference for record in records}
    row = to_row(ref(), Outcome("success", value=spoken), BillingFields(), subtitles=links)
    assert row["language"] == "ja"
    assert row["hook"]["text"] == text
    assert row["wordLevelTimestamps"] is None
    assert row["subtitles"]["srt"]["key"].endswith(".srt")
    assert row["subtitles"]["vtt"]["url"].startswith("https://api.apify.com/v2/key-value-stores/privateStore/records/")
    assert all("token=" not in record.reference["url"] for record in records)
    assert len(subtitle_records(subtitle_files(spoken, include_srt=False), "Example:123", "privateStore")) == 1


def test_dataset_shape_and_nulls():
    schema = json.loads(Path(".actor/dataset_schema.json").read_text())["fields"]
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    video = to_row(ref(), Outcome("skipped", "MUSIC_ONLY"), BillingFields())
    error = to_row(InputRef("datasetItems", 3, 2), Outcome("failed", "INVALID_DATASET_ITEM"), BillingFields())
    validator.validate(video)
    validator.validate(error)
    assert video["metadata"]["viewCount"] is None and video["metadata"]["likeCount"] == 0
    assert video["metadata"]["publishedAt"] is None
    assert video["metadata"]["discoveryProfiles"] == ["profile"]
    assert error["metadata"] is None and error["videoId"] is None
    assert error["provenance"] == [{"field": "datasetItems", "index": 3, "itemIndex": 2}]
    unknown = to_row(ref(), Outcome("partial", "BILLING_UNRESOLVED"), BillingFields(
        charged=None, billed_minutes=None, charged_events=None, confirmed_charge_usd=None,
    ))
    validator.validate(unknown)
    assert unknown["charged"] is None and unknown["billedMinutes"] is None and unknown["chargedEvents"] is None


def test_summary_reconciles_mixed_inputs():
    paid = to_row(ref("carousel:1", position=2), Outcome("success"), BillingFields(
        charged=True, billed_minutes=1, charged_events={"transcript": 1}, confirmed_charge_usd=Decimal("0.012"),
    ), is_new=True, first_seen_at=datetime(2026, 11, 8, tzinfo=UTC))
    free = to_row(ref("carousel:2", position=5), Outcome("skipped", "SILENCE"), BillingFields(), is_new=True)
    waiting = to_row(ref("other"), Outcome("deferred", "BUDGET_LIMIT", True), BillingFields())
    bad = to_row(InputRef("startUrls", 1), Outcome("failed", "INVALID_URL"), BillingFields())
    summary = summarize(
        [paid, free, waiting, bad], submitted=4, unique=3, duplicates=2, watchlist_id="daily",
        previously_answered=0, stop_reason="BUDGET_LIMIT",
        continuation=Continuation("thisDataset", 1, "BUDGET_LIMIT"),
    ).to_dict()
    schema = json.loads(Path(".actor/key_value_store_schema.json").read_text())["collections"]["summary"]["jsonSchema"]
    Draft7Validator(schema).validate(summary)
    assert summary["submitted"] == 4 and summary["discovered"] == 5
    assert summary["unique"] == 3 and summary["duplicate"] == 2
    assert (summary["successful"], summary["skipped"], summary["deferred"], summary["inputErrors"]) == (1, 1, 1, 1)
    assert summary["billed"] == 1 and summary["confirmedChargeUsd"] == .012
    assert summary["chargedEvents"] == {"transcript": 1} and summary["newAnswers"] == 2
    assert summary["continuation"]["resumeFromDatasetId"] == "thisDataset"
