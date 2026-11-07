# Competitor and fixture baseline

Observed on November 7, 2026. Steadyfetch is the primary direct benchmark. Apify's official Reel Scraper, APISmith, and SIÁN are live comparators for the overlapping inputs. Store discovery also surfaced Headply, Tactful Anvil, Automly, Tenfoldfleet, Parseforge, and DeepMine. Their listings informed the capability inventory. The selection for live runs emphasized active usage and complementary transcription and metadata behavior.

| Actor | Observed or documented comparison surface |
| --- | --- |
| [Steadyfetch](https://apify.com/steadyfetch/instagram-reel-transcript-scraper) | Same Actor for handles, Reel links, CDN inputs, and dataset chaining. Provides a timed opening hook, segment timestamps, original language, run receipts, and watchlist memory. Its direct-link output left publisher and some post metadata absent on the matched single fixture. |
| [Apify official Reel Scraper](https://apify.com/apify/instagram-reel-scraper/input-schema) | Profile and Reel discovery with an optional per-minute transcript. Shows plays, views, engagement, duration, music, coauthor data, pinned status, and optional share count. The matched transcript is a text field. |
| [APISmith](https://apify.com/apple_yang/instagram-transcripts-scraper) | Single and bulk transcription return original text, segments, metadata, and video/audio URLs. Profile mode provides metadata. Its bulk run returned a distinct row for the unavailable source. |
| [SIÁN](https://apify.com/sian.agency/instagram-ai-transcript-extractor) | Timestamped subtitles and optional word timing, diarization, translation, and metadata. The Store schema validates bulk URL objects. The single run included an Actor-start event. |
| [Tactful Anvil](https://apify.com/tactful_anvil/instagram-reels-transcript), [Headply](https://apify.com/headply/instagram-reels-transcript-scraper), [DeepMine](https://apify.com/deepmine/instagram-reel-transcript-scraper) | Useful comparison fields include collaborator attribution, plays and views as separate metrics, original caption, publication time, music, thumbnail, hook, subtitle formats, and charging rules. The wider inventory is evidence for field and copy coverage. |

## Measurement

GitHub's public verification workflow submitted the runs through Apify CLI. It measured wall time from the CLI invocation and polled for the first nonempty transcript. Paid add-ons were omitted except the official scraper's transcript feature. Per-case spending and runtime caps belong to this benchmark campaign. Raw inputs and results remain in the account's restricted benchmark storage. Anonymous storage access returned HTTP 403 after the documented access update. [Apify storage update](https://docs.apify.com/api/v2/key-value-store-put)

| Case | Transcript rows | First text, seconds | End to end, seconds | Settled run USD |
| --- | ---: | ---: | ---: | ---: |
| Steadyfetch, single | 1 | 6.84 | 7.90 | 0.0150 |
| APISmith, single | 1 | 8.46 | 8.57 | 0.0055 |
| SIÁN, single | 1 | 29.44 | 39.76 | 0.0330 |
| Apify official, single | 1 | 14.05 | 14.05 | 0.0516 |
| Steadyfetch, mixed | 2 | 10.64 | 11.19 | 0.0300 |
| APISmith, mixed | 2 | 8.49 | 22.20 | 0.0120 |
| SIÁN, mixed with validated URL objects | 2 | unavailable | 59.84 | 0.0610 |
| Steadyfetch, NASA requested up to 12 | 9 | 10.44 | 31.47 | 0.1350 |
| Apify official, NASA requested up to 12 | 4 | 13.71 | 14.61 | 0.2994 |
| Steadyfetch, personal account | 0 | none | 21.70 | 0.0000 |
| Steadyfetch, multilingual profile | 2 | 11.58 | 13.25 | 0.0300 |

The NASA run comparisons used the same handle and requested count under the same spending cap. Steadyfetch returned nine transcripts and three no-speech rows. The official actor returned four transcripts and settled just below the cap. Its completion time covers fewer delivered results. SIÁN's mixed run populated an error row's transcript field with a placeholder. The campaign excluded that row from its usable result count. The first-text timing from that run is unavailable because the original observer also counted that field.

Apify's terminal status arrived before the final charge counters for several cases. The settled numbers above came from later reads of the same run IDs. Settlement and receipt verification must account for the observed lag.

The Steadyfetch and APISmith single transcripts differed by one normalized word edit across roughly 225 words. This measures agreement between outputs. For independent accuracy, the short spoken candidate was downloaded, its audio stream and 8.89-second duration confirmed with FFprobe, and its visible captions read from frames sampled at 2 Hz. Both mixed-run transcripts for that clip matched the caption wording after normalization. Store test runs should use the real clip from the fixture catalog and verify availability again.

## Fixtures and transfer to acquisition testing

`tests/fixtures/catalog.json` records the public personal profile and known Reel, creator and business profiles, a post with three video children, and a cross-publisher collaboration. The account-type observation comes from the profile comparison, and the Actor's own cloud retrieval must verify it in Task 03. Browserless local reads of the candidate profile API returned HTTP 429. The local embed pages returned HTTP 200 without a usable media field in the initial response. Cloud probes will determine how the candidate routes behave on Apify.

Keep signed source URLs and raw competitor records in the restricted storage. The shorter spoken clip is the launch-example candidate. Record independently observed expiry when the retained CDN link expires. Audio edge-case recipes in the catalog give deterministic source timelines for quality calibration.

The category inventory and usage snapshot were checked with Apify CLI Store search and actor metadata. Live numbers describe this campaign, with repeat measurement reserved for decisions where run variance changes the result.

Verified public automation runs `42410541359`, `42410794349`, `42410984893`, `42411108181`. Raw per-case run IDs and rows are in the restricted benchmark store.
