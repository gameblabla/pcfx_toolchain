#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

if [[ -n "${PCFX_HEADLESS:-}" && -x "$PCFX_HEADLESS" ]]; then
    emulator_path="$PCFX_HEADLESS"
elif [[ -x "$PCFX_BIN_DIR/pcfx-headless" ]]; then
    emulator_path="$PCFX_BIN_DIR/pcfx-headless"
elif [[ -x "$PCFX_REPO_ROOT/vendor/pcfxemu/pcfx-headless" ]]; then
    emulator_path="$PCFX_REPO_ROOT/vendor/pcfxemu/pcfx-headless"
else
    pcfx_die "pcfx-headless is not built; run scripts/build-headless.sh"
fi

if [[ "$#" -eq 0 ]]; then
    exec "$emulator_path" --help
fi

explicit_bios_arg=0
for run_arg in "$@"; do
    if [[ "$run_arg" == "--bios-dir" || "$run_arg" == --bios-dir=* ]]; then
        explicit_bios_arg=1
        break
    fi
done

if [[ -z "${PCFX_BIOS_DIR:-}" && "$explicit_bios_arg" -eq 0 ]]; then
    echo "NOTE    no PCFX_BIOS_DIR set; pcfx-headless will search its normal locations" >&2
    echo "NOTE    BIOS images are not included in this toolkit" >&2
fi

exec "$emulator_path" "$@"
