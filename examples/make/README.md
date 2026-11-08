# Transcribe an Instagram Reel in Make

1. Download the [ReelSaid blueprint](https://raw.githubusercontent.com/aimansour/reelsaid/main/examples/make/reelsaid.blueprint.json). In a new scenario, open the **More** menu, select **Import blueprint**, and select the downloaded file.
2. Open **Transcribe Reel**, the HTTP v4 module. Keep **Authentication type** set to **API key** and add a credential. Select **In the header**, enter **Authorization** as the parameter name, and enter `Bearer YOUR_APIFY_API_TOKEN` as the key. You can find the token under **Settings → Integrations** in Apify Console.
3. Click **Run once** to transcribe the example Reel. Open the iterator's output bundle and select `transcript`, `language`, or `status` when mapping values into the next module.
4. Change the URL in the HTTP request body before saving the scenario for your own content.

For a longer batch, start an asynchronous Apify run and fetch the dataset when the run completes. [Make blueprint import](https://help.make.com/blueprints) · [HTTP credentials](https://apps.make.com/api-key-authentication-type) · [ReelSaid API guide](https://github.com/aimansour/reelsaid#transcribe-your-first-reel)
