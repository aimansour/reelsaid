#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
[[ ${1:-} == batch ]]
: "${REELSAID_GROQ_KEYS:?The runner transcription credential is required}"

root=$PWD
umask 077
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/reelsaid"
cp src/reelsaid/*.py "$scratch/reelsaid/"
reel=$(jq -er .shortSpoken.url tests/fixtures/catalog.json)
input=$(jq -cn --arg reel "$reel" '{startUrls:[$reel],preferCaptions:false,wordLevelTimestamps:true}')
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
