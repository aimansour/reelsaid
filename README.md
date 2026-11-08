<img src="https://raw.githubusercontent.com/aimansour/reelsaid/main/assets/reelsaid-logo.png" alt="ReelSaid logo" width="96" height="96">

# ReelSaid — Instagram Reels Transcript API

**Every Reel, in Words.**

ReelSaid turns public Instagram Reels and video posts into original-language transcripts, timestamped sentences, word-level timing, and SRT and WebVTT subtitles. Use a Reel URL, a list of links, a public profile, or an Apify dataset. Speech recognition uses **Whisper Large-v3**, the largest model size in the Whisper family.

Each video gets a structured result with its transcript, opening three-second hook, language, and post metadata. Use the results to research what creators say, index video for search, generate subtitles, or send the spoken text to an AI agent. Run ReelSaid in Apify Console, over the API, or through Apify MCP. [ReelSaid on Apify](https://apify.com/aimansour/reelsaid)

## Transcribe your first Reel

Open the Actor, paste a public Instagram Reel URL into **Instagram URLs**, and select **Start**. The Console includes a short, spoken Reel you can explicitly submit to try the Actor. Replace the URL with your own when ready. Empty API input returns a structured input error. [Open the Input tab](https://apify.com/aimansour/reelsaid/input-schema)

The same example works over the API with your Apify token. The synchronous route is useful for a short clip. [Single Reel input](https://github.com/aimansour/reelsaid/blob/main/examples/api/reel.json)

```bash
curl --fail-with-body --silent --show-error \
  'https://api.apify.com/v2/acts/aimansour~reelsaid/run-sync-get-dataset-items?timeout=90' \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{
    "startUrls": ["https://www.instagram.com/reel/DS46KJNjva9/"],
    "wordLevelTimestamps": true
  }'
```

For profiles and batches, start an asynchronous run with `POST /v2/acts/aimansour~reelsaid/runs`. Read `data.id`, `data.defaultDatasetId`, and `data.defaultKeyValueStoreId` from the response. Poll `GET /v2/actor-runs/{runId}` and read the results from `GET /v2/datasets/{datasetId}/items`. Use the `maxTotalChargeUsd` run parameter to set a spending limit. [Apify API guide](https://docs.apify.com/academy/api/run-actor-and-retrieve-data-via-api)

## Inputs

| Field | Use |
| --- | --- |
| `startUrls` | Public Reel, video post, carousel, IGTV, share, or profile URLs. Accepts `/reel/`, `/p/`, and `/tv/` paths and direct Instagram CDN audio or video URLs. |
| `profiles` | Public personal, creator, or business account handles and profile URLs. |
| `shortcodes` | Instagram video identifiers such as `DS46KJNjva9`. |
| `datasetId` | An accessible Apify dataset containing source links or video records. Grant read access when prompted. |
| `datasetItems` | Inline records with fields such as `postUrl`, `shortcode`, `videoUrl`, and `audioUrl`. Include the original post URL so ReelSaid can recover an expired media link. |
| `language` | `auto` by default, or a language code such as `en`, `es`, `ar`, or `ja`. Text stays in the spoken language. |
| `preferCaptions` | Prefer usable, timed original-language captions when present. Defaults to `true`. |
| `wordLevelTimestamps` | Include individual word timings when available. Defaults to `false`. |
| `includeSrt`, `includeVtt` | Write subtitle files when the transcript has usable timing. Both default to `true`. |
| `dateFrom`, `dateTo`, `lastDays` | Filter by publication date. Use UTC dates in `YYYY-MM-DD` format. |
| `minViews`, `minLikes` | Filter by engagement when the metric is available. |
| `minDurationSeconds`, `maxDurationSeconds` | Filter by the media duration before transcription. |
| `skipPinned`, `sort`, `maxResults` | Skip pinned profile Reels, choose `newest` or `mostViewed`, and cap the number of selected videos. |
| `watchlistId`, `newReelsOnly` | Monitor a public account and skip videos your Apify account already received a final answer for. |
| `forceRefresh` | Request a fresh transcript and an independent quality and billing decision. |
| `resumeFromDatasetId` | Continue unfinished work from a previous ReelSaid run in your account. |

Combine input modes in one request. ReelSaid merges duplicate Reel references and keeps source provenance. Every video child in a carousel receives its own result. [Profile example](https://github.com/aimansour/reelsaid/blob/main/examples/api/profile.json) · [Dataset example](https://github.com/aimansour/reelsaid/blob/main/examples/api/dataset.json)

## Results, subtitles, and errors

| Field | Use |
| --- | --- |
| `transcript`, `segments` | Full spoken text and timed segments with `text`, `startSeconds`, and `endSeconds`. |
| `wordLevelTimestamps`, `hook` | Individual word timings when requested, plus available speech from the opening three seconds. |
| `language`, `durationSeconds`, `wordCount`, `transcriptSource` | Spoken language, timeline duration, word count, and source of the transcript. |
| `metadata` | Original post caption, publisher, discovery profile, collaborators, publication date, cover, audio details, and available view, play, like, and comment counts. Missing values are `null`. |
| `subtitles` | SRT and WebVTT references in the run's key-value store. Use the returned record URL and your Apify access to download a file. |
| `status`, `errorCode`, `retryable`, `quality` | Per-item outcome, reason, retry guidance, and available speech and coverage evidence. |
| `charged`, `billedMinutes`, `chargedEvents`, `confirmedChargeUsd` | Confirmed billing for the result in the current run. |

Each row has `kind: "video"` or `kind: "input"` and `schemaVersion: 1`. A batch can return successful, partial, skipped, failed, and deferred outcomes together. Inspect `quality` for the affected fraction, timing gaps, and speech classification when available. Codes such as `INVALID_URL`, `CONTENT_UNAVAILABLE`, `MEDIA_URL_EXPIRED`, and `TEMPORARILY_BLOCKED` identify the affected item. The example comes from a real run, with the post caption, expiring media URLs, and subtitle record links removed. [Example dataset response](https://github.com/aimansour/reelsaid/blob/main/examples/api/output.json)

The run summary is the `SUMMARY` record at `GET /v2/key-value-stores/{storeId}/records/SUMMARY`. It reports outcome counts, confirmed event charges, and a continuation when there is work left. Use `completedDatasetIds` to find results preserved from earlier runs.

## Watch profiles and resume batches

Save a profile input as an Apify task, set `watchlistId` and `newReelsOnly: true`, and add a schedule. The first run can return eligible existing Reels. Later runs use your account's answer history, including answers recorded under other watchlist names. Cached transcripts are reusable within your Apify account. [Apify schedules](https://docs.apify.com/actors/running/schedules)

When a time, result, or spending limit pauses a run, submit the summary's `resumeFromDatasetId` in a new run. ReelSaid continues the saved selection and keeps previously completed results in their original datasets. A spending limit is checked against each video's full quote before transcription.

## How billing works

Pay per qualifying video transcript. The base event covers the first three minutes, with an additional event for each started minute beyond that. A qualifying carousel child is billed as its own video. Silence, music-only clips, unavailable media, and results with unresolved defects affecting more than 20% of the timeline are free. A usable partial result can qualify when the affected fraction is 20% or less. Reusing a cached result carries no new transcript charge. [Current pricing](https://apify.com/aimansour/reelsaid/pricing)

## Apify MCP and automation

For AI agents, connect to Apify MCP and search for **Instagram Reels transcript API** or select `aimansour/reelsaid` explicitly. Fetch the Actor details for its input schema, call the Actor with the selected source, and read its dataset. Use the summary for continuation and the key-value store for subtitle files. [Apify MCP setup](https://docs.apify.com/agents/quickstart)

| Integration | Starting point |
| --- | --- |
| n8n | Import the workflow, select an Apify Header Auth credential, and run the included Reel. [n8n setup and workflow](https://github.com/aimansour/reelsaid/blob/main/examples/n8n/README.md) |
| Make | Import the blueprint, connect Apify, and map the transcript to your next module. [Make setup and blueprint](https://github.com/aimansour/reelsaid/blob/main/examples/make/README.md) |
| Zapier | Use the setup guide to send an Apify result to your next Zap step. [Zapier setup](https://github.com/aimansour/reelsaid/blob/main/examples/zapier/README.md) |

The original Instagram post copy is in `metadata.caption`. Use `transcript` for what was spoken, `hook.text` for the opening, and `segments` or the subtitle files for time-aligned editing.
