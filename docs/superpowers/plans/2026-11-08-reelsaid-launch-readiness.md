# ReelSaid Launch Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ReelSaid ready for a measured competitive launch with a fast Standby API, runner-local monitoring, and a Store package built around real use cases.

**Architecture:** Keep the existing Python transcription pipeline and native Apify batch interface. Add an interactive Standby entry point with caller-scoped processing and an OpenAPI contract. The public GitHub repository runs verification and release operations against approved private source revisions.

**Tech Stack:** Python, Apify SDK and CLI, pytest, Docker, GitHub Actions, and the existing Groq-backed transcription pipeline. Select the HTTP server, supported Standby accounting integration, and email transport in their owning tasks.

**Spec:** [Approved ReelSaid launch readiness design](../specs/2026-11-08-reelsaid-launch-readiness-design.md), revision `c4e0702`. This plan takes the release forward from the [verified private candidate](../../engineering/evidence/release.md) and replaces Task 17 of the [original plan](2026-11-07-reelsaid-implementation.md).

## Global Constraints

- Use the owner's existing native execution choice with `superpowers:executing-plans`. Execute Tasks 01 through 12 in order with one active task. Finish the current task's evidence, verification, and commit before opening the next. A candidate commit for a cloud check belongs to the current task.
- Conduct research, live comparisons, and experiments in the owning task. Test choices whose outcomes can change the implementation. Preserve the established ReelSaid input, multilingual, quality, privacy, budget, and settlement contracts.
- Apply the installed official `apify-actor-development` skill. Pass `--user-agent apify-agent-skills/apify-actor-development` to Apify CLI commands used for this work. Use `Actor.log` for runtime logging, with sanitized structured values.
- Run Actions in the public repository with pinned, owner-authorized private source. Keep private source, credentials, raw competitor results, fixture details, signed links, and diagnostics on authorized surfaces. Keep the private repository free of Actions jobs.
- Use the agreed brand strings and public Whisper Large-v3 description. Write product copy in clear international English. Use GPT-6.1 Sol Max for agent reviews, including the review before public release.
- Require evidence for first usable transcript and total time against the fastest quality-equivalent competitors. Keep a remaining speed gap in the current task until it is resolved or the owner makes an explicit decision based on the measured tradeoff.
- Keep final numerical pricing for the owner's decision in Task 12. Public release is on demand and includes the approved Actor Tasks.

## Review Focus

- A missing body, empty JSON, or misspelled source field cannot start the real Store example or cause a charge. Tasks 01 and 07 test the runtime and HTTP paths.
- Concurrent Standby callers cannot spoof the trusted identity or read each other's cache, output, or receipts. Tasks 06 and 07 test platform identity and request isolation.
- A request budget that covers the base event alone stops before transcription, and a lost acknowledgement or a repeated request cannot cause a second debit. Task 07 covers both.
- An error placeholder, cached answer, or shorter workload cannot win a fresh, like-for-like benchmark. Task 03 pins the comparison rules.
- An early workflow failure or runtime timeout reaches the owner by email and keeps the check failed. Task 02 verifies failure handling and alert delivery with sanitized content.

## Files and interfaces

| Location | Responsibility |
| --- | --- |
| Private `src/reelsaid/__main__.py`, `actor.py`, `quality.py`, `billing.py`, `state.py` | SDK lifecycle, shared processing, quality, caller state, and settlement. Reuse the existing `run(raw: JsonObject, context: ActorContext) -> RunSummary` contract. |
| Private `src/reelsaid/standby.py`, `.actor/web_server_schema.json`, `.actor/actor.json` | Interactive request handling, SDK server lifecycle, and the served HTTP contract. |
| Private `scripts/check-runner.sh`, `scripts/ci-verify`, `tests/test_runner.py`, `tests/test_monitoring.py`, `tests/test_standby.py` | Runner-local exercise, failure notification tests, and endpoint regressions. |
| Private `scripts/benchmark-market.py`, `scripts/benchmark-reelsaid.py`, `scripts/summarize-performance.py`, `tests/automation/test_market_benchmark.py` | Shared observation, competitor and candidate runs, and comparable results. |
| Private `docs/engineering/evidence/launch-` files and `probes/standby/` | Research decisions, benchmark evidence, and restricted cloud probe references. |
| Public `.github/workflows/verify.yml`, `.github/scripts/`, `.github/workflows/release.yml` | Pinned verification, twice-daily runner smoke, failure notification, and on-demand promotion. |
| Public `README.md`, `llms.txt`, `store/listing.json`, `store/tasks.json`, `examples/api/` | Product copy, discovery fields, launch Task definitions, and tested examples. |

### Task 01 — Run the actual Actor code on a GitHub runner

**Files** · Private `src/reelsaid/__main__.py`, `scripts/check-runner.sh`, `scripts/ci-verify`, `tests/test_runner.py`, `docs/engineering/evidence/launch-monitoring.md`. Public `.github/workflows/verify.yml` and existing checkout/verification helpers.

**Produces** · `bash scripts/check-runner.sh batch` and manual `check=runner-health`. The command runs the approved code with Apify's local SDK storage, returning success only after it verifies the written output.

- [ ] Verify the installed skill's local CLI workflow and production dependency setup during this task. Select a deterministic source fixture and a representative live public source that exercise retrieval and transcription from the runner.
- [ ] Add `test_local_apify_run_writes_default_dataset` and `test_local_invalid_input_is_free`. Assert `row["status"] == "success"` and `row["transcript"].strip()` for the valid fixture. Assert `NO_SOURCE` for absent or empty input, `UNKNOWN_INPUT` for a misspelled field, and `row["charged"] is False` and zero provider calls in all three invalid cases.
- [ ] Run `./scripts/verify runner`. Expect the new CLI runtime case to fail at the current cloud-only guard.
- [ ] Implement the local output and execution path in `main()` using the same `ActorContext` and `run()` as production. Use fresh local storage and explicitly scoped test credentials. Run the actual entry point through `apify run` with the skill's CLI flag. Make the runner verification independent of the Apify deployment token and prove it does not submit an Apify Actor run.
- [ ] Run `./scripts/verify runner` and dispatch `runner-health` from the public repository with an exact private revision. Expect schema-valid local results for the fixtures and a genuine result from the live probe. Record the runner evidence and commit.

### Task 02 — Schedule the runner check and verify urgent email

**Files** · Public `.github/workflows/verify.yml` and the notification wiring selected in this task. Private `tests/test_monitoring.py`, `docs/engineering/evidence/launch-monitoring.md`.

**Consumes** · Task 01's `runner-health` command. **Produces** · The trusted 12-hour schedule and one sanitized owner alert per failed check.

- [ ] Check current GitHub scheduling and notification behavior and the authorized email options. Pick a route that can actually deliver the requested alert to the owner. Confirm a recipient through available authorized configuration, or ask for the specific missing email connection when needed.
- [ ] Add `test_failure_alert_before_runtime_starts` and `test_runtime_failure_alert_preserves_failure`. Assert one alert with the GitHub run link and a safe stage label for checkout failure and for a runtime failure or timeout. Assert zero alerts on success and that a mail error cannot turn a failed check green.
- [ ] Run `./scripts/verify monitoring`. Expect the unwired cases to fail.
- [ ] Point the scheduled check at the approved runner-local revision using `PERIODIC_SOURCE_REVISION`. Set two scheduled times 12 hours apart. Wire the selected email route with secret references and trusted event conditions, including failure that occurs before the private script starts. Use explicit cloud verification for release.
- [ ] Run `./scripts/verify monitoring` and `actionlint` on the public workflows. Dispatch successful and controlled failure cases through the public workflow. Verify actual delivery to the owner, zero alerts for success, and clean public logs. Record the schedule and verified delivery path and commit.

### Task 03 — Freeze the comparison protocol and observer

**Files** · Private `scripts/benchmark-market.py`, `scripts/summarize-performance.py`, `tests/automation/test_market_benchmark.py`, `tests/fixtures/market-reels.json`, `docs/engineering/evidence/launch-market.md`. Public verification dispatch and private `scripts/ci-verify` as needed for `check=compare`.

**Produces** · A private campaign matrix and observation records with `actor`, `surface`, `case`, `cacheCondition`, `quality`, `firstUsableSeconds`, `totalSeconds`, `completedVideoIds`, and `settledChargeUsd`. Keep raw run and case evidence restricted.

- [ ] Inventory current transcription competitors through Store, MCP, and search, starting with Steadyfetch. Identify overlapping native and Standby products. Find reference clips and establish independently checked text and speech verdicts for multilingual, clear, quiet, short, speech-over-music, silence, and music-only cases.
- [ ] Freeze the equivalence criteria and matched matrix before ranking speed. Use language-appropriate text accuracy, missing openings or endings, hallucinations, repetition, timing, and usable coverage. Record equal workload, requested features, cold and warm conditions, how first usable output is observed, and when billing is settled.
- [ ] Preserve `test_error_text_does_not_count_as_transcription`. Add `test_fresh_comparison_rejects_cached_result` and `test_rejects_shorter_workload`. Assert both case pairs are excluded from the matched comparison.
- [ ] Run `python3 -m unittest discover -s tests/automation -p test_market_benchmark.py`. Expect the new comparison cases to fail at the missing qualification checks.
- [ ] Extend the existing observer and comparison summary to write the matrix and measurements, including error responses and terminal billing. Add a trusted dispatch for the private harness. Rerun the benchmark tests, verify the public wrapper with a synthetic private marker, and commit the observer and frozen protocol.

### Task 04 — Measure competitor behavior and the current ReelSaid baseline

**Files** · Private `scripts/benchmark-market.py`, `scripts/benchmark-reelsaid.py`, `docs/engineering/evidence/launch-market.md`.

**Consumes** · Task 03's matrix and observer. **Produces** · A quality-ranked baseline, the fastest qualified peers by surface and timing metric, and a behavior report with observed, inferred, and unknown processing evidence.

- [ ] Dispatch `check=compare` for the current ReelSaid native baseline and competitors' supported native and Standby surfaces. Use matched single and batch requests and repeat comparisons where platform variance could change the ordering. Record the usable workload and settled usage. Qualify timing comparisons only for cases that delivered the matched workload.
- [ ] Send the agreed empty object, missing input where supported, misspelled field, malformed URL, and mixed-source cases. Map equivalent fields for each product. Record status, example substitution, usable outputs, and settled charges. Keep the run spending cap safe for controls that may trigger a competitor example.
- [ ] Compare the known audio pairs. Use explicit documentation or exposed traces for processing-order claims. Report compatible outcomes and timings as evidence of behavior and mark the processing order unknown when that is all the surface reveals.
- [ ] Present the strongest observations and the implications for ReelSaid's policy to the owner while this task is active. Run the comparison summary on the restricted evidence and verify each winner meets Task 03's quality and workload checks. Commit the results and the selected targets.

### Task 05 — Improve native speed and tune the audio decision from evidence

**Files** · Private `src/reelsaid/quality.py`, `src/reelsaid/actor.py`, measured hot-path modules, `scripts/benchmark-reelsaid.py`, `tests/test_quality.py`, `tests/test_actor.py`, `docs/engineering/evidence/launch-performance.md`.

**Consumes** · Task 04's quality baseline and gaps. **Produces** · A measured native candidate with a documented quality strategy and stage timings kept in restricted evidence.

- [ ] Time the existing candidate from request to first usable result and completion. Isolate bottlenecks in retrieval, preflight, provider work, validation, ordering, storage, and startup. Compare pre-ASR, post-ASR, and conditional policies on the same reference cases where evidence leaves a real tradeoff. Explain the proposed change and its observed effect to the owner during this task.
- [ ] Add a focused regression for each measured behavior change and verify red before implementation. Pin `test_audio_policy_preserves_free_and_mixed_speech_outcomes` for a changed audio policy with assertions that silence and music-only results have zero events, mixed speech produces usable text, and the 20% boundary still qualifies while unresolved defects above it are free. Include the existing quality, billing, and resume cases in the green check.
- [ ] Implement only the changes supported by the measured tradeoff. Keep full-quote admission, ordered delivery, original language, recovery, and protected diagnostics. Run `./scripts/verify quality`, `./scripts/verify actor`, and `./scripts/verify billing`.
- [ ] Rerun the matched fresh cloud cases against the qualified targets. Verify quality, first usable latency, total time, and cost. Keep a remaining gap in this task or record the owner's measured decision. Commit the selected path and evidence.

### Task 06 — Prove the Standby platform contract on a private deployment

**Files** · Private `probes/standby/`, `docs/engineering/evidence/launch-standby.md`.

**Consumes** · Task 04's observed Steadyfetch workflow and Task 05's shared runtime. **Produces** · The verified path and request/response contract for interactive transcription, caller authentication and accounting rules, and a named server choice with verified SDK lifecycle.

- [ ] Read the skill's Standby reference, current Apify Standby and pay-per-event docs, and the relevant Steadyfetch Standby evidence. Compare authentication, caller identity, request shape, synchronous responses, errors, and how the stable URL differs from the per-run server URL. Choose the useful user-facing behaviors for ReelSaid's own contract.
- [ ] Use an isolated private probe on Apify to verify the SDK-provided port, readiness header and status, stable hostname, local start, and repeated requests. Establish the trusted authentication and caller identity boundary, including forged client headers and calls from separate authorized caller contexts.
- [ ] Prove the supported request billing and storage behavior on the isolated test deployment. Verify charge attribution, budget enforcement, zero-charge controls, retry behavior, and caller-scoped output. Check current Store test and quality signal behavior when Standby is enabled.
- [ ] Record the tested interface, required auth and accounting inputs, verified server stack, and probe rollback. If evidence reveals a conflict that changes a charge or privacy promise, bring the observed behavior and viable choices to the owner within this task. Commit the verified probe and contract.

### Task 07 — Implement and verify the interactive Standby API

**Files** · Private `src/reelsaid/standby.py`, `src/reelsaid/__main__.py`, applicable shared runtime modules, `.actor/actor.json`, `.actor/web_server_schema.json`, `pyproject.toml`, `uv.lock`, `tests/test_standby.py`, `scripts/check-runner.sh`, `docs/engineering/evidence/launch-standby.md`.

**Consumes** · Task 06's proven platform and HTTP contracts. **Produces** · `create_app(resolve_context)` and `async serve_standby()` in `reelsaid.standby`, the documented JSON endpoint, and `check-runner.sh standby`.

- [ ] Add `test_readiness_uses_no_processing`, `test_empty_or_invalid_request_has_no_side_effect`, `test_spoofed_identity_cannot_access_other_caller`, and `test_full_quote_and_repeat_settle_once`. Assert `GET /` with `x-apify-container-server-readiness-probe` returns HTTP 200 with zero ASR and charge calls. Assert structured errors and zero work for missing, empty, or malformed body and wrong source field. Assert no cross-caller cache, result, or receipt access, zero ASR for a budget below the full quote, and one debit across an overlapping request and a lost acknowledgment. In `test_logs_omit_request_data_and_credentials`, assert the logs contain the safe outcome code and omit the supplied token, signed media URL, and transcript canaries.
- [ ] Run `./scripts/verify standby`. Expect the new endpoint and logging cases to fail for the missing service.
- [ ] Implement the HTTP service with Task 06's server and trusted context resolver. Reuse `run()` and existing per-video media, quality, storage, and settlement contracts where they apply. Bind to the SDK port. Keep request input separate from Actor initialization and use `Actor.log` for sanitized outcomes and timing. Enable `usesStandbyMode` and bind the OpenAPI v3 file through `webServerSchema`.
- [ ] Validate every served route against the schema. Run `./scripts/verify standby` and the skill's schema validation. Exercise local readiness and transcription through `apify run`. Add both to the runner check and repin `PERIODIC_SOURCE_REVISION` after a successful trusted dispatch.
- [ ] Deploy the exact private candidate and repeat all exposed endpoint checks, including authenticated requests, unauthenticated errors, repeated requests, caller isolation, and the batch referral response. Verify the native run and stable Standby routes, inspect public log isolation, and commit.

### Task 08 — Verify the fastest equivalent native and Standby results

**Files** · Private `scripts/benchmark-reelsaid.py`, `scripts/summarize-performance.py`, `docs/engineering/evidence/launch-performance.md`, and the measured hot path if tuning is needed.

**Consumes** · Tasks 03–05 and 07. **Produces** · A matched comparison for the release candidate across both surfaces.

- [ ] Run the approved comparable cases from the same observer for the candidate and strongest qualified peers. Separate cold and warm Standby traffic, matching the comparable state of each service. Report both first usable and total time and the quality and completed workload alongside them.
- [ ] If a measured bottleneck remains, add its focused regression, verify red, and test the justified change with the same inputs and cost accounting. Use the same candidate revision for both final surface checks.
- [ ] Verify the candidate beats each relevant quality-equivalent timing target or record the owner's explicit decision on the remaining gap. Run `./scripts/verify all` and the final private cloud comparison. Record what the results support and commit.

### Task 09 — Rewrite the public product experience and choose discovery metadata

**Files** · Public `README.md`, `llms.txt`, `store/listing.json`, `examples/api/standby.json`, and related API examples. Private `.actor/actor.json`, `.actor/input_schema.json`, `tests/test_package.py`, `docs/engineering/evidence/launch-package.md`, and README staging if Store rendering requires an adaptation.

**Produces** · An approved Store and GitHub package and a recorded inventory of applicable tags, categories, topics, and agent-facing fields.

- [ ] Audit comparable listings and docs using the official skill's README guidance. Compare what the first screen helps the visitor do, use cases, example result, input explanation, pricing placement, and API detail. Inventory the full applicable metadata and evaluate each plausible label against use-case and search intent.
- [ ] Add `test_package_has_no_code_first_run_and_standby_example`. Assert the primary no-code trial comes before code, the public example validates against the matching contract, and the verified Whisper Large-v3 and brand language is present.
- [ ] Run `./scripts/verify package`. Expect the new test to fail for the missing Standby example.
- [ ] Write product-first English with a clear action and real outcome. Organize technical detail for developers and agents, including Standby auth, response shape, and the native batch route. Explain the stable Standby address and the per-run Container Web Server address. Apply the selected metadata, record why credible alternatives were passed over, and verify the rendering on GitHub and the private Store candidate. Bind the approved Store README to the package revision used for deployment.
- [ ] Run the package suite, check the public links, preview the actual first-run experience and agent-visible descriptions, and commit both repositories' package changes.

### Task 10 — Prepare and test discoverable public Actor Tasks

**Files** · Public `store/tasks.json` and Task links in the package. Private `scripts/prepare-tasks.sh`, `tests/test_launch_tasks.py`, `docs/engineering/evidence/launch-package.md`.

**Consumes** · Task 09's package and search/use-case audit. **Produces** · Versioned Task definitions and tested private Apify tasks with stable identities. Each definition has a slug, title, description, and runnable input.

- [ ] Read the owner's [Apify Actor Task examples](https://blog.apify.com/actor-task-examples/) reference and current publication guidance. Choose distinct cases from observed demand, product fit, and value to a user or agent.
- [ ] Add `test_task_examples_use_explicit_valid_sources` and `test_task_sync_is_idempotent`. Assert every Task passes the Actor input contract, has a distinct slug and purpose, and preparing the same definition twice preserves its identity and avoids duplicate creation.
- [ ] Run `./scripts/verify launch_tasks`. Expect failures at the missing definitions and preparation entry point.
- [ ] Write and stage the Task definitions. Implement `scripts/prepare-tasks.sh` to create or reconcile the private tasks from the approved package. Use the CLI for supported actions and the API for the remaining fields. Run each with its real example and verify the promised outcome.
- [ ] Run `./scripts/verify launch_tasks` and the package suite through trusted verification. Record verified private Task identities and publication order and commit.

### Task 11 — Rehearse the full private candidate and obtain release review

**Files** · Private `scripts/release-actor.sh`, `tests/test_release.py`, `docs/engineering/evidence/release.md`. Public `.github/workflows/release.yml` as needed for the verified release path.

**Consumes** · The verified runtime, runner monitoring, package, and private tasks. **Produces** · Exact private and public revisions, build and Task identities, a tested promotion path, and a reviewed release candidate.

- [ ] Add `test_release_rejects_unverified_task_or_schema`. Assert a changed Task definition or OpenAPI schema prevents promotion.
- [ ] Run `./scripts/verify release`. Expect the promotion guard test to fail.
- [ ] Bind the OpenAPI schema, package, and Task definitions to the candidate receipt and verify them at promotion. Rerun `./scripts/verify release` and expect all cases to pass.
- [ ] Rehearse the combined candidate from the public workflow. Verify native prefill, invalid input, Standby endpoint behavior, native MCP, Task examples, and rollback. Confirm current Apify reliability and usability signals, source visibility, and public log, artifact, and cache isolation.
- [ ] Confirm the pinned runner-local workflow with both entry points and verified email failure handling. Record the final timing and cost evidence with the exact candidate identifiers.
- [ ] Obtain the Superpowers whole-branch release review from GPT-6.1 Sol Max. Resolve material findings with the owning checks, then record the reviewed candidate and commit.

### Task 12 — Apply the owner's prices and publish on demand

**Files** · Private `docs/engineering/evidence/release.md` and the approved release configuration. Public verified Store and Task package.

**Consumes** · Task 11's exact reviewed candidate and the owner's last-stage price and release decision. **Produces** · The live Actor and discoverable published Tasks with verified pricing and entry points.

- [x] Present the measured operating cost and pricing implications. Get the owner's final numerical prices. Apply the selected effective schedule privately, verify the tiers, charged events, zero-charge controls, and full-quote spend behavior for native and Standby requests, and pin the verified pricing digest.
- [x] On the owner's launch request, run the on-demand workflow for the exact candidate and publish the approved Tasks in the verified order. Confirm the effective prices, source visibility, and candidate identity.
- [x] Verify the visitor-facing Store page, GitHub links, Task discovery, real examples, native API and MCP, and live Standby endpoints. Confirm the scheduled runner and the supported Store quality signals. Record the release and commit.
