# Instagram retrieval in Apify cloud

The public verification workflow deployed and ran a private HTTP probe on Apify with default egress. The probe used guest Instagram requests. Direct media availability was checked with byte ranges against the matching asset's signed CDN URL.

| Route | Cloud result | Decision |
| --- | --- | --- |
| Logged-out post GraphQL | The exact short Reel returned three video variants. The selected CDN URL returned HTTP 206. The Carousel returned three video children. | Primary post and Carousel resolution. |
| Public post HTML with embedded Relay data | The exact short Reel returned three variants and a CDN HTTP 206. The Carousel returned the same three video children. | Independent post fallback. Parse the exact media entity and distinguish recommendations. |
| Embed and media-info routes | The tested embed pages exposed no playable variant. Media info redirected to login in the tested cloud run. | Keep them out of the selected routes. |
| yt-dlp | Returned formats for the short Reel. Its tested Carousel path stopped on a nonvideo child. | Reference behavior for single-video handling. Enumerate Carousel children in ReelSaid. |
| Logged-out Reels tab GraphQL | From a handle alone, listed one Reel for the verified public Personal fixture. Returned 12 NASA Reels, then 12 different Reels using the continuation cursor. The list contained plays, likes, comments, and pinned-user fields. | Primary profile discovery and paging. Use the Reel detail path for playable media and richer post metadata. |
| Logged-out profile root query | Returned the public profile's canonical username, account identity, and Relay ID. A separate profile-by-ID query observed account type 1 for the Personal fixture. | Profile identity and public/private evidence. |
| Direct profile HTML and older listing queries | The Apify HTML requests redirected to login, older listing responses were empty or rate-limited, and Instaloader hit the login redirect. | Use clear retryable retrieval outcomes when a profile listing is unavailable. |

Apify run `BO80A4Acz3ynfR8tb` verified the matching post and Carousel responses. Apify run `16fcZttwBU0igCSFG` verified guest handle discovery and pagination. For NASA, the guest first-page response was about 12.7 KB and the continuation about 12.7 KB before detail hydration. Apify run `9HjgbbxgEBIYjp1Sm` repeated the profile discovery and paging. It also checked all three matching Carousel child URLs with HTTP 206 on both paths and resolved the public Personal fixture's actual Reel. The collaboration returned publisher `nasajohnson` and coauthors `iss` and `nasa`, separate from discovery under `nasa`. On that run, the short post returned about 371 KB via GraphQL and 818 KB via HTML. These measurements describe the recorded samples.

## Request derivation

A fresh local guest session on the public Reels tab served the list in embedded Relay data with no authenticated session cookie. Its query preloader and delivered client module identified the guest first-page and continuation request shapes. Replaying those HTTP requests on Apify returned the usable list when HTML navigation from the cloud redirected. Keep the account username, numeric owner ID, Relay ID, and cursor distinct.

The application should preserve the requested discovery profile separately from the publisher carried by the post data. Merge profile metrics and post metadata by exact shortcode or child identity. Keep a signed media URL as received. Preserve unavailable metadata as null, including when a visible play count exists and the source has no separate view count.

The private probe demonstrates Python with curl_cffi as one viable candidate. Runtime and media selection follow the next task's evidence. No Trial Reel fixture with confirmed current status was found. [yt-dlp Instagram extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py) · [Instaloader profile implementation](https://github.com/instaloader/instaloader/blob/master/instaloader/structures.py) · [Gallery-dl report](https://github.com/mikf/gallery-dl/issues/9564)
