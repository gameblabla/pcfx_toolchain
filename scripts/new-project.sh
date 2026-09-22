#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

project_name="${1:-}"
project_path="${2:-}"
[[ -n "$project_name" ]] || pcfx_die "usage: $0 NAME [DESTINATION]"
if [[ -z "$project_path" ]]; then
    project_path="$PCFX_REPO_ROOT/$project_name"
fi
[[ ! -e "$project_path" ]] || pcfx_die "destination already exists: $project_path"

mkdir -p "$project_path"
cp -a "$PCFX_REPO_ROOT/examples/hello/." "$project_path/"
cat > "$project_path/TOOLKIT_ORIGIN.txt" <<EOF
Generated from pcfx_toolchain/examples/hello.
Set V810GCC, LIBPCFX, and CDLINK as needed, then run: make cd
EOF
echo "created $project_path"
