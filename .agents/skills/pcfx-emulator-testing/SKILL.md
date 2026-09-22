---
name: pcfx-emulator-testing
description: Run, screenshot, script input for, and profile a PC-FX program with pcfx-headless. Covers the ~1200-frame BIOS boot delay, controller command files, savestates, RAM dumps, the V810+KING cycle profiler, measuring fps, and which emulator results are trustworthy on real hardware. Use whenever you need to see or measure what your program actually does.
---

# Testing with pcfxemu (headless)

`prebuilt/bin/pcfx-headless` is the test harness. It runs a disc image for a fixed number of
frames with no window, and can dump a screenshot, audio, RAM, or a savestate.

Run the path setup from `PCFX_Skills/AGENTS.md` first. The commands below assume the
current directory is the toolkit root and that `PCFX_BIOS_DIR` points to an external,
legally obtained BIOS. The BIOS is deliberately not part of this bundle.

## 1. The command

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx \
    --frames 1800 --screenshot shot.png yourgame.cue
```

| Option | Meaning |
|---|---|
| `--bios-dir DIR` | directory or file holding the external PC-FX BIOS (`$PCFX_BIOS_DIR`) |
| `--frames N` | run exactly N emulated **video fields** (60 per second) |
| `--screenshot F.png` | write the final framebuffer |
| `--commands FILE` | scripted controller input (below) |
| `--pad BUTTONS` | initial pad state, e.g. `START+A` |
| `--state-in/--state-out` | load/save an emulator savestate |
| `--dump ram FILE` | dump the 2 MB RAM image at exit |
| `--wav F.wav` | capture audio |
| `--y4m F.y4m` | capture **every** frame as video (for motion checks) |
| `--auto-run` | pulse RUN/START during boot (needed for some BIOS prompts) |

## 2. ⚠ The BIOS boot delay — read this before believing a screenshot

The PC-FX BIOS plays a boot animation before your code runs. **Measured on this workspace:**

| `--frames` | What the screenshot shows |
|---|---|
| 240, 600 | the **PC-FX BIOS logo** |
| 900 | black (disc loading) |
| **1200+** | **your program** |

**Always use `--frames 1800` for a first look.** Screenshotting at 240 frames, seeing the
PC-FX logo and concluding your program is broken is the most common mistake in this
workspace. If you need many samples, take a savestate once past boot and `--state-in` it.

## 3. Scripting input

```
# commands.txt  — frame numbers are absolute
0    NONE
1300 START          # absolute state: START held
1320 NONE
1400 +RIGHT +A      # relative: press
1500 -RIGHT -A      # relative: release
```

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2400 \
    --commands commands.txt --screenshot shot.png game.cue
```

Buttons: `A B C X Y Z START SELECT UP DOWN LEFT RIGHT`. Remember frame numbers must be
past the ~1200-frame boot, or your inputs land in the BIOS.

## 4. Measuring fps

fps is **quantized to 60/N** because the frame loop waits for a video field: 60, 30, 20,
15, 12, 10 fps correspond to 1, 2, 3, 4, 5, 6 fields. So average work only helps when a
frame *crosses a field boundary* — 50 ms IS 20 fps. Look at the distribution of field
counts, not just the mean.

The authoritative approach is a 32-bit global that increments only when a completed
image is presented. Start from a warmed savestate, dump RAM at the start and end, find
the symbol address from the fresh ELF, and compute:

```text
presented = (after_nframe - before_nframe) & 0xffffffff
fps = presented * 60 / profiler_video_frames
```

Do not use emulator wall-clock speed, `% of a field`, or a polling HUD as renderer FPS.
Repeat from the same warm state and publish only when the captures agree within the
noise gate. A phase-counter array can be added for attribution, but the presented-frame
counter is the FPS authority.

## 5. The V810 + KING profiler

```bash
# Use the project's instrumented profiler build, not an ordinary headless binary.
V810_PROF_CSV=hist.csv "$PCFXEMU_PROF" --bios-dir "$PCFX_BIOS_DIR" --pcfx \
    --state-in warm.state --frames 3000 --dump ram after.ram game.cue 2> prof.txt
python3 "$PCFX_TOOLKIT_ROOT/tools/large-game/doom/v810_prof_symbols.py" \
    hist.csv --elf build/game.elf --sort cycles
```

The instrumented binary must print a `V810 PROFILE` block at exit. A stock headless
build without those hooks cannot report DRAM or i-cache counters. Per video field the
profiler reports:

- **V810**: instruction count, mean CPI, per-opcode cycles *including load-use and pairing
  penalties*, MUL/DIV counts, **1 KB icache** hit/miss plus a per-address miss map,
  branch taken/not-taken split, **flag-use stall** rate, **2 KiB DRAM page** penalties
  (split code-refill vs data), and a hot-PC histogram.
- **KING**: KRAM bandwidth per engine (CPU writes, SCSI-DMA, ADPCM, RAINBOW, BG reads), a
  register histogram by name, a KRAM contention map, and an **exact per-word same-field
  collision detector** (0 = your double-buffering is safe).

`$PCFX_TOOLKIT_ROOT/tools/large-game/doom/v810_disasm.py <func> --csv hist.csv` annotates a function's disassembly
with per-32-byte-block cycles and icache misses — this is how you find the exact
thrashing instruction.

## 6. A/B measurement discipline

1. Same flags on both sides; **`make clean` between builds** (stale objects silently keep
   old flags — this has produced false results here before).
2. Same capture window, same input script, same starting savestate.
3. Compare **deltas** of counters between two RAM dumps.
4. **The layout noise floor is ±3%** — any code change anywhere reshuffles icache
   conflicts. A single number inside ±3% is noise, not a result. See [pcfx-v810-performance].
5. **Correctness gate**: freeze the game state at a fixed tic, screenshot, and require the
   PNG/PPM hash to match a reference before claiming a change is "byte-identical".

## 7. What the emulator does NOT prove

Do not claim real-hardware correctness from a green emulator run.

- The **cycle model is an approximation** (upstream Mednafen's, plus local additions like
  the flag-use stall). Optimizations tuned to ±1 cycle carry silicon risk; optimizations
  that remove instructions or memory traffic are safe everywhere.
- **CD/SCSI timing and KING DMA** diverge most. This workspace has documented emulator
  errata: `vendor/pcfxemu/docs/king-dma-erratum.md`, `king-pio-read-erratum.md`,
  `king-scsi-page-contention.md`, and `vendor/libpcfx/docs/CD_DMA_MATRIX_RESULTS.md` (a real
  hardware test matrix). Read them before trusting a CD path.
- Note the emulator prints `[KING] PIO-read erratum ENABLED` — it is deliberately
  modelling a real hardware hang. Disable with `PCFX_KING_PIO_ERRATUM=0` only to isolate.
- Register writes that "work" in the emulator may be ignored or fatal on silicon. Prefer
  sequences that retail games and `vendor/libpcfx/examples/` actually use.

### The classes it cannot see at all

If your bug is in the left column, **a clean emulator run is not evidence of anything**,
and a screenshot diff cannot confirm the fix. These were all found on real hardware only,
after the emulator said the port was fine.

| Bug class | Why the emulator misses it | Found by |
|---|---|---|
| Register write landing mid-picture instead of in blanking | it applies the write instantly and cleanly whenever it arrives | real HW: colour-noise bands, tearing |
| Palette RAM burst during display | no display/VCE port contention modelled | real HW: noise across the picture |
| A KING/VDC sequence interrupted by an IRQ mid-run | no bus arbitration between the CPU run and the engine | real HW: garbled text, dropped tiles |
| CD DMA vs KING page contention | timing-approximate; see the errata above | `CD_DMA_MATRIX_RESULTS.md` burns |
| Unpopulated / mirrored KRAM addresses | the emulator backs the whole address space with RAM | real HW: silent corruption |
| Sub-cycle races (SATB DMA latch, RAINBOW re-arm edge) | scanline-granular, not dot-granular | real HW |

**Do not invent an emulator procedure for these.** Comparing two screenshots at the same
frame number proves nothing about *when in the frame* a write happened — the emulator will
render both identically. The honest report is: "the emulator cannot confirm this class of
fix; it is justified from the C6261/C6272 manual and needs a hardware burn."

What the emulator *is* good for, even here: proving you did not **regress** — that the
program still boots, still renders, still reads the pad, and did not get slower.

## Related

[pcfx-bringup] to produce the disc · [pcfx-v810-performance] for what the numbers mean.
