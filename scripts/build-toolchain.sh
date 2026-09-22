#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

MODE=copy
SOURCE_PATH=""
if [[ "${1:-}" == "--build" ]]; then
    MODE=build
elif [[ "${1:-}" == "--copy" ]]; then
    MODE=copy
    SOURCE_PATH="${2:-}"
elif [[ -n "${1:-}" ]]; then
    pcfx_die "usage: $0 [--copy PATH] [--build]"
fi

mkdir -p "$PCFX_TOOLCHAIN_DIR"

if [[ "$MODE" == copy ]]; then
    if [[ -z "$SOURCE_PATH" ]]; then
        SOURCE_PATH="$(pcfx_find_toolchain || true)"
    fi
    [[ -n "$SOURCE_PATH" ]] || pcfx_die "no existing V810_GCC found; pass --copy PATH or use --build"
    [[ -x "$SOURCE_PATH/bin/v810-gcc" ]] || pcfx_die "not a V810_GCC directory: $SOURCE_PATH"
else
    pcfx_need_command cp
    pcfx_need_command curl
    TOOLCHAIN_WORK="$PCFX_BUILD_DIR/v810-gcc-source"
    mkdir -p "$PCFX_BUILD_DIR"
    if [[ ! -x "$TOOLCHAIN_WORK/build_compiler.sh" ]]; then
        cp -a "$PCFX_REPO_ROOT/vendor/v810-gcc/." "$TOOLCHAIN_WORK/"
        rm -f "$TOOLCHAIN_WORK/.git"
    fi
    echo "TOOLCHAIN building from vendor/v810-gcc (this is a multi-stage GCC build)"
    (cd "$TOOLCHAIN_WORK" && ./build_compiler.sh)
    SOURCE_PATH="$TOOLCHAIN_WORK/v810-gcc"
    [[ -x "$SOURCE_PATH/bin/v810-gcc" ]] || pcfx_die "toolchain build finished without $SOURCE_PATH/bin/v810-gcc"
fi

destination="$PCFX_TOOLCHAIN_DIR/v810-gcc"
source_real="$(cd "$SOURCE_PATH" && pwd -P)"
destination_real="$(mkdir -p "$PCFX_TOOLCHAIN_DIR" && cd "$PCFX_TOOLCHAIN_DIR" && pwd -P)/v810-gcc"
if [[ "$source_real" != "$destination_real" ]]; then
    rm -rf "$destination"
    cp -a "$SOURCE_PATH" "$destination"
else
    echo "TOOLCHAIN already available at $destination"
fi
echo "TOOLCHAIN installed in $destination"
"$destination/bin/v810-gcc" --version | head -1
