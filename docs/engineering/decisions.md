# ReelSaid engineering decisions

## Repository boundary

The public packaging repository `aimansour/reelsaid` owns Actions runs. The private source repository `aimansour/reelsaid-core` has Actions disabled. A dedicated read-only SSH deploy key grants the public verifier access to the private source. Store the key, repository locator, and Apify authentication in GitHub Actions secrets.

The owner dispatches verification from the public default branch with a full commit SHA. The workflow fetches the private `main` tip and verifies its SHA before executing. Private output is suppressed at the public runner boundary. Public verification returns a generic success or failure message and uses ephemeral GitHub-hosted runners. Future tasks will store their detailed run evidence on trusted surfaces.

Use Apify CLI 1.11.0 for the initial account check. This version is for automation and does not choose the Actor's runtime.

## Actor runtime and implementation bindings

Use Python 3.12, the official Apify SDK 4.2 series, and curl_cffi 0.17 for the measured HTTP paths. Use FFprobe and FFmpeg only where media inspection, preparation, or repair needs them. Use uv for dependency locking and pytest for the task suites. The measured Node fetch control received HTTP 200 without media for the same public short Reel. Python and curl_cffi already handled the cloud profile, detail, CDN, and Groq requests. Retain compact Docker layers and choose final resource settings from Task 14.

Use `src/reelsaid/contracts.py` for shared typed records. `JsonObject` is a JSON object mapping, IDs are opaque strings, and `RunContext` carries authenticated run and tenant identity, deadline, and authorized platform clients. Use async boundaries for HTTP, storage, and Actor runs. Pure parsing, presentation, and price quoting remain synchronous.

| Task | Native source and callable | Test file |
| --- | --- | --- |
| 05 | `src/reelsaid/input.py`, `parse_input(raw: JsonObject) -> InputPlan`, shared `Outcome[T]` in `contracts.py` | `tests/test_contract.py` |
| 06 | `src/reelsaid/discovery.py`, `async discover(plan: InputPlan, context: RunContext) -> Discovery` | `tests/test_discovery.py` |
| 07 | `src/reelsaid/media.py`, `async inspect_media(ref: VideoRef, context: RunContext) -> Outcome[MediaPlan]` | `tests/test_media.py` |
| 08 | `src/reelsaid/state.py`, async `State.lookup`, `acquire`, `lookup_answer`, `record_answer`, `load_checkpoint`, and `save_checkpoint` with the task's contract | `tests/test_state.py` |
| 09 | `src/reelsaid/groq.py`, `async transcribe(media: MediaPlan, options: TranscriptOptions, context: RunContext) -> Outcome[TranscriptDraft]` | `tests/test_groq.py` |
| 10 | `src/reelsaid/quality.py`, `async evaluate_video(media: MediaPlan, options: TranscriptOptions, context: RunContext) -> Outcome[TranscriptResult]` | `tests/test_quality.py` |
| 11 | `src/reelsaid/output.py`, `to_row(ref: VideoRef | InputRef, outcome: Outcome[TranscriptResult], billing: BillingFields) -> DatasetRow`, `subtitle_files(result: TranscriptResult) -> SubtitleFiles` | `tests/test_output.py` |
| 12 | `src/reelsaid/billing.py`, `quote(duration_seconds: Decimal, tier: Tier, prices: Prices) -> ChargeQuote`, `reserve(quote: ChargeQuote, run_budget: RunBudget) -> ReservationDecision`, `async settle(staged_result: StagedResult, reservation: Reservation, context: RunContext) -> ChargeReceipt` | `tests/test_billing.py` |
| 13 | `src/reelsaid/actor.py`, `async run(raw_input: JsonObject, context: RunContext) -> RunSummary`; entry point `src/reelsaid/__main__.py` | `tests/test_actor.py` |

Use `pyproject.toml` and `uv.lock`. The suite command is `uv run --locked pytest -q tests/test_<suite>.py`, with an optional `-k <case>`. Expose it as `./scripts/verify <suite> [case]`. Use `uv run --locked pytest -q` for the complete deterministic suite.

Use direct media URLs as the provisional ASR transport. Upload mono FLAC when media inspection or targeted repair has already prepared an audio track or a direct URL fails. The independent speech signal remains mandatory for suspect output. The measured WebRTC VAD signal is a candidate for Task 10. Choose production thresholds from a wider reference set.
