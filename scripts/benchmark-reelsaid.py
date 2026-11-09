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


def native_baseline(build, *, timings=False):
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
    for name, references in cases.items():
        urls = [fixtures[reference]["url"] for reference in references]
        record = f"key-value-stores/{store['id']}/records/native-{build}-{name}"
        benchmark(actor, {"startUrls": urls, "forceRefresh": True}, 0.20, record,
                  build=build, case=name, cache_condition="fresh",
                  requested_ids=[url.strip("/").split("/")[-1] for url in urls], timings=timings)
        observation = market["read_record"](record)
        if observation.get("status") != "SUCCEEDED" or (timings and not observation.get("timings")):
            raise RuntimeError(f"Baseline observation failed: {name}")


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
    args = parser.parse_args()
    if args.native_baseline:
        native_baseline(args.native_baseline, timings=args.require_timings)
    else:
        main()
