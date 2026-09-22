#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$0")/lib.sh"

MODE="${PCFX_SKILL_MODE:-select}"
SKILLS="${PCFX_SKILLS:-pcfx-bringup,pcfx-emulator-testing}"
OUTPUT="${1:-$PCFX_BUILD_DIR/pcfx-system.md}"
mkdir -p "$(dirname "$OUTPUT")"

if [[ "$MODE" == "select" ]]; then
    python3 "$PCFX_REPO_ROOT/PCFX_Skills/eval/build_prompt.py" \
        --mode select --skills "$SKILLS" --out "$OUTPUT"
else
    python3 "$PCFX_REPO_ROOT/PCFX_Skills/eval/build_prompt.py" \
        --mode "$MODE" --out "$OUTPUT"
fi
echo "wrote $OUTPUT"
