#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."

user_agent=apify-agent-skills/apify-actor-development
actor=aimansour~reelsaid-standby-probe
push=$(apify actors push --dir probes/standby --wait-for-finish 0 --json --user-agent "$user_agent")
build_id=$(jq -er '.build.id' <<<"$push")
deadline=$((SECONDS + 180))
while (( SECONDS < deadline )); do
    receipt=$(apify api GET "actor-builds/$build_id" --user-agent "$user_agent")
    status=$(jq -er '.data.status' <<<"$receipt")
    case "$status" in
        SUCCEEDED) break ;;
        READY|RUNNING) sleep 2 ;;
        *) printf '%s\n' 'Private server build failed.' >&2; exit 1 ;;
    esac
done
[[ ${status:-} == SUCCEEDED ]]
build=$(jq -er '.data.buildNumber' <<<"$receipt")
python3 probes/standby/check-cloud.py "$actor" "$build" "${1:-SINGLE_TENANT}"
