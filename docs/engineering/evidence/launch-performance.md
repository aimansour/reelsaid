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

## Continued native speed work

The owner chose to continue improving the native run before starting Standby. The Apify log identifies the image-pull interval on the exact single-Reel runs. It lasted 5.127 seconds on the extended clip and 4.384 seconds on wildlife. The batch pulled an already present image in 0.004 seconds. Steadyfetch's two observed workers pulled already present images in 0.003 and 0.004 seconds. These are observed cache conditions for those runs. They explain a material share of the exact latency gap.

The official base's Debian FFmpeg install fetched 130 MB of package archives and reported 455 MB of additional disk usage. The candidate compiles FFmpeg 9.0.2 in a disposable build stage using a source checksum verified against the official release signature. A local non-assembly build produced 27 MiB of stripped tools, or 12.61 MB gzip-compressed. Nine file fixtures across the accepted container families passed the runtime's probe, decoded as speech, and produced the lossless fallback. The hosted experiment retains the same actor runtime and uses the stage-built tools. [FFmpeg release verification](https://ffmpeg.org/download.html#releases) · [Lean-media cloud comparison](https://github.com/aimansour/reelsaid/actions/runs/42562430740)

Groq supports segment and word timestamp granularities. A separate paired check isolates the elapsed provider request and output quality with both timestamp options on the same inputs. Its experimental setting is owner-only. [Groq speech-to-text parameters](https://console.groq.com/docs/speech-to-text#using-the-api) · [Timestamp comparison](https://github.com/aimansour/reelsaid/actions/runs/42562867059)

The lean-media build completed in 6 minutes 44 seconds on its first hosted source compilation. It passed all eight measured cases with the selected allocation and retained the free music outcome. Its cold extended result arrived first at 9.27 seconds and completed at 10.12, against 10.85 and 11.44 for the previously verified image. The lean wildlife cold result remained close to the older cold run. With the image already present, extended reached 5.57/5.99 seconds and wildlife reached 5.57/6.92 seconds. Wildlife's differences from Steadyfetch's 5.30/6.64-second observations fall within the polling interval. The two qualified lean batch observations were 6.39/7.77 and 5.09/5.93 seconds. Both completed ahead of the measured Steadyfetch batch. The verified media tools are now the runtime's compiled layer.

Across four paired provider requests per timestamp mode, the median ASR stage was 747.8 milliseconds with word and segment timestamps and 725.9 milliseconds with segments alone. Both modes passed the four anchors on the extended clip. On wildlife, both segment-only results retained an unsupported ending and failed the closing-text check. Both word-timed results removed the unsupported ending and qualified. Retain word timing for quality analysis. The user-facing word-timestamp option still controls which fields are delivered.

The runtime mounts the pinned dependency installer during the dependency layer build. The installer is absent from the final image. The two subtitle files are written concurrently and the dataset row is delivered after both writes succeed. The timing trace observed separate write calls around 60 to 70 milliseconds each. The regression verifies the concurrent writes, output order, and a single billing event.

The earlier cloud retrieval probes measured the full bootstrap and GraphQL sequence at 0.893 and 1.008 seconds for the short Reel. The public post page took 0.953 and 0.803 seconds. For the Carousel, the post page varied from 0.636 to 2.069 seconds while bootstrap plus GraphQL took 0.866 and 1.067 seconds. The direct page remains a validated fallback. These timings favor keeping the primary GraphQL route while focusing the native speed work on image startup and delivery.

## Exact optimized build and fresh clips

Exact private build `0.1.26` passed all eight hosted checks with the compiled media layer and concurrent subtitle writes. The successful interruption test covers a failed WebVTT write after settlement, recovery of both subtitle files, and a single provider call and charge. The full local suite passed 85 tests with 13 fixture-dependent skips. [Exact optimized build](https://github.com/aimansour/reelsaid/actions/runs/42563669960)

| Workload | Image pull | First usable text | Total | Apify usage |
| --- | ---: | ---: | ---: | ---: |
| 60-second speech | 3.523 s | 9.73 s | 10.48 s | $0.000606 |
| 60-second speech, fresh repeat | 0.002 s | 5.71 s | 6.48 s | $0.000553 |
| Wildlife | 3.756 s | 10.14 s | 10.87 s | $0.000616 |
| Wildlife, fresh repeat | 0.003 s | 8.74 s | 9.48 s | $0.000601 |
| Music | 0.003 s | — | 7.38 s | $0.000472 |
| Panel | 0.003 s | 5.93 s | 6.68 s | $0.000556 |
| Two-Reel batch | 0.004 s | 7.42 s | 8.20 s | $0.000956 |
| Two-Reel batch, fresh repeat | 0.003 s | 6.13 s | 7.68 s | $0.000924 |

The fresh extended repeat beat the earlier Steadyfetch reference on both measures. The fresh wildlife repeat still trailed despite having the image on its worker. Both batches completed faster than the Steadyfetch reference. One was faster on both measures. The eight observations include zero words and zero events for music at confidence 0.951.

The holdout compared the same unseen videos and independently reviewed caption anchors on the exact private build, Steadyfetch, and Lance API. ReelSaid forced fresh transcription, and the four competitor runs charged for their deliveries without indicating a prior delivery. The physical image cache was evaluated separately using the platform's image-pull log timestamps. [Fresh single-Reel comparison](https://github.com/aimansour/reelsaid/actions/runs/42590758303)

| Clip | Actor | Image pull | First usable text | Total | Caption and timing gate |
| --- | --- | ---: | ---: | ---: | --- |
| Pyramid | ReelSaid | 4.277 s | 10.16 s | 10.58 s | Passed |
| Pyramid | Steadyfetch | 0.003 s | 5.86 s | 7.57 s | Passed |
| Pyramid | Lance API | 0.005 s | 22.00 s | 23.30 s | Failed |
| Glacier | ReelSaid | 0.002 s | 6.00 s | 6.85 s | Failed |
| Glacier | Steadyfetch | 0.004 s | 7.12 s | 9.24 s | Failed |
| Glacier | Lance API | 0.004 s | 15.48 s | 18.49 s | Failed |

The glacier clip did not produce a quality-qualified speed comparison. ReelSaid and Lance each matched three of four anchors. Steadyfetch matched two. ReelSaid substituted a word in the opening anchor while retaining the closing line and the original speech timing. The separate no-audio Reel returned `NO_AUDIO` in 4.80 seconds with zero words, zero events, and $0.000453 in owner-run Apify usage. Steadyfetch and Lance settled at $0.045 in event charges across the four fresh competitor observations.

The CPU-only dependency experiment targets the runtime layer added above the Apify base. The installed Linux wheel bundles contain separate GPU/compiler tooling, standalone ONNX native API binaries, and translation catalogs that the existing CPU inference and ISO language lookup paths do not load. A temporary isolated copy without those components passed all 37 focused audio, actor, media, and output cases. [Apify performance guidance](https://docs.apify.com/actors/development/performance) · [CPU runtime experiment](https://github.com/aimansour/reelsaid/actions/runs/42591376565)

The `0.1.27` experiment passed the same eight hosted quality checks. Image pulls for the two matched cold speech clips dropped from 3.52 to 2.87 seconds and from 3.76 to 3.00 seconds. Cold first/total changed from 9.73/10.48 to 8.68/9.36 on the extended clip and from 10.14/10.87 to 8.82/9.52 on wildlife. The warm runs delivered extended in 5.48/6.18 and wildlife in 6.90/7.58 seconds. Both warm batches led the Steadyfetch batch with 5.40/6.82 and 5.72/6.40 seconds. Music remained free at 0.951 classification confidence. That run had a 2.89-second image pull, so its total cannot be compared directly to the warm music baseline.

The pinned HTTP wheel contains removable native symbols. Stripping them saved 11.81 MB in a local gzip comparison. The stripped wheel imported successfully and passed the full local suite with the existing 13 skips. The selected dependency stage now strips it and omits the validated CPU-only payloads before copying the environment into the runtime. Build tools stay in the disposable stage. The exact optimized build `0.1.28` passed all ten hosted checks. [Exact CPU runtime verification](https://github.com/aimansour/reelsaid/actions/runs/42592043759)

| Workload | Image pull | First usable text | Total | Apify usage |
| --- | ---: | ---: | ---: | ---: |
| 60-second speech | 2.403 s | 7.16 s | 7.75 s | $0.000586 |
| 60-second speech, fresh repeat | 0.002 s | 5.00 s | 5.61 s | $0.000553 |
| Wildlife | 4.412 s | 9.44 s | 10.05 s | $0.000619 |
| Wildlife, fresh repeat | 0.003 s | 5.72 s | 6.34 s | $0.000565 |
| Music | 2.427 s | — | 8.80 s | $0.000502 |
| Panel | 2.476 s | 7.43 s | 8.06 s | $0.000587 |
| Two-Reel batch | 0.002 s | 5.57 s | 6.22 s | $0.000925 |
| Two-Reel batch, fresh repeat | 0.003 s | 4.51 s | 5.83 s | $0.000909 |
| Pyramid | 0.002 s | 4.92 s | 5.52 s | $0.000556 |
| Pyramid, fresh repeat | 0.003 s | 5.63 s | 6.32 s | $0.000566 |

Both pyramid repeats used fresh transcription on warm image workers. They matched the independently reviewed anchors and ending, and both completed ahead of Steadyfetch's warm 5.86/7.57-second run. The first result led by 0.94 seconds on the faster repeat and by 0.23 seconds on the other, within polling resolution for the latter. The warm extended case and both warm batches also led on first result and completion. The warm wildlife result remained 0.42 seconds behind on first text and completed 0.30 seconds sooner. The cold wildlife run still took 4.41 seconds to pull the image. No cold-worker Steadyfetch reference was observed, so the native cold-user speed gap remains open.

Four comparable instrumented cases at 256 MB put median wildlife discovery at 1.218 seconds, with a 2.283-second maximum. The guest setup accounted for up to 1.807 seconds. The median ASR stage was 0.705 seconds and independent classification 0.302 seconds. The measured retrieval tail warrants checking whether the first post request can safely omit a separate guest setup. The comparison uses new sessions and exact video and Carousel child matching.

The cloud probe compared fresh sessions in alternating order for the extended, wildlife, pyramid, and Carousel fixtures. Every stateless response returned HTTP 200 in 0.149–0.175 seconds, with roughly 512 KB of response data and zero matching videos. The current guest setup returned all six expected video identities across the four fixtures in 0.606–0.936 seconds. The Carousel returned all three children. The current path remains selected. An unsuccessful stateless request would add a round trip and over 500 KB before the same fallback. [Cloud retrieval verification](https://github.com/aimansour/reelsaid/actions/runs/42592966708)
