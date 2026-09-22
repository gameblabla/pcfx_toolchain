#!/usr/bin/env bash

set -euo pipefail

PCFX_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCFX_BUILD_DIR="${PCFX_BUILD_DIR:-$PCFX_REPO_ROOT/build}"
PCFX_PREBUILT_DIR="${PCFX_PREBUILT_DIR:-$PCFX_REPO_ROOT/prebuilt}"
PCFX_BIN_DIR="$PCFX_PREBUILT_DIR/bin"
PCFX_SDK_DIR="$PCFX_PREBUILT_DIR/sdk"

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
        "${V810GCC:-}"
        "$PCFX_PREBUILT_DIR/v810-gcc"
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
    [[ -n "$found" ]] || pcfx_die "V810 toolchain not found; set V810GCC, run scripts/build-toolchain.sh, or install /opt/v810-gcc"
    printf '%s\n' "$found"
}

pcfx_stage_linux64_toolchain() {
    local source="$PCFX_PREBUILT_DIR/v810-gcc"
    local destination="$PCFX_PREBUILT_DIR/v810-gcc-linux64"

    [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || return 0
    [[ -x "$source/bin/v810-gcc" ]] || return 0

    rm -rf -- "$destination"
    if ! cp -al -- "$source" "$destination" 2>/dev/null; then
        rm -rf -- "$destination"
        cp -a -- "$source" "$destination"
    fi
    echo "TOOLCHAIN staged Linux64 bundle at $destination"
}

pcfx_prebuilt_tool() {
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
    find "$root" -type f -print0 | sort -z | xargs -0 sha256sum
}
