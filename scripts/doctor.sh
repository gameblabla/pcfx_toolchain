#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
    STRICT=1
fi

for command_name in git make gcc python3 tar sha256sum; do
    if command -v "$command_name" >/dev/null 2>&1; then
        echo "ok      $command_name: $(command -v "$command_name")"
    else
        echo "missing $command_name"
        STRICT=1
    fi
done

for dependency_path in vendor/v810-gcc vendor/libpcfx vendor/pcfxtools vendor/pcfxemu vendor/doompcfx; do
    if pcfx_submodule_ready "$PCFX_REPO_ROOT/$dependency_path"; then
        echo "ok      $dependency_path populated"
    else
        echo "missing $dependency_path (run: git submodule update --init --recursive)"
        STRICT=1
    fi
done

if toolchain_path="$(pcfx_find_toolchain || true)"; then
    echo "ok      V810_GCC: $toolchain_path"
    "$toolchain_path/bin/v810-gcc" --version | head -1
else
    echo "warn    V810_GCC: not found (host-only checks still work)"
fi

if [[ -x "$PCFX_BIN_DIR/pcfx-headless" ]]; then
    echo "ok      pcfx-headless: $PCFX_BIN_DIR/pcfx-headless"
else
    echo "warn    pcfx-headless: not built (run scripts/build-headless.sh)"
fi

if [[ -n "${PCFX_BIOS_DIR:-}" ]]; then
    if [[ -f "$PCFX_BIOS_DIR" || -d "$PCFX_BIOS_DIR" ]]; then
        echo "ok      PCFX_BIOS_DIR: $PCFX_BIOS_DIR (not copied or packaged)"
    else
        echo "warn    PCFX_BIOS_DIR does not exist: $PCFX_BIOS_DIR"
    fi
else
    echo "note    no PCFX_BIOS_DIR set; BIOS is intentionally external"
fi

if [[ "$STRICT" -eq 1 ]]; then
    if ! pcfx_find_toolchain >/dev/null 2>&1; then
        pcfx_die "doctor found required setup errors"
    fi
fi
