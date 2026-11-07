# ReelSaid engineering decisions

## Repository boundary

The public packaging repository `aimansour/reelsaid` owns Actions runs. The private source repository `aimansour/reelsaid-core` has Actions disabled. A dedicated read-only SSH deploy key grants the public verifier access to the private source. Store the key, repository locator, and Apify authentication in GitHub Actions secrets.

The owner dispatches verification from the public default branch with a full commit SHA. The workflow fetches the private `main` tip and verifies its SHA before executing. Private output is suppressed at the public runner boundary. Public verification returns a generic success or failure message and uses ephemeral GitHub-hosted runners. Future tasks will store their detailed run evidence on trusted surfaces.

Use Apify CLI 1.11.0 for the initial account check. This version is for automation and does not choose the Actor's runtime.
