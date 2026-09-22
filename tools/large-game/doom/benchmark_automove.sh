#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

map=${1:-6}
start_fields=${2:-3000}
end_fields=${3:-6000}
wad=${DOOM1WAD:-../doom1.wad}
bios=${PCFX_BIOS_DIR:-$root/..}
prefix=${TMPDIR:-/tmp}/doom_pcfx_automove_e1m${map}

make clean
make DOOM1WAD="$wad" \
    EXTRA="-DDEV_WARP -DDEV_WARP_MAP=$map -DCOARSE_RENDER_PROFILE -DDEV_BENCH_AUTOMOVE"

capture()
{
    local fields=$1 dump=$2
    pcfx-headless --bios-dir "$bios" --pcfx --auto-run \
        --frames "$fields" --dump ram "$dump" doom_pcfx.cue || test -s "$dump"
    test "$(wc -c < "$dump")" -eq 2097152
}

capture "$start_fields" "${prefix}_${start_fields}.ram"
capture "$end_fields" "${prefix}_${end_fields}.ram"

python3 tools/read_render_profile.py "${prefix}_${end_fields}.ram" \
    --before "${prefix}_${start_fields}.ram"
