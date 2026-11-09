# ReelSaid API recipes

Use an Apify API token in the `Authorization: Bearer` header. Set `APIFY_TOKEN` in your environment before running these examples. Send explicit video sources. The sample in the Console runs only when you submit it. Empty or misspelled source fields return an input error.

## Get one transcript with Standby

The stable service address is `https://aimansour--reelsaid.apify.actor/`. Download `standby.json` to use the example, or send your own public Reel URL as `reelUrl`. The options go in the JSON body. Use `language: "auto"` for detection, `wordLevelTimestamps: true` for word timings, and `includeSrt` and `includeVtt` to control subtitle output. Set `maxTotalChargeUsd` in the body to cap event spending for the request. Use a native run for a list, profile, dataset, continuation, or a carousel with multiple videos. [Standby example](https://github.com/aimansour/reelsaid/blob/main/examples/api/standby.json) · [OpenAPI reference](https://apify.com/aimansour/reelsaid/server)

```bash
curl --fail-with-body --silent --show-error \
  'https://aimansour--reelsaid.apify.actor/' \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data @standby.json
```

| Endpoint | Result |
| --- | --- |
| `GET /` | Returns HTTP 200 with `{"status":"ready"}`. Use the same Apify token. |
| `POST /` | HTTP 200 includes `requestId`, `rows`, `summary`, `delivered`, `charged`, and `notes`. Check the row's status for the transcription outcome. |

The HTTP error response includes a machine-readable `errorCode` when the request reaches ReelSaid. Correct the input on HTTP 400, reduce the body on 413, or send JSON on 415. For 401 or 403, check the token and Actor access. For 429 or 503, use retry guidance and back off. Apify can return its own gateway error body.

Read `rows[0].transcript` for the full spoken text. Subtitle content is inline at `rows[0].subtitles.srt.content` and `rows[0].subtitles.vtt.content` when available. Keep the returned `requestId` when reporting a problem. The Container Web Server address belongs to one run. Use the stable Standby address above in an integration.

## Start a native run

Download an example input and pass it as the JSON body. The native interface accepts a single Reel, a list, public accounts, or an Apify dataset. [Single Reel](https://github.com/aimansour/reelsaid/blob/main/examples/api/reel.json) · [Profile](https://github.com/aimansour/reelsaid/blob/main/examples/api/profile.json) · [Dataset](https://github.com/aimansour/reelsaid/blob/main/examples/api/dataset.json)

```bash
curl --fail-with-body --silent --show-error \
  'https://api.apify.com/v2/acts/aimansour~reelsaid/runs' \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data @profile.json
```

Use `maxTotalChargeUsd` in the run URL query to set the native event budget. Read `data.id`, `data.defaultDatasetId`, and `data.defaultKeyValueStoreId` from the response. The run endpoint returns quickly, so you can poll the run or read dataset rows as they arrive. For one short clip, the native `run-sync-get-dataset-items` endpoint waits and returns the rows directly. [Apify API guide](https://docs.apify.com/academy/api/run-actor-and-retrieve-data-via-api)

| Read | Endpoint |
| --- | --- |
| Run status | `GET /v2/actor-runs/{runId}` |
| Result rows | `GET /v2/datasets/{datasetId}/items` |
| Summary and continuation | `GET /v2/key-value-stores/{storeId}/records/SUMMARY` |
| Subtitle files | Use the returned native subtitle URL with your Apify access. |

### Fields to map in your workflow

| Field | What it tells you |
| --- | --- |
| `kind`, `schemaVersion`, `videoId` | Row type, contract version, and stable video identity. A native run can also emit an input row. |
| `transcript`, `segments`, `wordLevelTimestamps`, `hook` | Full spoken text, timed segments and optional words, and the first three seconds of speech. Timings are in seconds. |
| `language`, `durationSeconds`, `wordCount`, `transcriptSource` | Language, duration, word count, and whether speech recognition or existing captions supplied the text. |
| `metadata` | Post URL, shortcode, publisher, discovery profile, caption, publication date, cover, audio, engagement, and available collaborators. Missing values are `null`. |
| `status`, `errorCode`, `retryable`, `quality` | Outcome, specific error, retry guidance, and speech or transcript coverage evidence when available. |
| `charged`, `billedMinutes`, `chargedEvents`, `confirmedChargeUsd` | Event receipt for that result. The amount can be `null` if the precise price is unavailable at response time. |

[Example native dataset row](https://github.com/aimansour/reelsaid/blob/main/examples/api/output.json)

If `SUMMARY` includes a continuation, submit its `resumeFromDatasetId` in a new native run. Use `completedDatasetIds` to find results already delivered in earlier runs. Repeated requests can reuse results within the same Apify account and interface. Standby and native runs keep separate histories. Set `forceRefresh` when you want a fresh transcription and its own quality and billing decision.
