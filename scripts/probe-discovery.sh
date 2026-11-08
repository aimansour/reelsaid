#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
cp -R probes/discovery/. "$workspace/"
mkdir "$workspace/reelsaid"
cp src/reelsaid/{contracts,input,instagram,discovery}.py "$workspace/reelsaid/"
apify actors push --dir "$workspace" --wait-for-finish 300 --json
apify actors call aimansour/reelsaid-discovery-probe --input '{}' --timeout 150 --memory 512 --silent --json
