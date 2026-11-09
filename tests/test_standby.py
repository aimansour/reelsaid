import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from jsonschema import Draft7Validator

from reelsaid.billing import BASE_EVENT
from reelsaid.standby import create_app

from test_actor import CAROUSEL, Case, LONG, SHORT
from test_billing import Provider
from test_state import FakeAccount


HOST = "test-reelsaid.apify.actor"
TOKEN = "Bearer standby-auth-canary"
SIGNED = "https://scontent.cdninstagram.com/video.mp4?oe=standby-signed-canary"


def headers(tenant="alice", request_id="request-1", *, host=HOST):
    return {
        "Host": host,
        "X-Apify-User-ID": tenant,
        "X-Apify-Standby-Caller-Type": "USER",
        "X-Actor-Request-ID": request_id,
        "Authorization": TOKEN,
    }


class Contexts:
    def __init__(self):
        self.cases = {name: Case() for name in ("alice", "bob")}
        for name, case in self.cases.items():
            case.account = FakeAccount(name)
        self.providers = {name: Provider() for name in self.cases}
        self.calls = []

    async def __call__(self, identity, budget):
        self.calls.append(identity.user_id)
        case = self.cases[identity.user_id]
        return replace(case.context(identity.request_id, cap=budget), provider=self.providers[identity.user_id])

    def client(self):
        return TestClient(TestServer(create_app(self, gateway_host=HOST)))


def test_readiness_uses_no_processing():
    async def check():
        contexts = Contexts()
        async with contexts.client() as client:
            result = await client.get("/", headers={"X-Apify-Container-Server-Readiness-Probe": "true"})
            assert result.status == 200 and await result.text() == "OK"
        assert not contexts.calls
        assert all(not provider.calls for provider in contexts.providers.values())

    asyncio.run(check())


def test_empty_or_invalid_request_has_no_side_effect():
    async def check():
        contexts = Contexts()
        async with contexts.client() as client:
            for payload in (None, {}, {"startURL": f"https://www.instagram.com/reel/{SHORT}/"},
                            {"reelUrl": "https://example.org/reel"}, {"reelUrl": SIGNED, "maxTotalChargeUsd": -1}):
                response = await client.post("/", json=payload, headers=headers())
                assert response.status in {400, 415}
                assert (await response.json())["errorCode"]
            response = await client.post("/", data=b"{", headers={**headers(), "Content-Type": "application/json"})
            assert response.status == 400 and (await response.json())["errorCode"] == "INVALID_JSON"
            response = await client.post("/", json={"profiles": ["account"]}, headers=headers())
            assert response.status == 400 and (await response.json())["errorCode"] == "USE_NATIVE_RUN"
        assert not contexts.calls
        assert all(not case.inspect_calls for case in contexts.cases.values())

    asyncio.run(check())


def test_spoofed_identity_cannot_access_other_caller():
    async def check():
        contexts = Contexts()
        payload = {"shortcodes": [SHORT], "maxTotalChargeUsd": 0.012}
        async with contexts.client() as client:
            first = await client.post("/", json=payload, headers=headers())
            assert first.status == 200 and (await first.json())["rows"][0]["charged"] is True
            direct = await client.post("/", json=payload, headers=headers(host="worker.runs.apify.net"))
            assert direct.status == 403
            bob = await client.post("/", json=payload, headers={
                **headers("bob", "request-bob"), "X-Actor-User-ID": "alice",
            })
            assert bob.status == 200
            row = (await bob.json())["rows"][0]
            assert row["cached"] is False and row["chargedEvents"] == {BASE_EVENT: 1}
        assert contexts.calls == ["alice", "bob"]
        assert contexts.cases["alice"].asr_calls == contexts.cases["bob"].asr_calls == [SHORT]

    asyncio.run(check())


def test_full_quote_and_repeat_settle_once():
    async def check():
        contexts = Contexts()
        case = contexts.cases["alice"]
        provider = contexts.providers["alice"]
        async with contexts.client() as client:
            budget = await client.post("/", json={"shortcodes": [LONG], "maxTotalChargeUsd": 0.014}, headers=headers())
            assert budget.status == 200
            assert (await budget.json())["summary"]["stopReason"] == "SPEND_LIMIT"
            assert not case.asr_calls and not provider.calls
            payload = {"shortcodes": [SHORT], "maxTotalChargeUsd": 0.012}
            provider.lose_response = True
            case.pause.clear()
            first = asyncio.create_task(client.post("/", json=payload, headers=headers(request_id="request-a")))
            async with asyncio.timeout(2):
                while not case.asr_calls:
                    await asyncio.sleep(.01)
            repeat = asyncio.create_task(client.post("/", json=payload, headers=headers(request_id="request-b")))
            case.pause.set()
            for result in await asyncio.gather(first, repeat):
                assert result.status == 200 and (await result.json())["rows"]
        assert provider.events == {BASE_EVENT: 1}
        assert case.asr_calls == [SHORT]

    asyncio.run(check())


def test_logs_omit_request_data_and_credentials(caplog):
    caplog.set_level(logging.INFO)

    async def check():
        contexts = Contexts()
        async with contexts.client() as client:
            response = await client.post("/", json={"reelUrl": SIGNED}, headers=headers())
            assert response.status == 200
            assert (await response.json())["rows"][0]["transcript"] == "One good sentence."

    asyncio.run(check())
    assert "SUCCESS" in caplog.text
    for private in (TOKEN, SIGNED, "One good sentence."):
        assert private not in caplog.text


def test_openapi_matches_success_and_carousel_referral():
    def json_schema(value):
        if isinstance(value, list):
            return [json_schema(entry) for entry in value]
        if not isinstance(value, dict):
            return value
        result = {key: json_schema(entry) for key, entry in value.items() if key != "nullable"}
        if value.get("nullable") and "type" in result:
            result["type"] = [result["type"], "null"]
        return result

    definition = json_schema(json.loads((Path(__file__).parents[1] / ".actor/web_server_schema.json").read_text()))

    def validate(name, instance):
        Draft7Validator({"components": definition["components"], "$ref": f"#/components/schemas/{name}"}).validate(instance)

    async def check():
        contexts = Contexts()
        async with contexts.client() as client:
            payload = {"shortcodes": [SHORT], "wordLevelTimestamps": True, "includeSrt": False}
            validate("TranscriptionRequest", payload)
            response = await client.post("/", json=payload, headers=headers())
            assert response.status == 200
            result = await response.json()
            validate("TranscriptionResponse", result)
            assert result["rows"][0]["subtitles"]["vtt"]["content"].startswith("WEBVTT")
            carousel = await client.post("/", json={"shortcodes": [CAROUSEL]}, headers=headers(request_id="carousel"))
            assert carousel.status == 400
            error = await carousel.json()
            validate("RequestError", error)
            assert error["errorCode"] == "USE_NATIVE_RUN"
        assert contexts.cases["alice"].asr_calls == [SHORT]
        assert contexts.providers["alice"].events == {BASE_EVENT: 1}

    asyncio.run(check())
