#!/usr/bin/env bash
set -eu

package_root=$(pwd -P)
if (
    cd -- "$1"
    exec env -i HOME="$HOME" PATH="$PATH" APIFY_TOKEN="${APIFY_TOKEN:-}" \
        PACKAGE_ROOT="$package_root" bash scripts/ci-verify "$2"
) >/dev/null 2>&1; then
    printf '%s\n' 'Private verification passed.'
else
    printf '%s\n' 'Private verification failed.'
    exit 1
fi
