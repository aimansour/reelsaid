"""Derive comparable delivery, costs, and modeled contribution from restricted observations."""

from collections import Counter
from decimal import Decimal
import json
from math import ceil
from pathlib import Path
import re
from urllib.parse import urlsplit


BASE = {"BRONZE": 0.011, "SILVER": 0.010, "GOLD": 0.009, "PLATINUM": 0.0085, "DIAMOND": 0.0085}
PER_HOUR = {"whisper-large-v3": 0.111, "whisper-large-v3-turbo": 0.04}
ADDITIONAL = 0.003
RATES = {
    "ACTOR_COMPUTE_UNITS": (0.16, 0.13),
    "DATA_TRANSFER_EXTERNAL_GBYTES": (0.19, 0.18),
    "DATA_TRANSFER_INTERNAL_GBYTES": (0.045, 0.04),
    "DATASET_READS": (0.00000036, 0.00000032),
    "DATASET_WRITES": (0.0000045, 0.000004),
    "KEY_VALUE_STORE_READS": (0.0000045, 0.000004),
    "KEY_VALUE_STORE_WRITES": (0.000045, 0.00004),
    "KEY_VALUE_STORE_LISTS": (0.000045, 0.00004),
    "REQUEST_QUEUE_READS": (0.0000036, 0.0000032),
    "REQUEST_QUEUE_WRITES": (0.000009, 0.000008),
}


def qualified(row):
    if not isinstance(row.get("transcript"), str) or not any(c.isalnum() for c in row["transcript"]):
        return False
    if row.get("status") == "success":
        return True
    affected = (row.get("quality") or {}).get("affectedFraction")
    return row.get("status") == "partial" and affected is not None and affected <= 0.2


def summarize_case(case):
    if case.get("status") in {"SUBMITTING", "READY", "RUNNING"}:
        return {"status": case["status"]}
    rows = case.get("rows") or []
    eligible = [row for row in rows if qualified(row)]
    models = (case.get("metrics") or {}).get("models")
    potential_asr = None
    if models is not None:
        potential_asr = sum(details["potentialBilledSeconds"] * PER_HOUR[name] / 3600
                            for name, details in models.items())
    platform = case.get("usageTotalUsd")
    usage = case.get("usage") or {}
    usage_usd = case.get("usageUsd") or {}
    minutes = sum(
        max(0, ceil((Decimal(str(row["durationSeconds"])) - 180) / 60))
        for row in eligible if row.get("durationSeconds") is not None
    )
    contribution = {}
    if potential_asr is not None and platform is not None:
        for tier, price in BASE.items():
            compute_cost = platform
            if tier in {"SILVER", "GOLD"}:
                column = 0 if tier == "SILVER" else 1
                compute_cost = sum(
                    usage.get(service, 0) * RATES[service][column] if service in RATES else observed
                    for service, observed in usage_usd.items()
                )
            gross = len(eligible) * price + minutes * ADDITIONAL
            contribution[tier] = {
                "gross": round(gross, 6),
                "platform": round(compute_cost, 6),
                "paidOnly": round(0.8 * gross - compute_cost - potential_asr, 6),
                "with20PercentFree": round(0.8 * (0.8 * gross - compute_cost) - potential_asr, 6),
                "with50PercentFree": round(0.5 * (0.8 * gross - compute_cost) - potential_asr, 6),
            }
    return {
        "runId": case.get("runId"),
        "status": case.get("status"),
        "memoryMbytes": case.get("memoryMbytes"),
        "seconds": case.get("seconds"),
        "firstTranscriptSeconds": case.get("firstTranscriptSeconds"),
        "qualified": len(eligible),
        "outcomes": dict(Counter(row.get("errorCode") or row.get("status") for row in rows)),
        "languages": dict(Counter(row["language"] for row in eligible if row.get("language"))),
        "stop": (case.get("summary") or {}).get("stopReason"),
        "discovered": (case.get("summary") or {}).get("unique"),
        "peakMiB": round((case.get("stats") or {}).get("memMaxBytes", 0) / 1048576, 1),
        "rxBytes": (case.get("stats") or {}).get("netRxBytes"),
        "platformUsd": platform,
        "potentialAsrUsd": round(potential_asr, 6) if potential_asr is not None else None,
        "contribution": contribution,
    }


def word_error(reference, actual):
    words = lambda text: re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    expected, observed = words(reference), words(actual)
    if not expected:
        return None
    previous = list(range(len(observed) + 1))
    for index, left in enumerate(expected, 1):
        current = [index]
        for position, right in enumerate(observed, 1):
            current.append(min(previous[position] + 1, current[-1] + 1, previous[position - 1] + (left != right)))
        previous = current
    return round(previous[-1] / len(expected), 3)


def compare(reelsaid, competitor):
    expected = {row.get("shortCode") or urlsplit(row.get("postUrl") or "").path.strip("/").split("/")[-1]: row
                for row in competitor.get("rows", [])}
    comparisons = {}
    fields = ("publisher", "caption", "publishedAt", "durationSeconds", "coverUrl", "audio",
              "viewCount", "playCount", "likeCount", "commentCount", "pinned", "coauthors")
    for row in reelsaid.get("rows", []):
        metadata = row.get("metadata") or {}
        code = metadata.get("shortcode")
        if code not in expected:
            continue
        rival = expected[code]
        comparisons[code] = {
            "status": row.get("status"),
            "qualified": qualified(row),
            "competitorStatus": rival.get("status"),
            "normalizedDisagreement": word_error(rival["transcript"], row["transcript"])
            if rival.get("transcript") and row.get("transcript") else None,
            "observedMetadata": [key for key in fields if metadata.get(key) is not None],
        }
    return comparisons


if __name__ == "__main__":
    import sys

    cases = [json.loads(Path(filename).read_text(encoding="utf-8")) for filename in sys.argv[1:]]
    print(json.dumps([summarize_case(case) for case in cases], indent=2))
