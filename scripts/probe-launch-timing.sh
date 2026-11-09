#!/usr/bin/env bash
set -euo pipefail

public_package=${1:?The trusted public package is required}
mode=${2:-timing}
case "$mode" in
    timing) check=--compare-policies ;;
    startup|cached-base) check=--startup-check ;;
    lean-media) check=--lean-media-check ;;
    native) check= ;;
    *) exit 2 ;;
esac
scratch=$(mktemp -d)
stage=actor-selection
cleanup() {
    local status=$?
    if (( status != 0 )); then
        python3 - "$mode" "$stage" "$status" <<'PY' >/dev/null 2>&1 || true
from runpy import run_path
import sys

benchmark = run_path("scripts/benchmark-market.py")
request = benchmark["request"]
store = request("GET", f"key-value-stores/{benchmark['STORE']}")["data"]
if store["generalAccess"] == "RESTRICTED":
    mode, stage, status = sys.argv[1:]
    request("PUT", f"key-value-stores/{store['id']}/records/native-workflow-error-{mode}",
            {"stage": stage, "exitCode": int(status)})
PY
    fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
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
    dockerfile = root.parents[1] / "Dockerfile"
    base = "FROM apify/actor-python:3.12@sha256:5d6bcde0bbc82bb4e2293e09bd7a7e037222e858acddc546a463c5aa51f69e2a"
    if not dockerfile.read_text().startswith(base + "\n"):
        edit(dockerfile, {"FROM python:3.12-slim-bookworm": base})
if sys.argv[3] == "lean-media":
    dockerfile = root.parents[1] / "Dockerfile"
    edit(dockerfile, {
        "RUN apt-get update \\\n    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg \\\n"
        "    && rm -rf /var/lib/apt/lists/*": "COPY --from=media-tools /native/ /usr/local/",
    })
    tools = Path("scripts/lean-media.Dockerfile").read_text()
    dockerfile.write_text(tools + "\n" + dockerfile.read_text())
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
    stage=overlay
    prepare_overlay
    project=$scratch
    tag=launch-timing
fi
stage=deployment
if [[ $mode == lean-media ]]; then
    export REELSAID_BUILD_WAIT_SECONDS=660
fi
bash "$project/scripts/deploy-actor.sh" "$public_package" "$tag" >"$scratch/build.json"
stage=build-receipt
build_id=$(jq -er '.build | select(.status == "SUCCEEDED") | .id' "$scratch/build.json")
build=$(apify api GET "actor-builds/$build_id" --user-agent "$user_agent" |
    jq -er '.data | select(.status == "SUCCEEDED") | .buildNumber')
stage=default-check
[[ $(apify api GET "acts/$actor" --user-agent "$user_agent" | jq -er "$default_selection") == "$stable" ]]
options=(--native-baseline "$build")
if [[ -n $check ]]; then
    options+=(--require-timings "$check")
    if [[ $mode == lean-media ]]; then
        options+=(--verify-native)
    fi
else
    options+=(--verify-native)
fi
stage=native-cases
python3 scripts/benchmark-reelsaid.py "${options[@]}"
