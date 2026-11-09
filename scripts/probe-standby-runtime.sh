#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."

package=${1:?The public package is required}
agent=apify-agent-skills/apify-actor-development
actor=aimansour~reelsaid
selection='.data | select(.isPublic == false) | .defaultRunOptions.build as $build | .taggedBuilds[$build].buildId // $build'
stable=$(apify api GET "acts/$actor" --user-agent "$agent" | jq -er "$selection")
receipt=$(bash scripts/deploy-actor.sh "$package" launch-standby)
build=$(jq -er '.build | select(.status == "SUCCEEDED") | .number' <<<"$receipt")
[[ $(apify api GET "acts/$actor" --user-agent "$agent" | jq -er "$selection") == "$stable" ]]
python3 scripts/verify-standby-runtime.py "$build"
