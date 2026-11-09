"""Exercise the private server using the real Apify gateway."""

import json
import os
from hashlib import sha256
from runpy import run_path
import sys
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, urlopen


benchmark = run_path("scripts/benchmark-market.py")
request = benchmark["request"]
opener = build_opener(benchmark["NoRedirect"]())
actor, build, mode = sys.argv[1:]
cross = mode == "CROSS"
tenancy = "MULTI_TENANT" if cross else mode
expected_actor = "aimansour~reelsaid-standby-probe"
event = "probe-result"
store_name = benchmark["STORE"]
forged = "reelsaid-forged-probe-value"


def server_call(url, method, path, payload=None, *, auth="Authorization", headers=None, timeout=125, token=None):
    target = url + path
    supplied = dict(headers or {})
    if auth:
        supplied[auth] = "Bearer " + (token or os.environ["APIFY_TOKEN"])
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        supplied["Content-Type"] = "application/json"
    try:
        response = opener.open(Request(target, data=body, headers=supplied, method=method), timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        if response.status >= 400 or response.headers.get_content_type() != "application/json":
            return response.status, None
        return response.status, json.load(response)


def settle(run_id):
    for _ in range(28):
        run = request("GET", f"actor-runs/{run_id}")["data"]
        if run["status"] in benchmark["TERMINAL"]:
            return benchmark["settled_run"](run)
        sleep(2)
    raise RuntimeError("The private Standby probe did not idle out.")


def guest_api(token, path):
    try:
        response = urlopen(Request(f"https://api.apify.com/v2/{path}",
                                  headers={"Authorization": "Bearer " + token}), timeout=12)
    except HTTPError as error:
        return error.code, None
    with response:
        return response.status, json.load(response)


def main():
    if actor != expected_actor:
        raise ValueError("Only the private verification Actor can be used.")
    if tenancy not in ("SINGLE_TENANT", "MULTI_TENANT"):
        raise ValueError("Choose a supported private Standby tenancy.")
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
    benchmark_store = request("GET", f"key-value-stores/{store_name}")["data"]
    assert benchmark_store["generalAccess"] == "RESTRICTED"
    suffix = "-cross" if cross else "-multi" if tenancy == "MULTI_TENANT" else ""
    receipt = f"key-value-stores/{benchmark_store['id']}/records/standby-platform-{build}{suffix}"
    report = {"stage": "configuration", "build": build, "tenancy": tenancy}
    published = False
    try:
        try:
            selected = request("PUT", f"acts/{actor}", {"actorStandby": {
                "isEnabled": True, "tenancy": tenancy, "build": build, "memoryMbytes": 256,
                "idleTimeoutSecs": 30, "desiredRequestsPerActorRun": 1, "maxRequestsPerActorRun": 2,
                "shouldPassActorInput": False,
            }})["data"]
        except HTTPError as error:
            report.update(configurationStatus=error.code, configurationError=json.load(error).get("error", {}).get("type"))
            raise
        assert selected["isPublic"] is False and selected["actorStandby"]["build"] == build
        assert selected["actorStandby"]["tenancy"] == tenancy
        endpoint = selected["standbyUrl"].rstrip("/")
        parsed = urlsplit(endpoint)
        assert parsed.scheme == "https" and parsed.hostname.endswith(".apify.actor")
        assert not (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment)

        report["stage"] = "native"
        native = request("POST", f"acts/{actor}/runs", {}, build=build, timeout=25, waitForFinish=25)["data"]
        assert native["status"] == "SUCCEEDED"
        report.update(stage="gateway", nativeOrigin=native["meta"]["origin"])
        unauthenticated, _ = server_call(endpoint, "GET", "/", auth=None)
        report["unauthenticatedStatus"] = unauthenticated
        assert unauthenticated in {401, 403}
        health, ready = server_call(endpoint, "GET", "/")
        assert health == 200 and ready == {"status": "ready"}

        def call(mode, *, token=None, **kwargs):
            status, body = server_call(endpoint, "POST", "/probe", {"mode": mode, **kwargs}, token=token)
            assert status == 200
            return body

        first = call("observe")
        report["first"] = first
        assert first["origin"] == "STANDBY" and first["readinessSeen"]
        assert first["callerContext"] and first["runId"] and first["port"] > 0
        assert not first["authorizationForwarded"]
        caller_context = sha256(source["userId"].encode()).hexdigest()[:16]
        assert first["gatewayCallerContext"] == caller_context
        spoofed, replay = server_call(endpoint, "POST", "/probe", {"mode": "observe"},
                                      auth="X-Apify-Authorization", headers={
            "X-Actor-Request-ID": forged, "X-Actor-User-ID": forged, "X-Apify-User-ID": forged,
        })
        report["forgedStatus"] = spoofed
        assert spoofed == 200
        assert replay["gatewayCallerContext"] == caller_context
        assert replay["callerContext"] == first["callerContext"] and replay["runId"] == first["runId"]
        report.update(stage="storage", first=first, forged=replay)
        storage = call("store")
        stored = request("GET", f"key-value-stores/{storage['storageId']}/records/{storage['storageKey']}")
        assert stored == {"callerContext": first["callerContext"]}
        run = request("GET", f"actor-runs/{first['runId']}")["data"]
        assert run["buildNumber"] == build and run["meta"]["origin"] == "STANDBY"
        assert run["userId"] == source["userId"]
        report["deployment"] = run.get("serverActorDeployment")
        container = urlsplit(run.get("containerUrl") or "")
        if (container.scheme == "https" and container.hostname and container.hostname.endswith(".runs.apify.net")
                and not (container.username or container.password or container.query or container.fragment)):
            try:
                direct_status, direct = server_call(container.geturl().rstrip("/"), "POST", "/probe",
                                                    {"mode": "observe"}, auth=None, timeout=6, headers={
                    "X-Actor-Request-ID": forged, "X-Apify-User-ID": forged,
                })
            except (URLError, TimeoutError) as error:
                report["directError"] = type(error).__name__
            else:
                report.update(directStatus=direct_status, direct=direct)

        guest_token = None
        if cross:
            assert report["directStatus"] == 403
            guest_token = os.environ["APIFY_STANDBY_TEST_TOKEN"]
            guest_status, guest = guest_api(guest_token, "users/me")
            assert guest_status == 200
            guest_user = guest["data"]["id"]
            assert guest_user != source["userId"]
            guest_context = sha256(guest_user.encode()).hexdigest()[:16]
            report["stage"] = "temporary-visibility"
            try:
                visible = request("PUT", f"acts/{actor}", {
                    "isPublic": True, "isSourceCodeHidden": True,
                    "defaultRunOptions": {"build": build, "timeoutSecs": 25, "memoryMbytes": 256},
                })["data"]
            except HTTPError as error:
                report.update(publishStatus=error.code, publishError=json.load(error).get("error", {}).get("type"))
                raise
            published = visible["isPublic"]
            assert published and visible["isSourceCodeHidden"]
            report["stage"] = "cross-account"
            guest_first = call("observe", token=guest_token)
            assert guest_first["gatewayCallerContext"] == guest_context
            assert guest_first["callerContext"] == caller_context and guest_first["runId"] == first["runId"]
            guest_store = call("store", token=guest_token)
            assert guest_store["storageId"] == storage["storageId"]
            assert guest_store["storageKey"] != storage["storageKey"]
            record = f"key-value-stores/{guest_store['storageId']}/records/{guest_store['storageKey']}"
            assert request("GET", record) == {"callerContext": guest_context}
            assert guest_api(guest_token, record)[0] in {401, 403, 404}
            report.update(separateAccounts=True, sharedRun=True, isolatedStorageKeys=True, guestStorageDenied=True)

        report.update(stage="charges", runId=run["id"], storageOwnerMatches=True)
        zero = call("zero", token=guest_token)
        refused = call("charge", token=guest_token, maxTotalChargeUsd=0)
        assert zero["settlement"] == "no-event" and refused["settlement"] == "budget-rejected"
        assert not (zero.get("eventsObserved") or {}).get(event)
        assert not (refused.get("eventsObserved") or {}).get(event)
        report.update(zero=zero, refused=refused)
        if tenancy == "MULTI_TENANT":
            unattributed = call("charge", token=guest_token, maxTotalChargeUsd=0.001)
            report["unattributed"] = unattributed
            assert unattributed["settlement"] == "rejected"
        charge_input = {"maxTotalChargeUsd": 0.001, "usePlatformRequestId": tenancy == "MULTI_TENANT"}
        charged = call("charge", token=guest_token, **charge_input)
        repeated = call("charge", token=guest_token, **charge_input)
        if cross:
            assert charged["gatewayCallerContext"] == guest_context == repeated["gatewayCallerContext"]
        assert charged["runId"] == first["runId"] == repeated["runId"]
        report.update(charged=charged, repeated=repeated, stage="idle-settlement")
        finished = settle(run["id"])
        report.update(stage="settled", events=finished.get("chargedEventCounts"),
                      externalChargedUsd=finished.get("externalChargedTotalUsd"),
                      usage=finished.get("usageTotalUsd"), usageUsd=finished.get("usageUsd"),
                      usagePaidByRunner=(finished.get("pricingInfo") or {}).get("isPPEPlatformUsagePaidByUser"))
        assert charged["settlement"] == repeated["settlement"] == "acknowledged"
        if tenancy == "MULTI_TENANT":
            assert finished["externalChargedTotalUsd"] == 0.001
        else:
            assert finished["chargedEventCounts"][event] == 1
    finally:
        if published:
            try:
                restored = request("PUT", f"acts/{actor}", {"isPublic": False})["data"]
                assert restored["isPublic"] is False
                report["visibilityRestored"] = True
            except HTTPError as error:
                report.update(visibilityRestored=False, rollbackStatus=error.code,
                              rollbackError=json.load(error).get("error", {}).get("type"))
                request("PUT", f"acts/{actor}", {"isDeprecated": True, "actorStandby": {"isEnabled": False}})
        request("PUT", receipt, report)
    if published and not report.get("visibilityRestored"):
        raise RuntimeError("The temporary verification listing could not return to private visibility.")
    print("Private server lifecycle, request isolation controls and one-event replay passed.")


if __name__ == "__main__":
    main()
