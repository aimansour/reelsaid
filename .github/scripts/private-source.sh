#!/usr/bin/env bash
set -euo pipefail

scratch=$1
revision=$2
selection=${3:-head}
[[ -n $SOURCE_KEY && -n $APIFY_TOKEN ]]
[[ $SOURCE_REPOSITORY =~ ^git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$ ]]
[[ -z $revision || $revision =~ ^[0-9a-f]{40}$ ]]
umask 077
printf '%s\n' "$SOURCE_KEY" > "$scratch/key"
printf '%s\n' 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' > "$scratch/known_hosts"
export GIT_SSH_COMMAND="ssh -i '$scratch/key' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile='$scratch/known_hosts' -o HostKeyAlgorithms=ssh-ed25519"
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
rm -f -- "$scratch/key"
