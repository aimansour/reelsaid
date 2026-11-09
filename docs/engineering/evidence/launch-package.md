# Launch package review

## Store and GitHub reading paths

| Reference | Observed approach | ReelSaid decision |
| --- | --- | --- |
| [Steadyfetch](https://apify.com/steadyfetch/instagram-reel-transcript-scraper) | Early pricing and a Console or API sample lead into a compact input-to-output table and live transcript rows. An empty request invokes its billed sample. The integration and Server details live further down. | Lead with an explicit Console action and a real result excerpt. The sample is a normal transcription when submitted. Keep absent or malformed API input separate from the sample. |
| [Lance API](https://apify.com/lance_api/instagram-video-transcript-scraper) | Explains text, timed segments, subtitle formats, and exclusions before a five-step Console trial, then puts sample JSON and complete field references nearby. | Make the Console trial three steps. Give readers the plain-language output table next and move the field and endpoint reference to the API recipes. |
| [Panix](https://apify.com/panix/instagram-reel-transcript) | Leads with differentiators, charging policy, timestamps, account monitoring, and a comparison table, followed by input examples. | Put creator and marketing outcomes before options. Explain the real charging policy in one section and keep recognition model routing internal. |
| [TubeText](https://apify.com/tubetext/instagram-reels-transcript) | Gives no-code and MCP quickstarts their own headings before a synchronous API example. | Give agent users a ready-to-use prompt and an explicit source contract. Explain the native batch path and the one-video Standby path separately. |
| [APISmith](https://apify.com/apple_yang/instagram-transcripts-scraper) | Leads with two modes and detailed capability and data tables before Console instructions. Profile mode returns metadata. | Bring the trial forward. Show that a public profile can supply videos for transcription. Keep the full field list in the input form and API recipes. |
| [Headply](https://apify.com/headply/instagram-reels-transcript-scraper) | Early table covers inputs, outputs, languages, schedule, setup, and cost, followed by clear audience examples. | Keep comparable scannability with a short result table. Use specific jobs for editors, marketers, researchers, and agents. |
| [Quarra](https://apify.com/quarra/instagram-transcript-scraper) | Opens with transcription and policy, then presents its own benchmark and extensive implementation and language detail before the examples. | Preserve original-language and timing promises, put the sample near the top, and keep comparative speed, quality scoring, and implementation in private evidence. |
| [Apify Instagram Scraper](https://apify.com/apify/instagram-scraper) and [Google Maps Scraper](https://apify.com/compass/crawler-google-places) | The skill's reference listings use outcome-focused headings, plain-language input patterns, and separate technical sections for concrete tasks. | Use headings that answer user questions. Keep the public README usable on GitHub and Store by staging its body under Apify's own title. |

The release candidate uses the same primary source in the Console prefill, the native sample, the Standby example, and the existing no-code templates. The private Store build stores the staged body from the exact public GitHub package revision. The Store renderer supplies its own title. The GitHub README supplies the brand heading and its existing linked asset. [Actor README guidance](https://docs.apify.com/actors/publishing/actor-readme) · [Actor quality score](https://docs.apify.com/actors/publishing/quality-score)

## Discovery metadata

The Actor API exposes title, description, SEO title, SEO description, and categories. The agent response format surfaces title, description, and categories. Apify MCP retrieves the input and output contracts and the README through the Actor details tool. Use the same customer-facing vocabulary across the input schema, Store description, API examples, and `llms.txt`. The API has build tags for version routing. Discovery uses the documented category and text fields. [Update Actor](https://docs.apify.com/api/v2/actor-put) · [Store response formats](https://docs.apify.com/api/v2/store-get) · [Apify MCP discovery](https://docs.apify.com/mcp)

| Store category candidates | Decision |
| --- | --- |
| `SOCIAL_MEDIA`, `VIDEOS`, `AI` | Select in this order. Instagram is the source, video transcription is the purpose, and speech recognition is central to the output. |
| `FOR_CREATORS`, `MARKETING`, `AUTOMATION` | Real audiences and workflows. Cover them in the use cases and task copy so the main categories stay centered on the source and result. |
| `DEVELOPER_TOOLS`, `INTEGRATIONS`, `AGENTS` | Explain the API, automation recipes, and native MCP support. These are ways to use the product. |
| `MCP_SERVERS`, `OPEN_SOURCE`, `DEVELOPER_EXAMPLES` | The interface is a transcript API exposed through Apify's MCP. The public repository contains the product documentation and examples. |
| `BUSINESS`, `EDUCATION`, `NEWS`, `SEO_TOOLS` | Some users in these groups benefit from transcripts. Their categories describe broad destinations for the text. |
| `COVID_19`, `ECOMMERCE`, `GAMES`, `JOBS`, `LEAD_GENERATION`, `OTHER`, `REAL_ESTATE`, `SPORTS`, `TRAVEL` | Available in Apify's category constants. None describes this product's primary source or action. |

GitHub topics cover source (`instagram`, `instagram-reels`, `instagram-transcript`), action (`video-to-text`, `transcription`, `speech-to-text`, `whisper`), output (`subtitles`, `srt`, `webvtt`), and integration (`apify`, `mcp`, `n8n`, `make-com`, `zapier`). The existing `make` topic is broader and can be confused with the build tool. Use `make-com` for the published blueprint. Generic AI, programming-language, and web-scraping labels would be less precise for a repository whose public content is usage and integration material. [GitHub topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)

The title names the brand and the task users search for. The Store description prioritizes transcript, language, timestamps, subtitles, and available inputs. The separate search description is 145 characters and keeps the actual outputs visible. The long-form copy uses natural phrases such as “Instagram Reels to text”, “Instagram Reels transcript API”, and “word-by-word timing” where they answer the reader's question.
