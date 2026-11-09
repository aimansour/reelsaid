# Launch competitor comparison protocol

## Inventory

Store CLI, native MCP searches, and web results surfaced different candidates. Steadyfetch leads the direct group in observed monthly usage. APISmith, SIÁN, afanasenko, Lance API, TubeText, Scraping Solutions, and the official Reel Scraper are credible overlapping candidates. Include APIMint and Tracefetch as explicit controls for the audio decision. Screen additional active results where the supported transcript and timing features warrant a test. A Store description is evidence of a claim. Timed, charged observations belong in the live comparison.

| Product | Relevant published or API-observed surface |
| --- | --- |
| [Steadyfetch](https://apify.com/steadyfetch/instagram-reel-transcript-scraper) | Apify run and confirmed Standby URL. The publisher documents bearer authentication, direct JSON output, and per-event charging on Standby. |
| [APISmith](https://apify.com/apple_yang/instagram-transcripts-scraper), [SIÁN](https://apify.com/sian.agency/instagram-ai-transcript-extractor), [Lance API](https://apify.com/lance_api/instagram-video-transcript-scraper), [TubeText](https://apify.com/tubetext/instagram-reels-transcript) | Native comparison candidates discovered in MCP results. Their current Actor metadata has no Standby URL. |
| [afanasenko](https://apify.com/afanasenko/instagram-reel-script-extractor), [Scraping Solutions](https://apify.com/scraping_solutions/instagram-reels-transcript-scraper-audio-to-text), [Apify](https://apify.com/apify/instagram-reel-scraper) | Native candidates for overlapping transcript and media features. |
| [APIMint](https://apify.com/apimint/instagram-reel-transcript-scraper) | The publisher says it detects music-only media before transcription and leaves that result uncharged. |
| [Tracefetch](https://apify.com/tracefetch/instagram-reels-transcript) | The publisher says it transcribes music-only media, returns a no-speech verdict, and bills the processed audio. |

## Cases and references

The case catalog is `tests/fixtures/market-reels.json`. Use the independently checked short spoken Reel and the longer captioned Reel for exact short text and coverage anchors respectively. The longer Reel's caption frames include an early instruction and the closing words near the end of the 60-second audio. A Spanish Reel and the music-field clip are available and have audio tracks. The Spanish overlays report editorial context, so score the clip for original-language output and coverage, and keep its overlays separate from a verbatim reference. The music-field verdict starts as a publisher claim and is tested separately.

Use the original Arabic FLEURS test recording with its dataset reference text, a 24 dB quieter copy, a copy mixed with a generated instrumental chord, digital silence, and the chord alone. The generation parameters and original WAV checksum are in the catalog. These controls separate audio policy behavior from Instagram retrieval and provide independently labeled speech and no-speech inputs. Use the public Instagram cases across rivals. Use generated and dataset audio in the policy tests and only for a direct-media rival when it accepts the same source. [Google FLEURS dataset](https://huggingface.co/datasets/google/fleurs)

FFmpeg produced the reference audio variants at 16 kHz. The current local detector labeled original, quiet, and mixed Arabic speech as speech, digital silence as silence, and the chord as no speech. It independently classified the publisher's music-field clip as music-only with confidence 0.951. These are detector observations to compare with the source controls and later live results.

## Qualification before timing

Freeze a comparison's exact video identities, output features, reference checks, and cache condition before the run. Grade all speech cases in the original language. Use normalized word edits for word-delimited languages and character edits where token boundaries make that comparison unreliable. Count at most one edit of difference in a verified reference excerpt as equivalent, after allowing equivalent spelling and punctuation. Require the verified opening and closing anchors, plausible monotonic timings within the media, and no material omission, fabricated phrase, or repetition. Score reference excerpts separately from transcript lengths, and retain an explicit ungraded result when the evidence supports only language or behavior. A no-speech control passes quality when it gives a usable reason with no invented speech. Report its charges separately.

Compare the same requested and completed identities. Cases with error placeholders, unfinished work, duplicate rows replacing expected results, and unresolved quality stay out of the speed ranking. Use an unseen source or a supported explicit refresh to establish a fresh result and keep uncertain cache status separate. Compare warm server requests with fresh output separately from cached repeat responses. A published native and Standby path each gets its own matched comparison.

Measure native time from caller submission through the first observable usable dataset row and through completion. Report the polling interval as observation granularity. A complete JSON Standby response makes its first usable row available at response completion. Wait for terminal charge counters separately from the latency clock. Keep metered platform usage separate from transcript events. Record exact charge amounts only when the settled counters and applicable prices establish them.

Run empty, absent-body, misspelled, malformed-URL, and mixed controls with supported fields and bounded test spend. Use the restricted Apify store for payloads and raw rows. Mark processing order as publisher-documented, observed from a trace, or unknown, and report outcomes and charge evidence even when the internal sequence is unknown.

The comparison suite rejected a cached response, an unknown cache state, and two equally shortened workloads. The trusted public dispatch validated the harness and log boundary before live runs. [Comparison harness verification](https://github.com/aimansour/reelsaid/actions/runs/42511169054)

## Live observations in progress

The first fresh-attempt comparison on the 60-second captioned Reel delivered the following observations. The same observer measured first usable dataset output and terminal run completion. The ReelSaid and Steadyfetch texts had zero normalized word disagreement and passed all four independent caption anchors. The timing interval on ReelSaid was 0.02 to 60.37 seconds and on Steadyfetch it was 0 to 60.26 seconds. Identical words establish output agreement for this case. They leave processing order unknown.

| Actor | First usable text | Total | Caption anchors |
| --- | ---: | ---: | ---: |
| ReelSaid | 12.33 s | 13.12 s | 4/4 |
| Steadyfetch | 6.51 s | 8.80 s | 4/4 |
| APISmith | 13.33 s | 14.07 s | 4/4 |
| SIÁN | 31.67 s | 44.31 s | 4/4 |

APISmith and SIÁN each differed from the ReelSaid text by approximately one normalized word on this case. Treat this as an early case observation until the remaining runs, reference checks, and workload matches are collected. [Live single-Reel campaign](https://github.com/aimansour/reelsaid/actions/runs/42511478923)

The extended clip also qualified Lance API at 16.32 s first and 17.81 s total and Panix at 14.24 s first and 14.98 s total. Other native cases missed a reference anchor, returned coarse analysis beats or text without segments, exceeded the media timing bounds, or timed out. The observer learned the Lance API source URL and nested transcript shape and afanasenko's spoken transcript field from the actual outputs. A missing first-output observation stays null.

Steadyfetch Standby returned HTTP 200, a direct transcript, and one transcript event in 5.32 seconds for the single-Reel request. Its invalid input returned HTTP 200 in 3.78 seconds with a normalization note, an unavailable row, zero delivered transcripts, and zero charged events. Both responses had rows, summary, delivered and charged fields, notes, and a request ID. This validates the observable request and response pattern. [Standby observations](https://github.com/aimansour/reelsaid/actions/runs/42512099615)

The music-field case returned an uncharged `QUALITY_UNVERIFIED` partial in ReelSaid. The result contained 45 words and carried an unknown speech classification, while the independently decoded file was classified as music locally. Steadyfetch emitted a transcript and one transcript event ($0.015). APISmith emitted no usable text and one speech-to-text event ($0.0045). Lance API returned text and one transcript-minute event ($0.005). Tracefetch returned text and one transcript event plus an Actor-start event ($0.00605 total). TubeText labeled the result as lyrics and charged two Actor-start events ($0.0001 total). APIMint returned `no-speech` and charged one Actor-start event ($0.00005). APIMint's and Tracefetch's published descriptions specify when they check speech. The exposed logs describe results. The live order of detector and model calls remains unknown. The local and cloud disagreement in ReelSaid identifies a reproducible issue for the policy task. [Music-field observations](https://github.com/aimansour/reelsaid/actions/runs/42512154484)

The direct-audio controls separate the model input from Instagram retrieval. The detector reported speech on original Arabic, 24 dB quieter Arabic, and Arabic over an instrumental chord. It reported digital silence with confidence 1.0 and no speech on the instrumental chord with confidence 0.969. It reported speech on the public Spanish clip and music on the second field clip from the NASA corpus with confidence 0.952. The results compare classifier verdicts. The live field runs compare competitor delivery and billing on public Instagram sources.

The mixed English, Spanish, and music batch gave ReelSaid two qualified transcripts at 13.35 s first and 17.70 s total. The Spanish transcript arrived first. Steadyfetch returned three transcripts, including music, at 4.41 s first and 6.24 s total with zero transcript events across three previously observed sources. Panix returned two transcripts and a no-speech result at 12.88 s first and 14.62 s total with uncertain cache history. TubeText returned two transcripts and a lyrics result at 14.41 s first and 16.01 s total with explicit refresh. The unverified ReelSaid music row fails the expected no-speech verdict. APIMint and SIÁN timed out, and Memo23 reported three deadlines. These runs establish behavior and observed latencies. Use independently captioned, previously unseen speech sources in the fresh batch comparison for a comparable speed target. [Mixed-batch observations](https://github.com/aimansour/reelsaid/actions/runs/42512351035)

## Native input behavior

ReelSaid returned one `NO_SOURCE` row for an empty object or absent body and one `UNKNOWN_INPUT` row for a misspelled field. All three yielded zero transcripts and an explicit uncharged result. The owner candidate has no live price. The SDK counters for this Actor are unavailable in the benchmark, so the evidence for these cases is the uncharged rows and the runner contract.

Steadyfetch attempted its default public creator in both the empty and absent-body cases. Both requests had zero saved source fields. The resulting rows and summaries identified the attempted default. Discovery stopped after about 54 seconds in each run with zero transcripts and zero charges. Its misspelled field returned an input error with a suggested field, zero transcripts, and zero charges. APISmith completed all three with empty datasets and zero charges. Lance API's submissions returned HTTP 400 in all three cases. APIMint and Tracefetch failed each submitted run with zero transcript events and one Actor-start event per run. This comparison supports keeping explicit input errors and requiring a selected source for ReelSaid. [Empty, absent, and misspelled input controls](https://github.com/aimansour/reelsaid/actions/runs/42512877703)
