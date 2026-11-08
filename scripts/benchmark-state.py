"""Bounded Steadyfetch experiment for concurrent runs and account memory."""

import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import sleep


MARKET = runpy.run_path("scripts/benchmark-market.py")
REQUEST = MARKET["request"]
BENCHMARK = MARKET["benchmark"]
ACTOR = MARKET["ACTORS"]["steady"]
RECORD_PREFIX = "v2-state"
FIRST = "DfdV-dGPQVX"
SECOND = "DfdSpM1PMVs"
FALLBACK = "DeMIwYYPAMt"
WATCH = "reelsaid-state-nov8"


def payload(code, watchlist=None):
    result = {
        "reelUrls": [f"https://www.instagram.com/reel/{code}/"],
        "maxItems": 1,
        "includeOnScreenText": False,
    }
    if watchlist:
        result.update(watchlistId=watchlist, newReelsOnly=True)
    return result


def start(case, store_id):
    label, data = case
    record = f"key-value-stores/{store_id}/records/{RECORD_PREFIX}-{label}"
    BENCHMARK(ACTOR, data, 0.05, record)
    result = REQUEST("GET", record)
    if result.get("status") != "SUCCEEDED":
        raise RuntimeError("Steadyfetch benchmark did not succeed")
    return result


def summarize(report):
    run = REQUEST("GET", f"actor-runs/{report['runId']}")["data"]
    rows = []
    for row in report["rows"]:
        summary = row.get("_summary")
        fields = summary if isinstance(summary, dict) else row
        rows.append({
            key: fields[key]
            for key in (
                "shortCode", "status", "repeat", "charged", "isNew", "firstSeenAt", "firstSeenRunId",
                "repeatCheck", "delivered", "chargedRows", "skippedSeen", "newItems", "repeats",
            )
            if key in fields
        } | {"hasTranscript": MARKET["usable"](row)})
    return {
        "runId": run["id"],
        "datasetId": run["defaultDatasetId"],
        "status": run["status"],
        "startedAt": run["startedAt"],
        "finishedAt": run["finishedAt"],
        "usageTotalUsd": run.get("usageTotalUsd"),
        "chargedEventCounts": run.get("chargedEventCounts"),
        "rows": rows,
    }


def overlap(first, second):
    return max(datetime.fromisoformat(run["startedAt"]) for run in (first, second)) < min(
        datetime.fromisoformat(run["finishedAt"]) for run in (first, second)
    )


def main():
    store = REQUEST("GET", f"key-value-stores/{MARKET['STORE']}")["data"]
    if store["generalAccess"] != "RESTRICTED":
        raise RuntimeError("Benchmark evidence requires restricted storage")
    store_id = store["id"]
    reports = {}

    def run(label, data):
        return start((label, data), store_id)

    def pair(label, data):
        labels = [f"{label}-a", f"{label}-b"]
        with ThreadPoolExecutor(max_workers=2) as threads:
            futures = {name: threads.submit(run, name, data) for name in labels}
            reports.update({name: future.result() for name, future in futures.items()})
        return labels

    direct = pair("direct", payload(FIRST))
    reports["direct-repeat"] = run("direct-repeat", payload(FIRST))
    watched = pair("watch", payload(SECOND, WATCH))
    reports["watch-repeat"] = run("watch-repeat", payload(SECOND, WATCH))
    reports["watch-other-list"] = run("watch-other-list", payload(SECOND, WATCH + "-alt"))
    fallback = []
    if not any(MARKET["usable"](row) for name in direct + watched for row in reports[name]["rows"]):
        fallback = pair("fallback", payload(FALLBACK))
        reports["fallback-repeat"] = run("fallback-repeat", payload(FALLBACK))

    sleep(5)
    observed = {name: summarize(report) for name, report in reports.items()}
    evidence = {
        "runs": observed,
        "overlap": {
            names[0].rsplit("-", 1)[0]: overlap(*(observed[name] for name in names))
            for names in (direct, watched, fallback) if names
        },
    }
    REQUEST("PUT", f"key-value-stores/{store_id}/records/{RECORD_PREFIX}-summary", evidence)


if __name__ == "__main__":
    main()
