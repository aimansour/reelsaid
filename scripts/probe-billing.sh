#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
actor=aimansour~reelsaid-billing-probe
apify actors push --dir probes/billing --wait-for-finish 300 --json
apify api GET "acts/$actor" >"$workspace/actor.json"
jq -e '.data.isPublic == false' "$workspace/actor.json"
if ! jq -e 'any(.data.pricingInfos[]?; .pricingModel == "PAY_PER_EVENT")' "$workspace/actor.json"; then
    if ! apify api PUT "acts/$actor" -d - <probes/billing/pricing.json >"$workspace/pricing.json"; then
        jq -e '.error.type == "cannot-monetize-without-payout-billing-info"' "$workspace/pricing.json"
    fi
fi
apify api POST "acts/$actor/runs" -p '{"maxTotalChargeUsd":0.018,"memory":256,"timeout":45,"waitForFinish":45}' \
    -d '{"charge":true}' >"$workspace/run.json"
store=$(jq -er 'select(.data.status == "SUCCEEDED") | .data.defaultKeyValueStoreId' "$workspace/run.json")
apify api GET "key-value-stores/$store/records/RESULT" >"$workspace/result.json"
jq -e '.maxChargeRun == 0.018 and (.maxChargeEnv | tonumber) == 0.018 and
    (."APIFY_USER_PRICING_TIER" | IN("FREE","BRONZE","SILVER","GOLD","PLATINUM","DIAMOND"))' "$workspace/result.json"
if jq -e '.error.type == "cannot-monetize-without-payout-billing-info"' "$workspace/pricing.json" 2>/dev/null; then
    jq -e '.chargeError.type == "cannot-charge-non-pay-per-event-actor"' "$workspace/result.json"
else
    jq -e '.first["reel-transcript"] == 1 and .replayed["reel-transcript"] == 1 and
        .final["reel-transcript"] == 1 and .final["additional-minute"] == 2' "$workspace/result.json"
fi
