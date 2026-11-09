#!/usr/bin/env bash
set -euo pipefail

public_package=${1:?The trusted public package is required}
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
user_agent=apify-agent-skills/apify-actor-development
actor=aimansour~reelsaid

apify api GET "acts/$actor" --user-agent "$user_agent" >"$scratch/actor.json"
default_selection='.data | select(.isPublic == false) | .defaultRunOptions.build as $build | .taggedBuilds[$build].buildId // $build'
stable=$(jq -er "$default_selection" "$scratch/actor.json")
owner=$(jq -er '.data.userId' "$scratch/actor.json")
mkdir -p "$scratch/scripts" "$scratch/src"
cp -a .actor "$scratch/"
cp -a src/reelsaid "$scratch/src/"
cp Dockerfile .dockerignore pyproject.toml uv.lock "$scratch/"
cp scripts/install-quality-models scripts/deploy-actor.sh "$scratch/scripts/"
cp scripts/launch_timing_overlay.py "$scratch/src/reelsaid/_launch_timing.py"

python3 - "$scratch/src/reelsaid/__main__.py" "$owner" <<'PY'
from pathlib import Path
import sys

file = Path(sys.argv[1])
source = file.read_text()
edits = {
    "import asyncio": "from . import _launch_timing as timing\n\nimport asyncio",
    '        env = Actor.get_env()': (
        '        env = Actor.get_env()\n'
        f'        if env["user_id"] != {sys.argv[2]!r}:\n'
        '            await Actor.fail(status_message="Private diagnostic build.")\n'
        '            return\n'
        '        inspect, evaluate = timing.instrument(ApifyOutput)'
    ),
    "measure = environ.get(\"REELSAID_BENCHMARK\") == \"1\"": "measure = True",
    "provider=provider, read_previous=output.read, concurrency=concurrency, discovery_concurrency=concurrency,": (
        "provider=provider, read_previous=output.read, concurrency=concurrency, discovery_concurrency=concurrency,\n"
        "            inspect=inspect, evaluate=evaluate,"
    ),
    '        message = f"{summary.successful}': (
        '        await output.put("REELSAID_STAGE_TIMINGS", timing.snapshot())\n'
        '        message = f"{summary.successful}'
    ),
}
for original, replacement in edits.items():
    if source.count(original) != 1:
        raise SystemExit("Timing overlay no longer matches the runtime entry point.")
    source = source.replace(original, replacement)
file.write_text(source)
PY

bash "$scratch/scripts/deploy-actor.sh" "$public_package" launch-timing >"$scratch/build.json"
build_id=$(jq -er '.build | select(.status == "SUCCEEDED") | .id' "$scratch/build.json")
build=$(apify api GET "actor-builds/$build_id" --user-agent "$user_agent" |
    jq -er '.data | select(.status == "SUCCEEDED") | .buildNumber')
[[ $(apify api GET "acts/$actor" --user-agent "$user_agent" | jq -er "$default_selection") == "$stable" ]]
python3 scripts/benchmark-reelsaid.py --native-baseline "$build" --require-timings
