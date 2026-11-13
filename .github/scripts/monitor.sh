#!/usr/bin/env bash
set -euo pipefail

run_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
failure() {
    printf '::error title=%s::%s\n' "$1" "$run_url"
    exit 1
}

case "${MONITOR_CASE:-normal}" in
    normal) ;;
    checkout-failure) failure 'Source checkout failed' ;;
    runtime-failure) unset REELSAID_GROQ_KEYS ;;
    *) failure 'Verification setup failed' ;;
esac
for attempt in 1 2; do
    if timeout --kill-after=10s 225s bash .github/scripts/verify.sh runner-health >/dev/null 2>&1; then
        printf '%s\n' 'Verification passed.'
        exit 0
    else
        status=$?
    fi
    case $status in
        124|137)
            if [[ $attempt == 2 ]]; then
                failure 'Runtime check timed out'
            fi
            printf '%s\n' 'Verification timed out. Retrying once.'
            ;;
        *) failure 'Runtime check failed' ;;
    esac
done
