#!/usr/bin/env bash
set -euo pipefail

public_package=${1:?The trusted public package is required}
mode=${2:-timing}
case "$mode" in
    timing) check=--compare-policies ;;
    startup|cached-base) check=--startup-check ;;
    native) check= ;;
    *) exit 2 ;;
esac
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
user_agent=apify-agent-skills/apify-actor-development
actor=aimansour~reelsaid

apify api GET "acts/$actor" --user-agent "$user_agent" >"$scratch/actor.json"
default_selection='.data | select(.isPublic == false) | .defaultRunOptions.build as $build | .taggedBuilds[$build].buildId // $build'
stable=$(jq -er "$default_selection" "$scratch/actor.json")

prepare_overlay() {
    local owner
    owner=$(jq -er '.data.userId' "$scratch/actor.json")
    mkdir -p "$scratch/scripts" "$scratch/src"
    cp -a .actor "$scratch/"
    cp -a src/reelsaid "$scratch/src/"
    cp Dockerfile .dockerignore pyproject.toml uv.lock "$scratch/"
    cp scripts/install-quality-models scripts/deploy-actor.sh "$scratch/scripts/"
    cp scripts/launch_timing_overlay.py "$scratch/src/reelsaid/_launch_timing.py"

    python3 - "$scratch/src/reelsaid" "$owner" "$mode" <<'PY'
from pathlib import Path
import sys

def edit(file, changes):
    source = file.read_text()
    for original, replacement in changes.items():
        if source.count(original) != 1:
            raise SystemExit("Timing overlay no longer matches the runtime.")
        source = source.replace(original, replacement)
    file.write_text(source)


root = Path(sys.argv[1])
if sys.argv[3] == "cached-base":
    edit(root.parents[1] / "Dockerfile", {
        "FROM python:3.12-slim-bookworm": (
            "FROM apify/actor-python:3.12@sha256:"
            "5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a"
        ),
    })
edit(root / "__main__.py", {
    "import asyncio": "from . import _launch_timing as timing\n\nimport asyncio",
    '        env = Actor.get_env()': (
        '        env = Actor.get_env()\n'
        '        timing.mark("sdkReady")\n'
        f'        if env["user_id"] != {sys.argv[2]!r}:\n'
        '            await Actor.fail(status_message="Private diagnostic build.")\n'
        '            return\n'
        '        inspect, evaluate = timing.instrument(ApifyOutput)'
    ),
    "        plan = parse_input(raw)": (
        '        timing.policy = raw.pop("_reelsaidTimingPolicy", "conditional")\n'
        '        if timing.policy not in {"conditional", "before", "after"}:\n'
        '            raise ValueError("Unknown timing policy.")\n'
        '        plan = parse_input(raw)'
    ),
    "        stopping = asyncio.Event()": (
        '        timing.mark("settingsReady")\n'
        '        stopping = asyncio.Event()'
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
})
edit(root / "quality.py", {
    "from .audio_quality import": "from . import _launch_timing as timing\nfrom .audio_quality import",
    "if draft is None and not (media.audio.file or licensed_track):": (
        'if draft is None and timing.policy != "before" and (\n'
        '        timing.policy == "after" or not (media.audio.file or licensed_track)\n'
        '    ):'
    ),
    "if not _suspect(draft, media):": 'if timing.policy != "after" and not _suspect(draft, media):',
})
PY
}

project=$PWD
tag=launch-native
if [[ -n $check ]]; then
    prepare_overlay
    project=$scratch
    tag=launch-timing
fi
bash "$project/scripts/deploy-actor.sh" "$public_package" "$tag" >"$scratch/build.json"
build_id=$(jq -er '.build | select(.status == "SUCCEEDED") | .id' "$scratch/build.json")
build=$(apify api GET "actor-builds/$build_id" --user-agent "$user_agent" |
    jq -er '.data | select(.status == "SUCCEEDED") | .buildNumber')
[[ $(apify api GET "acts/$actor" --user-agent "$user_agent" | jq -er "$default_selection") == "$stable" ]]
options=(--native-baseline "$build")
if [[ -n $check ]]; then
    options+=(--require-timings "$check")
fi
python3 scripts/benchmark-reelsaid.py "${options[@]}"
