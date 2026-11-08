# Full-price billing verification

## Platform contract

Apify reports the run spending limit in `ACTOR_MAX_TOTAL_CHARGE_USD` and in the run options. The scoped client read its own run in a private cloud test. The environment returned `APIFY_USER_PRICING_TIER=FREE` while the private user API returned 403 using the same token. The Actor uses the run's pricing snapshot and tier, with both cap sources checked. The Python charging manager in SDK 4.2.1 skips tiered events, so the Actor uses the original run's charge endpoint directly. [Actor run](https://docs.apify.com/api/v2/actor-run-get) · [Charge endpoint](https://docs.apify.com/api/v2/post-charge-run)

The direct endpoint can report a successful charge beyond the customer cap even though the excess does not count toward payouts. Admission reserves the full video quote before transcription. An earlier unsettled reservation can block admission temporarily. Once earlier reservations settle, the first unaffordable video establishes the checkpoint boundary. Previous charged counts initialize the budget for a restarted run.

## Settlement

A native restricted record holds the transcript before the first debit. A separate guarded journal records the authorized amounts and cap, each pending event's original counter and attempt timestamp, and confirmed counts. The original run serializes debits. A request retries with its stable identifier within a 150-second safety window inside Apify's documented three-minute validity. A later run can recover the transcript and recorded receipt. After the window, only authoritative counters or a saved acknowledgement can confirm an interrupted event. An unresolved event blocks further admission in that run. [Idempotency](https://docs.apify.com/api/v2/post-charge-run)

The deterministic suite covers all provisional tiers and duration boundaries, full admission, reservation release, runtime rates, transport response loss, interruption and original-run reconciliation. It verifies that a sibling run and a retry beyond the idempotency window send zero additional debit calls.

## Live test status

The private test Actor `aimansour/reelsaid-billing-probe` completed run `u7svO7EbFuvJxC0Dn`. The cloud environment and run API both returned the submitted cap of $0.014. At that point Apify refused to enable pay-per-event with HTTP 400 `cannot-monetize-without-payout-billing-info`. Without that configuration, the run's debit request was rejected with HTTP 405 `cannot-charge-non-pay-per-event-actor`. Steadyfetch's settled comparison run `MNKmRNx4ahyfGY2Sw` exposed event counts and $0.015 of charged usage. [Payout setup](https://docs.apify.com/actors/monetize/monthly-payouts)

The trusted public workflow reproduced the $0.018 cap and expected account rejection in private run `gq9ovdPwYPsFkTS4a`. A separate verification run passed the 50-test suite and all four schemas. [Cloud workflow](https://github.com/aimansour/reelsaid/actions/runs/42462243029) · [Verification workflow](https://github.com/aimansour/reelsaid/actions/runs/42462242961)

## Paid event API after payout setup

After the owner completed payout setup, Apify enabled tiered pricing on the private probe. The actual run snapshot omitted the platform-usage configuration flag and included the effective tier table. The production loader accepts the run shape and validates the event set, prices, and cap. The private pricing configuration explicitly leaves platform usage out of customer events.

| Private run | Observed result |
| --- | --- |
| `FB03qEwzcgbZwJljF` | The runtime quoted $0.018 for 241 seconds and admitted it at the exact cap. Repeating the base event with the same key produced one accepted transcript event and two accepted additional-minute events. |
| `P0yyAt8xOgTrEOJcq` | The production settlement module wrote two durable results and intentionally dropped the second successful acknowledgement. Both receipts settled at $0.012, the journal held two confirmed base events with no pending claim, and Apify reported exactly two base events. |

The run API counters can lag successful responses. The protected run journal preserves acknowledged cumulative event totals and the active debit before a retry or restart. This prevents a delayed count from the previous video from confirming a new video. These were owner-run platform tests. Apify accepted the events and reported zero externally accounted events for these runs. [Live billing verification](https://github.com/aimansour/reelsaid/actions/runs/42482027955)
