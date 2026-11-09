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
