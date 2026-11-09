#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
mode=${1:-}
[[ $mode == batch || $mode == standby ]]
: "${REELSAID_GROQ_KEYS:?The runner transcription credential is required}"

root=$PWD
umask 077
scratch=$(mktemp -d)
server_pid=
cleanup() {
    if [[ -n $server_pid ]]; then
        kill -TERM -- "-$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
mkdir "$scratch/reelsaid"
cp src/reelsaid/*.py "$scratch/reelsaid/"
reel=$(jq -er .shortSpoken.url tests/fixtures/catalog.json)
input=$(jq -cn --arg reel "$reel" '{startUrls:[$reel],preferCaptions:false,wordLevelTimestamps:true}')
if [[ $mode == standby ]]; then
    port=$(python3 - <<'PY'
import socket
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
    )
    (
        cd -- "$scratch"
        unset APIFY_TOKEN
        export PATH="$root/.venv/bin:$PATH" REELSAID_MODEL_DIR="$root/.quality-models"
        export APIFY_IS_AT_HOME=0 APIFY_LOCAL_STORAGE_DIR="$scratch/storage" APIFY_API_BASE_URL=http://127.0.0.1:1
        export APIFY_META_ORIGIN=STANDBY ACTOR_WEB_SERVER_PORT="$port"
        exec setsid apify run --entrypoint reelsaid --input '{}' --user-agent apify-agent-skills/apify-actor-development
    ) &
    server_pid=$!
    endpoint="http://127.0.0.1:$port/"
    for _ in {1..40}; do
        if curl -fsS --max-time 1 -H 'X-Apify-Container-Server-Readiness-Probe: true' "$endpoint" \
            >"$scratch/ready" 2>/dev/null; then
            break
        fi
        kill -0 "$server_pid"
        sleep .25
    done
    [[ $(cat "$scratch/ready") == OK ]]
    [[ $(curl -sS --max-time 8 -w '%{http_code}' -o "$scratch/invalid.json" \
        -H 'Content-Type: application/json' --data '{}' "$endpoint") == 400 ]]
    jq -e '.errorCode == "INVALID_INPUT"' "$scratch/invalid.json" >/dev/null
    curl -fsS --max-time 75 -H 'Content-Type: application/json' --data "$input" "$endpoint" >"$scratch/result.json"
    jq -e '.delivered == 1 and .charged == {} and (.rows[0] |
        .status == "success" and .transcriptSource == "asr" and .language == "en"
        and (.transcript | length > 0) and (.wordLevelTimestamps | length > 0)
        and .charged == false and (.subtitles.srt.content | length > 0)
        and (.subtitles.vtt.content | startswith("WEBVTT")))' "$scratch/result.json" >/dev/null
    printf '%s\n' 'Local runner verified Standby readiness, request validation and timed transcription.'
    exit
fi
(
    cd -- "$scratch"
    unset APIFY_TOKEN
    export PATH="$root/.venv/bin:$PATH"
    export REELSAID_MODEL_DIR="$root/.quality-models"
    export APIFY_IS_AT_HOME=0 APIFY_LOCAL_STORAGE_DIR="$scratch/storage" APIFY_API_BASE_URL=http://127.0.0.1:1
    apify run --entrypoint reelsaid --input "$input" --user-agent apify-agent-skills/apify-actor-development
)
jq -se 'length == 1 and (.[0] |
    .status == "success" and .transcriptSource == "asr" and .language == "en"
    and (.transcript | length > 0) and (.wordLevelTimestamps | length > 0)
    and .charged == false and .subtitles.srt != null and .subtitles.vtt != null)' \
    "$scratch"/storage/datasets/default/[0-9]*.json >/dev/null
printf '%s\n' 'Local runner delivered a timed transcript and subtitle records.'
