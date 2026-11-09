#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
public_package=${1:-}
build_tag=${2:-latest}
package=$(mktemp -d)
trap 'rm -rf -- "$package"' EXIT
mkdir -p "$package/.actor" "$package/scripts" "$package/src/reelsaid"
cp .actor/*.json "$package/.actor/"
cp src/reelsaid/*.py "$package/src/reelsaid/"
cp Dockerfile .dockerignore pyproject.toml uv.lock "$package/"
cp scripts/install-quality-models "$package/scripts/"
if [[ -n $public_package ]]; then
    cp -- "$public_package/README.md" "$package/.actor/README.md"
fi
user_agent=apify-agent-skills/apify-actor-development
push=$(apify actors push --dir "$package" --build-tag "$build_tag" \
    --no-apply-env-vars-to-build --wait-for-finish 0 --json --user-agent "$user_agent")
build_id=$(jq -er '.build.id' <<< "$push")
deadline=$((SECONDS + 300))
while (( SECONDS < deadline )); do
    build=$(apify api GET "actor-builds/$build_id" --user-agent "$user_agent")
    status=$(jq -er --arg id "$build_id" '.data | select(.id == $id) | .status' <<< "$build")
    case "$status" in
        SUCCEEDED) break ;;
        READY|RUNNING) sleep 2 ;;
        *) printf '%s\n' 'Actor build failed.' >&2; exit 1 ;;
    esac
done
if [[ ${status:-} != SUCCEEDED ]]; then
    printf '%s\n' 'Actor build did not finish in time.' >&2
    exit 1
fi

actor_id=$(jq -er '.data.actId' <<< "$build")
build_number=$(jq -er '.data.buildNumber' <<< "$build")
for _ in {1..10}; do
    actor=$(apify api GET "acts/$actor_id" --user-agent "$user_agent")
    if jq -e --arg tag "$build_tag" --arg id "$build_id" '.data.taggedBuilds[$tag].buildId == $id' \
        <<< "$actor" >/dev/null; then
        jq --arg number "$build_number" '.build.status = "SUCCEEDED" | .build.number = $number' <<< "$push"
        exit
    fi
    sleep 1
done
printf '%s\n' 'Actor build tag did not resolve to the verified build.' >&2
exit 1
