#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
input=${1:-'{}'}
user_agent=apify-agent-skills/apify-actor-development
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
cp -R probes/discovery/. "$workspace/"
mkdir "$workspace/reelsaid"
cp src/reelsaid/{contracts,input,instagram,discovery,media}.py "$workspace/reelsaid/"
apify actors push --dir "$workspace" --wait-for-finish 300 --json --user-agent "$user_agent"
apify actors call aimansour/reelsaid-discovery-probe --input "$input" --timeout 150 --memory 512 --silent --json --user-agent "$user_agent"
