# ReelSaid Core

ReelSaid transcribes public Instagram Reels and other Instagram videos. This repository contains the Apify Actor, including the native batch runner, Standby HTTP API, input and output schemas, and test suite. [Apify Store](https://apify.com/aimansour/reelsaid) · [Documentation and workflow templates](https://github.com/wip-bunker-42/reelsaid)

## Run locally

Use Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js, the Apify CLI, and FFmpeg with `ffprobe` on your PATH. From the repository root, install the locked dependencies and download the audio analysis models.

```bash
uv sync --locked
bash scripts/install-quality-models
```

Set `REELSAID_GROQ_KEYS` in your shell to a JSON object mapping an account label to your own Groq API key. Save an explicit Reel URL in the input below.

```bash
mkdir -p storage/key_value_stores/default
cat > storage/key_value_stores/default/INPUT.json <<'JSON'
{"startUrls":["https://www.instagram.com/reel/DS46KJNjva9/"],"wordLevelTimestamps":true}
JSON
PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" apify run --entrypoint reelsaid --user-agent apify-agent-skills/apify-actor-development
```

The local dataset is written to `storage/datasets/default`. The automated tests use fixtures and can run without Groq credentials.

```bash
./scripts/verify all
```

## License

ReelSaid is released under the [MIT License](LICENSE).
