"""Check the production discovery code with logged-out cloud traffic."""

import asyncio
from datetime import UTC, datetime

from apify import Actor
from curl_cffi.requests import AsyncSession, RequestsError

from reelsaid.contracts import RunContext
from reelsaid.discovery import discover
from reelsaid.input import parse_input
from reelsaid.instagram import InstagramClient


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
        context = RunContext(instagram, Actor.apify_client, datetime.now(UTC), lambda: False)
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
        await Actor.push_data({
            "primaryVideos": len(result.videos),
            "personalFixture": True,
            "duplicateInputs": result.duplicates,
            "carouselChildren": len(expected),
            "firstPage": len(first.entries),
            "secondPage": len(second.entries),
            "htmlFallback": True,
        })


if __name__ == "__main__":
    asyncio.run(main())
