"""Compare bounded ReelSaid cloud cases using the original market observer."""

import json
from pathlib import Path
from runpy import run_path


market = run_path(str(Path(__file__).with_name("benchmark-market.py")))
request, benchmark = market["request"], market["benchmark"]
store_name = market["STORE"]
actor = "aimansour~reelsaid"
campaign = "parallel"


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
        ("single-512", {"startUrls": [market_fixture["referenceReel"]]}, 512, 55),
        ("single-256", {"startUrls": [market_fixture["referenceReel"]]}, 256, 55),
        ("mixed-512", {"startUrls": market_fixture["mixedUrls"]}, 512, 65),
        ("profile-512", {"profiles": [market_fixture["profile"]], "maxResults": 12}, 512, 65),
        ("matched-512", {"startUrls": profile_urls}, 512, 130),
        ("batch-512", {"startUrls": larger}, 512, 150),
        ("batch-256", {"startUrls": larger}, 256, 150),
        ("batch-1024", {"startUrls": larger}, 1024, 150),
        ("languages-512", {"profiles": ["bbcarabic"], "maxResults": 2}, 512, 65),
    ]
    for label, payload, memory, timeout in cases:
        benchmark(actor, {**payload, **common}, 0.30, f"{path}/reelsaid-{campaign}-{label}",
                  memory=memory, timeout=timeout)


if __name__ == "__main__":
    main()
