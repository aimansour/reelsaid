#!/usr/bin/env bash
set -euo pipefail

scratch=$1
revision=$2
selection=${3:-head}
[[ $SOURCE_REPOSITORY =~ ^https://github\.com/[A-Za-z0-9-]+/reelsaid-core\.git$ ]]
[[ -z $revision || $revision =~ ^[0-9a-f]{40}$ ]]
umask 077
export GIT_TERMINAL_PROMPT=0
git -C "$scratch" init -q
if [[ $selection == approved ]]; then
    [[ -n $revision ]]
    git -C "$scratch" fetch --quiet --no-tags "$SOURCE_REPOSITORY" refs/heads/main
    git -C "$scratch" merge-base --is-ancestor "$revision" FETCH_HEAD
    fetched=$revision
else
    git -C "$scratch" fetch --quiet --depth=1 --no-tags "$SOURCE_REPOSITORY" refs/heads/main
    fetched=$(git -C "$scratch" rev-parse FETCH_HEAD)
    [[ -z $revision || $fetched == "$revision" ]]
fi
git -C "$scratch" checkout --quiet --detach "$fetched"
