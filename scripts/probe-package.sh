#!/usr/bin/env bash
set -euo pipefail

: "${PACKAGE_ROOT:?Set PACKAGE_ROOT to the public package checkout}"
: "${APIFY_TOKEN:?Set APIFY_TOKEN to an account with access to ReelSaid}"

umask 077
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
image=docker.n8n.io/n8nio/n8n:2.46.6
workflow_id=ReelSaidPackage1
credential_id=ReelSaidHeader1

jq -n --arg id "$credential_id" \
    '[{id:$id,name:"ReelSaid Apify",type:"httpHeaderAuth",
      data:{name:"Authorization",value:("Bearer " + env.APIFY_TOKEN)}}]' > "$scratch/credentials.json"
jq --arg id "$workflow_id" --arg credential "$credential_id" \
    '.id=$id | (.nodes[] | select(.name=="Transcribe Reel") | .credentials.httpHeaderAuth) =
      {id:$credential,name:"ReelSaid Apify"}' \
    "$PACKAGE_ROOT/examples/n8n/reelsaid.json" > "$scratch/workflow.json"

docker run --rm --user "$(id -u):$(id -g)" \
    --env N8N_USER_FOLDER=/verify --env N8N_DIAGNOSTICS_ENABLED=false \
    --env N8N_VERSION_NOTIFICATIONS_ENABLED=false --env N8N_COMMUNITY_PACKAGES_ENABLED=false \
    --mount "type=bind,source=$scratch,target=/verify" --entrypoint sh "$image" \
    -ec 'n8n import:credentials --input=/verify/credentials.json >/verify/import.log 2>&1
         n8n import:workflow --input=/verify/workflow.json >>/verify/import.log 2>&1
         n8n execute --id="$1" --rawOutput >/verify/result.json 2>/verify/execute.log' sh "$workflow_id"

# n8n also writes initialization messages to stdout with --rawOutput.
sed -n '/^{/,/^}/p' "$scratch/result.json" |
jq -se 'last | .data.resultData.runData["Map transcript"][0].data.main[0][0].json
    | .status == "success" and .language == "en" and .wordCount > 0
      and (.transcript | length > 0) and (.wordLevelTimestamps | length > 0)' >/dev/null
printf '%s\n' 'Fresh n8n workflow delivered a timed transcript to the mapping node.'
