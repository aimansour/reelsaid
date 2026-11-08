"""Verify the product ASR adapter with real media and configured Groq accounts."""

import asyncio
import os
import re
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic

from curl_cffi.requests import AsyncSession

from instagram import emit
from reelsaid.contracts import RunContext, TranscriptOptions
from reelsaid.discovery import discover
from reelsaid.groq import MODELS, TURBO, GroqAdapter, GroqPool, GroqTransport, load_accounts, transcribe
from reelsaid.input import parse_input
from reelsaid.instagram import InstagramClient
from reelsaid.media import MediaClient, inspect_media


SHORT = "DS46KJNjva9"
SPANISH = "Dfax6SllBLR"


class ObservedTransport(GroqTransport):
    def __init__(self, session):
        super().__init__(session)
        self.observations = []

    async def send(self, account, model, *, url, file, language):
        start = monotonic()
        response = await super().send(account, model, url=url, file=file, language=language)
        self.observations.append({
            "account": account.name, "model": model, "http": response.status,
            "uploadBytes": file.stat().st_size if file else 0,
            "milliseconds": round((monotonic() - start) * 1000),
        })
        return response


async def main():
    accounts = load_accounts(os.environ["REELSAID_GROQ_KEYS"])
    async with AsyncSession(impersonate="chrome", trust_env=False) as instagram_session, \
               AsyncSession(impersonate="chrome", trust_env=False) as media_session, \
               AsyncSession(impersonate="chrome", trust_env=False) as groq_session:
        transport = ObservedTransport(groq_session)
        media_client = MediaClient(media_session)
        context = RunContext(
            InstagramClient(instagram_session), None, datetime.now(UTC), lambda: False, media_client,
            GroqAdapter(transport, GroqPool(accounts)),
        )
        discovered = await discover(parse_input({"shortcodes": [SHORT, SPANISH]}), context)
        refs = {video.metadata.shortcode: video for video in discovered.videos}
        short = (await inspect_media(refs[SHORT], context)).value
        spanish = (await inspect_media(refs[SPANISH], context)).value
        assert short and short.audio and spanish and spanish.audio
        try:
            for model in MODELS:
                for _ in accounts:
                    result = await transcribe(short, TranscriptOptions(), context, models=(model,))
                    assert result.status == "success", result.error_code
                    assert result.value.text and len(result.value.words) == 25
            direct = transport.observations[:]
            assert len({(call["account"], call["model"]) for call in direct if call["http"] == 200}) == 2 * len(accounts)
            assert all(call["uploadBytes"] == 0 for call in direct)

            for hint in ("auto", "es"):
                result = await transcribe(spanish, TranscriptOptions(language=hint), context, models=(TURBO,))
                assert result.status == "success", result.error_code
                assert result.value.language.casefold() == "spanish"

            url = short.audio.url
            stale = re.sub(r"([?&]oe=)[^&]+", r"\g<1>1", url, count=1)
            assert stale != url
            retained = await media_client.materialize(short.audio)
            try:
                expired = replace(short, audio=replace(short.audio, url=stale, file=retained))
                result = await transcribe(expired, TranscriptOptions(), context, models=(TURBO,))
                assert result.status == "success", result.error_code
                assert len(result.value.words) == 25
            finally:
                if short.audio.file != retained:
                    retained.unlink(missing_ok=True)
            rejected, uploaded = transport.observations[-2:]
            assert rejected["http"] >= 400 and rejected["uploadBytes"] == 0
            assert uploaded["http"] == 200 and 0 < uploaded["uploadBytes"] < short.audio.source_bytes
            emit({
                "case": "adapter", "accountsVerified": len(accounts), "modelCount": len(MODELS),
                "directCalls": len(direct), "directMilliseconds": [call["milliseconds"] for call in direct],
                "spanishAutoAndHint": True, "uploadRecovered": True,
                "sourceBytes": short.audio.source_bytes, "uploadBytes": uploaded["uploadBytes"],
            })
        finally:
            short.close()
            spanish.close()


if __name__ == "__main__":
    asyncio.run(main())
