# Apify media and Groq feasibility

Private Apify run `8eNgpX0w5AuTOXH5F` resolved the Instagram media with ReelSaid's guest HTTP probe and sent the real signed media URL to both approved Groq models. Three independent supplied credentials returned HTTP 200 with each model. The third credential in the supplied order returned `401 invalid_api_key` after the HTTP control reached the Groq API. Keep the pool configurable and add that account when a replacement credential is available.

| Comparison | Measured result |
| --- | --- |
| Direct short Reel, Turbo | 396–559 ms across three accounts. Three segments and 25 timed words in each response. |
| Direct short Reel, Large-v3 | 534–639 ms across three accounts. Three segments and 25 timed words in each response. |
| Mono FLAC upload | 513 ms for Turbo and 1,083 ms for Large-v3 on the measured account. Both returned 25 timed words. |
| Media preparation | The MP4 was 2,403,401 bytes. Its mono FLAC sidecar was 309,707 bytes, with 252 ms for fetch and preparation. |
| Spanish | The signed URL returned Spanish both with automatic detection and with the `es` hint. |
| Node standard-fetch control | HTTP 200 with no media payload on the same public post. Python and the tested HTTP client resolved the media in the same Apify run. |

The short reference's words matched after normalization on the direct URL and upload paths for both models. The same reference matched with an instrumental bed mixed under the speech. Provider timings can extend slightly beyond the media, so align and clamp published times to the measured timeline. Use the measured media duration for billing.

The 9-second silence and chord samples triggered nonempty transcripts from both models. In those samples Turbo reported zero `no_speech_prob`, while Large-v3 reported about 0.70 and 0.64. The WebRTC speech detector produced fractions of 0 for silence, 0.01 for the chord bed, 0.737 for clean speech, and 1.0 for speech mixed with the bed. This supports an independent audio signal as a quality check, with calibration in Task 10. The 79.7-second public no-speech candidate returned six words from Turbo, which leaves its actual speech coverage for audio-based validation.

Each successful first call reported a request limit of 2,000 and remaining count of 1,999 in the observed account/model response. The headers did not report the hourly or daily audio limits. Treat observed request resets and future `Retry-After` as provider signals, and separately configure audio and request windows from the account's limits. The provider documents a 10-second minimum billable request, which matters for the short sample and repair costs. [Groq speech-to-text](https://console.groq.com/docs/speech-to-text) · [Groq rate limits](https://console.groq.com/docs/rate-limits)

The probe credentials live in an encrypted Apify runtime environment variable with build-time access disabled. GitHub started the build and run through the existing deployment secret.

Private Apify run `GVjRGOqNa4NxcN4Re` changed the URL expiry to a past value as a controlled access failure. Instagram CDN returned 403 and Groq reported `media_fetch_failed`. Resolving the original post again and retrying the refreshed URL returned HTTP 200 and 25 timed words. This proves the controlled recovery path. Keep the observed HTTP and provider errors separate from whether a stored link is known to have naturally expired.

## Product adapter

Public workflow `42444540220` ran the adapter in private Apify run `XnQHVT75KWedrFdph`. All six account and model pairs returned 25 timed words through the direct URL path. The six requests took 512 to 624 ms each. Spanish auto-detection and an explicit `es` hint preserved Spanish text. A deliberately stale signed URL failed at Groq. The adapter reused retained media, uploaded 309,707 bytes of mono FLAC from the 2,403,401-byte original, and recovered the full 25-word transcript.

The local admission window tracks requests per minute and day and audio seconds per hour and day, independently for each organization and model. Use the published Free defaults for the measured accounts and support runtime overrides for account-specific allowances. An optional organization-wide budget applies when configured. A run-specific starting position distributes simultaneous cold runs across accounts. The provider remains the authority across runs, with response headers, cooldown, and a bounded wait feeding each run's scheduler. [Groq rate limits](https://console.groq.com/docs/rate-limits)
