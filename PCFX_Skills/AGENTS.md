# AGENTS.md — PC-FX homebrew

Operating manual for an AI agent creating or improving a NEC PC-FX (1994, V810) homebrew
project in this workspace. **Read this whole file before writing any code.**

---

## 0. STOP: what you think you know about the PC-FX is wrong

The PC-FX is rare and badly documented online. Pretrained knowledge about it is
**overwhelmingly false**. These are real, measured errors that models confidently produce.
If you catch yourself about to write anything in the left column, stop and use the right.

| ❌ Common false belief | ✅ Reality |
|---|---|
| "It's tile-based, there's no bitmap mode" | KING **BG0 in 256-colour mode is a linear bitmap framebuffer**. That is how nearly every homebrew here draws. |
| Palette is RGB 555 / RGB 888 / RGB332 | The HuC6261 has **512 shared palette entries**, each packed `Y8U4V4` in a 16-bit word: `Y<<8 | U<<4 | V`. Direct-color KING modes bypass this palette. See [pcfx-2d-picture] for choosing an image path and [pcfx-yuv-palette] for conversion. A screenshot rendered from a wrong RGB guess still looks like "a colour" — a vision model will not catch this. Verify numerically with [pcfx-color-verification] before trusting any colour claim. |
| VRAM is memory-mapped at `0x8000` / `0x80000000` | **KRAM is not memory-mapped.** It is reachable *only* through KING I/O ports `0x600` (index) and `0x604` (data). `0x80000000`–`0x807FFFFF` is a memory-mapped alias of the **I/O port space** (`0x80000400` = VDC-A status, port `0x400`; `pcfxemu` `mem-handler.inc`) — not KRAM, not RAM. |
| Poll a status bit at `0x80000004` (or the VDC status VD bit, `0x80000400` & `0x20`) for vblank | Read the **Tetsu raster counter at I/O port `0x300`**, and you must read it **twice until two reads agree** (hardware bug). VD only rises while VDC CR bit 3 is set, so one CR write turns that wait into a permanent black screen. See [pcfx-frame-timing]. |
| Build the CD with `mkfxiso` / `cdrecord` / `mkisofs` | `bincat` then **`pcfx-cdlink`** with a `cdlink.txt`. See [pcfx-bringup]. |
| There's a 3D accelerator you can use | The HuC6273 "Aurora" 3D chip exists **only on the PC-FXGA development board**, not in a retail PC-FX. **All 3D here is 100% software on the V810.** |
| Screen is 320x224 | 256x240 at the 5 MHz dotclock (what everything here uses), or 320 wide at 7 MHz. |
| `in.h` reads main RAM | `in.*`/`out.*` are **I/O bus only**. `in.*` from main RAM returns 0. Use `ld.*`/`st.*` for RAM. |

**Rule: if a fact is not in these skills or in the source of a project in this workspace,
you do not know it. Go and read the code. Do not invent register numbers.**

## 0.1 Evidence hierarchy: resolve conflicts from primary sources

For any hardware-facing question — register semantics, timing, colour, bus/KRAM
behaviour, boot, compatibility, or performance behaviour — use this precedence:

1. **Original Japanese Hudson Soft manuals in `DOCUMENTATION/ORIGINAL_JPN/`.** These
   are the ultimate hardware reference in this repository. `DOCUMENTATION/README.txt`
   says the English translation is incomplete; use it as a search aid, then check the
   original Japanese WRI figures/text when the wording or bit layout matters.
2. **Confirmed real-hardware tests recorded in the skills.** Treat only tests with a
   stated setup and result as evidence. They can expose an implementation discrepancy,
   but do not silently erase or rewrite the manual claim; record the discrepancy.
3. **`vendor/pcfxemu/` source.** This is the reference for what this emulator actually
   implements, not proof that retail hardware behaves the same way.
4. **SDK headers/examples, local project code, session transcripts, and emulator
   captures.** These are useful implementation evidence, but inherit the limits of
   their source and are not independent hardware authority.
5. **General knowledge, analogy, or inference.** Use these only after the repository
   evidence has been checked, and label the result as unverified when it remains one.

This hierarchy applies to every workflow: a new project, bringing up an existing user
project, debugging, refactoring, and optimization. If sources disagree, inspect the
higher-priority source, state the conflict, and avoid inventing a compromise. For an
emulator-only question, answer what `pcfxemu` does; do not promote that answer into a
retail-hardware claim.

---

## 1. The workspace

All paths in this bundle are relative to the toolkit root. When a command is run
from the repository root, this portable setup points it at the bundled tools; when
the project is elsewhere, set `PCFX_TOOLKIT_ROOT` to the toolkit root.

```bash
export PCFX_TOOLKIT_ROOT="${PCFX_TOOLKIT_ROOT:-.}"
export PCFX_SKILLS="${PCFX_SKILLS:-$PCFX_TOOLKIT_ROOT/PCFX_Skills}"
export V810_GCC="${V810_GCC:-${V810GCC:-$PCFX_TOOLKIT_ROOT/toolchain/v810-gcc}}"
export V810GCC="${V810GCC:-$V810_GCC}"  # compatibility alias
export LIBPCFX="${LIBPCFX:-$PCFX_TOOLKIT_ROOT/vendor/libpcfx}"
export PCFXEMU="${PCFXEMU:-$PCFX_TOOLKIT_ROOT/toolchain/bin/pcfx-headless}"
export PCFXEMU_PROF="${PCFXEMU_PROF:-$PCFX_TOOLKIT_ROOT/toolchain/bin/pcfx-headless-prof}"
export PATH="$V810_GCC/bin:$PATH"
# Set this only when running the emulator; the BIOS remains external.
# export PCFX_BIOS_DIR="$YOUR_LEGALLY_OBTAINED_BIOS_DIR"
```

Do not replace these with paths from the machine that produced the bundle.
The repository scripts use the same discovery order: `V810_GCC`, the bundled
`$PCFX_TOOLKIT_ROOT/toolchain/v810-gcc`, then a system-installed V810 toolchain.
`V810GCC` is retained as a compatibility alias; `PCFX_TOOLCHAIN_DIR` can relocate
the bundled directory.

| Path | What it is |
|---|---|
| `vendor/libpcfx/` | The SDK: `king.h`, `tetsu.h`, `vdc.h`, `contrlr.h`, `timer.h`, `cd.h`, `sound.h`. **`vendor/libpcfx/examples/` is the single best source of correct bring-up code.** |
| `vendor/pcfxemu/` | Mednafen-derived emulator source. The bundled `toolchain/bin/pcfx-headless` is the test harness; `PROFILE=1` builds add a V810+KING profiler. |
| `DOCUMENTATION/` | Bundled NEC/Hudson chip manuals and translations (`C6230`=SoundBox/ADPCM, `C6261`=Tetsu, `C6272`=KING including the HuC6271 RAINBOW transfer and scroll rules, `C6273`=FXGA-board-only). There is **no** HuC6270 (VDC) or HuC6271 manual here; VDC facts come from `vendor/pcfxemu` and label as such. Authoritative when the SDK is ambiguous. |
| `vendor/v810-gcc/` and `toolchain/v810-gcc/` | V810 compiler source and the bundled compiler binary. |
| `vendor/doompcfx/` | Most mature bundled port and the deepest Doom performance source in this toolkit. |
| `tools/large-game/doom/` | Reusable large-game asset, CD, checksum, and profiling helpers copied from the local Doom workspace. |
| `PCFX_Skills/` | This bundle: measured hardware notes, templates, evals, and the local-model wrapper. |
| `wolf-pcfx/` | Reached **60 fps** — the reference for "fast enough". Has the asm Tetsu frame wait. |
| `emeraldpcfx/` | The reference for **VDC** (tiles/sprites/two-chip layering). Its README is a detailed design document. |
| `descent-pcfx/` (~2 fps), `AirGT/` (~10 fps), `3DCharacterSpinning/` (~3 fps) | Software-3D projects. Read their `PERFORMANCE.md` / `verification/` before repeating their experiments. |

Every project directory also holds `NNNN-NN-NN-*-local-command-*.txt` session transcripts.
They are long, but they record *why* things were done. Grep them before redoing an experiment.

## 2. Toolchain and build

```bash
export V810_GCC="${V810_GCC:-${V810GCC:-$PCFX_TOOLKIT_ROOT/toolchain/v810-gcc}}"
export V810GCC="${V810GCC:-$V810_GCC}"
export PATH="$V810_GCC/bin:$PATH"
```

GCC is **4.9.4**, C99/gnu99. Standard flags (from `vendor/libpcfx/examples/example.mk`, verified):

```
-O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function
```

The normal SDK template links with `-T ldscripts/v810.x`, `crt0.o`, and
`-lpcfx -lc -lsim -lgcc`. A performance-critical renderer may impose a stricter
freestanding contract and link only its required device archive. In that case, read
**[pcfx-freestanding-runtime]**, remove libc/libgcc assumptions deliberately, and audit
the final map and ELF; do not merely delete libraries and hope the link is clean.

Building a bootable disc is `objcopy -O binary` → `bincat` → `pcfx-cdlink`. The exact,
verified sequence and a copy-paste project template are in **[pcfx-bringup]**.

**Always `make clean` between A/B performance builds** — stale objects silently keep old
flags and will invalidate your measurement.

## 3. Running and seeing your output

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx \
    --frames 1800 --screenshot shot.png yourgame.cue
```

**⚠ The BIOS boot animation takes ~1200 frames.** Measured on this exact setup:

| `--frames` | What you see |
|---|---|
| 240 / 600 | the **PC-FX BIOS logo** — *not your program* |
| 900 | black (disc loading) |
| **1200+** | your program's output |

So **always use `--frames 1800` or more** for a first look. If you screenshot at 240 frames,
see the PC-FX logo, and conclude your program is broken, you have made the single most
common mistake in this workspace. Full harness details in **[pcfx-emulator-testing]**.

## 4. Hardware in one page

- **CPU** NEC V810 @ 21.477 MHz. 32-bit RISC, 32 GPRs, **no branch predictor, no dcache**,
  **1 KB direct-mapped icache**. 2 MB main RAM (code + heap share it).
- **KING (HuC6272)** — 1 MB KRAM, 4 background layers, CD/SCSI DMA, ADPCM. I/O ports only.
- **Tetsu / VCE (HuC6261)** — video mixer, 512-entry **YUV** palette, raster counter,
  layer priorities, cellophane (translucency).
- **VDC ×2 (HuC6270)** — two PC-Engine-style tile/sprite chips, 64 KB VRAM each. Good for
  2D and for sprite overlays on top of a KING bitmap.
- **RAINBOW (HuC6271)** — YUV/DCT video decoder, used for backgrounds/skies/FMV.
- Layer order is set on Tetsu; VDC1 mixes over VDC0 on transparency.

Which drawing surface to choose is the first design decision of any project — start with
**[pcfx-2d-picture]** for a still image or pixel-format choice, then use
**[pcfx-king-framebuffer]** (bitmap), **[pcfx-vdc-tiles-sprites]** (tiles/sprites), or
**[pcfx-rainbow]** (compressed natural-picture background) for the selected path.

## 5. Performance reality check

Set expectations *before* designing, so you don't promise 60 fps for a scene that cannot reach it.

| Workload | Measured here |
|---|---|
| 2D tiles/sprites via VDC hardware | 60 fps |
| Raycaster, 256×240 (wolf-pcfx) | **60 fps** |
| BSP software renderer (doom-pcfx) | 15–20 fps |
| Textured 3D world + model (AirGT) | ~10 fps |
| Complex static 3D character, 8bpp, full geometry | **3.017 fps** measured corrected baseline |
| Animation-safe complex character, 10 compressed clips, live transform/raster | **2.967 fps** emulator-profiler baseline |
| Full 6-DOF 3D engine (descent-pcfx) | ~2 fps |

**The V810 has no hardware 3D or FPU.** It does have 32-bit `DIV`/`DIVU`; use those
explicitly when a strict build must not pull software arithmetic helpers. Software 3D
above a few hundred textured pixels per frame is slow. Reduce overdraw, record traffic, and unnecessary
per-face/per-pixel work first. Do not silently lower a requested output resolution. When the
source asset must remain intact, use [pcfx-character-8bpp] to preserve every vertex/face and
a native 256x240 raster while using the 512x256 KING affine surface only as presentation
packing. Keep the release face-area threshold at zero and verify `(uv >> 2) & 63` texture
sampling before blaming the source asset.

The three levers that actually move the needle, in order:
1. **Do less rendering work** — culling, overdraw, record traffic, and only when the
   output contract permits it, viewport size or LOD.
2. **1 KB icache** — a hot loop that doesn't fit evicts itself every iteration.
3. **2 KiB DRAM page changes** — `colormap[texture[t]]` flips the open page twice *per pixel*;
   batching 4 pixels cut a real span drawer's cost measurably.

Full cycle model, the measured do-and-don't catalogue, and the **±3% layout noise floor**
(any edit anywhere moves fps by up to ±3%, so a predicted win under ~1 ms/frame is
unmeasurable) are in **[pcfx-v810-performance]**. Read it *before* any perf work.

## 6. How to work

1. **Start from working code.** Copy the [pcfx-bringup] template or the nearest
   `vendor/libpcfx/examples/` example. Never start from a blank file.
2. **Get a black screen booting first**, then a solid colour, then content. Verify each step
   with a screenshot. Do not write 500 lines and then try to debug a boot failure.
3. **Change one thing at a time**, and screenshot after each.
4. **Measure, don't predict.** Claims like "this will be faster" are worthless here; the
   noise floor eats most predicted wins.
5. **Grep the session transcripts and git logs before re-running an experiment** — most
   obvious ideas have already been tried, and many are recorded as measured failures.
6. **Do not claim it works on real hardware** because the emulator is happy. The emulator's
   cycle model and some KING/CD behaviours are approximations — see the hardware-risk notes
   in [pcfx-emulator-testing].

## 7. Skills

| Skill | Use it when |
|---|---|
| **pcfx-bringup** | Creating any new project; boot/linker/CD-image problems. **Start here.** |
| **pcfx-3d-from-scratch** | Building a 3D program from nothing: output contract, renderer class, asset pipeline, transform/cull/sort/raster/present, ordered bring-up gates. |
| **pcfx-self-improve** | The working loop itself: what to do next, how to profile-route, when to brute-force, how to check the picture, what you may claim. |
| **pcfx-king-framebuffer** | Drawing a bitmap: BG0 8bpp, KRAM writes, double buffering. |
| **pcfx-2d-picture** | Putting a picture onscreen; choosing KING 2/4/8bpp, direct YUV 64K/16M, VDC 16-colour tiles, or RAINBOW; exact palette and pixel-format rules. |
| **pcfx-yuv-palette** | Any colour work — converting art, wrong/muddy colours. |
| **pcfx-palette-transitions** | Fast indexed-screen fades, startup garbage, and blanking-safe palette animation. |
| **pcfx-color-verification** | Proving a colour is actually right — numeric check against a screenshot, names a wrong-colour-format bug (RGB332/RGB555 vs. real YUV) instead of leaving it as "looks off". |
| **pcfx-frame-timing** | Vsync, the Tetsu raster double-read, tearing, frame pacing, fps measurement. |
| **pcfx-input** | Reading the FX-Pad. |
| **pcfx-vdc-tiles-sprites** | 2D games: tilemaps, scrolling, sprites, two-chip layering. |
| **pcfx-kram-layout** | Planning KRAM; corruption where two subsystems overlap. |
| **pcfx-software-3d** | Any 3D: budget, LOD, viewport — decide *what* to draw. |
| **pcfx-3d-rasterizer** | The per-pixel inner loop: span/column kernels, the KING write cursor, DRAM-page load clustering, hand-scheduled V810 drawers. |
| **pcfx-3d-pipeline** | Wiring a 3D renderer to the screen; a verified 60 fps template, and the two bugs that render it black. |
| **pcfx-character-8bpp** | One large textured mesh must remain intact; native 256x240 affine packing, exact UV/atlas sampling, compact face pipeline, black outline. |
| **pcfx-character-animation** | Any shared COLLADA base skeleton, compatible animation clips, influence-safe mesh, frame-zero root/body motion, PCA1/LZ4 CD archive, viewer controls and animation profiling. |
| **pcfx-freestanding-runtime** | A renderer must avoid newlib/libgcc, float, int64, software helpers, timer IRQs, and registered handlers; audit source, map, and ELF. |
| **pcfx-fixed-point** | Any math. There is no FPU — a `float` is a disaster, not a slowdown. |
| **pcfx-v810-performance** | **Before** any optimization work. Cycle costs + measured failures. |
| **pcfx-v810-cpu-model** | When modifying or auditing the emulator profiler/cycle model itself. |
| **pcfx-v810-profiling** | Getting the numbers: `pcfx-headless-prof`, icache, DRAM pages, flag stalls. |
| **pcfx-optimize-loop** | Build knobs and automated search; the noise floor; recording results. |
| **pcfx-emulator-testing** | Running, screenshotting, scripting input, and what it cannot prove. |
| **pcfx-vision-assets** | Looking at a screenshot; asking the user for source art. |
| **pcfx-audio** | ADPCM sound effects and CD-DA music. |
| **pcfx-2d-code-examples** | Real working CD-DA/ADPCM/VDC/KING/microcode code examples, including the two VDC colour-mode patterns. |
| **pcfx-cd-assets** | Getting data off the disc at runtime; asset pipelines. |
| **pcfx-rainbow** | RAINBOW (HuC6271) video: start from `examples/rainbow-still` or the PCFV+MP2 player, stream format, authoring, per-field re-arm, scrolling, emulator gates. |
| **pcfx-liberis-port** | Moving code from liberis (`eris_*`) to libpcfx: mapping table and the calls that are not equivalent. |
| **pcfx-regression-triage** | Worked before, broken now: baseline, fresh emulator, hot-PC spin finding, map-based state, gated fix. |

Skills live in `$PCFX_SKILLS/<name>/SKILL.md`. **Read the whole skill before acting on it**, and
copy code blocks verbatim instead of re-deriving them from the prose around them.

`PCFX_Skills/SKILLS.md` is a symptom-to-module router; start there when you know the
symptom but not which module owns it. `PCFX_Skills/eval/` measures whether the bundle
actually teaches what it claims, using real fixes from this workspace's git history.

### The optimization order, since it is the thing most often got wrong

1. **Profile** (`pcfx-v810-profiling`) — never optimize an unprofiled program.
2. **Remove avoidable rendering work** (`pcfx-software-3d`) without changing the requested
   output dimensions; for the full character use native 256x240 affine packing from
   `pcfx-character-8bpp`, never asset decimation or an implicit 128x120 upscale. For
   animation, preserve influence seams, animated root/body transforms, and object-space clips with `pcfx-character-animation`.
3. **Enforce the runtime contract** (`pcfx-freestanding-runtime`) when hidden libc,
   soft-float, 64-bit, software-div, prolog, or handler code is forbidden.
4. **Fix the memory behaviour** — compact/interleaved streams, DRAM page clustering,
   then icache conflicts.
5. **Search the knobs** (`pcfx-optimize-loop`) — placement is not predictable.
6. **Hand-schedule** (`pcfx-v810-performance`) — last, and only for a profiler-proven >10% hot loop; use `pcfx-character-8bpp` for its character-specific kernels.

On this machine multiplies are cheap (all slow ops together measured **0.17%** of a
frame) while compares, taken branches and I/O port reads are expensive. "Avoid the
multiply" is not a PC-FX rule; let the profile decide.
