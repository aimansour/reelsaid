#!/usr/bin/env bash
set -euo pipefail

wrapper=$1
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
marker="reelsaid-private-marker-$RANDOM-$RANDOM"
mkdir -p "$scratch/scripts"
cat > "$scratch/scripts/ci-verify" <<SCRIPT
#!/usr/bin/env bash
printf '%s\n' '$marker'
printf '%s\n' '$marker' >&2
test "\$1" = pass
SCRIPT

for mode in pass fail; do
    status=0
    output=$(bash "$wrapper" "$scratch" "$mode" 2>&1) || status=$?
    if [[ $output == *"$marker"* ]]; then
        echo 'Private command output reached the public stream.'
        exit 1
    fi
    if [[ $mode == pass ]]; then
        if [[ $status != 0 || $output != 'Private verification passed.' ]]; then
            echo 'Expected a clean public success signal.'
            exit 1
        fi
    elif [[ $status != 1 || $output != 'Private verification failed.' ]]; then
        echo 'Expected a clean public failure signal.'
        exit 1
    fi
done

echo 'Both public output isolation cases passed.'
