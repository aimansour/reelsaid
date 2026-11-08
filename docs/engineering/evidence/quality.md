# Speech classification and transcript quality

Measured on mono 16 kHz audio. The comparison uses known English speech, digital silence, white noise, a synthetic chord, CC0 solo piano, and speech mixed with that piano. The speech fixture begins in a separately verified public Reel. The synthetic chord has known zero speech. Its three tones provide a detector control with limited evidence about music. [Piano fixture and license](https://commons.wikimedia.org/wiki/File:Goldberg_Variations_01_Aria.ogg)

| Fixture | WebRTC voiced fraction | Silero voiced fraction | YAMNet mean music score |
| --- | ---: | ---: | ---: |
| English speech | 0.990 | 0.973 | 0.085 |
| Silence | 0.000 | 0.000 | 0.004 |
| White noise | 0.000 | 0.000 | 0.001 |
| Synthetic chord | 0.010 | 0.000 | 0.046 |
| Solo piano | 0.708 | 0.000 | 0.978 |
| Speech over piano | 0.988 | 0.973 | 0.474 |

The 9–12 second local cases took roughly 63–91 ms each for Silero. YAMNet took 60–91 ms with one CPU thread. Use Silero for speech timing and conditionally run YAMNet when Silero finds no sustained speech. Raw class scores measure the available signal on these fixtures. The calibration uses a 0.5 frame threshold, two adjacent frames for an initial speech span, a 0.65 music score for confident music, and a conservative unknown outcome for ambiguous speech. A verified piano sample receives a high music confidence. The synthetic chord and noise receive a free no-speech result. [Silero release and MIT license](https://github.com/snakers4/silero-vad/tree/v6.2.3) · [YAMNet model and license](https://www.kaggle.com/models/google/yamnet/tfLite/classification-tflite/1)

Prefer the direct audio or video URL when the transcript has plausible timing and coverage. Verify known local audio before ASR. Check uncertain transcripts with independent audio evidence, including late starts, early endings, sparse text, suspected repetition, and signs of music or weak speech. Keep confidence null when the fast path has no independent confidence score. Only select separately supplied, timed original-language captions that pass the same speech-coverage check. The Instagram caption under a post stays in metadata.

Use the media timeline as the denominator for the union of affected intervals. Evaluate speech spans against available word and segment times. At exactly 20% a usable partial is eligible. Above 20% attempt the second approved model. When the defect has a short contiguous repair window, reuse retained audio and align the replacement timestamps to the full timeline. Reassess the result and preserve a usable uncharged partial when the defect remains above the boundary or its coverage is uncertain.

Private Apify run `6G2HuTcDyiULMNhcy` in public verification workflow `42460164921` used the product quality module. The real English and Spanish Reels passed with timed speech and zero measured defect. The speech-over-piano case also passed. Digital silence finished in 57 ms, and solo piano in 158 ms with confidence 0.979. Both took the free path before ASR. The long NASA candidate had ambiguous speech evidence and returned a usable uncharged partial after repair. Its ground truth remains unverified.
