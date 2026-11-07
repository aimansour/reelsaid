# GitHub automation verification

The public repository `aimansour/reelsaid` runs the verification workflow at revision `c890782`. The private source repository `aimansour/reelsaid-core` is private, has Actions disabled, and reports zero runs. Its automation deploy key is read-only and limited to that repository.

| Public run | Observed result |
| --- | --- |
| `42410079545` | Success. A pinned checkout of private commit `ceda4bc` ran an authenticated Apify CLI account listing. |
| `42410082286` | Expected failure with the generic verification failure message. |
| `42410134548` | Expected rejection of a SHA that did not match the private branch tip. |

The local test failed before the public wrapper existed and passed after it was added. It exercised private stdout, stderr, and exit handling. Actionlint passed. The three public run logs were inspected for the private canary, source repository locator, and credential-shaped strings. None were present. GitHub reported zero public Actions artifacts and cache entries.

The current workflow is a manually dispatched verification lane. Production release, scheduled checks, and build caching are verified in their assigned tasks.
