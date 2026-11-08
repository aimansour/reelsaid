"""Check the production discovery code with logged-out cloud traffic."""

import asyncio
import re
from dataclasses import replace
from datetime import UTC, datetime

from apify import Actor
from curl_cffi.requests import AsyncSession, RequestsError

from reelsaid.contracts import RunContext
from reelsaid.discovery import discover
from reelsaid.input import parse_input
from reelsaid.instagram import InstagramClient
from reelsaid.media import MediaClient, inspect_media


SHORT = "DS46KJNjva9"
CAROUSEL = "Ddm6E9OGt5D"
PERSONAL = "CsuFa_Mga41"
COLLAB = "DfaaAP7BvIu"


class HtmlOnly(AsyncSession):
    async def post(self, url, **kwargs):
        raise RequestsError("Post GraphQL unavailable in this test")


async def main():
    async with Actor, AsyncSession(impersonate="chrome", trust_env=False) as session:
        instagram = InstagramClient(session)
        plan = parse_input({
            "startUrls": [f"https://www.instagram.com/reel/{SHORT}/?igsh=test"],
            "shortcodes": [SHORT, CAROUSEL, COLLAB],
            "profiles": ["astro_kjell"],
        })
        context = RunContext(instagram, Actor.apify_client, datetime.now(UTC), lambda: False, MediaClient(session))
        result = await discover(plan, context)
        assert not result.input_outcomes, [item.error_code for item in result.input_outcomes]
        assert result.duplicates == 1
        assets = {video.metadata.shortcode for video in result.videos}
        assert {SHORT, CAROUSEL, PERSONAL, COLLAB} <= assets
        expected = tuple(video for video in result.videos if video.metadata.shortcode == CAROUSEL)
        assert [video.metadata.carousel_position for video in expected] == [2, 6, 10]
        assert all(video.video_url for video in result.videos)
        assert any(video.metadata.publisher == "astro_kjell" for video in result.videos)
        assert any(video.metadata.publisher == "nasajohnson" for video in result.videos)

        first = await instagram.profile("nasa")
        assert first.cursor and first.entries
        second = await instagram.profile("nasa", first.cursor)
        assert second.entries and {x["code"] for x in first.entries}.isdisjoint(x["code"] for x in second.entries)

        async with HtmlOnly(impersonate="chrome", trust_env=False) as html_session:
            html = await discover(
                parse_input({"shortcodes": [CAROUSEL]}),
                RunContext(InstagramClient(html_session), Actor.apify_client, datetime.now(UTC), lambda: False),
            )
        assert [video.video_id for video in html.videos] == [video.video_id for video in expected]
        short = next(video for video in result.videos if video.metadata.shortcode == SHORT)
        assert short.video_url and "oe=" in short.video_url
        expired = replace(
            short,
            video_url=re.sub(r"([?&]oe=)[^&]+", r"\g<1>1", short.video_url),
            alternate_video_urls=(),
        )
        standalone = await inspect_media(
            replace(expired, metadata=replace(expired.metadata, shortcode=None)), context,
        )
        assert standalone.error_code == "MEDIA_URL_EXPIRED", standalone.error_code
        recovered = await inspect_media(expired, context)
        assert recovered.status == "success", recovered.error_code
        media = recovered.value
        assert media.video_id == short.video_id and media.audio and media.audio.has_audio
        try:
            assert 8 < media.duration_seconds < 10
            evidence = {
                "durationSeconds": float(media.duration_seconds),
                "mediaBytes": media.audio.source_bytes,
                "rangeOnly": media.audio.file is None,
                "expiredWithoutOrigin": standalone.error_code,
                "recoveredExpiredUrl": True,
            }
        finally:
            media.close()
        await Actor.push_data({
            "primaryVideos": len(result.videos),
            "personalFixture": True,
            "duplicateInputs": result.duplicates,
            "carouselChildren": len(expected),
            "firstPage": len(first.entries),
            "secondPage": len(second.entries),
            "htmlFallback": True,
            **evidence,
        })


if __name__ == "__main__":
    asyncio.run(main())
