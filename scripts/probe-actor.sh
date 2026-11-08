#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
actor=aimansour~reelsaid

mkdir -p "$workspace/package/scripts"
cp -R .actor src Dockerfile .dockerignore pyproject.toml uv.lock "$workspace/package/"
cp scripts/install-quality-models "$workspace/package/scripts/"
apify actors push --dir "$workspace/package" --no-apply-env-vars-to-build --wait-for-finish 300 --json
apify api GET "acts/$actor" >"$workspace/actor.json"
jq -e '.data.isPublic == false and (.data.taggedBuilds.latest.buildId | length > 0)' "$workspace/actor.json"

run_actor() {
    local name=$1 input=$2 options=${3:-'{"memory":512,"timeout":90,"waitForFinish":60}'}
    apify api POST "acts/$actor/runs" -p "$options" -d "$input" >"$workspace/$name-run.json"
    local dataset store
    dataset=$(jq -er 'select(.data.status == "SUCCEEDED") | .data.defaultDatasetId' "$workspace/$name-run.json")
    store=$(jq -er .data.defaultKeyValueStoreId "$workspace/$name-run.json")
    apify datasets get-items "$dataset" --format json >"$workspace/$name-rows.json"
    apify api GET "key-value-stores/$store/records/SUMMARY" >"$workspace/$name-summary.json"
}

run_actor empty '{}'
jq -e 'length == 1 and .[0].errorCode == "NO_SOURCE" and .[0].charged == false' "$workspace/empty-rows.json"
run_actor typo '{"startURL":"https://www.instagram.com/reel/DS46KJNjva9/"}'
jq -e 'length == 1 and .[0].errorCode == "UNKNOWN_INPUT" and .[0].charged == false' "$workspace/typo-rows.json"

apify api GET "acts/$actor/versions/0.1" >"$workspace/version.json"
jq -e '.data.applyEnvVarsToBuild == false' "$workspace/version.json"
if ! jq -e 'any(.data.envVars[]?; .name == "REELSAID_GROQ_KEYS" and .isSecret == true)' "$workspace/version.json"; then
    exit 0
fi

prefill=$(jq -c '{startUrls: .properties.startUrls.prefill, forceRefresh: true, wordLevelTimestamps: true}' .actor/input_schema.json)
run_actor prefill "$prefill"
jq -e 'length == 1 and .[0].status == "success" and .[0].language == "en" and
    .[0].wordCount >= 20 and (.[0].wordLevelTimestamps | length >= 20) and
    .[0].subtitles.srt != null and .[0].subtitles.vtt != null' "$workspace/prefill-rows.json"
run_actor cached "$(jq -c '.forceRefresh = false' <<<"$prefill")"
jq -e 'length == 1 and .[0].status == "success" and .[0].cached == true and .[0].charged == false' "$workspace/cached-rows.json"
run_actor budget "$prefill" '{"memory":512,"timeout":90,"waitForFinish":60,"maxTotalChargeUsd":0.011}'
jq -e '.stopReason == "SPEND_LIMIT" and .continuation.remaining == 1 and .billed == 0' "$workspace/budget-summary.json"

run_actor mixed '{"shortcodes":["DS46KJNjva9","Ddm6E9OGt5D"],"startUrls":["https://example.org/invalid"],"forceRefresh":true}'
jq -e 'any(.[]; .errorCode == "INVALID_URL") and any(.[]; .videoId == "DS46KJNjva9" and .status == "success") and
    ([.[] | .metadata.carouselPosition | select(. != null)] | sort) == [2,6,10]' "$workspace/mixed-rows.json"

run_actor batch '{"shortcodes":["DS46KJNjva9","Dfax6SllBLR"],"maxResults":1,"forceRefresh":true}'
dataset=$(jq -er .data.defaultDatasetId "$workspace/batch-run.json")
jq -e '.successful == 1 and .continuation.remaining == 1 and .stopReason == "RESULT_LIMIT"' "$workspace/batch-summary.json"
run_actor resumed "$(jq -cn --arg dataset "$dataset" '{resumeFromDatasetId:$dataset}')"
jq -e --arg dataset "$dataset" '.successful == 1 and .continuation == null and .completedDatasetIds == [$dataset]' "$workspace/resumed-summary.json"
jq -e -s '.[0][0].videoId != .[1][0].videoId' "$workspace/batch-rows.json" "$workspace/resumed-rows.json"
