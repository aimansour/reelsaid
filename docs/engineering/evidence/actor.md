# Private Actor integration

The public verification workflow built ReelSaid on Apify with the actual Actor entry point and native input, result, output, and storage schemas. Build `91IhWR5hBWLMRkpx8` was private and used limited runtime permissions. The three working Groq accounts were provisioned as one encrypted runtime variable. The initial build took its environment snapshot before the secret was created, so that build reported `PROVIDER_UNAVAILABLE`. A rebuild after provisioning supplied the secret to the run while build-time exposure remained disabled.

| Run | Observed behavior |
| --- | --- |
| `IuPRPilZxPbIDmwM8` and `iS0okheW7g2JoraXG` | Empty input and an unknown input field each returned one clear input error and zero charged rows. |
| `buo7SEvAf0ewGSSH5` | The Console's prefilled URL returned 25 English words and 25 timed words in a fresh transcription. Both subtitle files were downloaded through their Apify records. All four native output links pointed to the result and file collections. |
| `k14gB0OwMzsJkJaRF` | Repeated work returned the cached transcript with no new charged events. |
| `v0pPAqhmFC5dhkP8y` | The $0.011 run cap stopped before the $0.012 candidate and saved one video for continuation. |
| `aYmvmoedhNbhhErB6` | One malformed URL, three separate silent carousel videos, and one spoken Reel each returned its own outcome. The valid spoken Reel succeeded. |
| `9w6yIeOBuZyLVh1ac` and `wSxrT4OMXy6LDjgNT` | A result limit paused an English and Spanish batch. The continuation emitted the other video and referenced the original dataset. |
| `UtEHkaeOLUyIfh2Oq` | A native Apify schedule invoked a task with a fresh watchlist name. Its answer history skipped the previously delivered Reel and reported the first-seen run. |
| `VPK8sbmQZ0oNc1g7q` | A 10-second cloud run wrote `TIME_LIMIT` and a continuation before the platform timeout. No transcription or event charge occurred. |

The deterministic suite exercises priced video and carousel settlement, stable recovery after a dataset acknowledgement is lost, and overlapping refreshes. The private cloud build verified non-monetized product behavior. Later cloud runs verified native event acknowledgement and replay in the isolated billing Actor after payout setup. [Cloud workflow](https://github.com/aimansour/reelsaid/actions/runs/42463416526) · [Time limit](https://github.com/aimansour/reelsaid/actions/runs/42463649740) · [Verification workflow](https://github.com/aimansour/reelsaid/actions/runs/42463416544) · [Billing workflow](https://github.com/aimansour/reelsaid/actions/runs/42482027955)
