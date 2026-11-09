"""Compare bounded ReelSaid cloud cases using the original market observer."""

import argparse
import json
from pathlib import Path
from runpy import run_path


market = run_path(str(Path(__file__).with_name("benchmark-market.py")))
request, benchmark = market["request"], market["benchmark"]
store_name = market["STORE"]
actor = "aimansour~reelsaid"
campaign = "allocation"


def native_baseline(build, *, timings=False, compare_policies=False, startup_check=False, verify_native=False):
    store = request("GET", f"key-value-stores/{store_name}")["data"]
    if store["generalAccess"] != "RESTRICTED":
        raise RuntimeError("Benchmark evidence requires restricted storage")
    fixtures = json.loads(Path("tests/fixtures/market-reels.json").read_text())["launchReferences"]
    cases = {
        "extended": ["extended-captioned"],
        "wildlife": ["wolves-captioned"],
        "music": ["music-field"],
        "panel": ["panel-captioned"],
        "batch": ["field-report-captioned", "interview-captioned"],
    }
    experiments = [(name, references, "conditional", None, "") for name, references in cases.items()]
    if startup_check:
        experiments = [(name, cases[name], "conditional", None, "") for name in ("batch", "music")]
        experiments.extend(
            (name, cases[name], "conditional", memory, "")
            for name in ("extended", "wildlife") for memory in (512, 256, 1024)
        )
    if compare_policies:
        experiments.extend(
            (name, cases[name], "conditional", memory, "")
            for name in ("extended", "wildlife") for memory in (512, 1024)
        )
        experiments.extend(
            ("extended", cases["extended"], "conditional", memory, "-repeat") for memory in (1024, 256)
        )
        experiments.extend(
            (name, cases[name], policy, None, "") for policy in ("before", "after") for name in ("extended", "music")
        )
    for name, references, policy, memory, repeat in experiments:
        urls = [fixtures[reference]["url"] for reference in references]
        label = f"{name}-{memory or policy}" if memory or policy != "conditional" else name
        record = f"key-value-stores/{store['id']}/records/native-{build}-{label}{repeat}"
        payload = {"startUrls": urls, "forceRefresh": True}
        if policy != "conditional":
            payload["_reelsaidTimingPolicy"] = policy
        benchmark(actor, payload, 0.20, record,
                  build=build, case=name, cache_condition="fresh", memory=memory,
                  requested_ids=[url.strip("/").split("/")[-1] for url in urls], timings=timings)
        observation = market["read_record"](record)
        if observation.get("status") != "SUCCEEDED" or (timings and not observation.get("timings")):
            raise RuntimeError(f"Baseline observation failed: {label}")
        if verify_native:
            verify_native_case(observation, [fixtures[reference] for reference in references])


def verify_native_case(observation, references):
    memory = 256 if len(references) == 1 else 512
    if observation["memoryMbytes"] != memory:
        raise RuntimeError("Native allocation did not match the selected memory.")
    rows = observation["rows"]
    if len(rows) != len(references):
        raise RuntimeError("Native verification did not deliver the selected workload.")
    grade = run_path(str(Path(__file__).with_name("summarize-performance.py")))["caption_grade"]
    for reference in references:
        identity = reference["url"].strip("/").split("/")[-1]
        row = next((row for row in rows if market["completed_ids"]([row]) == [identity]), None)
        if row is None:
            raise RuntimeError("Native verification did not deliver a selected identity.")
        if "captionAnchors" in reference:
            if not market["usable"](row) or not grade(row, reference)["equivalent"]:
                raise RuntimeError("Native verification missed reference speech or timings.")
        elif row["errorCode"] != "MUSIC_ONLY" or row["transcript"] or row["charged"] or row["chargedEvents"]:
            raise RuntimeError("Native verification did not return a free music result.")


def main():
    store = request("GET", f"key-value-stores/{store_name}")["data"]
    if store["generalAccess"] != "RESTRICTED":
        raise RuntimeError("Benchmark evidence requires restricted storage")
    path = f"key-value-stores/{store['id']}/records"
    market_fixture = json.loads(Path("tests/fixtures/market-reels.json").read_text())
    catalog = json.loads(Path("tests/fixtures/catalog.json").read_text())
    steady = request("GET", f"{path}/v1-steady-profile")
    profile_urls = list(dict.fromkeys(
        row["postUrl"] for row in steady["rows"] if row.get("postUrl") and row.get("shortCode")
    ))
    larger = list(dict.fromkeys([
        *profile_urls, market_fixture["referenceReel"], *market_fixture["mixedUrls"],
        catalog["multilingual"]["url"], catalog["profiles"]["personal"]["observedReel"],
        catalog["carousel"]["url"], catalog["collaboration"]["url"],
    ]))
    common = {"forceRefresh": True}
    cases = [
        ("profile-2048", {"profiles": [market_fixture["profile"]], "maxResults": 12}, 2048, 100),
        ("batch-2048", {"startUrls": larger}, 2048, 150),
    ]
    for label, payload, memory, timeout in cases:
        benchmark(actor, {**payload, **common}, 0.30, f"{path}/reelsaid-{campaign}-{label}",
                  memory=memory, timeout=timeout)
    benchmark(actor, {"startUrls": ["https://www.instagram.com/tv/CcQYG13JmeM/"], **common}, 0.012,
              f"{path}/reelsaid-{campaign}-long-cap", memory=512, timeout=80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-baseline", metavar="BUILD")
    parser.add_argument("--require-timings", action="store_true")
    parser.add_argument("--verify-native", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--compare-policies", action="store_true")
    mode.add_argument("--startup-check", action="store_true")
    args = parser.parse_args()
    if args.native_baseline:
        native_baseline(args.native_baseline, timings=args.require_timings, compare_policies=args.compare_policies,
                        startup_check=args.startup_check, verify_native=args.verify_native)
    else:
        main()
