# Transcribe an Instagram Reel in n8n

1. Download [reelsaid.json](https://raw.githubusercontent.com/wip-bunker-42/reelsaid/main/examples/n8n/reelsaid.json). In the n8n editor, open the workflow menu and select **Import from File**.
2. Open **Transcribe Reel** and select a **Header Auth** credential. Create one with **Name** set to `Authorization` and **Value** set to `Bearer YOUR_APIFY_API_TOKEN`. Find your token under **Settings → Integrations** in Apify Console.
3. Select **Execute workflow** to transcribe the sample Reel. Open **Map transcript** to find the spoken text, language, and status. Its output also includes the original fields, including `segments` and `subtitles`.
4. Replace the example URL in the request body. Connect the next node to **Map transcript** and use `{{ $json.transcript }}` as its text input.

For profiles or long batches, use an asynchronous Apify run and fetch its dataset after completion. [ReelSaid API guide](https://github.com/wip-bunker-42/reelsaid#transcribe-your-first-reel)
