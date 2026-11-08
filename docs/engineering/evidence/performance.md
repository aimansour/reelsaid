# ReelSaid cloud performance and contribution

## Campaign design

The public verification workflow submits controlled private runs through Apify CLI. It uses the same clock and observer as the competitor campaign. Wall time includes CLI submission and platform startup. The observer polls for the first nonempty transcript. A qualified video is a usable success or a measured partial result with at most 20% affected. Music, silence, absent audio, errors, and results with unresolved defects above 20% are excluded from projected revenue. Qualifying partial results remain identifiable in the output.

The private benchmark store keeps the inputs, per-video evidence, original run IDs, and raw counters. `scripts/summarize-performance.py` derives qualified counts, observed language, metered platform usage, and modeled contribution. Word agreement compares matched results after normalization. It is separate from independent ground-truth accuracy. The short spoken reference has independent visible-caption verification.

## Baseline and transfer findings

| Case | Memory | First transcript | End to end | Qualified | Received bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original single | 256 MB | 6.55 s | 6.69 s | 1 | 328,547 |
| Original mixed | 512 MB | 10.52 s | 11.09 s | 2 | 644,368 |
| Original NASA profile | 512 MB | — | 60.77 s | 0 | 3,311,645 |
| Ordered concurrent NASA profile | 512 MB | 12.37 s | 66.46 s | 5 | 94,208,114 |
| Concurrent large batch before audio optimization | 1024 MB | 34.63 s | 93.77 s | 11 | 116,924,072 |
| Concurrent large batch with audio optimization | 512 MB | 12.60 s | 119.21 s | 12 | 12,565,221 |
| Concurrent large batch with audio optimization | 1024 MB | 14.82 s | 68.25 s | 12 | 12,388,871 |
| NASA profile with audio optimization | 1024 MB | 12.48 s | 41.45 s | 7 | 9,879,656 |
| Steadyfetch NASA baseline | — | 10.44 s | 31.47 s | 9 | — |

The original profile exhausted its time while hydrating account history. A bounded newest-first profile now stops discovery once the requested recent eligible count is available and persists the next page. Recent discovery and the video pipeline overlap network operations. Admission and delivery each follow the selected order. Work after the first unaffordable video reaches no ASR request.

Three longer files had fast-start MP4 indexes between 66.6 and 92.2 KB. Their first 64 KiB contained the index header and the exact index boundary. Fetching through that boundary avoided a full progressive download for duration inspection. On four verified URLs, same-post audio-only representations were 86 to 987 KB compared with 2.4 to 12.2 MB for the corresponding video, and their durations were within 0.115 seconds. The verifier validates the source, stream, and alignment before using it. The optimized 1024 MB batch received 89.4% fewer bytes than the prior 1024 MB run on the same set. [Instagram extraction reference](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/instagram.py)

An experimental parallel-window Silero pass reduced local inference time by roughly twofold on the tested audio. Its frame classification differed from continuous inference by 4.6% on a difficult fixture, so production keeps continuous inference. Word-level alignment reduces overestimation when a coarse ASR segment extends across silence. The coverage threshold remains 20%.

## Cost method

Use settled Apify usage counters. Immediately after the terminal status, the NASA profile initially reported $0.002553. Its settled usage was $0.005769, including $0.00255 for key-value writes and $0.00216 for compute. The private benchmark meters accepted and potentially billed Groq seconds, including repair. The projected paid Groq cost uses $0.04 per hour for Turbo and $0.111 per hour for Large-v3, with the ten-second minimum. This estimates contribution at published usage rates. The connected free Groq accounts provide quota for verification. [Groq speech to text](https://console.groq.com/docs/speech-to-text)

For paid Apify tiers, contribution uses 80% of gross event revenue minus platform usage and modeled ASR. Free Apify-tier traffic produces no developer event revenue, with platform usage covered by Apify. Its external ASR expense remains in the traffic-mix models. Enterprise platform costs use the measured un-discounted costs as a conservative estimate. [Apify pricing and costs](https://docs.apify.com/actors/monetize/pricing-and-costs)

Verified campaigns. [Original runtime](https://github.com/aimansour/reelsaid/actions/runs/42464018713) · [Concurrent runtime](https://github.com/aimansour/reelsaid/actions/runs/42464568767) · [Audio optimization](https://github.com/aimansour/reelsaid/actions/runs/42465357368)

## Candidate workload

The next campaign held the full continuous voice detector and refined defect timing using the actual timed words inside coarse provider segments. Both NASA runs then returned nine qualified transcripts and three music-only outcomes across the 12 selected Reels. At 1024 MB the first text arrived in 15.38 seconds and the run finished in 48.45 seconds. At 2048 MB those figures were 15.13 and 42.65 seconds. Steadyfetch's earlier comparison was 10.44 and 31.47 seconds for the same number of transcripts.

The 20-video mixed batch delivered 14 qualified transcripts at both allocations. The 2048 MB run finished in 52.58 seconds compared with 94.88 seconds at 1024 MB. Settled Apify charges were $0.011325 and $0.010867 respectively. The run used $0.012195 of modeled paid ASR at both allocations. A six-Reel cloud case confirmed original-language results in English, Spanish, Arabic, and Japanese, with five qualified transcripts and one no-speech result.

The legacy /tv/ source stopped under the $0.012 base-only budget and issued no ASR request. Its 894 KB MP4 index motivated the larger bounded range read used in the final verification. [Candidate benchmark](https://github.com/aimansour/reelsaid/actions/runs/42481497993)
