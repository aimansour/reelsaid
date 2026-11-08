#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
cp -R probes/state/. "$workspace/"
apify actors push --dir "$workspace" --wait-for-finish 300 --json
key="probe-$(python3 -c 'from uuid import uuid4; print(uuid4().hex)')"
actor=aimansour/reelsaid-state-probe
apify actors call "$actor" --input "{\"role\":\"holder\",\"key\":\"$key\"}" --timeout 65 --memory 256 --silent --json &
holder=$!
apify actors call "$actor" --input "{\"role\":\"contender\",\"key\":\"$key\"}" --timeout 65 --memory 256 --silent --json &
contender=$!
result=0
wait "$holder" || result=1
wait "$contender" || result=1
exit "$result"
