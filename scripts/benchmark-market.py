"""One bounded benchmark campaign, run from the trusted verification workflow."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

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
USER_AGENT = "apify-agent-skills/apify-actor-development"
NO_RESULT = {
    "error", "failed", "private_or_removed", "skipped", "deferred", "no_speech", "no-speech", "no_audio",
    "lyrics", "input_note", "run_summary", "deadline",
}


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
    if not isinstance(row, dict):
        return False
    status = str(row.get("status") or "").lower()
    if (status in NO_RESULT or row.get("errMsg") or row.get("error")
            or row.get("noSpeech") is True or row.get("hasSpeech") is False):
        return False
    if status == "partial":
        quality = row.get("quality")
        fraction = quality.get("affectedFraction") if isinstance(quality, dict) else None
        if not isinstance(fraction, (int, float)) or not 0 <= fraction <= 0.20:
            return False
    for key in ("text", "transcript", "fullText", "fullTranscript", "transcription", "spokenTranscript"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return True
        if isinstance(val, dict) and usable(val):
            return True
    return False


def completed_ids(rows):
    ids = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        post_url = (metadata.get("postUrl") or row.get("postUrl") or row.get("reelUrl")
                    or row.get("normalizedUrl") or row.get("instagramUrl") or row.get("inputUrl") or row.get("url") or "")
        match = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", urlsplit(post_url).path) if isinstance(post_url, str) else None
        identity = metadata.get("shortcode") or row.get("shortCode") or row.get("shortcode")
        identity = identity or (match[1] if match else row.get("videoId"))
        if identity and row.get("status") not in {"deferred", "pending", "running"}:
            ids.append(str(identity))
    return ids


def settled_run(run):
    previous = None
    for _ in range(4):
        sleep(2)
        run = request("GET", f"actor-runs/{run['id']}")["data"]
        counters = (run.get("chargedEventCounts"), run.get("usageTotalUsd"))
        if counters == previous:
            return run
        previous = counters
    return run


def event_total(run):
    counts = run.get("chargedEventCounts")
    if counts is None:
        return None
    events = ((run.get("pricingInfo") or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    total = 0
    for name, count in counts.items():
        if not count:
            continue
        price = events.get(name, {}).get("eventPriceUsd")
        if price is None:
            return None
        total += price * count
    return round(total, 9)


def benchmark(actor, payload, cap, record, *, memory=None, timeout=75, case=None, cache_condition="unknown",
              requested_ids=()):
    report = {"actor": actor, "input": payload, "capUsd": cap, "status": "SUBMITTING"}
    if case:
        report.update(surface="native", case=case, cacheCondition=cache_condition, quality=None,
                      requestedVideoIds=requested_ids, completedVideoIds=[], settledChargeUsd=None)
    if read_record(record) is not None:
        return
    request("PUT", record, report)
    start = monotonic()
    try:
        options = {"maxTotalChargeUsd": cap, "timeout": timeout}
        if memory is not None:
            options["memory"] = memory
        command = ["apify", "api", "POST", f"acts/{actor}/runs", "-p", json.dumps(options), "--user-agent", USER_AGENT]
        if payload is not None:
            command.extend(("-d", "-"))
        started = subprocess.run(command, input=json.dumps(payload) if payload is not None else "",
                                 capture_output=True, text=True, timeout=45, check=True)
        run = json.loads(started.stdout)["data"]
        report.update(runId=run["id"], datasetId=run["defaultDatasetId"], status=run["status"])
        request("PUT", record, report)
        first_text = None
        rows = []
        while monotonic() - start < max(110, timeout + 30):
            run = request("GET", f"actor-runs/{run['id']}", waitForFinish=0 if case else 2)["data"]
            rows = request("GET", f"datasets/{run['defaultDatasetId']}/items", limit=30)
            if first_text is None and any(map(usable, rows)):
                first_text = round(monotonic() - start, 2)
            if run["status"] in TERMINAL:
                break
            if case:
                sleep(0.35)
        total = round(monotonic() - start, 2)
        if case and run["status"] in TERMINAL:
            run = settled_run(run)
        report.update(status=run["status"], seconds=total,
                      firstTranscriptSeconds=first_text, usageTotalUsd=run.get("usageTotalUsd"),
                      chargedEventCounts=run.get("chargedEventCounts"), rows=rows)
        if case:
            if any(isinstance(row, dict) and row.get("cached") is True for row in rows):
                cache_condition = "cached-repeat"
            report.update(cacheCondition=cache_condition, firstUsableSeconds=first_text,
                          totalSeconds=total, completedVideoIds=completed_ids(rows),
                          settledChargeUsd=event_total(run))
        if memory is not None:
            report.update(memoryMbytes=memory, build=run.get("buildNumber"), stats=run.get("stats"),
                          usage=run.get("usage"), usageUsd=run.get("usageUsd"))
            store = run["defaultKeyValueStoreId"]
            for label, key in (("summary", "SUMMARY"), ("metrics", "REELSAID_METRICS")):
                report[label] = read_record(f"key-value-stores/{store}/records/{key}")
    except subprocess.CalledProcessError as exc:
        report.update(status="SUBMISSION_UNCONFIRMED", cliExit=exc.returncode,
                      cliResponse=exc.stderr if case else None)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        report.update(error=type(exc).__name__)
    request("PUT", record, report)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def standby_benchmark(actor, endpoint, payload, record, *, case, cache_condition="unknown", timeout=75,
                      requested_ids=()):
    url = urlsplit(endpoint)
    if url.scheme != "https" or not url.hostname or not url.hostname.endswith(".apify.actor") or url.username or url.password:
        raise ValueError("Standby benchmark requires an Apify hostname")
    if read_record(record) is not None:
        return
    report = {"actor": actor, "surface": "standby", "case": case, "cacheCondition": cache_condition,
              "input": payload, "status": "SUBMITTING", "quality": None, "settledChargeUsd": None,
              "requestedVideoIds": requested_ids, "completedVideoIds": []}
    request("PUT", record, report)
    headers = {"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    start = monotonic()
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        with build_opener(NoRedirect).open(Request(endpoint, body, headers, method="POST"), timeout=timeout) as response:
            result = json.load(response)
            total = round(monotonic() - start, 2)
            rows = result.get("rows", []) if isinstance(result, dict) else result
            if not isinstance(rows, list):
                raise ValueError("Unexpected response rows")
            report.update(status="SUCCEEDED", httpStatus=response.status, response=result, rows=rows,
                          totalSeconds=total, completedVideoIds=completed_ids(rows),
                          firstUsableSeconds=total if any(map(usable, rows)) else None)
            if any(isinstance(row, dict) and row.get("cached") is True for row in rows):
                report["cacheCondition"] = "cached-repeat"
    except HTTPError as exc:
        report.update(status="HTTP_ERROR", httpStatus=exc.code, response=exc.read(65536).decode(errors="replace"))
    except (OSError, ValueError) as exc:
        report.update(status="OBSERVATION_FAILED", error=type(exc).__name__)
    report.setdefault("totalSeconds", round(monotonic() - start, 2))
    request("PUT", record, report)


def launch(group):
    if group == "contract":
        return
    manifest = json.loads(Path("tests/fixtures/launch-runs.json").read_text())
    cases = manifest[group]
    store = request("GET", f"key-value-stores/{STORE}")["data"]
    if store["generalAccess"] != "RESTRICTED":
        raise RuntimeError("Benchmark evidence requires restricted storage")
    for item in cases:
        record = f"key-value-stores/{store['id']}/records/launch-{item['id']}"
        options = {"case": item["case"], "cache_condition": item.get("cacheCondition", "unknown"),
                   "requested_ids": item.get("requestedVideoIds", [])}
        if item["surface"] == "standby":
            standby_benchmark(item["actor"], item["endpoint"], item.get("input"), record, **options)
        else:
            benchmark(item["actor"], item.get("input"), item["capUsd"], record, **options)


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
    if sys.argv[1:2] == ["--launch"]:
        launch(sys.argv[2] if len(sys.argv) > 2 else "contract")
    else:
        main()
