#!/usr/bin/env bash

set -euo pipefail

PCFX_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCFX_BUILD_DIR="${PCFX_BUILD_DIR:-$PCFX_REPO_ROOT/build}"
PCFX_TOOLCHAIN_DIR="${PCFX_TOOLCHAIN_DIR:-$PCFX_REPO_ROOT/toolchain}"
PCFX_BIN_DIR="$PCFX_TOOLCHAIN_DIR/bin"
PCFX_SDK_DIR="$PCFX_TOOLCHAIN_DIR/sdk"

pcfx_die() {
    echo "pcfx-toolkit: $*" >&2
    exit 1
}

pcfx_need_command() {
    command -v "$1" >/dev/null 2>&1 || pcfx_die "required command not found: $1"
}

pcfx_find_toolchain() {
    local candidate
    local candidates=(
        "${V810_GCC:-}"
        "${V810GCC:-}"
        "$PCFX_TOOLCHAIN_DIR/v810-gcc"
        "/opt/v810-gcc"
    )
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate/bin/v810-gcc" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

pcfx_require_toolchain() {
    local found
    found="$(pcfx_find_toolchain || true)"
    [[ -n "$found" ]] || pcfx_die "V810 toolchain not found; set V810_GCC, run scripts/build-toolchain.sh, or install /opt/v810-gcc"
    printf '%s\n' "$found"
}

pcfx_bundled_tool() {
    local name="$1"
    if [[ -x "$PCFX_BIN_DIR/$name" ]]; then
        printf '%s\n' "$PCFX_BIN_DIR/$name"
        return 0
    fi
    if [[ -x "$PCFX_REPO_ROOT/vendor/pcfxemu/$name" ]]; then
        printf '%s\n' "$PCFX_REPO_ROOT/vendor/pcfxemu/$name"
        return 0
    fi
    return 1
}

pcfx_submodule_ready() {
    local path="$1"
    [[ -f "$path/.git" || -d "$path/.git" ]]
}

pcfx_hash_tree() {
    local root="$1"
    (cd "$root" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
}
