#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
cp -R probes/output/. "$workspace/"
cp .actor/{dataset_schema,output_schema,key_value_store_schema}.json "$workspace/.actor/"
mkdir "$workspace/reelsaid"
cp src/reelsaid/{audio_quality,contracts,discovery,groq,input,instagram,media,output,quality}.py "$workspace/reelsaid/"
apify actors push --dir "$workspace" --wait-for-finish 300 --json
apify actors call aimansour/reelsaid-output-probe --input '{}' --timeout 80 --memory 512 --silent --json
