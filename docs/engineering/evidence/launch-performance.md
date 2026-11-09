# Native launch performance

## Exact candidate baseline

The market campaign observed the deployed default `0.1.9`. This measurement requested the reviewed private build `0.1.12` by version, confirmed the resolved build on each run, forced a fresh transcription, and used the Actor's normal allocation. The caller clock includes the CLI submission and platform startup. The settled cost column records Apify usage for the private owner runs.

| Workload | Memory | First usable text | Completion | Apify usage | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| 60-second reference | 256 MB | 12.82 s | 14.08 s | $0.0006333 | Success |
| 30-second wildlife | 256 MB | 16.73 s | 17.99 s | $0.0006845 | Billable partial by policy, with an unsupported two-word ending |
| Music field clip | 256 MB | — | 11.00 s | $0.0005832 | Uncharged `QUALITY_UNVERIFIED` |
| 58-second discussion | 256 MB | 10.43 s | 11.71 s | $0.0006005 | Success, with two segment starts out of order |
| Recent two-Reel batch | 512 MB | 10.41 s | 11.78 s | $0.0009901 | Two successes |

Independent full-video and audio-sidecar decoding classified the music clip as music-only at confidence 0.951 on both renditions. The independent audio track reported 33.110 seconds and the video timeline reported 34.600 seconds. The 1.490-second difference is above the existing alignment tolerance. Full video decoding locally classified the clip as music in 2.63 seconds. The smaller standalone track decoded and classified in 0.61 seconds. The observed cloud peak of 96.6 MiB was below the 256 MB allocation. Trace the selected source and classifier boundary on Apify before changing policy.

The wildlife recording had an unsupported interval from 30.000 to 30.143 seconds after the last audible sentence. It had other coverage defects, so its result can remain partial even after removing the unsupported text. The discussion had a brief overlapping interjection returned before a segment whose start timestamp was 0.24 seconds earlier. Both problems reproduced on the exact private candidate. The focused regressions exercise trimming an independently unsupported tail, preserving an audible ending after a pause, and sorting segment starts while keeping the transcript text unchanged.

## Restricted stage timing

An owner-only diagnostic build published from the trusted public workflow captured stage timings in its private run, copied them to the restricted benchmark store, and removed the diagnostic record from the run store. The deployed default continued to resolve to its prior build. The extended case used 5.318 seconds from the platform's run timestamp to the process's initial timing mark, 1.801 seconds through initial SDK setup, 2.257 seconds for discovery, 0.077 seconds for media preflight, and 0.890 seconds in ASR. The dataset write took 0.050 seconds. Wildlife had a 0.660-second platform-to-process interval and paid 0.670 seconds for media retrieval, decoding, and classification after its initial 0.814-second ASR request. The panel started its process 0.310 seconds after the platform run timestamp and delivered first text in 6.27 seconds. Startup varied by more than five seconds on this pass. [Restricted stage timing dispatch](https://github.com/aimansour/reelsaid/actions/runs/42558201558)

In the music case the initial ASR request used a direct URL. Verification obtained and decoded an audio payload in 0.236 seconds. The classifier ran for 0.319 seconds and returned unknown. The difference was in the classification evidence. FFprobe on the independently downloaded video showed an embedded audio stream of 33.225 seconds and a full video duration of 34.600 seconds. The separate 33.110-second audio is within the prior 0.35-second tolerance when compared to the actual audio stream. An integration test reproduced the video-versus-audio duration mismatch, then verified that alignment uses both stream boundaries and preserves the full video duration for admission and output.

## Audio policy and output

On the actual Apify rendition, the voice detector emitted one isolated 32-millisecond frame at 0.5296. No contiguous speech span was present. The independent music score was 0.9491. This explains the cloud `unknown` result even though the offline rendition of the same Reel passed the existing test. The classifier now recognizes high-confidence music with that narrow pattern. The regression preserves two consecutive speech frames and leaves a stronger isolated voice score uncertain. The result is `MUSIC_ONLY` at 0.949 confidence with zero words and zero charge. Full-video bytes were selected by the cloud verifier for this fixture. The media alignment change independently avoids the full-video transfer where the aligned sidecar is delivered.

| Verification order | 60-second speech quality stage | Music quality stage | Music provider audio | Results |
| --- | ---: | ---: | ---: | --- |
| Conditional | 1.045 s | 1.123 s | 35 s | Caption-equivalent speech and free music |
| Before ASR | 1.468 s | 0.802 s | 0 s | Caption-equivalent speech and free music |
| Always after ASR | 1.750 s | 1.241 s | 35 s | Caption-equivalent speech and free music |

All three used the same input pair and classifier revision. The conditional path keeps URL transcription for clear speech and checks the audio when transcript evidence or a known music source calls for it. Verification can run before the model when a retained audio file or an identified licensed track is available. The alternative that always verifies before ASR saved 35 provider seconds on the music clip, or roughly $0.000389 at the modeled paid Turbo rate. It added 0.423 seconds to the clear-speech quality stage and required media verification on that case. Always verifying after ASR used the same provider seconds as conditional and added 0.705 seconds to the clear-speech stage. Retain conditional verification for the default traffic mix. The audio policy and billing regression confirms that spoken audio over music qualifies, a measured defect of exactly 20% qualifies, and unresolved defects above 20% and verified non-speech have zero events. [Audio policy and allocation observations](https://github.com/aimansour/reelsaid/actions/runs/42559047994)

The wildlife and panel outputs passed the independently captioned checks after the quality fixes. The wildlife result contained the verified last sentence, with no unsupported tail words. Its other flagged gaps kept it partial. The panel's segment starts were chronological.

## Startup experiment

Alternating five local cold interpreter starts with and without a prepared bytecode cache reduced median application import from 1.951 to 0.685 seconds. The bytecode referenced on that path occupied 10.27 MB. Loading the classifier libraries only on the audio-analysis path separately reduced the local import median from 0.855 to 0.706 seconds across three runs per variant. The Docker build now compiles locked dependencies, the standard library, and the packaged source. The hosted check compares both single-Reel workloads across 256 MB, 512 MB, and 1024 MB and reruns the qualified batch. [uv Docker bytecode guidance](https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode)

In the hosted 512 MB extended case, the SDK-ready mark moved from 1.420 to 0.843 seconds after process entry. Container startup moved from 0.345 to 4.277 seconds between those runs. The precompiled slim build reached the extended first result in 5.76 seconds at 256 MB on a low-startup run. It reached the wildlife first result in 5.92 seconds at 512 MB and 7.43 seconds at 256 MB. This separates an application startup improvement from platform scheduling and container variance. [Hosted precompilation comparison](https://github.com/aimansour/reelsaid/actions/runs/42559522832)

Apify documents its standardized images as pre-cached on worker machines. A second matched cloud experiment used a digest-pinned official Python base with the same lockfile, precompilation, fixtures, and observer. The official image passed the caption and free-music checks. It produced the fastest observed 60-second result at 256 MB, at 5.27 seconds first and 6.12 seconds total. It also reduced the observed cold batch from 12.24 seconds first and 13.62 seconds total to 10.01 and 10.89 seconds. Other runs still had platform-to-process delays close to five seconds. Keep cold and low-startup observations separate. [Apify runtime caching](https://docs.apify.com/actors/development/performance#use-standardized-images-to-accelerate-actor-startup-times) · [Hosted base image comparison](https://github.com/aimansour/reelsaid/actions/runs/42559918421)

The official-base wildlife run at 256 MB delivered first text in 5.91 seconds and finished in 6.80. At 512 MB it delivered first text in 6.02 seconds and finished in 6.49. The total difference was smaller than the 0.35-second polling interval, and the 512 MB run consumed 0.000633 compute units versus 0.000315 at 256 MB. The 1024 MB case used 0.001383 compute units and finished in 7.36 seconds. Keep the existing single-video allocation, the previously measured batch and profile allocations, and the precompiled official base. This selection saves compute while preserving the measured output quality.

## Exact uninstrumented verification

The trusted public workflow built and measured private build `0.1.23` from the selected runtime. The actor stayed private and the existing default resolved to `0.1.9`. The five exact cases passed source identity, caption coverage, ordered timestamps, expected memory, and the free music contract. There were no stage or model instrumentation records on these runs. [Exact native verification](https://github.com/aimansour/reelsaid/actions/runs/42561458692)

| Workload | First usable text | Total | Compute units | Outcome |
| --- | ---: | ---: | ---: | --- |
| 60-second speech | 10.85 s | 11.44 s | 0.000664 | All four caption anchors and expected end |
| Wildlife | 9.59 s | 10.19 s | 0.000591 | Verified closing line, timed partial within the eligibility boundary |
| Music | — | 5.66 s | 0.000265 | `MUSIC_ONLY`, confidence 0.951, zero words and zero events |
| Panel | 4.93 s | 5.57 s | 0.000275 | All four anchors and chronological segment starts |
| Recent two-Reel batch | 4.43 s | 6.39 s | 0.000642 | Two qualified transcripts |

The batch outperformed the quality-equivalent Steadyfetch observation of 6.72 seconds first and 9.27 seconds total. The native single cases trailed Steadyfetch's matched 6.51/8.80-second extended and 5.30/6.64-second wildlife observations. Earlier low-startup runs beat the extended target. The exact results establish a batch lead on the tested workload and a remaining single-Reel speed gap for launch measurement.

The build initially succeeded while the CLI log stream stayed open until the workflow failed. The deployment script now polls the exact build and verifies its tag. A second failure exposed an oversized metadata response being passed as one shell argument. The receipt now carries only the confirmed status and numeric build version, and a regression covers a large metadata response. The final workflow passed with the exact runtime and kept the public log boundary intact.
