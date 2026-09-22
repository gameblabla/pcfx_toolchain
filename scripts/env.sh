#!/usr/bin/env bash

# Source this file from a shell:
#   source scripts/env.sh

set -euo pipefail
PCFX_ENV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PCFX_ENV_TOOLCHAIN="${V810GCC:-}"
if [[ -z "$PCFX_ENV_TOOLCHAIN" || ! -x "$PCFX_ENV_TOOLCHAIN/bin/v810-gcc" ]]; then
    if [[ -x "$PCFX_ENV_ROOT/prebuilt/v810-gcc/bin/v810-gcc" ]]; then
        PCFX_ENV_TOOLCHAIN="$PCFX_ENV_ROOT/prebuilt/v810-gcc"
    elif [[ -x /opt/v810-gcc/bin/v810-gcc ]]; then
        PCFX_ENV_TOOLCHAIN=/opt/v810-gcc
    fi
fi

if [[ -z "$PCFX_ENV_TOOLCHAIN" || ! -x "$PCFX_ENV_TOOLCHAIN/bin/v810-gcc" ]]; then
    echo "env.sh: no V810 toolchain found; run scripts/build-toolchain.sh" >&2
else
    export V810GCC="$PCFX_ENV_TOOLCHAIN"
    export PATH="$V810GCC/bin:$PATH"
fi

export PCFX_TOOLKIT_ROOT="$PCFX_ENV_ROOT"
export LIBPCFX="${LIBPCFX:-$PCFX_ENV_ROOT/vendor/libpcfx}"
export PCFX_HEADLESS="${PCFX_HEADLESS:-$PCFX_ENV_ROOT/prebuilt/bin/pcfx-headless}"
export PCFX_CDLINK_LARGE="${PCFX_CDLINK_LARGE:-$PCFX_ENV_ROOT/prebuilt/bin/pcfx-cdlink-large}"

echo "PC-FX environment: root=$PCFX_TOOLKIT_ROOT libpcfx=$LIBPCFX" >&2
if [[ -n "${V810GCC:-}" ]]; then
    echo "PC-FX environment: V810GCC=$V810GCC" >&2
fi
