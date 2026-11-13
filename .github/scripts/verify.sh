#!/usr/bin/env bash
set -eu

package_root=$(pwd -P)
if (
    if [[ $1 == runner-health ]]; then
        exec env -i HOME="$HOME" PATH="$PATH" REELSAID_GROQ_KEYS="${REELSAID_GROQ_KEYS:-}" \
            bash scripts/ci-verify "$@"
    fi
    exec env -i HOME="$HOME" PATH="$PATH" APIFY_TOKEN="${APIFY_TOKEN:-}" \
        APIFY_STANDBY_TEST_TOKEN="${APIFY_STANDBY_TEST_TOKEN:-}" \
        PACKAGE_ROOT="$package_root" RELEASE_PRICING_SHA256="${RELEASE_PRICING_SHA256:-}" \
        bash scripts/ci-verify "$@"
) >/dev/null 2>&1; then
    printf '%s\n' 'Verification passed.'
else
    printf '%s\n' 'Verification failed.'
    exit 1
fi
