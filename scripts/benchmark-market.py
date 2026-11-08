"""One bounded benchmark campaign, run from the trusted verification workflow."""

import json
import os
import subprocess
from pathlib import Path
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.apify.com/v2"
STORE = "aimansour~reelsaid-benchmark-private"
ACTORS = {
    "steady": "steadyfetch~instagram-reel-transcript-scraper",
    "apple": "apple_yang~instagram-transcripts-scraper",
    "sian": "sian.agency~instagram-ai-transcript-extractor",
    "apify": "apify~instagram-reel-scraper",
    "profiles": "deepmine~instagram-profile-scraper",
}
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def request(method, path, body=None, **params):
    url = f"{API}/{path}" + (f"?{urlencode(params)}" if params else "")
    headers = {"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, json.dumps(body).encode() if body is not None else None,
                         headers, method=method), timeout=15) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def read_record(path):
    try:
        return request("GET", path)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def usable(row):
    if row.get("status") in {"error", "failed", "private_or_removed"} or row.get("errMsg"):
        return False
    for key in ("text", "transcript", "fullText", "fullTranscript", "transcription"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, dict) and usable(val):
            return True
    return False


def benchmark(actor, payload, cap, record, *, memory=None, timeout=75):
    report = {"actor": actor, "input": payload, "capUsd": cap, "status": "SUBMITTING"}
    if read_record(record) is not None:
        return
    request("PUT", record, report)
    start = monotonic()
    try:
        options = {"maxTotalChargeUsd": cap, "timeout": timeout}
        if memory is not None:
            options["memory"] = memory
        started = subprocess.run(
            ["apify", "api", "POST", f"acts/{actor}/runs",
             "-p", json.dumps(options), "-d", "-"],
            input=json.dumps(payload), capture_output=True, text=True, timeout=20, check=True,
        )
        run = json.loads(started.stdout)["data"]
        report.update(runId=run["id"], datasetId=run["defaultDatasetId"], status=run["status"])
        request("PUT", record, report)
        first_text = None
        rows = []
        while monotonic() - start < max(110, timeout + 30):
            run = request("GET", f"actor-runs/{run['id']}", waitForFinish=2)["data"]
            rows = request("GET", f"datasets/{run['defaultDatasetId']}/items", limit=30)
            if first_text is None and any(map(usable, rows)):
                first_text = round(monotonic() - start, 2)
            if run["status"] in TERMINAL:
                break
        report.update(status=run["status"], seconds=round(monotonic() - start, 2),
                      firstTranscriptSeconds=first_text, usageTotalUsd=run.get("usageTotalUsd"),
                      chargedEventCounts=run.get("chargedEventCounts"), rows=rows)
        if memory is not None:
            report.update(memoryMbytes=memory, build=run.get("buildNumber"), stats=run.get("stats"),
                          usage=run.get("usage"), usageUsd=run.get("usageUsd"))
            store = run["defaultKeyValueStoreId"]
            for label, key in (("summary", "SUMMARY"), ("metrics", "REELSAID_METRICS")):
                report[label] = read_record(f"key-value-stores/{store}/records/{key}")
    except subprocess.CalledProcessError as exc:
        report.update(status="SUBMISSION_UNCONFIRMED", cliExit=exc.returncode)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        report.update(error=type(exc).__name__)
    request("PUT", record, report)


def main():
    store = request("GET", f"key-value-stores/{STORE}")["data"]
    if store["generalAccess"] != "RESTRICTED":
        raise RuntimeError("Benchmark evidence requires restricted storage")
    fixtures = json.loads(Path("tests/fixtures/market-reels.json").read_text())
    reel, mixed = fixtures["referenceReel"], fixtures["mixedUrls"]
    cases = [
        ("steady", "single", {"reelUrls": [reel]}, 0.15),
        ("apple", "single", {"videoUrl": reel}, 0.15),
        ("sian", "single", {"instagramUrl": reel}, 0.15),
        ("steady", "mixed", {"reelUrls": mixed}, 0.20),
        ("apple", "mixed", {"bulkUrls": mixed}, 0.20),
        ("sian", "mixed", {"bulkUrls": mixed}, 0.20),
        ("steady", "profile", {"handles": [fixtures["profile"]],
                               "maxReelsPerHandle": fixtures["profileLimit"]}, 0.30),
        ("apify", "single", {"username": [reel], "includeTranscript": True}, 0.15),
        ("apify", "profile", {"username": [fixtures["profile"]],
                               "resultsLimit": fixtures["profileLimit"], "includeTranscript": True}, 0.30),
        ("profiles", "fixture-types", {"usernames": ["yashinrush9", "lyssamariexo",
                                                     "nasa", "levainbakery", "humansofny"],
                                         "includeLatestPosts": True, "includeReels": True}, 0.15),
        ("profiles", "consumer-candidates", {
            "usernames": ["astrophysicsmania", "national.archaeology", "echoesofunboundcuriosity",
                          "thekindcookie.ph", "cookiegentle", "petitebakerystudio",
                          "_kaicealea", "slimreshae", "somedaysbakery",
                          "reidwiseman", "astro_kjell", "astro_jessica"],
            "includeLatestPosts": False, "includeReels": True,
        }, 0.15),
        ("sian", "mixed-corrected", {"bulkUrls": [{"url": url} for url in mixed]}, 0.20),
        ("steady", "personal", {"handles": ["astro_kjell"], "maxReelsPerHandle": 2}, 0.15),
        ("steady", "spanish", {"handles": ["bbcmundo"], "maxReelsPerHandle": 3}, 0.15),
    ]
    for actor, label, payload, cap in cases:
        benchmark(ACTORS[actor], payload, cap,
                  f"key-value-stores/{store['id']}/records/v1-{actor}-{label}")


if __name__ == "__main__":
    main()
