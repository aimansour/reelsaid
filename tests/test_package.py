import json
import os
import re
import struct
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from reelsaid.input import parse_input
from reelsaid.standby import _input as parse_standby_input


EXAMPLE_FILES = ("reel", "profile", "dataset")
SYNC_URL = "https://api.apify.com/v2/acts/aimansour~reelsaid/run-sync-get-dataset-items?timeout=90"
PUBLIC_REPO = r"github(?:usercontent)?\.com/wip-bunker-42/reelsaid/"
PUBLIC_FILES = ("README.md", "llms.txt", "assets", "examples", "store")


@pytest.fixture
def package():
    if not (root := os.environ.get("PACKAGE_ROOT")):
        pytest.skip("Set PACKAGE_ROOT to verify the public packaging checkout.")
    checkout = Path(root)
    assert (checkout / "README.md").is_file()
    return checkout


def read_json(path):
    return json.loads(path.read_text())


def test_public_api_inputs_match_actor_schema(package):
    schema = read_json(Path(".actor/input_schema.json"))
    schema["additionalProperties"] = False
    for name in EXAMPLE_FILES:
        example = read_json(package / f"examples/api/{name}.json")
        Draft7Validator(schema).validate(example)
        plan = parse_input(example)
        assert plan.sources and not plan.outcomes
    sample = read_json(package / "examples/api/reel.json")
    assert sample["startUrls"] == schema["properties"]["startUrls"]["prefill"]
    assert sample["language"] == "auto" and sample["wordLevelTimestamps"]


def test_public_output_matches_actor_schema(package):
    rows = read_json(package / "examples/api/output.json")
    assert len(rows) == 1
    row = rows[0]
    Draft7Validator(read_json(Path(".actor/dataset_schema.json"))["fields"]).validate(row)
    assert row["status"] == "success" and row["transcript"] and row["wordLevelTimestamps"]
    assert row["wordCount"] == len(row["wordLevelTimestamps"])
    assert row["metadata"]["caption"] is None
    assert all(reference is None for reference in row["subtitles"].values())


def test_package_has_no_code_first_run_and_standby_example(package):
    standby = read_json(package / "examples/api/standby.json")
    spec = read_json(Path(".actor/web_server_schema.json"))
    request = spec["paths"]["/"]["post"]["requestBody"]["content"]["application/json"]
    assert standby == request["example"]
    Draft7Validator(spec["components"]["schemas"]["TranscriptionRequest"]).validate(standby)
    options, _, issue = parse_standby_input(standby)
    assert issue is None and options["startUrls"] == read_json(package / "examples/api/reel.json")["startUrls"]

    readme = (package / "README.md").read_text()
    trial = readme.index("## Transcribe your first Reel")
    code = readme.index("```bash")
    first_run = readme[trial:code]
    assert "Instagram URLs" in first_run and "**Start**" in first_run
    assert "## What you get" in first_run and "## What you can do with Reel transcripts" in first_run
    assert "Every Reel, in Words." in readme[:trial] and "Whisper Large-v3" in readme[:code]
    assert "aimansour--reelsaid.apify.actor" in readme and "examples/api/standby.json" in readme
    store_readme = subprocess.check_output(["bash", "scripts/store-readme", package / "README.md"], text=True)
    assert store_readme == readme[readme.index("**Every Reel, in Words.**"):]
    assert not re.search(r"^# ", store_readme, re.MULTILINE)


def test_automation_templates_send_the_verified_example(package):
    example = read_json(package / "examples/api/reel.json")
    workflow = read_json(package / "examples/n8n/reelsaid.json")
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert not workflow["active"] and all("credentials" not in node for node in nodes.values())
    request = nodes["Transcribe Reel"]["parameters"]
    assert request["url"] == SYNC_URL and request["method"] == "POST"
    assert request["genericAuthType"] == "httpHeaderAuth"
    assert json.loads(request["jsonBody"]) == example
    assert workflow["connections"]["Transcribe Reel"]["main"][0][0]["node"] == "Map transcript"
    assert nodes["Map transcript"]["parameters"]["assignments"]["assignments"][0]["value"] == "={{ $json.transcript }}"

    request, iterator = read_json(package / "examples/make/reelsaid.blueprint.json")["flow"]
    assert request["module"] == "http:MakeRequest" and request["version"] == 4
    assert request["parameters"]["authenticationType"] == "apiKey"
    assert "apiKeyKeychain" not in request["parameters"]
    assert request["mapper"]["url"] == SYNC_URL and request["mapper"]["method"] == "post"
    assert request["mapper"]["parseResponse"] is True
    assert json.loads(request["mapper"]["jsonStringBodyContent"]) == example
    assert iterator["module"] == "builtin:BasicFeeder"
    assert iterator["mapper"]["array"] == "{{1.data}}"


def test_branding_and_public_links(package):
    listing = read_json(package / "store/listing.json")
    actor = read_json(Path(".actor/actor.json"))
    readme = (package / "README.md").read_text()
    title = "ReelSaid — Instagram Reels Transcript API"
    assert listing["title"] == actor["title"] == title
    assert listing["description"] == actor["description"]
    assert len(listing["description"]) <= 300
    assert f"# {title}" in readme and "**Every Reel, in Words.**" in readme
    assert all("Whisper Large-v3" in copy for copy in [readme, listing["description"]])
    png = (package / "assets/reelsaid-logo.png").read_bytes()
    assert png[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert struct.unpack(">II", png[16:24]) == (512, 512)

    for path in package.rglob("*.md"):
        if ".git" in path.parts:
            continue
        for target in re.findall(PUBLIC_REPO + r"(?:blob/main/|main/)([^)#\"\s]+)", path.read_text()):
            assert (package / target).is_file(), f"{path.name} links to missing {target}"


def test_public_assets_contain_no_credentials_or_signed_media(package):
    credential = re.compile(r"(?:gsk_|ghp_|apify_api_|github_pat_)[A-Za-z0-9_]{20,}")
    signed_media = re.compile(r"https://[^\s\"]+(?:cdninstagram\.com|fbcdn\.net)[^\s\"]*\?")
    for entry in PUBLIC_FILES:
        path = package / entry
        paths = path.rglob("*") if path.is_dir() else [path]
        for asset in paths:
            if asset.is_file() and asset.suffix != ".png":
                copy = asset.read_text()
                assert not credential.search(copy), asset.name
                assert not signed_media.search(copy), asset.name
