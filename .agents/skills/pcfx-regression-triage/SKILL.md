---
name: pcfx-regression-triage
description: Procedure for "it worked before and is broken now" on PC-FX - after a library port, refactor, re-encode, toolchain or emulator update. Known-good baseline first, reproduce both on a fresh emulator, find where the CPU is actually spinning with the profiler's hot-PC histogram, read state through the linker map, bisect the diff, and gate the fix with a check that has been shown to fail. Use for a black screen, hang, silence or glitch that appeared after a change, and before telling anyone a regression is fixed.
---

# Regression triage: worked before, broken now

Written from a real failure chain (2026-09-22, RAINBOW + MP2 player): one agent ported
the player to libpcfx, changed the build, the encoder and the asset in one pass; a
second agent committed "job finished" after host-only checks; the user got a black
screen; the second agent then spent its session reading RAM by hand-computed offsets
and debugging a CD state machine that was never broken. The actual bug was one
changed register write, found in three commands with the steps below.

## The rules

1. **Nothing is fixed until the disc ran.** Host tests, a clean build and a strict
   asset check are necessary, not sufficient. Run the disc in `pcfx-headless` and
   read runtime evidence before saying "done" or committing.
2. **One change class per step.** Port, then verify; re-encode, then verify. A port
   plus a new encoder plus a new build script cannot be attributed when it breaks.
3. **Never compute an address by hand.** Symbols come from the linker map or `nm`.
4. **A stuck state machine is usually a stuck caller.** Find where the CPU is,
   not where the data stopped.

## Step 1 — get a known-good baseline and reproduce both

Pick whichever exists: the last working disc image (a shipped zip, a CI artifact),
the previous git revision, or the pre-port sources rebuilt with the old library
(the toolchain still ships `liberis.a`; see [pcfx-liberis-port] §1).

Before running anything, make sure the emulator is the current one
([pcfx-emulator-testing] §8): rebuild `pcfx-headless` if `vendor/pcfxemu` is newer
than the binary. Then run **good and bad at the same frame counts** and compare
screenshots and counters. If the good build is also bad now, the change you are
chasing is not the cause (a stale emulator, a missing BIOS, or a bug that was always
there — `LOOP=1` in the RAINBOW player was broken in the original too).

## Step 2 — where is the CPU?

```bash
V810_PROF_OUT=build/hot.csv "$PCFX_TOOLKIT_ROOT/toolchain/bin/pcfx-headless-prof" \
    --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2000 game.cue 2> build/prof.txt
python3 "$PCFX_TOOLKIT_ROOT/tools/large-game/doom/v810_prof_symbols.py" \
    build/hot.csv --elf build/game.elf --top 5
grep -A6 'hot code' build/prof.txt            # 32-byte PC buckets by cycles
"$V810_GCC/bin/v810-objdump" -d --start-address=0xd2e0 --stop-address=0xd320 build/game.elf
```

One function at ~98% of cycles in a program that should be decoding video means a
spin loop. With `-O3` the loop is often inlined into its caller, so disassemble the
hot bucket. In the incident this showed

```text
d2fe: ld.h 0[r20], r10     ; r20 = 0x80000400, VDC-A status
d302: andi 32, r10, r10    ; VD bit
d306: be   d2fe            ; spin until VD
```

i.e. a vblank wait on a flag nothing raised any more ([pcfx-frame-timing],
"waiting on the VDC status VD bit"). Common spin sites and their modules:

| Hot loop polls | Usually means | Read |
|---|---|---|
| port `0x300` / `tetsu_get_raster` | mixed raw/decoded raster constants | [pcfx-frame-timing] §2 |
| `0x80000400`/`0x80000500` bit `0x20` | VD wait without CR bit 3 | [pcfx-frame-timing] |
| KING `0x600/0x604` SCSI regs | CD read/erratum, disarmed or never-armed DMA | [pcfx-cd-assets], [pcfx-emulator-testing] §7 |
| none, CPU in BIOS (`non-RAM PC`) | crashed/returned to BIOS, bad boot image | [pcfx-bringup] |

## Step 3 — read state through the map

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2500 --dump ram build/ram.bin game.cue
"$V810_GCC/bin/v810-nm" build/game.elf | grep -i 'frames_presented\|g_done\|underflow'
```

or a parser like `pcfx_rainbow_mp2_startup_sync_package/tools/extract_pcfv_stats.py`.
Progress counters say *whether* the program advances; step 2 says *where it is*.

## Step 4 — bisect the change, not the program

`diff -u good/src bad/src` (or `git diff good..bad`). List every **semantic** change,
not just renames: a library call replaced by one that "does the same thing" is the
first suspect ([pcfx-liberis-port] §3 lists the known non-equivalent pairs). Revert
changes one at a time on a scratch copy until the bad build turns good.

## Step 5 — fix, then gate the fix

- Make the smallest fix that the evidence points to; cite the higher-priority source
  for any hardware claim (manual > hardware test > `pcfxemu` source).
- Gate it with a check that reads runtime evidence (frames presented, underflows,
  pixel comparison) — for RAINBOW, the template `make validate` targets.
- **Show the gate failing on the bad build** before trusting it passing on the good
  one. A gate that has never failed is decoration.
- Re-run the neighbours: other build modes (`LOOP=1`), the known-good asset, and
  past the first loop/restart.

## Step 6 — report

State what ran and what it printed: frames presented, counters, gate PASS/FAIL, and
what the emulator cannot prove (timing, IRQ-in-KING-pair, bus contention —
[pcfx-emulator-testing] §7). Say which parts are hardware-unverified.

## Related

[pcfx-self-improve] (the general loop) · [pcfx-emulator-testing] §8–9 ·
[pcfx-liberis-port] · [pcfx-v810-profiling] (reading the profile) · [pcfx-rainbow] §6.
