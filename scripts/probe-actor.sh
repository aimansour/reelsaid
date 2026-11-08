#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
actor=aimansour~reelsaid
task=
schedule=
cleanup() {
    if [[ -n $schedule ]]; then apify api DELETE "schedules/$schedule" >/dev/null 2>&1 || true; fi
    if [[ -n $task ]]; then apify api DELETE "actor-tasks/$task" >/dev/null 2>&1 || true; fi
    rm -rf -- "$workspace"
}
trap cleanup EXIT

bash scripts/deploy-actor.sh
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
run_actor prefill "$prefill" '{"timeout":90,"waitForFinish":60}'
jq -e '.data.options.memoryMbytes == 256' "$workspace/prefill-run.json"
jq -e 'length == 1 and .[0].status == "success" and .[0].language == "en" and
    .[0].wordCount >= 20 and (.[0].wordLevelTimestamps | length >= 20) and
    .[0].subtitles.srt != null and .[0].subtitles.vtt != null' "$workspace/prefill-rows.json"
run_actor cached "$(jq -c '.forceRefresh = false' <<<"$prefill")"
jq -e 'length == 1 and .[0].status == "success" and .[0].cached == true and .[0].charged == false' "$workspace/cached-rows.json"
run_actor budget "$prefill" '{"memory":512,"timeout":90,"waitForFinish":60,"maxTotalChargeUsd":0.011}'
jq -e '.stopReason == "SPEND_LIMIT" and .continuation.remaining == 1 and .billed == 0' "$workspace/budget-summary.json"
run_actor timed '{"profiles":["nasa"],"maxResults":12}' '{"timeout":10,"waitForFinish":40}'
jq -e '.data.options.memoryMbytes == 2048' "$workspace/timed-run.json"
jq -e '.stopReason == "TIME_LIMIT" and .continuation.reason == "TIME_LIMIT" and
    .successful == 0 and .billed == 0' "$workspace/timed-summary.json"

run_actor mixed '{"shortcodes":["DS46KJNjva9","Ddm6E9OGt5D"],"startUrls":["https://example.org/invalid"],"forceRefresh":true}'
jq -e 'any(.[]; .errorCode == "INVALID_URL") and any(.[]; .videoId == "DS46KJNjva9" and .status == "success") and
    ([.[] | .metadata.carouselPosition | select(. != null)] | sort) == [2,6,10]' "$workspace/mixed-rows.json"

run_actor batch '{"shortcodes":["DS46KJNjva9","Dfax6SllBLR"],"maxResults":1,"forceRefresh":true}'
dataset=$(jq -er .data.defaultDatasetId "$workspace/batch-run.json")
jq -e '.successful == 1 and .continuation.remaining == 1 and .stopReason == "RESULT_LIMIT"' "$workspace/batch-summary.json"
run_actor resumed "$(jq -cn --arg dataset "$dataset" '{resumeFromDatasetId:$dataset}')"
jq -e --arg dataset "$dataset" '.successful == 1 and .continuation == null and .completedDatasetIds == [$dataset]' "$workspace/resumed-summary.json"
jq -e -s '.[0][0].videoId != .[1][0].videoId' "$workspace/batch-rows.json" "$workspace/resumed-rows.json"

actor_id=$(jq -er .data.id "$workspace/actor.json")
test_name="reelsaid-verify-${GITHUB_RUN_ID:-$(date +%s)}"
task=$(jq -cn --arg id "$actor_id" --arg name "$test_name" '{
    actId:$id, name:$name, options:{build:"latest",memoryMbytes:512,timeoutSecs:80},
    input:{shortcodes:["DS46KJNjva9"], watchlistId:$name, newReelsOnly:true}
}' | apify api POST actor-tasks -d - | jq -er .data.id)
schedule=$(jq -cn --arg task "$task" --arg name "$test_name" '{
    name:$name, isEnabled:false, cronExpression:"0 4 * * *", timezone:"UTC",
    actions:[{type:"RUN_ACTOR_TASK", actorTaskId:$task}]
}' | apify api POST schedules -d - | jq -er .data.id)
apify api POST "schedules/$schedule/invoke" -d '{}' >"$workspace/invoked.json"
for _ in {1..20}; do
    apify api GET "actor-tasks/$task/runs" -p '{"limit":1,"desc":true}' >"$workspace/scheduled-run.json"
    scheduled_status=$(jq -r '.data.items[0].status // ""' "$workspace/scheduled-run.json")
    if [[ $scheduled_status == SUCCEEDED ]]; then break; fi
    if [[ $scheduled_status =~ ^(FAILED|TIMED-OUT|ABORTED)$ ]]; then exit 1; fi
    sleep 2
done
scheduled_dataset=$(jq -er '.data.items[0] | select(.status == "SUCCEEDED" and .meta.origin == "SCHEDULER") | .defaultDatasetId' "$workspace/scheduled-run.json")
apify datasets get-items "$scheduled_dataset" --format json |
    jq -e 'length == 1 and .[0].errorCode == "ALREADY_ANSWERED" and .[0].charged == false and .[0].firstSeenRunId != null'
