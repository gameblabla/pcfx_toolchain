#!/bin/bash
# gen_mappack_manifest.sh -- regenerate generated/mappack_manifest.txt, the authoritative
# per-map precache set the pack builder (tools/gen_pcfx_packs.py) consumes.
#
# For each E1 map it builds the engine with -DGEN_MAPPACK_MANIFEST. In that mode
# P_SpawnMapThing admits the union of easy, normal, and hard single-player things,
# then R_PrecacheLevel publishes their combined reserved lump set in reserve order
# through a compact RAM marker. This union is required: a normal-only manifest
# makes hard-only monsters collide and attack on Ultra-Violence while their
# missing sprite lumps resolve to the transparent gameplay fallback. Maps that
# fail to load (e.g. a pre-existing map-load OOM) are skipped with a warning.
#
# One build+run per map, only needed when doom1.wad or the precache logic changes;
# the result is checked in so normal builds never run the emulator.
#
# FRAMES only needs to cover boot + CD-load of the level far enough for
# R_PrecacheLevel/W_PrecacheEnd to fire and log the MAPPACK dump -- it does NOT
# need to simulate real play. That happens within the first ~150-450 engine
# frames after warp (measured: E1M1 lands its dump by frame ~150, E1M9 -- the
# heaviest map -- by ~450), so 8000 is a wide safety margin, not a tight bound.
# The previous default of 80000 was 10x oversized and cost ~5 min/map (~45 min
# total across BOOT + 9 maps) for no extra coverage; 8000 measures at ~30s/map
# (~5 min total) with the same result. If a future map's load genuinely needs
# more headroom, raise FRAMES for that run rather than the shared default.
set -u
cd "$(dirname "$0")/.."
WAD="${1:-../doom1.wad}"
OUT=generated/mappack_manifest.txt
BIOSDIR="$PWD/.."
EMU="${PCFX_HEADLESS:-../pcfxemu/pcfx-headless}"
FRAMES="${FRAMES:-8000}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
NEW_OUT="$TMP/mappack_manifest.txt"
FAIL=0

if [[ ! -x "$EMU" ]]; then
  echo "pcfx-headless not executable: $EMU" >&2
  exit 1
fi

extract() { # $1 = ram dump -> stdout "MAP <name> <n>\n<num> <NAME>..." or nonzero
python3 - "$1" src/generated/pcfx_iwad.bin <<'PY'
import sys,struct
ram=open(sys.argv[1],'rb').read()
wad=open(sys.argv[2],'rb').read()
i=ram.find(b'PCFXMMF!')
if i < 0:
    sys.exit(1)
name=ram[i+8:i+16].split(b'\0',1)[0].decode('ascii','replace')
n,ptr=struct.unpack_from('<II',ram,i+16)
ofs=ptr & 0x1fffff
if not name or not n or n > 4096 or ofs + n*4 > len(ram):
    sys.exit(1)
lumps=struct.unpack_from(f'<{n}I',ram,ofs)
nlumps,dirofs=struct.unpack_from('<II',wad,4)
if nlumps > 65536 or dirofs + nlumps*16 > len(wad):
    sys.exit(1)
print(f'MAP {name} {n}')
for lump in lumps:
    if lump >= nlumps:
        sys.exit(1)
    nm=wad[dirofs+lump*16+8:dirofs+lump*16+16].split(b'\0',1)[0]
    print(lump,nm.decode('ascii','replace'))
PY
}

mkdir -p generated
{
  echo "# PC-FX DOOM per-map asset manifest -- authoritative reserve set + order dumped by"
  echo "# the engine's R_PrecacheLevel (build -DGEN_MAPPACK_MANIFEST). Regenerate with"
  echo "# 'make mappack-manifest'. Lines: 'MAP <name> <n>' then '<lumpnum> <NAME>' x n."
} > "$NEW_OUT"

# BOOT pack: the whole-run resident UI set + TITLEPIC. Unlike the maps this run does
# NOT warp — it boots to the title so W_CacheLumpNum's ground-truth capture sees the
# real boot-resident set (dumped by W_BootManifestDump at the first title frame). Emit
# it FIRST so the BOOT pack sits at the front of pcfx_mappacks.bin.
echo "=== BOOT ==="
rm -rf build doom_pcfx.bin
if make -j"$JOBS" DOOM1WAD="$WAD" EXTRA="-DGEN_BOOTPACK_MANIFEST" >/dev/null 2>&1; then
  env PCFX_BIOS_DIR="$BIOSDIR" "$EMU" --bios-dir "$BIOSDIR" --pcfx --auto-run \
    --frames "${BOOT_FRAMES:-8000}" --dump ram "$TMP/boot.bin" doom_pcfx.cue >/dev/null 2>&1
  if extract "$TMP/boot.bin" > "$TMP/boot.txt" 2>/dev/null; then
    cat "$TMP/boot.txt" >> "$NEW_OUT"
    echo "  ok: $(head -1 "$TMP/boot.txt")"
  else
    echo "  WARN: BOOT produced no manifest (title not reached?) -- no boot pack"
    FAIL=1
  fi
else
  echo "  build failed, skipping BOOT"
  FAIL=1
fi

for M in 1 2 3 4 5 6 7 8 9; do
  echo "=== E1M$M ==="
  rm -rf build doom_pcfx.bin
  make -j"$JOBS" DOOM1WAD="$WAD" EXTRA="-DDEV_WARP -DDEV_WARP_MAP=$M -DGEN_MAPPACK_MANIFEST" >/dev/null 2>&1 \
    || { echo "  build failed, skipping"; FAIL=1; continue; }
  env PCFX_BIOS_DIR="$BIOSDIR" "$EMU" --bios-dir "$BIOSDIR" --pcfx --auto-run \
    --frames "$FRAMES" --dump ram "$TMP/mm$M.bin" doom_pcfx.cue >/dev/null 2>&1
  if extract "$TMP/mm$M.bin" > "$TMP/mm$M.txt" 2>/dev/null; then
    cat "$TMP/mm$M.txt" >> "$NEW_OUT"
    echo "  ok: $(grep -c '^[0-9]' "$TMP/mm$M.txt") lumps"
  else
    echo "  WARN: E1M$M produced no manifest (map-load failure?) -- no pack for it"
    FAIL=1
  fi
done
echo "=== manifest maps ==="
grep '^MAP ' "$NEW_OUT"
if [[ "$FAIL" != 0 || "$(grep -c '^MAP ' "$NEW_OUT")" != 10 ]]; then
  echo "manifest incomplete; keeping $OUT unchanged" >&2
  exit 1
fi
mv "$NEW_OUT" "$OUT"
