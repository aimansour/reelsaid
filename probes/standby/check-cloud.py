"""Exercise the private server using the real Apify gateway."""

import json
import os
from runpy import run_path
import sys
from time import sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener


benchmark = run_path("scripts/benchmark-market.py")
request = benchmark["request"]
opener = build_opener(benchmark["NoRedirect"]())
actor, build = sys.argv[1:]
expected_actor = "aimansour~reelsaid-standby-probe"
event = "probe-result"
store_name = benchmark["STORE"]
forged = "reelsaid-forged-probe-value"


def server_call(url, method, path, payload=None, *, auth="Authorization", headers=None):
    target = url + path
    supplied = dict(headers or {})
    if auth:
        supplied[auth] = "Bearer " + os.environ["APIFY_TOKEN"]
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        supplied["Content-Type"] = "application/json"
    try:
        response = opener.open(Request(target, data=body, headers=supplied, method=method), timeout=125)
    except HTTPError as error:
        response = error
    with response:
        if response.status >= 400:
            return response.status, None
        return response.status, json.load(response)


def settle(run_id):
    for _ in range(28):
        run = request("GET", f"actor-runs/{run_id}")["data"]
        if run["status"] in benchmark["TERMINAL"]:
            return benchmark["settled_run"](run)
        sleep(2)
    raise RuntimeError("The private Standby probe did not idle out.")


def main():
    if actor != expected_actor:
        raise ValueError("Only the private verification Actor can be used.")
    source = request("GET", f"acts/{actor}")["data"]
    assert source["isPublic"] is False
    pricing = {
        "pricingModel": "PAY_PER_EVENT",
        "isPPEPlatformUsagePaidByUser": False,
        "pricingPerEvent": {"actorChargeEvents": {event: {
            "eventTitle": "Private verification result",
            "eventDescription": "Apify request and replay test.",
            "eventPriceUsd": 0.001,
            "isPrimaryEvent": True,
        }}},
    }
    if not any(price["pricingModel"] == "PAY_PER_EVENT" for price in source.get("pricingInfos", [])):
        request("PUT", f"acts/{actor}", {"pricingInfos": [pricing]})
    selected = request("PUT", f"acts/{actor}", {"actorStandby": {
        "isEnabled": True, "tenancy": "SINGLE_TENANT", "build": build, "memoryMbytes": 256,
        "idleTimeoutSecs": 30, "desiredRequestsPerActorRun": 1, "maxRequestsPerActorRun": 2,
        "shouldPassActorInput": False,
    }})["data"]
    assert selected["isPublic"] is False and selected["actorStandby"]["build"] == build
    endpoint = selected["standbyUrl"].rstrip("/")
    parsed = urlsplit(endpoint)
    assert parsed.scheme == "https" and parsed.hostname.endswith(".apify.actor")
    assert not (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment)

    benchmark_store = request("GET", f"key-value-stores/{store_name}")["data"]
    assert benchmark_store["generalAccess"] == "RESTRICTED"
    receipt = f"key-value-stores/{benchmark_store['id']}/records/standby-platform-{build}"
    report = {"stage": "native", "build": build}
    try:
        native = request("POST", f"acts/{actor}/runs", {}, build=build, timeout=25, waitForFinish=25)["data"]
        assert native["status"] == "SUCCEEDED"
        report.update(stage="gateway", nativeOrigin=native["meta"]["origin"])
        unauthenticated, _ = server_call(endpoint, "GET", "/", auth=None)
        assert unauthenticated in {401, 403}
        health, ready = server_call(endpoint, "GET", "/")
        assert health == 200 and ready == {"status": "ready"}

        def call(mode, **kwargs):
            status, body = server_call(endpoint, "POST", "/probe", {"mode": mode, **kwargs})
            assert status == 200
            return body

        first = call("observe")
        assert first["origin"] == "STANDBY" and first["readinessSeen"]
        assert first["callerContext"] and first["runId"] and first["port"] > 0
        assert not first["authorizationForwarded"]
        spoofed, replay = server_call(endpoint, "POST", "/probe", {"mode": "observe"},
                                      auth="X-Apify-Authorization", headers={
            "X-Actor-Request-ID": forged, "X-Actor-User-ID": forged, "X-Apify-User-ID": forged,
        })
        assert spoofed == 200
        assert replay["callerContext"] == first["callerContext"] and replay["runId"] == first["runId"]
        report.update(stage="storage", first=first, forged=replay)
        storage = call("store")
        stored = request("GET", f"key-value-stores/{storage['storageId']}/records/STANDBY_PROBE")
        assert stored == {"callerContext": first["callerContext"]}
        run = request("GET", f"actor-runs/{first['runId']}")["data"]
        assert run["buildNumber"] == build and run["meta"]["origin"] == "STANDBY"
        assert run["userId"] == source["userId"]

        report.update(stage="charges", runId=run["id"], storageOwnerMatches=True)
        zero = call("zero")
        refused = call("charge", maxTotalChargeUsd=0)
        assert zero["settlement"] == "no-event" and refused["settlement"] == "budget-rejected"
        assert not (zero.get("eventsObserved") or {}).get(event)
        assert not (refused.get("eventsObserved") or {}).get(event)
        report.update(zero=zero, refused=refused)
        charged = call("charge", maxTotalChargeUsd=0.001)
        repeated = call("charge", maxTotalChargeUsd=0.001)
        assert charged["runId"] == first["runId"] == repeated["runId"]
        report.update(charged=charged, repeated=repeated, stage="idle-settlement")
        finished = settle(run["id"])
        report.update(stage="settled", events=finished.get("chargedEventCounts"),
                      usage=finished.get("usageTotalUsd"), usageUsd=finished.get("usageUsd"))
        assert charged["settlement"] == repeated["settlement"] == "acknowledged"
        assert finished["chargedEventCounts"][event] == 1
    finally:
        request("PUT", receipt, report)
    print("Private server lifecycle, request isolation controls and one-event replay passed.")


if __name__ == "__main__":
    main()
