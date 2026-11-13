#!/usr/bin/env bash
set -euo pipefail

manifest=$1
actor=$(apify api GET acts/aimansour~reelsaid --user-agent apify-agent-skills/apify-actor-development)
actor_id=$(jq -er '.data.id' <<< "$actor")
owner=$(jq -er '.data.userId' <<< "$actor")
list=$(apify api GET actor-tasks -p '{"limit":1000}' --user-agent apify-agent-skills/apify-actor-development)
jq -e '.data | .total == (.items | length)' <<< "$list" >/dev/null

same_config() {
    jq -e --argjson want "$1" '.data as $actual |
        $actual.input == $want.input and $actual.title == $want.title and
        $actual.description == $want.description and
        all($want.publicConfig | to_entries[]; $actual.publicConfig[.key] == .value)' <<< "$2" >/dev/null
}

definitions=$(jq -ec '.[]' "$manifest")
while IFS= read -r definition; do
    slug=$(jq -er '.slug | select(test("^reelsaid-[a-z0-9]+(-[a-z0-9]+)*$"))' <<< "$definition")
    wanted=$(jq -c '{input,title,description,publicConfig}' <<< "$definition")
    task_id=$(jq -er --arg slug "$slug" --arg owner "$owner" '
        [.data.items[] | select(.name == $slug and .userId == $owner)] |
        if length == 0 then "" elif length == 1 then .[0].id else error("Ambiguous task name") end
    ' <<< "$list")
    if [[ -z $task_id ]]; then
        jq -e '.data.isPublic == false' <<< "$actor" >/dev/null
        task_id=$(jq -c --arg actId "$actor_id" --arg name "$slug" '{actId:$actId,name:$name,input}' <<< "$wanted" |
            apify api POST actor-tasks -d - --user-agent apify-agent-skills/apify-actor-development | jq -er .data.id)
    fi
    path="actor-tasks/$task_id"
    current=$(apify api GET "$path" --user-agent apify-agent-skills/apify-actor-development)
    jq -e --arg id "$task_id" --arg slug "$slug" --arg actor "$actor_id" --arg owner "$owner" '
        .data | .id == $id and .name == $slug and .actId == $actor and .userId == $owner
    ' <<< "$current" >/dev/null
    if ! same_config "$wanted" "$current"; then
        jq -e '.data.isPublic != true and .data.publicConfig.publishedAt == null' <<< "$current" >/dev/null
        current=$(apify api PUT "$path" -d - --user-agent apify-agent-skills/apify-actor-development <<< "$wanted")
        same_config "$wanted" "$current"
    fi
    jq -cn --arg slug "$slug" --arg id "$task_id" '{slug:$slug,id:$id}'
done <<< "$definitions"
