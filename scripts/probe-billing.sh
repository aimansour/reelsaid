#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname "$0")/.."
workspace=$(mktemp -d)
trap 'rm -rf -- "$workspace"' EXIT
actor=aimansour~reelsaid-billing-probe
mkdir -p "$workspace/package/reelsaid"
cp -R probes/billing/. "$workspace/package/"
cp src/reelsaid/{billing,state,contracts}.py "$workspace/package/reelsaid/"
apify actors push --dir "$workspace/package" --wait-for-finish 300 --json
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
    jq -e '(.quote.total | tonumber) == 0.018 and .quote.admission == "admitted" and .quote.chargesEnabled == true and
        .chargeError == null' "$workspace/result.json"
    id=$(jq -er .data.id "$workspace/run.json")
    settled() {
        local run_id=$1 expected=$2
        for _ in {1..12}; do
            apify api GET "actor-runs/$run_id" >"$workspace/settled.json"
            if jq -e --argjson expected "$expected" '.data.chargedEventCounts == $expected' "$workspace/settled.json"; then
                return 0
            fi
            sleep 2
        done
        return 1
    }
    settled "$id" '{"reel-transcript":1,"additional-minute":2}'
    apify api POST "acts/$actor/runs" -p '{"maxTotalChargeUsd":0.024,"memory":256,"timeout":45,"waitForFinish":45}' \
        -d '{"settle":true}' >"$workspace/production-run.json"
    store=$(jq -er 'select(.data.status == "SUCCEEDED") | .data.defaultKeyValueStoreId' "$workspace/production-run.json")
    apify api GET "key-value-stores/$store/records/RESULT" |
        jq -e '.distinctKeys == 2 and .journal.pendingClaimId == null and .journal.events["reel-transcript"] == 2 and
            (.receipts | length == 2 and all(.state == "settled" and (.amount|tonumber) == 0.012))'
    settled "$(jq -er .data.id "$workspace/production-run.json")" '{"reel-transcript":2,"additional-minute":0}'
fi
