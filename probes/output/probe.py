"""Verify native Apify storage and output links with a small timed fixture."""

import asyncio
from decimal import Decimal

from apify import Actor

from reelsaid.contracts import InputRef, Outcome, VideoMetadata, VideoRef
from reelsaid.groq import Segment, Word
from reelsaid.output import SUMMARY_KEY, BillingFields, subtitle_files, subtitle_records, summarize, to_row
from reelsaid.quality import Assessment, TranscriptResult


async def main():
    async with Actor:
        env = Actor.get_env()
        text = "おはようございます。今日は晴れです。"
        ref = VideoRef("example", VideoMetadata(publisher="sample"), (InputRef("startUrls", 0),))
        spoken = TranscriptResult(
            text, "Japanese", Decimal("5.33"), (Segment(text, 0.1, 5.33),),
            (Word("おはようございます。", .1, 1.5), Word("今日は晴れです。", 1.75, 5.33)),
            "asr", "speech", 0.95, Assessment(0), True,
        )
        links = {}
        for record in subtitle_records(subtitle_files(spoken), ref.video_id, env["default_key_value_store_id"]):
            await Actor.set_value(record.key, record.content.encode(), content_type=record.content_type)
            links[record.format] = record.reference
        delivered = to_row(ref, Outcome("success", value=spoken), BillingFields(), subtitles=links)
        invalid = to_row(InputRef("startUrls", 1), Outcome("failed", "INVALID_URL"), BillingFields())
        rows = [delivered, invalid]
        await Actor.push_data(rows)
        summary = summarize(rows, submitted=2, unique=1, duplicates=0)
        await Actor.set_value(SUMMARY_KEY, summary.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
