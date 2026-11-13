<a href="https://apify.com/aimansour/reelsaid"><img src="https://raw.githubusercontent.com/wip-bunker-42/reelsaid/main/assets/reelsaid-logo.png" alt="ReelSaid logo" width="96" height="96"></a>

# ReelSaid — Instagram Reels Transcript API

**Every Reel, in Words.**

Turn public Instagram Reels into **searchable text, opening hooks, and ready-to-use subtitles**. Paste a Reel link to see what was said, or add a public profile to turn its Reels into a dataset you can search and share. You can start with an Apify account and a link. No Instagram login is required.

## Transcribe your first Reel

1. Open the **Input** tab on Apify.
2. In **Instagram URLs**, paste a public Reel link or leave the prefilled spoken clip in place. The example runs as a normal transcription when you select **Start**.
3. Select **Start**, then open the result to read the transcript. Use the timestamps to jump to a quote or download the SRT or WebVTT for editing.

[Open ReelSaid on Apify](https://apify.com/aimansour/reelsaid/input-schema)

## What you get

| Result | How to use it |
| --- | --- |
| **Full transcript and opening hook** | Find what someone said and review the speech in the first three seconds. |
| **Timestamps and subtitles** | Find the moment a quote starts, request word-by-word timing, or bring SRT and WebVTT into your editing workflow. |
| **Original-language speech** | Let ReelSaid detect the language or choose it yourself. Speech recognition uses **Whisper Large-v3**, the largest model size in the Whisper family. |
| **Post details alongside the text** | See the original caption, account, publication date, cover, audio details, and available engagement counts in their own fields. |

On the sample Reel, the hook starts with “One of my favorite quotes from Zig Ziglar is”. The timed segment starts at 0.10 seconds. In the full result you can see the entire quote, the timing for each word, and the separate post metadata. [See a real result in JSON](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/api/output.json)

## What you can do with Reel transcripts

- **Study hooks and scripts.** Compare how creators open their videos, introduce an idea, or ask viewers to take action. Filter by date and engagement to focus on the Reels that matter to your research.
- **Turn your videos into more content.** Give editors timed quotes and subtitle files, or turn a series of Reels into a newsletter, blog draft, or searchable archive.
- **Follow public accounts.** Save a profile and schedule ReelSaid to pick up new Reels for a recurring research or monitoring workflow.
- **Give AI agents the spoken content.** Pass the transcript and timing to an agent for search, summaries, or content analysis. Each result has a stable JSON shape and a per-video status.

Try a saved Apify example with real inputs. [Make Reel subtitles](https://apify.com/aimansour/reelsaid/examples/reelsaid-reel-subtitles) · [Compare opening hooks](https://apify.com/aimansour/reelsaid/examples/reelsaid-compare-reel-hooks) · [Monitor a public account](https://apify.com/aimansour/reelsaid/examples/reelsaid-monitor-instagram-reels) · [Transcribe a Spanish Reel](https://apify.com/aimansour/reelsaid/examples/reelsaid-spanish-reel-transcript) · [Prepare transcripts for AI](https://apify.com/aimansour/reelsaid/examples/reelsaid-instagram-transcripts-for-ai)

## Transcribe in bulk or follow an account

| Start with | What to enter |
| --- | --- |
| **A Reel, post, or list of links** | Paste them into **Instagram URLs**. ReelSaid accepts Instagram Reel, post, IGTV, and share links, plus direct Instagram CDN media URLs. It extracts each video in a carousel. |
| **A public account** | Enter a handle or profile URL in **Instagram profiles**. Public personal, creator, and business accounts work. |
| **A shortcode or another Apify run** | Use **Instagram shortcodes** or **Source Apify dataset ID**. API workflows can also pass inline records with `datasetItems`. Include the original post URL so ReelSaid can recover expired media. |

Clear the sample Reel when you want to run only your profile or dataset. You can also mix sources in a native run. ReelSaid recognizes repeated references to the same video and keeps their source information together. Filter by date, minimum views or likes, and video length. You can skip pinned Reels, sort by newest or most viewed, and cap the number of videos. [Full input options](https://apify.com/aimansour/reelsaid/input-schema)

To follow an account, save the profile input as an **Apify Task**, add a `watchlistId`, turn on **Only unanswered Reels**, and create a schedule. The first run can deliver matching existing Reels. Later runs use your account's answer history. [Profile input example](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/api/profile.json) · [Apify schedules](https://docs.apify.com/actors/running/schedules)

## How billing works

Pay per qualifying video transcript. The base event covers the first three minutes, with an additional event for each started minute after that. Each qualifying video in a carousel is billed individually. Silence, music-only clips, unavailable media, and transcripts with unresolved defects affecting more than 20% of the timeline have no transcript charge. A usable partial can qualify at 20% or less.

ReelSaid checks the full video quote before transcription and stops when the next transcript would exceed your run budget. A cached transcript has no new transcript charge within the same interface and Apify account. Native runs and Standby each keep their own history, so a first transcription in the other interface can have its own charge. [Current prices on Apify](https://apify.com/aimansour/reelsaid/pricing)

## Use ReelSaid with AI agents or automation

With **Apify MCP**, search for *Instagram Reels transcript API* or select `aimansour/reelsaid`. Read the Actor's input schema, run it with an explicit source, and fetch its dataset. This prompt gives an agent enough context to start.

> Use ReelSaid on Apify to transcribe my Instagram Reel in its original language. Return the opening hook, full transcript, and timestamps. Ask me for the public Reel URL if I haven't supplied it.

[Connect Apify MCP](https://docs.apify.com/agents/quickstart)

| Integration | Starting point |
| --- | --- |
| **n8n** | Import the workflow, select an Apify Header Auth credential, and map the result to the next step. [n8n workflow](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/n8n/README.md) |
| **Make** | Import the blueprint, connect your Apify credential, and choose where to send the transcript. [Make blueprint](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/make/README.md) |
| **Zapier** | Send the transcript to the next step in a Zap. [Zapier setup guide](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/zapier/README.md) |

## Instagram Reels Transcript API

### One video with Standby

Send a Reel URL in a JSON body to `POST /` on the stable Standby address. Authenticate with your Apify token. Read `rows[0]` for the transcript and `summary` for the result and billing counts. Standby returns requested subtitles inline.

```bash
curl --fail-with-body --silent --show-error \
  'https://aimansour--reelsaid.apify.actor/' \
  -H "Authorization: Bearer $APIFY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data @standby.json
```

Use the stable address for repeat requests and `GET /` for readiness. Apify also assigns a Container Web Server address to an individual run. That address belongs to that run and expires when it ends. [Standby JSON input](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/api/standby.json) · [Server reference](https://apify.com/aimansour/reelsaid/server)

### Batches, profiles, and continuation

Start a native run with `POST /v2/acts/aimansour~reelsaid/runs`. Use the returned dataset ID to read results as they arrive. Set `maxTotalChargeUsd` on the run to cap event spending. If a limit pauses the run, read its `SUMMARY` record and send the returned `resumeFromDatasetId` in a new run. Completed items stay in their original datasets. [API recipes and response fields](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/api/README.md)

## Questions about Reel transcripts

### Can I choose the transcript language?

Yes. `language: "auto"` detects it. A language code such as `es`, `ar`, or `ja` tells ReelSaid which language to expect. The text stays in the original spoken language. The result's `transcriptSource` shows whether it came from speech recognition or existing captions.

### Can I export the results?

Download a native run's dataset as JSON, CSV, or Excel from Apify. For subtitles, open the returned SRT or WebVTT file link with your Apify access. For text editing, use `transcript` for the spoken words and `metadata.caption` for the original Instagram post caption.

### What happens if one Reel fails?

You keep the successful results from the batch. Each video gets a status and, when relevant, an error code and retry guidance. If an old media URL has expired, include the original post URL or shortcode so ReelSaid can look up the current media. For help, share the run ID and the affected Reel in the Issues tab. [ReelSaid issues](https://apify.com/aimansour/reelsaid/issues)

## Open source

The Actor, documentation, and workflow examples are released under the [MIT License](https://github.com/wip-bunker-42/reelsaid/blob/main/LICENSE). [Browse the Actor source](https://github.com/wip-bunker-42/reelsaid/tree/main/src/reelsaid).

## Run locally

Install Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js, the Apify CLI, and FFmpeg with `ffprobe`. From the repository root, install the locked dependencies and download the audio analysis models.

```bash
uv sync --locked
bash scripts/install-quality-models
```

Set `REELSAID_GROQ_KEYS` to a JSON object mapping an account label to your own Groq API key. Copy the example input or save a JSON object with your own Reel URL.

```bash
mkdir -p storage/key_value_stores/default
cp examples/api/reel.json storage/key_value_stores/default/INPUT.json
PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" apify run --entrypoint reelsaid --user-agent apify-agent-skills/apify-actor-development
```

Read results in `storage/datasets/default`. Run the fixture-based tests with `./scripts/verify all`.
