# ReelSaid launch readiness

This design extends the [ReelSaid product design](2026-11-07-reelsaid-design.md) and the verified private candidate. It covers the competitive standard for release, interactive transcription through Apify Standby, twice-daily monitoring, and a Store experience for people and AI agents. The brand is **ReelSaid**, the Store title is **ReelSaid — Instagram Reels Transcript API**, and the tagline is **Every Reel, in Words.**

## Product goals

Help someone turn a public Instagram video into words they can read, reuse, search, subtitle, or send into a workflow. A marketer, business owner, or creator should be able to try it from the Store. Developers and agents should be able to find the right entry point, understand its contract, and use the result without guessing.

For launch readiness, demonstrate that ReelSaid beats the fastest quality-equivalent competitors on both time to first usable transcript and total completion time. A release decision also considers useful results delivered, quality, coverage, and cost per usable result. Apply the same standard to the native run and the interactive experience, with comparable traffic and cache states. A remaining speed gap calls for further optimization or an explicit release decision from the owner based on the measured tradeoff.

## Approaches

The owner selected **Standby for interactive transcription and the existing Apify run interface for batches**. A caller uses the stable Standby URL for an individual video they want transcribed in the current request. Profiles, collections, multi-video batches, scheduling, and continuation use native Actor runs and tasks. The Store and docs guide each caller to the right entry point. Study the customer-facing Standby experience at [Steadyfetch](https://apify.com/steadyfetch/instagram-reel-transcript-scraper) and match the useful parts of its documented and observed workflow. Use ReelSaid's own OpenAPI contract and established result conventions for client integrations.

The other approach considered was a unified HTTP entry point that returns a result for interactive requests and creates a background Apify run for longer requests. It gives clients one entry point and adds job submission, status, and authentication behavior to the HTTP surface. The selected split gives the interactive path its own response contract and uses native Apify jobs for batch lifecycle.

## Competitive evidence and quality

Identify current competitors through the Store and other relevant discovery sources. Include Steadyfetch and the strongest overlapping products, with enough coverage to find the fastest quality-equivalent alternative for each measured path. A faster competitor qualifies only on evidence from the same reference clips and comparable output. The speed target applies to whichever competitors actually set the bar for first result and completion. If different competitors lead on those measures, compare against both.

Use matched single and batch cases and independently checked transcripts. Cover multiple supported languages, clear speech, short and quiet speech, speech over music, silence, and music without speech. Evaluate text accuracy, missing opening and closing speech, repeated or invented text, timing, usable-result coverage, and metadata where it affects comparability. Define what counts as equivalent quality before choosing a speed winner. Measure from the caller's request until a usable transcript becomes available and until comparable work finishes. Distinguish a dataset row, an HTTP response, an error, and a placeholder. Record cold and warm behavior, cache state, repeat variability, and completed workload so an early stop or cached result cannot win a fresh run comparison.

Determine what each competitor actually does with an empty object, absent input where the API permits it, a misspelled field, a bad URL, and mixed valid and invalid inputs. Record whether it rejects, substitutes an example, processes valid items, returns structured errors, or charges. Keep ReelSaid's real example intentional in the Console and published tasks. Empty and invalid input must follow the validated error or mixed-input contract and carry no charges for invalid items.

Use paired media with known speech and music content to compare competitor outcomes, billing, latency, and any documented or exposed processing evidence. Separate confirmed processing order from behavioral clues and unknowns. Compare plausible before-ASR, after-ASR, and conditional validation strategies in ReelSaid when the evidence leaves a meaningful speed, cost, or quality tradeoff. Preserve speech over music, free outcomes for verified silence and music-only media, independent checks for omissions or fabricated speech, and the existing billing boundary at exactly 20% affected. Change ReelSaid's processing sequence only when the measured tradeoff supports it. Share the observed competitor behavior, the strength of the inference, and the proposed change with the owner during the work so they can steer the decision.

## Interactive Standby API

Enable Standby on ReelSaid. Use the platform's stable Standby address for persistent request handling and document the per-run Container Web Server address separately. Start the server on the port provided by the Apify SDK and keep it available across requests. Support Apify's readiness probe with `GET /`, the expected probe header, and a lightweight HTTP 200 response.

An authenticated transcription endpoint accepts per-request HTTP input for one selected video. Use a JSON request body for the transcription request. Apply ReelSaid's existing validation, original-language text, timing and available metadata conventions, and quality decisions for interactive video requests. Give callers a clear native-run path when they submit work intended for batches. Use Apify's supported authentication and caller identity so requests, account history, cache, output access, spend decisions, and charges are scoped to the actual caller. Preserve the verified eligibility, full-quote budget, and duplicate charge rules across the two entry points. Use the platform's supported request and billing behavior to establish those guarantees before public availability.

Define OpenAPI v3 through `webServerSchema` and cover every exposed endpoint, including readiness, methods, authentication, input, output, and errors. Provide calls people can use from the Store and an HTTP client. Validate each endpoint locally through the Apify environment and on an authorized Apify deployment, including unauthenticated and malformed requests, repeated requests to the same instance, and isolation between callers. Use Apify's native MCP for agent discovery and workflow access.

Use the Python SDK's `Actor.log` for product and operational logs. Log outcomes, request correlation, and timing with useful detail for diagnosis. Keep credentials, signed media links, private implementation details, transcripts, and raw request data out of public logs and alert messages. Keep the private source and build diagnostics on authorized surfaces.

## GitHub monitoring and urgent email

Every 12 hours, a trusted job in the public GitHub repository checks out an approved private revision and runs ReelSaid's own runtime on the GitHub-hosted runner. Exercise the same processing code and production dependencies locally on the runner with representative inputs, including the Standby readiness and transcription paths. Use predictable fixtures for regressions and representative live checks for the upstream dependencies that matter. Keep Apify cloud integration verification as a separate release check. Keep the private source, fixture details, logs, caches, artifacts, and credentials within the authorized boundary.

Send a prompt, sanitized email to the owner when the scheduled check fails. Include the failed stage and a link to the GitHub run so the owner can investigate. Verify delivery with a controlled failure and confirm the success path stays quiet. Choose the email delivery mechanism and schedule times from supported options during implementation.

## Store, documentation, and public tasks

Review how competitors order their listings, first-run instructions, examples, use cases, field explanations, billing, and integration details. Identify omissions and sections that would serve people better elsewhere on the page. Use the findings and the official Apify Actor Development skill to write clear, persuasive English. Lead with the job someone came to do, show a real result, and make the first action easy without requiring code. Put complete API, schema, integration, and advanced guidance where a developer or agent can find it. Keep the product copy consistent across Apify, GitHub, and MCP, including the agreed public description of Whisper Large-v3. Use measured claims and product-facing details.

Review the full set of applicable Apify discovery fields and labels, task metadata, and GitHub topics. Choose the most relevant combinations for the actual use cases and search intent on Apify Store, Google, GitHub, and MCP. Record why plausible labels were selected or set aside. Check the resulting listing and documentation as a newcomer, a developer, and an agent selecting an Actor.

Prepare publishable [Apify Actor Tasks](https://blog.apify.com/actor-task-examples/) with distinct, useful outcomes and thoughtfully written titles, descriptions, inputs, and examples. Choose the use cases based on observed demand and fit with ReelSaid. Test the prepared tasks with real inputs. Use language that helps people understand what they'll get and helps agents and search systems match the task to the right request. Include the approved tasks in the on-demand launch.

## Decisions for implementation and release

The implementation plan owns the research, live comparisons, evidence collection, experiments, and resulting technical choices. It determines the comparable competitors and cases, the supported Standby integration and billing details, the GitHub email route, and the discoverability and task choices. Use the official Apify Actor Development skill for the Actor and validate public changes on the intended surfaces. Use GPT-6.1 Sol Max for agent reviews.

Prepare a verified private release candidate and its public package. Confirm Apify's current Store testing and publication behavior for Standby and verify the supported readiness and quality signals. Final numerical pricing is the owner's last decision before launch. Validate the chosen prices and spending behavior on the private candidate, then publish the Actor and prepared public tasks on the owner's request. Verify the live Standby and native run paths, Store listing, published tasks, and agent discovery from a visitor's perspective.
