#!/usr/bin/env bash
set -euo pipefail

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
run_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
failure() {
    printf '::error title=%s::%s\n' "$1" "$run_url"
    exit 1
}

case "${MONITOR_CASE:-normal}" in
    normal) ;;
    checkout-failure) SOURCE_REVISION=invalid ;;
    runtime-failure) unset REELSAID_GROQ_KEYS ;;
    *) failure 'Verification setup failed' ;;
esac
if [[ ! "${SOURCE_REVISION:-}" =~ ^[0-9a-f]{40}$ ]] ||
    ! bash .github/scripts/private-source.sh "$scratch" "$SOURCE_REVISION" approved >/dev/null 2>&1; then
    failure 'Source checkout failed'
fi
unset SOURCE_KEY SOURCE_REPOSITORY SOURCE_REVISION
if timeout --kill-after=10s 8m bash .github/scripts/verify.sh "$scratch" runner-health >/dev/null 2>&1; then
    printf '%s\n' 'Private verification passed.'
else
    status=$?
    if [[ $status == 124 || $status == 137 ]]; then
        failure 'Runtime check timed out'
    fi
    failure 'Runtime check failed'
fi
