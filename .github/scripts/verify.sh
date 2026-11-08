#!/usr/bin/env bash
set -eu

package_root=$(pwd -P)
private_source=$1
shift
if (
    cd -- "$private_source"
    exec env -i HOME="$HOME" PATH="$PATH" APIFY_TOKEN="${APIFY_TOKEN:-}" \
        PACKAGE_ROOT="$package_root" RELEASE_PRICING_SHA256="${RELEASE_PRICING_SHA256:-}" \
        bash scripts/ci-verify "$@"
) >/dev/null 2>&1; then
    printf '%s\n' 'Private verification passed.'
else
    printf '%s\n' 'Private verification failed.'
    exit 1
fi
