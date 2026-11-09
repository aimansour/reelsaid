"""Verify the private ReelSaid build over both supported Apify entry points."""

import json
import os
from pathlib import Path
from runpy import run_path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener


observer = run_path("scripts/benchmark-market.py")
api = observer["request"]
actor = "aimansour~reelsaid"
build = sys.argv[1]
opener = build_opener(observer["NoRedirect"]())


def call(url, *, body=None, authenticated=True, headers=None):
    headers = dict(headers or {})
    if authenticated:
        headers["Authorization"] = "Bearer " + os.environ["APIFY_TOKEN"]
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    try:
        response = opener.open(Request(url, data=data, headers=headers), timeout=120)
    except HTTPError as error:
        response = error
    with response:
        result = json.load(response) if response.headers.get_content_type() == "application/json" else None
        return response.status, result


def main():
    before = api("GET", f"acts/{actor}")["data"]
    assert before["isPublic"] is False and before["isSourceCodeHidden"]
    store = api("GET", f"key-value-stores/{observer['STORE']}")["data"]
    assert store["generalAccess"] == "RESTRICTED"
    evidence = f"key-value-stores/{store['id']}/records/reelsaid-standby-runtime-{build}"
    report = {"stage": "configuration", "build": build}
    try:
        selected = api("PUT", f"acts/{actor}", {"actorStandby": {
            "isEnabled": True, "tenancy": "MULTI_TENANT", "build": build, "memoryMbytes": 256,
            "idleTimeoutSecs": 30, "desiredRequestsPerActorRun": 1, "maxRequestsPerActorRun": 2,
            "shouldPassActorInput": False,
        }})["data"]
        assert selected["isPublic"] is False and selected["defaultRunOptions"] == before["defaultRunOptions"]
        assert selected.get("pricingInfos") == before.get("pricingInfos")
        url = selected["standbyUrl"].rstrip("/") + "/"
        endpoint = urlsplit(url)
        assert endpoint.scheme == "https" and endpoint.hostname.endswith(".apify.actor")
        assert not (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment)

        report["stage"] = "readiness"
        report["unauthenticated"] = call(url, authenticated=False)[0]
        assert report["unauthenticated"] == 401
        report["health"], body = call(url)
        assert report["health"] == 200 and body == {"status": "ready"}

        report["stage"] = "validation"
        for label, payload, code in (
            ("empty", {}, "INVALID_INPUT"),
            ("wrongField", {"startURL": "ignored"}, "UNKNOWN_INPUT"),
            ("batch", {"profiles": ["example"]}, "USE_NATIVE_RUN"),
        ):
            status, error = call(url, body=payload)
            report[label] = [status, error.get("errorCode") if error else None]
            assert status == 400 and error["errorCode"] == code

        report["stage"] = "transcription"
        reel = json.loads(Path("tests/fixtures/catalog.json").read_text())["shortSpoken"]["url"]
        options = {"reelUrl": reel, "preferCaptions": False, "wordLevelTimestamps": True}
        status, first = call(url, body={**options, "forceRefresh": True})
        report["transcriptionHttp"] = status
        assert status == 200 and first["delivered"] == 1 and first["charged"] == {}
        row = first["rows"][0]
        assert row["status"] == "success" and row["transcriptSource"] == "asr" and row["language"] == "en"
        assert row["transcript"] and row["segments"] and row["wordLevelTimestamps"]
        assert row["subtitles"]["srt"]["content"] and row["subtitles"]["vtt"]["content"].startswith("WEBVTT")
        status, repeated = call(url, body=options)
        report["repeatHttp"] = status
        assert status == 200 and repeated["charged"] == {} and repeated["rows"][0]["cached"] is True
        assert repeated["rows"][0]["transcript"] == row["transcript"]

        report["stage"] = "direct-boundary"
        server_run = api("GET", f"acts/{actor}/runs/last", origin="STANDBY")["data"]
        assert server_run["buildNumber"] == build
        direct = urlsplit(server_run["containerUrl"])
        assert direct.scheme == "https" and direct.hostname.endswith(".runs.apify.net")
        report["directHttp"] = call(direct.geturl(), body=options, authenticated=False, headers={
            "X-Apify-User-ID": "test-caller", "X-Actor-Request-ID": "test-request",
            "X-Apify-Standby-Caller-Type": "USER",
        })[0]
        assert report["directHttp"] == 403

        report["stage"] = "native"
        native = api("POST", f"acts/{actor}/runs",
                     {"startUrls": [reel], "preferCaptions": False, "wordLevelTimestamps": True},
                     build=build, memory=256, timeout=60, maxTotalChargeUsd=0.05, waitForFinish=12)["data"]
        for _ in range(5):
            if native["status"] in observer["TERMINAL"]:
                break
            native = api("GET", f"actor-runs/{native['id']}", waitForFinish=10)["data"]
        assert native["status"] == "SUCCEEDED" and native["buildNumber"] == build
        rows = api("GET", f"datasets/{native['defaultDatasetId']}/items", limit=2)
        assert len(rows) == 1 and rows[0]["status"] == "success" and rows[0]["transcript"]
        assert rows[0]["subtitles"]["srt"]["url"] and rows[0]["subtitles"]["vtt"]["url"]
        report.update(stage="verified", native=True, standby=True, cachedRepeat=True, nativeDefaultPreserved=True)
    finally:
        api("PUT", evidence, report)
    print("Exact private build passed native and Standby request checks.")


if __name__ == "__main__":
    main()
