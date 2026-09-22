---
name: pcfx-v810-performance
description: Optimizing V810 code on PC-FX - instruction cycle costs, the 1 KB direct-mapped icache, the 2 KiB DRAM page penalty, load-use and flag-use stalls, fixed-point math, and the catalogue of optimizations measured to work or fail in this workspace. Read this BEFORE any performance work, and when writing hot loops, hand assembly, or choosing types.
---

# V810 performance

Read this **before** optimizing anything. It contains measured results — including
failures — from doom-pcfx, wolf-pcfx, AirGT and descent-pcfx. Re-running a known
failure is the most common waste of effort here.

**Caveat: the cycle numbers are the emulator's model.** They match the V810 manual where
it exists, but silicon is untested. Optimizations that *remove instructions or memory
traffic* are safe everywhere; ones tuned to a ±1-cycle detail are emulator-tuned.

## 1. The machine

- **V810 @ 21.477 MHz** — 21,477 cycles ≈ 1 ms. 32-bit RISC, 32 GPRs.
- **No branch predictor. No data cache.**
- **1 KB direct-mapped icache**, 128 lines × 8 bytes, tag = `addr >> 10`. Any two code
  addresses exactly 1 KB apart **conflict**.
- **2 MB main RAM**, code and heap share it.
- Registers: `r0`=zero, `r1`=asm temp, `r3`=sp, `r4`=gp, `r31`=lp,
  **`r30` = high 32 bits of the widening `mul`**.
- ABI (probed): **r6–r9 args, r6–r19 caller-saved, r20–r29 + fp callee-saved.** Hand asm
  that scratches r20+ without saving is a bug — this caused two real crashes here.

## 2. Instruction costs

| Instruction | Cycles | Notes |
|---|---|---|
| ALU reg/imm5 | 1 | |
| `ld.b/h/w` | 1 **+ penalty** | +2 after a non-load; +1 after another load; **+0 after mul/div** |
| `st.h/st.w` | 1 | +1 if the previous op was also a store |
| `in.b/h/w` | 3 | **I/O bus only** — `in.*` from main RAM returns 0 |
| `out.b/out.h` | 1 | +1 if previous op was an `out` |
| `out.w` | 1 | **+3** if previous was an `out` — no 32-bit I/O write exists |
| conditional branch | 3 taken / 1 not taken | **+2 flag-use stall** |
| `jmp/jr/jal` | 3 | |
| `mul/mulu` | 13 | 32×32→64, high half in **r30** |
| `div` / `divu` | 38 / 36 | microcoded |

**Flag-use stall (+2):** a conditional branch, `SETF`, or `STSR`-PSW immediately after a
flag-*writing* op costs +2. The universal `cmp; bcc` pair pays it — so putting a
flag-neutral instruction *between* the compare and the branch saves 2 cycles. Confirmed on
real FPGA hardware. Register-register data dependencies do **not** stall; don't space those.

**Load-use:** cluster loads back-to-back (2 cycles each instead of 3), and a load right
after a `mul`/`div` is free of penalty.

**Scale check:** 1 ms ≈ 21,500 cycles. Saving one cycle per wall column (~600–900/frame)
is ~0.04 ms/frame — **invisible**. Only per-pixel work (10–25k pixels/frame) and
per-call overhead on 1000+ calls/frame move the needle.

## 3. The 1 KB icache is the dominant lever

- A hot loop **larger than 1 KB evicts itself every iteration**. Shrinking doom-pcfx's
  Duff-device drawers from 16× to 8× so they fit was **+12.9% fps**. 4× measured identical
  to 8× — once it fits, fewer branches wins.
- A hot loop that aliases its caller/callee cache indices evicts itself on every call.
  doom-pcfx places hot routines at explicit linker offsets to control this.
- **±3% layout noise floor**: ANY code change anywhere reshuffles icache conflicts and
  moves fps by up to ±3% (±2 ms/frame). **A predicted win under ~1 ms/frame is
  unmeasurable and unshippable on its own.** This killed a drawer-inlining experiment
  (predicted +0.4 ms, measured −2.3 ms from displacement).

## 4. The 2 KiB DRAM page is a scheduling constraint

Main RAM charges **+3 cycles whenever an access leaves the open 2 KiB page**, and there is
**one** page register shared by data accesses *and* instruction-cache refills.

The classic `colormap[texture[texel]]` pattern flips the page **twice per pixel** (+6
cycles/pixel) when the texture and colormap live in different pages. The fix that worked:
**batch 4 pixels** — four texel addresses, four clustered `ld.b`, four colormap addresses,
four clustered `ld.h` — giving **2 page changes per 4 pixels instead of 8**. Measured:
doom-pcfx planes 20.1 → 16.5 ms/frame, whole frame 65.2 → 61.4 ms, byte-identical output.
**GCC will not do this for you.**

descent-pcfx measured DRAM page penalties at **24.96% of all field cycles** — larger than
its icache miss cost. If you are slow and don't know why, check this first.

Corollary: an icache miss inside a pixel loop costs more than its +2 refill, because the
refill also steals the open data page.

## 5. Codegen guidance

- **Types**: `ld.b`/`ld.h` **sign-extend**; `unsigned char`/`unsigned short` reads cost an
  extra `andi`. Use `int32_t`/`uint32_t` locals in hot loops and pre-widen tables.
- **No 64-bit, no float.** GCC 4.9.4 does *not* emit the widening `mul` for `(int64)a*b` —
  it calls `__muldi3`. Write `FixedMul` as inline asm using `mul` + `r30` (**clobber r30**),
  and `FixedDiv` on two hardware `divu`. Each 64-bit or float helper drags ~1 KB of libgcc
  into your 2 MB image. descent-pcfx's whole int32 conversion exists for this reason.
- **Globals cost `movhi`+`ld`**, and the load pays the +2 penalty. GCC hoists them into
  registers until register pressure runs out.
- **Big `static`/`.bss` arrays are dangerous** — the linker can place them across the
  `__gp` window where libc globals live, corrupting them (a real hang). Big buffers go on
  the heap.
- **Inline tiny hot helpers.** GCC 4.9.4 at -O2 left one-instruction KRAM primitives out of
  line — a `jal` around a single `out.h`. Audit with `v810-nm ELF`; fix with
  `__attribute__((always_inline))`.
- **Mixed optimization levels work**: file-level `-Os` with `#pragma GCC optimize("Ofast")`
  islands around pixel loops beat whole-file `-O2` (which loses icache fit).
- Keep hot branch targets 4-byte aligned. Bottom-tested `do/while` loops are slightly cheaper.

- **Immediate operands are not all the same width.** `ADD imm5,reg` is signed -16..15;
  GNU `as` may silently truncate a larger constant. `add 24,r20` became `add -8,r20`
  and corrupted a production face walker. Use `ADDI imm16,src,dst` for larger constants,
  disassemble the object, and audit source immediates.
- GCC 4.9.4 may synthesize `memcpy` from block-scope compound-literal arrays. Prefer
  file-scope `static const` lookup tables and always audit the linked symbols.

## 6. Measured catalogue

### Worked

| Change | Result |
|---|---|
| 8× Duff unroll so the drawer fits icache | **+12.9%** |
| `FixedMul` via widening `mul`+r30 asm | −9,912 B .text |
| `FixedDiv` via 2 hardware `divu` | −2,380 B, kills `__divdi3` |
| DRAM-page-clustered 4-pixel span kernel | planes 20.1→16.5 ms/frame |
| Purge float + 64-bit libcalls | ~1.7 KB RAM back |
| `always_inline` KRAM write primitives | per-pixel `jal` pair → bare `out.h` |
| 16-bit pre-doubled colormap | ~4 instructions/pixel off both drawers |
| Pre-lit flat/wall caches (heap, size-gated) | E1M1 +13% |
| Pre-converting all palettes out of the frame loop | killed ~8 ms/frame + 114–156 ms freezes |
| Icache placement of hot loops at tuned offsets | +4% |
| Timer-IRQ ms clock instead of polled vblank | fixed slow-motion under load |
| wolf-pcfx: split wall casting, single ray-cast state block | 37.6 → 60 fps |
| AirGT: quad-pixel sampler batching stores | 8.6 → 10.1 fps |
| Character: exact 128-pose native output stream | 3.017 → **30.117 FPS**; DRAM 46,447 → 23,996 cyc/field; i-cache 4,502 → 132 misses/field |

### Failed — do not retry without new information

| Attempt | Outcome |
|---|---|
| **`out.w` KRAM batching** | net **worse** (+3 I/O penalty + pack cost) |
| Hand-scheduled asm drawers | naive −0.8%; clustered version exactly **ties** GCC |
| 16× Duff / whole-file `-Os` / whole-file `-O2` | icache overflow or worse codegen |
| `always_inline` the dense column drawers into their caller | 16.66 → 16.05 fps (layout displacement) |
| Static `.bss` for big caches | gp-window corruption, hang |
| Undersized pre-lit caches (32-slot) | **4.5× slower** (re-bake storm) — cache must cover the working set or be disabled |
| SH2/RISC micro-idioms (`x!=-1`→`x>=0`) | zero benefit; imm5 covers both |
| Per-call `itu_ticks()` in hot loops | it's an I/O read; distorts what it measures |
| Coarser light quantization | +0.6 fps but visibly worse — rejected on quality |
| Out-of-range `ADD imm5` face stride | appeared faster, but `add 24` encoded as −8 and corrupted geometry |

### Open leads

- **Smaller viewport / fewer output pixels** — a proven lever only when the design
  allows it. The full-character contract requires native 256×240, so it was rejected.
  The accepted alternative is the exact finite-pose output stream in
  [pcfx-character-8bpp]: all 128 native indexed poses match the full-geometry baseline,
  while the release measures 30.117 presented FPS. Use this only for deterministic,
  enumerable visible states; it is not a general replacement for a live 3D renderer.
- **4bpp dual-BG mode** — deferred and unvalidated. Do not revive it in the current
  8bpp character renderer unless a separately scoped experiment is requested.
- RAINBOW RLE mode for large flat spans. Needs a feasibility spike.

## 7. Method

1. **Profile first** — `PROFILE=1` build, `v810_prof_symbols.py --sort cycles|misses`.
   See [pcfx-emulator-testing].
2. **Attack the biggest structural cost**, usually pixel count, DRAM pages, or icache —
   not individual instructions.
3. **A/B with `make clean` between builds**, same input, compare counter deltas.
4. **Reject anything inside ±3%** as noise.
5. **Gate on correctness**: freeze the game state and compare native buffers. For a
   finite pose set, compare every state byte-for-byte; screenshots alone are insufficient.
6. Record the result — including failures — in the project's docs or commit message.
   That is why the table above exists.

## Related

[pcfx-emulator-testing] for the profiler · [pcfx-software-3d] for 3D-specific budget ·
[pcfx-king-framebuffer] for the blit. Deepest bundled sources: `vendor/doompcfx/platform/`
and `tools/large-game/doom/`.
