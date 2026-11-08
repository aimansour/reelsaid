# ReelSaid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one production Apify Actor that turns public Instagram video into original-language transcripts, timed segments, and subtitle files, with dependable batch processing and billing.

**Architecture:** Public GitHub Actions verifies a trusted revision from the private source repository and requests Docker builds on Apify. The Actor discovers and resolves public media, admits work against the full price, and persists transcripts, watchlist state, and charge receipts across runs. Public documentation and integrations expose the native Apify interfaces.

**Tech Stack:** Apify Actors, Apify CLI and API, Docker, GitHub Actions, and GroqCloud `whisper-large-v3-turbo` and `whisper-large-v3`. Tasks 03 and 04 select and record the programming language, runtime, libraries, and test runner from evidence. The state backend, concurrency, resources, release transport, and final prices are decided in their owning tasks.

**Spec:** [Approved ReelSaid product design](../specs/2026-11-07-reelsaid-design.md), approved revision `872be93`.

## Global Constraints

- Execute Tasks 01 through 17 in order, one active task at a time. Finish its evidence, verification, review, and commit before opening the next task. Commit a candidate within the current task whenever a cloud check needs an immutable revision. Under subagent-driven execution, review each task before dispatching the next. Resolve failures or record the exact blocker in the current task.
- At execution, use the Superpowers worktree and TDD workflows where applicable. Run the named regression test red before changing product behavior, then run the owning suite green. Keep deterministic tests local to the test runner and run shared automation from the public repository. Use the cloud and paid probes only where they answer questions that affect a decision or establish real platform behavior.
- Extract public Instagram media in the Actor over HTTP with no Instagram login, browser, paid Apify proxy, or dependency on another Actor for extraction. Provide a primary path and at least one independent fallback. Compare other useful approaches that emerge during research.
- Use `language=auto` by default and support the multilingual repertoire exposed by the approved Whisper models. Preserve original language and script in the transcript, hook, and subtitle files. Keep product copy, fields, examples, and documentation in clear international English.
- Apply the full-price budget check before transcription. Bill each eligible carousel video separately. A usable result with 20% or less affected is eligible for normal billing. Trigger quality-driven repair only when the affected share exceeds 20%. Silence, music without intelligible speech, failed outcomes, and uncorrected results above the threshold carry zero events.
- Keep every Actions workflow and run in the public repository. Keep the private repository at zero Actions workflows or runs. Keep credentials, source, private fixtures, and diagnostics out of public logs, caches, artifacts, images, and docs. Use secret references and keep raw evidence access-controlled.
- Use **ReelSaid**, **ReelSaid — Instagram Reels Transcript API**, public repository `reelsaid`, and **Every Reel, in Words.** Name Whisper Large-v3 in public copy as part of the largest Whisper model tier. Keep routing and implementation details internal.

## Review Focus

- Empty API JSON or a misspelled source field never runs the Store example or incurs a charge. Task 05 `empty_input_never_uses_prefill` and Task 13 `api_input_and_store_prefill` cover both entry points.
- A budget that fits the base event but falls short of the full video price stops processing in order before ASR. Task 12 `base_only_budget_defers` and Task 13 `ordered_budget_stop_and_resume` own this case.
- A stale CDN URL from a historical dataset refreshes the correct carousel child and keeps a separate audio track when needed. Task 07 `expired_carousel_sidecar` pins the recovery.
- Overlapping runs and a lost billing response preserve a single owner, staged result, and charge. Task 08 `expired_lease_fences_owner` and Task 12 `settlement_response_lost` cover both boundaries.
- A first watchlist run delivers eligible existing videos. On later runs, terminal free outcomes are skipped and budget-deferred videos can be processed. Task 13 `watchlist_first_and_later_runs` pins the transition.

## Files and interfaces

| Location | Responsibility |
| --- | --- |
| Private `docs/engineering/decisions.md` and `docs/engineering/evidence/` | Evidence, alternatives, selected settings, private run references, and exact module and test paths. Preserve sanitized measurements and record which measurements informed each decision. |
| Private `.actor/actor.json`, `.actor/input_schema.json`, `.actor/dataset_schema.json`, `.actor/output_schema.json`, `.actor/key_value_store_schema.json` | Actor identity, Console/API input, dataset rows, result links, and file storage declarations. [Apify Actor definition](https://docs.apify.com/actors/development/actor-definition/actor-json) |
| Private `Dockerfile`, `.dockerignore`, `scripts/verify`, `tests/fixtures/` | Reproducible Docker runtime, restricted build context, stable verification command, and redacted or synthetic fixtures. |
| Private runtime modules `input`, `discovery`, `media`, `state`, `groq`, `quality`, `output`, `billing`, `actor` | Boundaries described by Tasks 05–13. Task 04 binds each module and its tests to exact physical files and idiomatic signatures in the selected stack. |
| Public `.github/workflows/verify.yml` and `.github/workflows/release.yml` | Trusted verification, scheduled checks, and explicitly requested release. Keep provider and extraction internals in private code. |
| Public `README.md`, `assets/reelsaid-logo.png`, `examples/api/{reel,profile,dataset,output}.json`, `examples/n8n/reelsaid.json`, `examples/make/reelsaid.blueprint.json`, `examples/zapier/README.md` | Store and GitHub product copy, verified brand asset, runnable examples, and actual import or template entry points. |

The signatures below describe data and ownership across tasks. `TenantId`, `RunId`, and `VideoId` are opaque IDs. `RunContext` carries the authenticated `tenantId`, `runId`, deadline, and authorized platform access. Task 04 records the exact native types, paths, dependency installation, and commands for `./scripts/verify <suite> [case]`. That entry point runs the chosen native test runner and propagates failures. Translate the assertions below into the chosen test syntax. A red gate requires a failure tied to the missing behavior. Shared contracts and the file map travel with each task.

### Task 01 — Establish the public automation and private source boundary

**Files** · Public `.github/workflows/verify.yml`. Private `docs/engineering/decisions.md`, `docs/engineering/evidence/automation.md`.

**Produces** · The repository and access mapping, trusted public run triggers, and a verified path for later private Apify probes.

- [ ] Review current GitHub workflow access, billing, cache visibility, and Apify CLI deployment guidance. Identify the authorized owner, the two repository identities, and the secrets needed for scoped source read and Apify test deployment. Choose a source and trigger mechanism that pins a verified private revision. [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) · [Private checkout](https://github.com/actions/checkout#checkout-multiple-repos-private) · [Apify deployment](https://docs.apify.com/actors/development/deployment)
- [ ] Configure the repos and public verification lane using secret references. Disable Actions in the private repo. Keep untrusted public contributions outside the private-source job. Install execution tooling as needed and use Apify CLI for supported operations.
- [ ] Exercise the public workflow on a synthetic private marker using both a passing case and a failing case.
- [ ] Verify repository visibility with `gh repo view`, private Actions status and zero runs with GitHub, and the public run with `gh run view --log`. Inspect public log, artifact, and cache surfaces for the synthetic marker and private build inputs. Record the successful public run and sanitized failure evidence privately.
- [ ] Review and commit the automation and evidence before the first benchmark run.

### Task 02 — Establish competitor and fixture baselines

**Files** · Private `docs/engineering/evidence/market.md`, `tests/fixtures/`.

**Consumes** · Task 01's trusted execution lane. **Produces** · `FixtureCatalog` with expected transcript or media verdict, metadata expectations, and a comparable run matrix.

- [ ] Inventory Steadyfetch (`steadyfetch/instagram-reel-transcript-scraper`) first, then other relevant Store leaders discovered through Store, MCP, and search. Record input/output coverage, filters, metrics, examples, scheduling behavior, price, first-run experience, and agent-facing copy. Use documentation, relevant GitHub and Reddit reports, and actual runs to resolve meaningful gaps.
- [ ] Select representative public inputs, including a verified personal profile, creator and business profiles, collaboration attribution, multiple video children, direct and expired CDN links, separate audio, multilingual speech, speech over music, music-only, and silence. Select a stable short public spoken Reel for Store `prefill`. Track a verified Trial Reel if found.
- [ ] Run the matched competitor cases on Apify. Record observed price, usable results, metadata, first-result latency, batch throughput, and transcript quality against references. Choose error and timing metrics suited to the fixture languages. Label unavailable measurements and repeat cases where variation could change the comparison. Capture a small, mixed, and large-batch comparison where useful.
- [ ] Verify each retained claim against a source or private run reference and commit the baseline. [Steadyfetch listing](https://apify.com/steadyfetch/instagram-reel-transcript-scraper)

### Task 03 — Select Instagram retrieval routes in Apify cloud

**Files** · Private `docs/engineering/evidence/retrieval.md`, `tests/fixtures/instagram/`, temporary probe source in the private working area.

**Consumes** · `FixtureCatalog`. **Produces** · Retrieval decision, failure evidence, response fixtures, and a runtime shortlist.

- [ ] Read upstream library code and current discussions about unauthenticated Instagram access. Consider public response data and Graph payloads, embed pages, Reels tab retrieval, specialized libraries, and any additional routes found. Identify the routes whose cloud behavior or cost is uncertain.
- [ ] Build minimal probes through the public workflow and run them on Apify with the Actor's intended access conditions. Check single posts and profiles, the personal fixture, pagination, publisher versus discovery account, carousel children, signed media, metrics, and fallback behavior. Record availability, request count, transfer, timing, and failure classes. Use local probes for diagnosis.
- [ ] Select primary and fallback routes from results in Apify cloud and verify that the fallback addresses a distinct failure mode. Record how each promised source and important metadata field will be resolved. Capture Trial Reel evidence when a fixture is found and record its deferred coverage otherwise.
- [ ] Review the cloud run references, sanitized fixtures, and route decision, then commit the evidence.

### Task 04 — Choose the runtime and validate media and transcription feasibility

**Files** · Private `docs/engineering/evidence/transcription.md`, `docs/engineering/decisions.md`, `tests/fixtures/audio/`.

**Consumes** · `FixtureCatalog` and Task 03's retrieval evidence. **Produces** · Runtime and dependency decisions, Groq routing candidates, and exact source/test bindings for Tasks 05–13.

- [ ] Compare plausible language, library, media, and container combinations against acquisition support, maintainability, throughput, latency, and Apify cost. Use small cloud probes for decisions that documentation or measured evidence leaves open. Reuse the Task 03 fixtures and evidence.
- [ ] Probe Groq's URL and upload paths on matched Instagram media for both approved models, including sidecar audio, multilingual language hints and detection, segment and word timing, and expiry behavior. Identify each authorized organization's actual per-model and shared quota signals, cooldown behavior, and minimum billable request effects. Use representative audio to compare speech/music classification and repair candidates. [Groq speech-to-text](https://console.groq.com/docs/speech-to-text) · [Groq rate limits](https://console.groq.com/docs/rate-limits)
- [ ] Select the stack and record its versions, actual module/test files, dependency lockfile, test runner, and exact verification commands. Bind every logical interface and named suite in this plan before its implementation. Record the evidence and provisional media, classification, and model policy for later calibration.
- [ ] Verify the chosen stack can perform a representative cloud acquisition and transcription with recorded results, and commit the decision.

### Task 05 — Validate Actor input and define the contract

**Files** · Private `.actor/actor.json`, `.actor/input_schema.json`, `scripts/verify`, module `input`, suite `contract`, and the manifest and lockfile bound in Task 04.

**Produces** · `parseInput(raw: JsonObject) -> InputPlan` with typed `sources`, validation `outcomes`, `filters`, and `options` including `TranscriptOptions`. `InputRef` identifies a submitted input. `Outcome<T>` carries `status`, `errorCode`, `retryable`, and a value when one is available, including usable partials.

- [ ] Set up the selected dependency manifest and native runner with the `scripts/verify` entry point.
- [ ] Write these cases in the `contract` suite.

  ```text
  empty_input_never_uses_prefill: assert sources({}) == sources({startUrlz: [example]}) == []
  mixed_sources_keep_valid_items: assert invalid_url_error and valid_siblings_preserved
  language_auto_and_hint: assert omitted_language == "auto" and explicit_supported_hint_preserved
  ```

- [ ] Run `./scripts/verify contract`. Expect failures on the missing parser behavior.
- [ ] Bind `startUrls` for one or many URLs, `profiles` for handles or profiles, `shortcodes`, `datasetId`, and `datasetItems`. Normalize the input into typed candidates. Define discovery filters, caption/word timing/subtitle options as needed by the spec, `watchlistId`, `newReelsOnly`, `forceRefresh`, and `resumeFromDatasetId`. Put Task 02's spoken Reel in Console `prefill`. Use runtime validation for item errors the platform schema can permit safely.
- [ ] Run `./scripts/verify contract`. Expect all cases to pass, including the schema check for mixed sources and the genuine prefill.
- [ ] Review and commit the schema, input module, and runner.

### Task 06 — Discover, normalize, and filter Instagram videos

**Files** · Private module `discovery`, suite `discovery`, `tests/fixtures/instagram/`.

**Consumes** · `InputPlan`, public retrieval routes from Task 03, and authenticated run context. **Produces** · `discover(plan: InputPlan, context: RunContext) -> Discovery` with ordered `VideoRef`s, unresolved input outcomes, and continuation state. `VideoRef` carries canonical post/child identifiers, source URLs, metadata, and provenance.

- [ ] Write these cases in the `discovery` suite.

  ```text
  mixed_sources_converge: assert equivalent /reel/, /p/, /tv/, tracked, shortcode, and dataset inputs converge with provenance
  profile_and_carousel: assert paginated_children == [first_video, second_video] and publisher != discovery_profile
  filters_and_order: assert requested date, last-days, views, likes, duration, and pinned filters precede ASR and both sorts have stable ties
  discovery_errors_are_rows: assert unknown_metric == null and block_is_retryable and unauthorized_dataset_is_rejected
                             assert private_and_removed_status_follow_available_evidence
  ```

- [ ] Run `./scripts/verify discovery`. Expect failures on unresolved and unfiltered fixtures.
- [ ] Implement the selected retrieval routes, authorized dataset paging, early deduplication, metadata, and pre-ASR filters. Finalize a duration filter after media inspection if discovery cannot resolve the value. Report missing filter metadata or an empty source explicitly. Keep the discovery cursor for interrupted batches.
- [ ] Run `./scripts/verify discovery`. Expect all cases and Task 03's captured cloud fixtures to pass.
- [ ] Review and commit the discovery changes.

### Task 07 — Resolve media, identity, and duration

**Files** · Private module `media`, suite `media`.

**Consumes** · `VideoRef`. **Produces** · `inspectMedia(ref: VideoRef, context: RunContext) -> Outcome<MediaPlan>`. `MediaPlan` carries `videoId`, trusted `durationSeconds`, audio availability, media and caption candidates, and transport inputs.

- [ ] Write these cases in the `media` suite.

  ```text
  expired_carousel_sidecar: assert refreshed_child_id == original_child_id and selected_audio == usable_sidecar
  signed_url_preserved: assert fetched_url == signed_input and expired_without_origin_has_error
  stable_cdn_identity: assert equivalent_asset_ids_match and distinct_carousel_children_stay_distinct
  media_destination_validation: assert rejected_redirect_requests == 0
  track_and_duration: assert missing_track_has_no_audio_verdict and duration_is_video_or_audio_only
  ```

- [ ] Run `./scripts/verify media`. Expect failures on media refresh, identity, and validation.
- [ ] Implement validated HTTP resolution, refresh, and lightweight duration/track inspection where reliable. Preserve available audio and reuse acquired bytes if upload is needed. Provide stable identity before ASR, keeping unmatched CDN inputs distinct when evidence is insufficient.
- [ ] Run `./scripts/verify media`. Expect all cases to pass.
- [ ] Review and commit the media changes.

### Task 08 — Persist account state and coordinate work across runs

**Files** · Private module `state`, suite `state`, `docs/engineering/evidence/state.md`.

**Consumes** · `VideoId` from known discovery identity or `MediaPlan`, authenticated `TenantId`, and run identity. **Produces** · `State` operations `lookup(tenantId, videoId, options) -> CacheLookup`, `acquire(videoId, runId) -> Outcome<Lease>`, `lookupAnswer(tenantId, watchlistId, videoId) -> AnswerState`, `recordAnswer(tenantId, watchlistId, videoId, outcome)`, `loadCheckpoint(tenantId, datasetId) -> Checkpoint`, and `saveCheckpoint(tenantId, datasetId, checkpoint)`. Bind guarded commit and release operations to the lease mechanism chosen here.

- [ ] Measure Steadyfetch with overlapping cold runs, later repeats, and a fresh watchlist. Match observed coordination within the calling Apify account. Compare native storage and claims against account isolation, recovery, and cost. Verify required Apify guarantees with a bounded concurrent cloud probe.
- [ ] Write these cases in the `state` suite.

  ```text
  expired_owner_allows_recovery: assert active_owners(account, video) == 1 and expired_owner_cannot_commit
  tenant_isolation: assert other_account_has_no_cache_watchlist_or_checkpoint_access
  overlapping_refresh_coalesces: assert concurrent_refreshes_share_one_processing_attempt
  checkpoint_preserves_completed_work: assert resumed_work_contains_pending_items_and_prior_paid_refs
  ```

- [ ] Run `./scripts/verify state`. Expect failures on the required state transitions.
- [ ] Implement native account-scoped claims, cache, watchlist state, and durable checkpoint access. Store reusable successes by video and result-changing options. Persist definitive account answers and preserve retryable work.
- [ ] Run `./scripts/verify state`. Expect all cases to pass.
- [ ] Review and commit the state evidence and implementation.

### Task 09 — Implement Groq transport and quota scheduling

**Files** · Private module `groq`, suite `groq`.

**Consumes** · `MediaPlan`, `TranscriptOptions` from `InputPlan`, and Task 04's provider evidence. **Produces** · `transcribe(media: MediaPlan, options: TranscriptOptions, context: RunContext) -> Outcome<TranscriptDraft>` with original text, language, timed segments, optional word times, and available quality signals.

- [ ] Write these cases in the `groq` suite.

  ```text
  url_first_and_upload_recovery: assert suitable_url_full_download_calls == 0 and upload_recovers_supported_url_failure
  model_and_account_quota: assert both_approved_models_participate and org_and_model_capacity_are_honored
  rate_limit_cooldown: assert throttled_scope_waits and independent_scope_progresses
  timestamps_and_language_hint: assert transcription_preserves_language_and_requested_timing
  ```

- [ ] Run `./scripts/verify groq`. Expect failures on the missing request and quota behavior.
- [ ] Implement the measured direct URL and upload paths, provider response mapping, and backpressure using actual organization/model quotas and provider signals. Coordinate quota usage across active runs where needed. Treat temporary provider failure as retryable and preserve the deadline and media identity across fallbacks.
- [ ] Run `./scripts/verify groq`. Expect all cases to pass.
- [ ] Verify the adapter against Task 04's provider contract with the existing private Apify probe, keeping diagnostics private.
- [ ] Review and commit the transport changes.

### Task 10 — Classify speech and enforce transcript quality

**Files** · Private module `quality`, suite `quality`, `tests/fixtures/audio/`.

**Consumes** · `MediaPlan` with eligible captions, `transcribe`, and Task 04's reference material. **Produces** · `evaluateVideo(media: MediaPlan, options: TranscriptOptions, context: RunContext) -> Outcome<TranscriptResult>` with source, classification, confidence, coverage, partial reason, and billability.

- [ ] Write these cases in the `quality` suite.

  ```text
  music_silence_and_speech: assert music_only, silence, and missing_audio have distinct free outcomes
                            assert music_only_has_validated_confidence and speech_over_music_has_text
  captions_and_asr_provenance: assert accepted_captions.source == "captions" and fallback.source == "asr"
  defect_boundary_and_repair: assert usable(20%).billable and repair_calls(20%) == 0
                              assert repair_attempted(above_20%) and unresolved_above_20_percent_is_free
  partial_coverage_edges: assert overlapping_defects_count_once and start_end_and_internal_gaps_are_reported
                          assert repeated_or_fabricated_speech_is_flagged
  ```

- [ ] Run `./scripts/verify quality`. Expect failures on classification, threshold, and coverage behavior.
- [ ] Implement classification and quality assessment based on the measured media and reference evidence. Measure defect share on the full video timeline or the audio-only timeline. Select usable captions and preserve actual timing granularity. Apply targeted repair and reassess. Return calibrated speech classification confidence from 0 to 1 or `null` when unavailable.
- [ ] Run `./scripts/verify quality`. Expect all cases to pass, including the multilingual speech and no-speech fixtures.
- [ ] Review and commit the calibrated behavior and fixtures.

### Task 11 — Publish stable transcript, metadata, and subtitle shapes

**Files** · Private module `output`, suite `output`, `.actor/dataset_schema.json`, `.actor/output_schema.json`, `.actor/key_value_store_schema.json`.

**Consumes** · `VideoRef` or `InputRef`, `Outcome<TranscriptResult>`, and `BillingFields` with `charged`, `billedMinutes`, and `chargedEvents`. **Produces** · `toRow(ref: VideoRef | InputRef, outcome: Outcome<TranscriptResult>, billing: BillingFields) -> DatasetRow`, `subtitleFiles(result: TranscriptResult) -> SubtitleFiles`, and a versioned `RunSummary` contract.

- [ ] Write these cases in the `output` suite.

  ```text
  hook_three_seconds: assert hook.includes(opening_words) and hook.omits(words_starting_at_or_after_3s)
  original_script_subtitles: assert srt_and_vtt_preserve_text_and_sentence_timing and word_times_keep_provider_precision
  dataset_shape_and_nulls: assert missing_metadata == null and video_and_input_error_rows_validate
  summary_reconciles_mixed_inputs: assert duplicate_inputs_and_carousel_children_reconcile_to_distinct_video_counts
  ```

- [ ] Run `./scripts/verify output`. Expect failures on schema, timing, and summary behavior.
- [ ] Implement the stable schema for `transcript`, sentence-level `segments`, `language`, `durationSeconds`, `wordCount`, `transcriptSource`, `wordLevelTimestamps`, `hook`, quality and partial details, and billing. Populate separate `metadata` with post, author, discovery profile, caption, publication date, duration, cover, audio or music, views or plays, likes, comments, carousel position, and other verified public fields. Include input-level errors, provenance, file references, reason and watchlist counts, and continuation details. Expose useful verified provider timing fields through the public contract and keep diagnostics internal.
- [ ] Run `./scripts/verify output`. Expect all cases to pass, including the schema and file-reference checks.
- [ ] Review and commit the output contract.

### Task 12 — Enforce full-price admission and recoverable settlement

**Files** · Private module `billing`, suite `billing`, `docs/engineering/evidence/billing.md`.

**Consumes** · `MediaPlan.durationSeconds`, `State`, the effective tier, run spending limit, and staged result. **Produces** · `quote(durationSeconds, tier, prices) -> ChargeQuote`, `reserve(quote, runBudget) -> ReservationDecision`, and `settle(stagedResult, reservation, context) -> ChargeReceipt` with confirmed events and settlement state.

- [ ] Verify how Apify exposes the run cap, effective event pricing, accepted counts, and idempotency behavior. Use the private test lane where ambiguity remains about interrupted settlement or platform-side enforcement. Select a recovery mechanism for the original authorized price and run budget. [Apify Pay Per Event](https://docs.apify.com/actors/monetize/pay-per-event) · [Charge API](https://docs.apify.com/api/v2/post-charge-run)
- [ ] Write these cases in the `billing` suite using the proposed prices.

  ```text
  quote_tiers_and_started_minutes: assert bronze_quote(180, 180.001, 181, 241) == [0.011, 0.014, 0.014, 0.017]
                                   assert platinum_quote(180) == 0.0085
  base_only_budget_defers: assert reserve(bronze_quote(181), 0.011) == deferred
                           assert reserve(bronze_quote(181), 0.014) == admitted
  free_result_releases_budget: assert free_outcome_releases_reservation and accepted_events == 0
  settlement_response_lost: assert accepted_event_is_counted_once and staged_result_is_recoverable
                            assert recovery_after_provider_retry_window_uses_persisted_billing_state
  ```

- [ ] Run `./scripts/verify billing`. Expect failures on quote, reservation, and recovery behavior.
- [ ] Implement preflight and per-run reservation accounting. Use the provisional base tiers FREE `$0.012`, BRONZE `$0.011`, SILVER `$0.010`, GOLD `$0.009`, PLATINUM/DIAMOND `$0.0085`, plus `$0.003` per started minute after 180 seconds. Keep pricing configurable. Charge only after a qualifying result is durable. Settle its full reserved price within the cap, preserve accepted counts on interruption, and reconcile before treating billing as complete.
- [ ] Run `./scripts/verify billing`. Expect all cases to pass, including original-run recovery and cross-run deduplication.
- [ ] Review and commit the billing changes and evidence.

### Task 13 — Integrate the Actor run, watchlists, and resume

**Files** · Private module `actor`, suite `actor`, `Dockerfile`, `.dockerignore`, `.actor/actor.json`.

**Consumes** · Tasks 05–12. **Produces** · `run(rawInput: JsonObject, context: RunContext) -> RunSummary` from the normal Apify entry point, with dataset rows, subtitle storage, receipts, and checkpoints.

- [ ] Write these cases in the `actor` suite using recorded replies and controlled state.

  ```text
  api_input_and_store_prefill: assert invalid_api_asr_calls == invalid_api_charges == 0 and submitted_prefill_has_transcript
  ordered_budget_stop_and_resume: assert first_unaffordable_and_later_asr_calls == 0
                                  assert completed_paid_refs_survive and resume_duplicate_rows == resume_duplicate_charges == 0
  watchlist_first_and_later_runs: assert first_run_delivers_existing_eligible and later_downloads_for_answered == 0
                                  assert no_speech_counts_as_answered and deferred_or_retryable_stays_eligible
                                  assert isNew_and_firstSeenAt_follow_first_delivered_answer
  batch_keeps_completed_results: assert successful_children_and_other_items_survive_an_item_failure
  cache_hit_and_refresh: assert cache_hit_asr_calls == cache_hit_charges == 0 and refreshes_coalesce
  duration_and_time_stops: assert above_limit_asr_calls == 0 and timed_out_run_checkpoints_pending_work
  ```

- [ ] Run `./scripts/verify actor`. Expect failures on the missing run orchestration.
- [ ] Wire input, discovery, filtering, canonical identity, watchlist/cache lookups, leases, media inspection, full-price reservation, quality, durable output, and settlement in that order where the data is available. Recheck identity after CDN resolution. Stop admission at the first uncovered price after earlier reservations settle or at the time limit. Retain completed rows and write the stop reason and continuation. Persist final watchlist answers and recover outstanding work from authenticated checkpoints.
- [ ] Run `./scripts/verify actor`. Expect all cases to pass.
- [ ] Build the private candidate on Apify from the public workflow.
- [ ] Verify the named cases on the candidate through API, Console prefill, and a native task/schedule. Check mixed batches, per-child billing, interruption, and result access with actual cloud storage.
- [ ] Review and commit the verified Actor integration.

### Task 14 — Optimize cloud performance and measure pricing

**Files** · Private `docs/engineering/evidence/performance.md`, `docs/engineering/decisions.md`, measured runtime and pricing configuration.

**Consumes** · Task 02's benchmark and Task 13's cloud candidate. **Produces** · Selected run settings and measured economics for the owner's launch pricing decision.

- [ ] Run ReelSaid on comparable single, mixed, profile, and large-batch inputs. Compare it with Steadyfetch and the other relevant baselines for quality, metadata, first-result latency, throughput, and completion rate. Include English alongside a representative range of supported languages and scripts.
- [ ] Test uncertainty that affects cost or reliability. Compare batch concurrency and resource allocation, URL versus transfer savings, state and storage overhead, quota scheduling, retries, and cold/warm behavior where the choice remains open. Track compute, data transfer, storage operations, build overhead, external ASR usage, and free or failed outcomes.
- [ ] Calculate contribution using actual Apify payout rules and metered run and external costs. Report paid-tier margins and representative mixes including FREE-plan usage. [Apify pricing and costs](https://docs.apify.com/actors/monetize/pricing-and-costs)
- [ ] Tune material gaps in quality, speed, reliability, and metadata against the comparable leader benchmarks. Present candidate prices and measured margins. The owner will select final prices immediately before launch in Task 17.
- [ ] Apply the selected runtime settings and keep the pricing evidence available for release.
- [ ] Run the applicable suites and representative Apify cloud cases with those settings. Document comparative performance and the modeled contribution margin before packaging.
- [ ] Commit the reproducible measurements and decisions.

### Task 15 — Create the public listing, brand, and workflow templates

**Files** · Public `README.md`, `assets/reelsaid-logo.png`, `examples/api/{reel,profile,dataset,output}.json`, `examples/n8n/reelsaid.json`, `examples/make/reelsaid.blueprint.json`, `examples/zapier/README.md`. Private `.actor/input_schema.json` and sample/output configuration, suite `package`.

**Consumes** · Verified schemas, example Reel, product results, and measured billing behavior. **Produces** · Public packaging ready for Store, GitHub, native MCP, and automation users. Final numerical prices follow the owner's decision in Task 17.

- [ ] Draft the Store metadata, GitHub description and topics, README, and MCP-facing copy using search intent from Google, the Store, GitHub, and agent discovery. Cover input modes, filters, outputs, timestamp and subtitle usage, watchlists, resume, errors, billing, and the real prefill. Use the agreed brand strings and public Whisper Large-v3 description. Include a genuine sanitized sample output.
- [ ] Create the ReelSaid logo and visually inspect it at Store icon size and in the listing composition. Export the supported PNG. Verify the brand is recognizable and the asset renders on the intended surfaces.
- [ ] Build runnable Apify API examples, an n8n workflow, and a Make blueprint. Document Zapier setup through its native Apify integration. The owner deferred authoring a Zapier template to a later session. [Apify n8n](https://docs.apify.com/integrations/n8n) · [Make blueprints](https://help.make.com/blueprints) · [Apify Zapier](https://docs.apify.com/integrations/zapier)
- [ ] Import the n8n template into a fresh workflow with a test connection and verify a transcript reaches the next step. Verify the Make blueprint and API contract in the package suite. The owner deferred authenticated Make import and execution.
- [ ] Add `./scripts/verify package` cases for schema/example consistency, public links, branding, and credential-free artifacts.
- [ ] Run `./scripts/verify package` through the public verification workflow. Expect all cases to pass. Review the public assets and MCP copy for the intended product details and visibility.
- [ ] Commit the verified package.

### Task 16 — Verify the on-demand release workflow and private build

**Files** · Public `.github/workflows/release.yml` and `.github/workflows/verify.yml`. Private `Dockerfile`, `.dockerignore`, suite `release`, `docs/engineering/evidence/release.md`.

**Consumes** · The verified private source revision and public package revision. **Produces** · A reproducible private Apify candidate and the on-demand production release path.

- [ ] Choose and test the source delivery and trigger wiring from the viable methods in the spec. Start builds and scheduled verification from the public repo. Pin source and package revisions and apply the same approved README and metadata to the Store. Use Apify CLI for supported actions and the API for pricing, visibility, and other fields the CLI lacks. [Apify deployment](https://docs.apify.com/actors/development/deployment) · [Apify builds](https://docs.apify.com/actors/development/builds-and-runs/builds)
- [ ] Add `./scripts/verify release` checks for candidate revision, sanitized logs and artifacts, source visibility, and successful default-input output.
- [ ] Verify Apify build cache behavior on successive builds of the selected Docker layout. Check the tested revision, final image, dependency and media tooling, and authorized runtime secrets. Exercise the trusted release workflow against a private candidate, including failed build and rollback behavior. Keep source and source-bearing Docker layers on authorized surfaces.
- [ ] Run `./scripts/verify release` and the equivalent Store default-input test on the private candidate. Expect a genuine transcript in the default dataset within the Store's test window. Verify the conditions that support Reliability and Ease of use, native API/MCP and schedules, billing and resume, source visibility, and public logs/artifacts/caches. [Store testing](https://docs.apify.com/actors/publishing/test)
- [ ] Record the evidence and get the Superpowers release review.
- [ ] Commit the verified release workflow and evidence with the exact candidate identifiers.

### Task 17 — Publish the verified candidate on demand

**Files** · Private `docs/engineering/evidence/release.md` and public release metadata.

**Consumes** · Task 16's verified candidate. **Produces** · A live Store Actor, linked public repository, and recorded public verification.

- [ ] Get the owner's final numerical prices, apply them, and verify the effective price table and spending cap on the private candidate. Use the on-demand workflow to publish when requested. Check the private source setting, final pricing and build identity, and that the Store package matches the public revision.
- [ ] Verify the live Store URL and native API and MCP discovery, real prefill and Store test status, public example and template links, result and subtitle access, and public repository discoverability. Verify the periodic check is scheduled in the public repository. Inspect the published listing and brand asset as a visitor. [Apify publishing](https://docs.apify.com/actors/publishing/publish) · [Apify MCP quickstart](https://docs.apify.com/agents/quickstart)
- [ ] Record the release, observed results, and links. Resolve regressions through the verified workflow and commit the release evidence.
