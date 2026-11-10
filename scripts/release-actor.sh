#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname "$0")/.."
umask 077

actor=acts/aimansour~reelsaid
mode=$1
scratch=$(mktemp -d)
rehearsal_version=
previous_options=
cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n $previous_options ]]; then
        apify api PUT "$actor" -d "$previous_options" >/dev/null || result=1
    fi
    if [[ -n $rehearsal_version ]]; then
        apify api DELETE "$actor/versions/$rehearsal_version" >/dev/null || result=1
    fi
    rm -rf -- "$scratch"
    exit "$result"
}
trap cleanup EXIT
trap 'printf "Release operation failed at line %s.\n" "$LINENO" >&2' ERR

get_actor() {
    apify api GET "$actor" > "$scratch/actor.json" || return
    jq -e '.data.isSourceCodeHidden == true and .data.actorPermissionLevel == "LIMITED_PERMISSIONS"' \
        "$scratch/actor.json" >/dev/null
}

default_build() {
    apify api GET "$actor/builds/default" | jq -er '.data | select(.status == "SUCCEEDED") | .id'
}

set_default() {
    jq -c --arg build "$1" '{defaultRunOptions:(.data.defaultRunOptions | .build=$build)}' "$scratch/actor.json" |
        apify api PUT "$actor" -d - > "$scratch/update.json"
    jq -e --arg build "$1" '.data.defaultRunOptions.build == $build and .data.isSourceCodeHidden' \
        "$scratch/update.json" >/dev/null
}

check_build() {
    apify api GET "actor-builds/$1" > "$scratch/build.json"
    jq -e --arg actor "$(jq -er .data.id "$scratch/actor.json")" '.data |
        .actId == $actor and .status == "SUCCEEDED" and .options.useCache
        and (.imageDigest | test("^(sha256:)?[0-9a-f]{64}$"))
        and (.inputSchema | length > 0)' "$scratch/build.json" >/dev/null
}

smoke() {
    local build_id=$1 force_refresh=$2 run_dataset
    check_build "$build_id"
    jq -c --argjson refresh "$force_refresh" '
        .data.inputSchema | fromjson | .properties | to_entries |
        map(select(.value | has("prefill")) | {key, value:.value.prefill}) | from_entries |
        if $refresh then . + {forceRefresh:true,wordLevelTimestamps:true} else . end' "$scratch/build.json" > "$scratch/input.json"
    jq -e '.startUrls | length == 1' "$scratch/input.json" >/dev/null
    jq -cn --arg build "$(jq -er .data.buildNumber "$scratch/build.json")" \
        '{build:$build,timeout:120,waitForFinish:60}' > "$scratch/options.json"
    apify api POST "$actor/runs" -p "$(cat "$scratch/options.json")" -d - \
        < "$scratch/input.json" > "$scratch/run.json"
    run_dataset=$(jq -er --arg id "$build_id" '.data | select(.status == "SUCCEEDED" and .buildId == $id
        and .stats.durationMillis < 300000) | .defaultDatasetId' "$scratch/run.json")
    apify datasets get-items "$run_dataset" --format json > "$scratch/rows.json"
    jq -e 'length == 1 and .[0].status == "success" and .[0].language == "en"
        and (.[0].transcript | length > 0) and .[0].wordCount >= 20
        and .[0].subtitles.srt != null and .[0].subtitles.vtt != null' "$scratch/rows.json" >/dev/null
    if [[ $force_refresh == true ]]; then
        jq -e '.[0].cached == false and (.[0].wordLevelTimestamps | length >= 20)' "$scratch/rows.json" >/dev/null
    fi
}

reject_empty() {
    local dataset options
    options=$(jq -cn --arg build "$1" '{build:$build,timeout:50,waitForFinish:45}')
    apify api POST "$actor/runs" -p "$options" > "$scratch/empty-run.json"
    dataset=$(jq -er '.data | select(.status == "SUCCEEDED") | .defaultDatasetId' "$scratch/empty-run.json")
    apify datasets get-items "$dataset" --format json |
        jq -e 'length == 1 and .[0].errorCode == "NO_SOURCE" and .[0].charged == false' >/dev/null
}

release_store() {
    local id
    id=$(apify api POST key-value-stores -p '{"name":"reelsaid-release-private"}' -d '{}' | jq -er .data.id)
    apify api PUT "key-value-stores/$id" -d '{"generalAccess":"RESTRICTED"}' |
        jq -er --arg id "$id" '.data | select(.id == $id and .generalAccess == "RESTRICTED") | .id'
}

digest() {
    local hash
    hash=$(sha256sum -- "$1") || return
    printf '%s\n' "${hash%% *}"
}

check_openapi() {
    jq -e --slurpfile expected .actor/web_server_schema.json \
        '.data.actorDefinition.webServerSchema == $expected[0]' "$scratch/build.json" >/dev/null
}

verified_tasks() {
    local definitions definition slug proof task_id
    definitions=$(jq -ec '.[]' "$task_manifest")
    while IFS= read -r definition; do
        slug=$(jq -er '.slug' <<< "$definition")
        proof=$(apify api GET "key-value-stores/$store/records/TASK-$slug")
        task_id=$(jq -er --arg slug "$slug" --arg build "$build_number" \
            'select(.verified == true and .slug == $slug and .build == $build) | .id' <<< "$proof")
        apify api GET "actor-tasks/$task_id" | jq -e --argjson want "$definition" \
            --arg actor "$actor_id" --arg id "$task_id" '
                .data as $task |
                $task.actId == $actor and $task.id == $id and $task.name == $want.slug and $task.options == null and
                $task.input == $want.input and $task.title == $want.title and $task.description == $want.description and
                all($want.publicConfig | to_entries[]; $task.publicConfig[.key] == .value)
            ' >/dev/null
        jq -cn --arg slug "$slug" --arg id "$task_id" '{slug:$slug,id:$id}'
    done <<< "$definitions"
}

get_actor
if [[ $mode == periodic ]]; then
    smoke "$(default_build)" true
    printf '%s\n' 'The deployed Actor returned a timed transcript.'
    exit
fi

: "${PACKAGE_ROOT:?Set PACKAGE_ROOT to the approved public checkout}"
source_revision=$2
package_revision=$3
[[ $source_revision =~ ^[0-9a-f]{40}$ && $package_revision =~ ^[0-9a-f]{40}$ ]]
[[ $(git rev-parse HEAD) == "$source_revision" ]]
[[ $(git -C "$PACKAGE_ROOT" rev-parse HEAD) == "$package_revision" ]]

actor_id=$(jq -er .data.id "$scratch/actor.json")
task_manifest="$PACKAGE_ROOT/store/tasks.json"
task_digest=$(digest "$task_manifest")
openapi_digest=$(digest .actor/web_server_schema.json)
store=$(release_store)
receipt="key-value-stores/$store/records/CANDIDATE"
case "$mode" in
    candidate)
        stable_id=$(default_build)
        if jq -e '.data.isPublic == false' "$scratch/actor.json" >/dev/null; then
            jq -c '. + {isSourceCodeHidden:true,exampleRunInput:null}' "$PACKAGE_ROOT/store/listing.json" |
                apify api PUT "$actor" -d - >/dev/null
            get_actor
        fi
        bash scripts/deploy-actor.sh "$PACKAGE_ROOT" candidate > "$scratch/deployment.json"
        build_id=$(jq -er '.build | select(.status == "SUCCEEDED") | .id' "$scratch/deployment.json")
        [[ $(default_build) == "$stable_id" ]]
        smoke "$build_id" false
        first_run=$(jq -er .data.id "$scratch/run.json")
        smoke "$build_id" true
        fresh_run=$(jq -er .data.id "$scratch/run.json")
        build_number=$(jq -er .data.buildNumber "$scratch/build.json")
        bash scripts/store-readme "$PACKAGE_ROOT/README.md" > "$scratch/store-readme.md"
        jq -ej .data.actorDefinition.readme "$scratch/build.json" | cmp - "$scratch/store-readme.md"
        apify api GET "$actor/versions/0.1" > "$scratch/version.json"
        jq -e '.data.applyEnvVarsToBuild == false and .data.buildTag == "candidate" and
            any(.data.envVars[]; .name == "REELSAID_GROQ_KEYS" and .isSecret == true) and
            all(.data.sourceFiles[]; .name | endswith(".pyc") | not)' "$scratch/version.json" >/dev/null
        check_openapi
        reject_empty "$build_number"
        bash scripts/probe-launch-tasks.sh "$task_manifest"
        verified_tasks > "$scratch/tasks.jsonl"
        previous_options=$(jq -c '{actorStandby:.data.actorStandby}' "$scratch/actor.json")
        python3 scripts/verify-standby-runtime.py "$build_number" "$scratch/standby.json"
        get_actor
        jq -e --slurpfile expected "$scratch/standby.json" '.data.actorStandby == $expected[0]' \
            "$scratch/actor.json" >/dev/null
        jq -cn --arg source "$source_revision" --arg package "$package_revision" --arg buildId "$build_id" \
            --arg build "$build_number" --arg firstRun "$first_run" --arg freshRun "$fresh_run" \
            --arg openApiSha256 "$openapi_digest" --arg taskManifestSha256 "$task_digest" \
            --slurpfile tasks "$scratch/tasks.jsonl" --slurpfile standby "$scratch/standby.json" \
            '{source:$source,package:$package,buildId:$buildId,build:$build,firstRun:$firstRun,freshRun:$freshRun,
              openApiSha256:$openApiSha256,taskManifestSha256:$taskManifestSha256,tasks:$tasks,standbySettings:$standby[0]}' |
            apify api PUT "$receipt" -d - >/dev/null
        previous_options=
        ;;
    rehearse|publish)
        apify api GET "$receipt" > "$scratch/receipt.json"
        build_id=$(jq -er --arg source "$source_revision" --arg package "$package_revision" \
            --arg openapi "$openapi_digest" --arg tasks "$task_digest" '
                select(.source == $source and .package == $package and
                       .openApiSha256 == $openapi and .taskManifestSha256 == $tasks) | .buildId
            ' "$scratch/receipt.json")
        check_build "$build_id"
        build_number=$(jq -er .data.buildNumber "$scratch/build.json")
        jq -e --arg build "$build_number" '.build == $build' "$scratch/receipt.json" >/dev/null
        check_openapi
        verified_tasks > "$scratch/tasks.jsonl"
        jq -e --slurpfile tasks "$scratch/tasks.jsonl" '.tasks == $tasks' "$scratch/receipt.json" >/dev/null
        jq -e --arg build "$build_number" --slurpfile receipt "$scratch/receipt.json" '
            .data.actorStandby.isEnabled == true and .data.actorStandby.build == $build and
            .data.actorStandby == $receipt[0].standbySettings
        ' "$scratch/actor.json" >/dev/null
        ;;
    *)
        exit 2
        ;;
esac

if [[ $mode == rehearse ]]; then
    jq -e '.data.isPublic == false' "$scratch/actor.json" >/dev/null
    stable_id=$(default_build)
    rehearsal_version=0.99
    version_input=$(jq -cn --arg version "$rehearsal_version" '{versionNumber:$version,sourceType:"SOURCE_FILES",
        buildTag:"rehearsal-failure",applyEnvVarsToBuild:false,
        sourceFiles:[{name:"Dockerfile",format:"TEXT",content:"FROM scratch\nRUN [\"/reelsaid-intentional-failure\"]\n"}]}')
    if ! apify api POST "$actor/versions" -d "$version_input" >/dev/null; then
        rehearsal_version=
        exit 1
    fi
    apify api POST "$actor/builds" -p "{\"version\":\"$rehearsal_version\",\"waitForFinish\":60,\"useCache\":true}" \
        -d '{}' > "$scratch/rehearsal.json"
    jq -e '.data.status == "FAILED"' "$scratch/rehearsal.json" >/dev/null
    [[ $(default_build) == "$stable_id" ]]
    previous_options=$(jq -c '{defaultRunOptions:.data.defaultRunOptions,actorStandby:.data.actorStandby}' "$scratch/actor.json")
    set_default "$build_number"
    [[ $(default_build) == "$build_id" ]]
    smoke "$build_id" false
    apify api PUT "$actor" -d "$previous_options" >/dev/null
    [[ $(default_build) == "$stable_id" ]]
    get_actor
    jq -e --argjson previous "$previous_options" '.data.actorStandby == $previous.actorStandby' \
        "$scratch/actor.json" >/dev/null
    previous_options=
fi

if [[ $mode == publish ]]; then
    : "${RELEASE_PRICING_SHA256:?An approved effective price schedule is required}"
    jq -ecS '[.data.pricingInfos[]? |
        select((.startedAt | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) <= now)] |
        max_by(.startedAt) | select(.pricingModel == "PAY_PER_EVENT")' \
        "$scratch/actor.json" > "$scratch/pricing.json"
    read -r pricing_digest _ < <(sha256sum "$scratch/pricing.json")
    [[ $pricing_digest == "$RELEASE_PRICING_SHA256" ]]
    smoke "$build_id" false
    jq -c --arg build "$build_number" --slurpfile actor "$scratch/actor.json" '
        . + {isPublic:true,isSourceCodeHidden:true,exampleRunInput:null,
        defaultRunOptions:($actor[0].data.defaultRunOptions | .build=$build),
        actorStandby:($actor[0].data.actorStandby | .build=$build)}' \
        "$PACKAGE_ROOT/store/listing.json" > "$scratch/promotion.json"
    for attempt in 1 2 3; do
        apify api PUT "$actor" -d - < "$scratch/promotion.json" >/dev/null || true
        if get_actor && jq -e --slurpfile approved "$scratch/promotion.json" '
            .data as $actor | all($approved[0] | to_entries[]; $actor[.key] == .value)' \
            "$scratch/actor.json" >/dev/null && [[ $(default_build) == "$build_id" ]]; then
            printf '%s\n' 'Release operation verified.'
            exit 0
        fi
        sleep "$attempt"
    done
    exit 1
fi

printf '%s\n' 'Release operation verified.'
