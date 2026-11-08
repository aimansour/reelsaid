#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
public_package=${1:-}
build_tag=${2:-latest}
package=$(mktemp -d)
trap 'rm -rf -- "$package"' EXIT
mkdir -p "$package/scripts"
cp -R .actor src Dockerfile .dockerignore pyproject.toml uv.lock "$package/"
cp scripts/install-quality-models "$package/scripts/"
if [[ -n $public_package ]]; then
    cp -- "$public_package/README.md" "$package/.actor/README.md"
fi
apify actors push --dir "$package" --build-tag "$build_tag" \
    --no-apply-env-vars-to-build --wait-for-finish 300 --json
