# Public package verification

The GitHub package uses the ReelSaid name, the Store title “ReelSaid — Instagram Reels Transcript API,” and the tagline “Every Reel, in Words.” The Store and GitHub copy describe the public sources, original-language transcript, timing, subtitles, metadata, and automation interfaces. The pricing section describes the event units and leaves the amounts to the owner at release.

The public example is the 25-word English result for `DS46KJNjva9`. It matches the explicit Console prefill and the single-Reel API, n8n, and Make inputs. The sample removes the original caption, temporary media references, and private subtitle record URLs.

The 512 × 512 PNG was exported from the original generated brand artwork and inspected at 48 × 48. The play mark and caption lines remain distinguishable at icon size.

The n8n 2.46.6 probe creates a fresh instance, imports a temporary Header Auth credential and the public workflow, and executes the workflow against the private Apify Actor. It asserts that the final mapping node receives a successful English transcript and timed words. The token and raw execution output stay in a temporary directory. The public automation reports only its overall status.

The Make blueprint uses HTTP v4 with a user-selected keychain credential and iterates the dataset response. Its endpoint, request body, and response contract match the n8n probe. The owner deferred import and execution inside Make. The Zapier guide uses the native Apify action and maps its transcript into a subsequent step. The owner deferred creating a Zapier template.
