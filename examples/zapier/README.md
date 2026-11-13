# Transcribe an Instagram Reel in Zapier

Add ReelSaid to a Zap using Zapier's native Apify integration. Start with a short Reel to make the transcript available as test data for the next step. [Open Apify in Zapier](https://zapier.com/apps/apify/integrations)

1. Create a Zap and choose the trigger that supplies your Reel URL. Test the trigger so the URL is available to map.
2. Add **Apify → Run Actor and Fetch Results**. Connect your Apify account, set **Search Actors from** to the Store, and select **ReelSaid — Instagram Reels Transcript API**. Use **My Actors** if you have private access to ReelSaid.
3. In the Actor input, set **Instagram URLs** to the URL from your trigger. For a first test, you can enter `https://www.instagram.com/reel/DS46KJNjva9/` and turn on **Word-level timestamps**. Where Zapier asks for raw input, paste the [single Reel JSON](https://github.com/wip-bunker-42/reelsaid/blob/main/examples/api/reel.json).
4. Select **Test step**. In the next step, map `transcript` to your destination's text field. You can also map `language`, `status`, and `hook.text`. Check `status` and require a nonempty transcript before using the text.

For profiles and long batches, use **Run Actor** and process the completed run's dataset with **Fetch Dataset Items**. [Apify's Zapier guide](https://docs.apify.com/integrations/zapier)
