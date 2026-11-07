#!/usr/bin/env bash
set -eu

if (
    cd -- "$1"
    exec env -i HOME="$HOME" PATH="$PATH" APIFY_TOKEN="${APIFY_TOKEN:-}" \
        bash scripts/ci-verify "$2"
) >/dev/null 2>&1; then
    printf '%s\n' 'Private verification passed.'
else
    printf '%s\n' 'Private verification failed.'
    exit 1
fi
