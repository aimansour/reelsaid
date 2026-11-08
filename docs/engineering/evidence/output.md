# Dataset and subtitle contract

The public result shape is versioned independently of the Actor build. It separates speech text, timing, post metadata, quality evidence, provenance, and confirmed billing. Each carousel child receives its own video identity and row. An unresolved input uses the same fields, with no video identity or metadata. A genuinely observed zero remains zero, while unavailable metadata remains null.

Sentence timing comes from aligning original-language text with available timed words. When a source supplies a segment or caption cue without exact sentence timing, the row reports the actual granularity. The hook includes words that start within the first three seconds and excludes words starting at or after the boundary. Subtitle files use the same verified timings and retain the original script.

Public workflow `42461181705` built and ran the output module as a private Actor. Apify run `TgM1F6V7uYw1JguYB` accepted one timed Japanese result and one invalid-input row. Its Run API exposed the dataset, summary, and subtitle collections. Both file records were retrieved through the API and retained their Japanese text. The summary reconciled one successful video, one unresolved input, and zero billed items.

The first cloud build rejected the 2020-12 metaschema reference after Apify CLI accepted it locally. Use Draft 7 for the native dataset and key-value JSON schemas. Apify adds signed query parameters to some Run API output links. The result row carries plain record URLs so callers can use their normal credentials. [Apify dataset schema](https://docs.apify.com/storage/dataset-schema) · [Apify output links](https://docs.apify.com/actors/development/actor-definition/output-schema)
