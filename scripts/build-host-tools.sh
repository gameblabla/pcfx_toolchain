#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

pcfx_need_command gcc
mkdir -p "$PCFX_BIN_DIR" "$PCFX_BUILD_DIR"

host_cflags=( -O2 -Wall -Wextra -DNDEBUG )

build_one() {
    local source_path="$1"
    local output_name="$2"
    echo "HOST    $output_name"
    gcc "${host_cflags[@]}" -s "$source_path" -o "$PCFX_BUILD_DIR/host-$output_name"
    install -m 0755 "$PCFX_BUILD_DIR/host-$output_name" "$PCFX_BIN_DIR/$output_name"
}

build_one "$PCFX_REPO_ROOT/vendor/pcfxtools/bincat.c" bincat
build_one "$PCFX_REPO_ROOT/vendor/pcfxtools/huobj.c" huobj
build_one "$PCFX_REPO_ROOT/vendor/pcfxtools/hulib.c" hulib
build_one "$PCFX_REPO_ROOT/vendor/pcfxtools/pcfx-cdlink.c" pcfx-cdlink

# Keep the upstream tool available, but use a separate name for the enhanced
# streamed implementation used by large games.
build_one "$PCFX_REPO_ROOT/tools/large-game/pcfxtools/pcfx-cdlink.c" pcfx-cdlink-large

pcfx_hash_tree "$PCFX_BIN_DIR" > "$PCFX_TOOLCHAIN_DIR/host-tools.SHA256SUMS"
echo "HOST    installed in $PCFX_BIN_DIR"
