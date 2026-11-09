#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."

user_agent=apify-agent-skills/apify-actor-development
actor=aimansour~reelsaid-standby-probe
mode=${1:-SINGLE_TENANT}
package=probes/standby
if [[ $mode == CROSS ]]; then
    workspace=$(mktemp -d)
    trap 'rm -rf -- "$workspace"' EXIT
    cp -R probes/standby/. "$workspace/"
    python3 probes/standby/prepare-cross.py "$workspace/qa_callers.py"
    package=$workspace
fi
push=$(apify actors push --dir "$package" --wait-for-finish 0 --json --user-agent "$user_agent")
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
python3 probes/standby/check-cloud.py "$actor" "$build" "$mode"
