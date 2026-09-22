#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

pcfx_need_command make
mkdir -p "$PCFX_BIN_DIR"

echo "EMU     building pcfx-headless"
make -C "$PCFX_REPO_ROOT/vendor/pcfxemu" -f Makefile.headless \
    CHD=YES PRGNAME="$PCFX_BIN_DIR/pcfx-headless"

echo "EMU     building pcfx-headless-prof"
make -C "$PCFX_REPO_ROOT/vendor/pcfxemu" -f Makefile.headless \
    CHD=YES PROFILE=1 PRGNAME="$PCFX_BIN_DIR/pcfx-headless-prof"

chmod 0755 "$PCFX_BIN_DIR/pcfx-headless" "$PCFX_BIN_DIR/pcfx-headless-prof"
sha256sum "$PCFX_BIN_DIR/pcfx-headless" "$PCFX_BIN_DIR/pcfx-headless-prof" \
    > "$PCFX_PREBUILT_DIR/headless.SHA256SUMS"
echo "EMU     staged in $PCFX_BIN_DIR"
