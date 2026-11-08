#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
package=$(mktemp -d)
trap 'rm -rf -- "$package"' EXIT
mkdir -p "$package/scripts"
cp -R .actor src Dockerfile .dockerignore pyproject.toml uv.lock "$package/"
cp scripts/install-quality-models "$package/scripts/"
apify actors push --dir "$package" --no-apply-env-vars-to-build --wait-for-finish 300 --json
