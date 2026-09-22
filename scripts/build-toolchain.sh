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

mkdir -p "$PCFX_PREBUILT_DIR"

if [[ "$MODE" == copy ]]; then
    if [[ -z "$SOURCE_PATH" ]]; then
        SOURCE_PATH="$(pcfx_find_toolchain || true)"
    fi
    [[ -n "$SOURCE_PATH" ]] || pcfx_die "no existing V810GCC found; pass --copy PATH or use --build"
    [[ -x "$SOURCE_PATH/bin/v810-gcc" ]] || pcfx_die "not a V810GCC directory: $SOURCE_PATH"
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

rm -rf "$PCFX_PREBUILT_DIR/v810-gcc"
cp -a "$SOURCE_PATH" "$PCFX_PREBUILT_DIR/v810-gcc"
echo "TOOLCHAIN staged in $PCFX_PREBUILT_DIR/v810-gcc"
"$PCFX_PREBUILT_DIR/v810-gcc/bin/v810-gcc" --version | head -1
