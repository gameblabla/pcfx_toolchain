#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/.." && pwd)
source_root="$repo_root/PCFX_Skills"

[[ -d "$source_root" ]] || {
    printf 'missing skill source: %s\n' "$source_root" >&2
    exit 1
}

for destination_root in "$repo_root/.agents/skills" "$repo_root/.opencode/skills"; do
    mkdir -p "$destination_root"
    for source_dir in "$source_root"/*; do
        [[ -f "$source_dir/SKILL.md" ]] || continue
        skill_id=${source_dir##*/}
        destination="$destination_root/$skill_id"
        rm -rf -- "$destination"
        cp -a -- "$source_dir" "$destination"
    done
done

printf 'synced PC-FX skills from %s\n' "$source_root"
