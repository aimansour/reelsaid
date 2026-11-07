#!/usr/bin/env bash
set -euo pipefail

apify actors push --dir probes/instagram --wait-for-finish 300 --json
apify actors call aimansour/reelsaid-retrieval-probe --input '{}' --timeout 260 --memory 512 --silent --json
