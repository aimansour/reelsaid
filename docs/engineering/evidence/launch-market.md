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
