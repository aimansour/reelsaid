# Runner monitoring evidence

## Local Actor runtime

Apify CLI launches the Python package from an isolated scratch directory. The SDK writes the default dataset and key-value store locally. The Actor uses the same run, discovery, media, and quality functions as its cloud entry point. Local state reuses the storage record format with process-scoped ownership. The production cloud state and event settlement use their existing interfaces. [Apify local storage](https://docs.apify.com/sdk/python/docs/concepts/storages)

All four CLI integration cases failed at the original cloud-only guard. After adding local execution, the valid fixture produced a schema-valid transcript row and one transcription call. The absent body, empty JSON, and misspelled field produced schema-valid uncharged input errors and zero transcription calls. The full local suite passed 79 tests.

The public manual runner check pinned private revision `4ad0be2`. It ran the CLI tests and obtained a fresh ASR transcript for the spoken Reel `DS46KJNjva9`, with timed words and SRT and WebVTT records in runner-local storage. The runner check receives a scoped provider credential and uses a loopback Apify API address. The Apify deployment token is absent from this check. The full job succeeded in 55 seconds. [Hosted runner verification](https://github.com/aimansour/reelsaid/actions/runs/42509744551)

## Schedule and notification route

The public runner health workflow schedules the same pinned runner-local check at 06:23 and 18:23 UTC. Explicit cloud checks use the separate Verify workflow. The schedule was committed and pushed through the owner's GitHub account.

GitHub Actions delivers workflow email according to the owner's notification preferences. The owner accepted this route and waived physical inbox confirmation. A failed job retains its failure status. The public run includes a sanitized stage annotation and a link for investigation. The shell-level tests cover source failure, runtime failure, a runtime timeout, successful completion, and suppression of private diagnostic output. [GitHub workflow notifications](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)

Manual dispatch exercised the same workflow with controlled source and runtime failures and a normal runner transcription. Both failure runs retained the failed conclusion and published one stage annotation with the corresponding run URL. The normal run succeeded. The public logs passed the private marker and credential pattern checks. [Source failure](https://github.com/aimansour/reelsaid/actions/runs/42510123003) · [Runtime failure](https://github.com/aimansour/reelsaid/actions/runs/42510175056) · [Successful runner check](https://github.com/aimansour/reelsaid/actions/runs/42510255355)
