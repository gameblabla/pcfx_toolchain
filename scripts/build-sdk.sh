#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

toolchain_path="$(pcfx_require_toolchain)"
pcfx_need_command make

mkdir -p "$PCFX_PREBUILT_DIR" "$PCFX_SDK_DIR"
export V810GCC="$toolchain_path"
export PATH="$V810GCC/bin:$PATH"

echo "SDK     building libpcfx with $V810GCC"
make -C "$PCFX_REPO_ROOT/vendor/libpcfx" clean all V810GCC="$V810GCC" PREFIX=v810

rm -rf "$PCFX_SDK_DIR/include" "$PCFX_SDK_DIR/ldscripts"
mkdir -p "$PCFX_SDK_DIR/include" "$PCFX_SDK_DIR/ldscripts"
cp -a "$PCFX_REPO_ROOT/vendor/libpcfx/include/." "$PCFX_SDK_DIR/include/"
cp -a "$PCFX_REPO_ROOT/vendor/libpcfx/ldscripts/." "$PCFX_SDK_DIR/ldscripts/"
cp "$PCFX_REPO_ROOT/vendor/libpcfx/libpcfx.a" "$PCFX_SDK_DIR/libpcfx.a"
cp "$PCFX_REPO_ROOT/vendor/libpcfx/src/crt0.o" "$PCFX_SDK_DIR/crt0.o"
cp "$PCFX_REPO_ROOT/vendor/libpcfx/LICENSE" "$PCFX_SDK_DIR/LICENSE.libpcfx"
echo "SDK     staged in $PCFX_SDK_DIR"
