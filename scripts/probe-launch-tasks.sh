#!/usr/bin/env bash
set -euo pipefail
umask 077

manifest=$1
user_agent=apify-agent-skills/apify-actor-development
api() { apify api "$@" --user-agent "$user_agent"; }
actor=$(api GET acts/aimansour~reelsaid)
build=$(jq -er '.data.taggedBuilds.candidate.buildNumber' <<< "$actor")
build_id=$(jq -er '.data.taggedBuilds.candidate.buildId' <<< "$actor")
store=$(api GET key-value-stores/aimansour~reelsaid-release-private |
    jq -er '.data | select(.generalAccess == "RESTRICTED") | .id')
tasks=$(bash scripts/prepare-tasks.sh "$manifest")
[[ $(bash scripts/prepare-tasks.sh "$manifest") == "$tasks" ]]
options=$(jq -cn --arg build "$build" '{build:$build,timeout:90,waitForFinish:60,maxTotalChargeUsd:0.25}')

while IFS= read -r task; do
    task_id=$(jq -er '.id' <<< "$task")
    slug=$(jq -er '.slug' <<< "$task")
    if [[ $slug == reelsaid-monitor-instagram-reels ]]; then
        # Each build verifies a first watchlist run independently of earlier examples.
        input=$(jq -ce --arg slug "$slug" --arg id "release-check-$build" \
            '.[] | select(.slug == $slug) | .input + {watchlistId:$id}' "$manifest")
        run=$(api POST "actor-tasks/$task_id/runs" -p "$options" -d "$input")
    else
        run=$(api POST "actor-tasks/$task_id/runs" -p "$options")
    fi
    receipt="key-value-stores/$store/records/TASK-$slug"
    jq -c --argjson task "$task" '.data | $task + {runId:.id,build:.buildNumber,datasetId:.defaultDatasetId}' <<< "$run" |
        api PUT "$receipt" -d - >/dev/null
    if jq -e '.data.status == "READY" or .data.status == "RUNNING"' <<< "$run" >/dev/null; then
        run_id=$(jq -er .data.id <<< "$run")
        run=$(api GET "actor-runs/$run_id" -p '{"waitForFinish":40}')
    fi
    dataset=$(jq -er --arg task "$task_id" --arg build "$build_id" '
        .data | select(.status == "SUCCEEDED" and .actorTaskId == $task and .buildId == $build) | .defaultDatasetId
    ' <<< "$run")
    rows=$(api GET "datasets/$dataset/items" -p '{"limit":20}')
    case "$slug" in
        reelsaid-reel-subtitles)
            jq -e 'length == 1 and .[0].status == "success" and
                (.[0].wordLevelTimestamps | length) == .[0].wordCount and
                .[0].subtitles.srt != null and .[0].subtitles.vtt != null' <<< "$rows" >/dev/null
            subtitles_store=$(jq -er .data.defaultKeyValueStoreId <<< "$run")
            for format in srt vtt; do
                key=$(jq -er --arg format "$format" '.[0].subtitles[$format].key' <<< "$rows")
                contents=$(api GET "key-value-stores/$subtitles_store/records/$key")
                [[ $contents == *" --> "* ]]
                if [[ $format == vtt ]]; then
                    [[ $contents == WEBVTT* ]]
                fi
            done
            ;;
        reelsaid-compare-reel-hooks)
            jq -e 'length == 2 and all(.[]; .status == "success" and
                (.hook.text | length) > 0 and .hook.startSeconds < 3 and .hook.endSeconds <= 3)' <<< "$rows" >/dev/null
            ;;
        reelsaid-monitor-instagram-reels)
            jq -e 'any(.[]; .status == "success" and
                ((.metadata.discoveryProfiles // []) | index("bbcnews")) != null)' <<< "$rows" >/dev/null
            ;;
        reelsaid-spanish-reel-transcript)
            jq -e 'length == 1 and .[0].status == "success" and .[0].language == "es" and
                .[0].wordCount > 4 and .[0].subtitles.srt != null' <<< "$rows" >/dev/null
            ;;
        reelsaid-instagram-transcripts-for-ai)
            jq -e 'length == 2 and all(.[]; .status == "success" and .schemaVersion == 1 and
                (.wordLevelTimestamps | length) > 0 and (.metadata.postUrl | startswith("https://www.instagram.com/")) and
                any(.provenance[]; .field == "datasetItems"))' <<< "$rows" >/dev/null
            ;;
        *) exit 2 ;;
    esac
    jq -c --argjson task "$task" --argjson rows "$rows" '
        .data | $task + {runId:.id,build:.buildNumber,datasetId:.defaultDatasetId,verified:true,
                         outcomes:($rows | group_by(.status) | map({key:.[0].status,value:length}) | from_entries)}
    ' <<< "$run" | api PUT "$receipt" -d - >/dev/null
done <<< "$tasks"
