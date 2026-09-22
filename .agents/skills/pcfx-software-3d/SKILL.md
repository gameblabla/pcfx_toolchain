---
name: pcfx-software-3d
description: Software 3D on PC-FX - realistic frame budgets from the measured projects here, fixed-point conventions, avoiding divides, triangle and span rasterization into KRAM, LOD and viewport strategy, and why there is no hardware 3D. Use when building or speeding up any 3D renderer, or when deciding whether a 3D design is feasible at all.
---

# Software 3D on the PC-FX

## 1. There is no hardware 3D

The HuC6273 "Aurora" 3D chip exists **only on the PC-FXGA development board**, not in a
retail PC-FX. Do not design around it. **Every triangle is software on the V810**, which
has no FPU, a 13-cycle multiply, a 36–38 cycle divide, no dcache and a 1 KB icache.

## 2. Budget before you design

Measured in this workspace:

| Project | Content | fps |
|---|---|---|
| wolf-pcfx | raycaster, 256×240, no real 3D transform | **60** |
| doom-pcfx | BSP, textured walls/floors, sprites | 15–20 |
| AirGT | textured 3D ground + car model | ~10 |
| 3DCharacterSpinning | 6,246-vertex animated textured character, 8bpp | **2.800** |
| descent-pcfx | full 6-DOF engine, exact collision | ~2 |

**Read that table before promising a frame rate.** A "simple spinning textured model"
is a 3 fps workload here. If you need 20+ fps with real 3D, you need a
raycaster/2.5D approach or a drastically reduced pixel count.

At 21.477 MHz you have **~358,000 cycles per 60 Hz field**, ~1.07 M for a 20 fps frame.
A perspective-correct textured pixel costs roughly 10–25 cycles once loads and DRAM page
changes are counted, so **20k textured pixels is already a ~15 fps frame** with nothing
left for transform, culling or game logic. A full 256×240 screen is 61,440 pixels.

**Corollary: pixel count is the budget.** Everything else is second order.

## 3. Draw fewer pixels — the levers that actually work

1. **Reduce raster pixels only when the output contract permits it.** Do not silently
   replace a requested 256×240 raster with 128×120 plus nearest-neighbour expansion.
   `3DCharacterSpinning` keeps a native 256×240 software raster and uses a 512×256
   KING affine source only as an 8bpp KRAM packing/presentation layout: one logical
   pixel per duplicated halfword, sampled with A=2.0. See [pcfx-character-8bpp].
2. **Shrink the viewport** (letterbox / cockpit surround). doom-pcfx names a smaller 3D
   viewport as *the one proven lever* to reach 20 fps game-wide. A cockpit or HUD border
   is both a style choice and a performance one.
3. **LOD by distance.** AirGT's distance-graded flat LOD for far ground patches gained
   5.5 → 6.1 fps, changing ≤1.3% of pixels, confined to the horizon.
4. **Cull earlier and more cheaply.** In descent-pcfx the *geometry* side
   (`fvi_sub`, `get_seg_masks`) cost as much as the rasterizer. Reducing the candidate set
   beat micro-optimizing arithmetic.
5. **Adaptive subdivision** of perspective correction — subdivide spans only where the
   perspective error is visible (AirGT's adaptive base).

## 4. Fixed point, and avoiding divides

Use **int32 fixed point everywhere.** Never 64-bit, never float — see
[pcfx-v810-performance] §5. descent-pcfx's whole "int32 conversion" commit series exists
because 64-bit math dragged in libgcc helpers and was far slower.

Common formats here: **16.16** for world coordinates, **8.8** (`Q8_8`) for compact
per-vertex data and KING affine coefficients.

```c
/* Widening 32x32->64 multiply: hardware `mul` puts the high word in r30.
 * GCC 4.9.4 will NOT generate this from (int64)a*b -- it calls __muldi3. */
static inline int FixedMul(int a, int b)   /* 16.16 * 16.16 -> 16.16 */
{
    int lo, hi;
    __asm__ ("mul %2, %0" : "=r"(lo), "=r"(hi) : "r"(b), "0"(a) : "r30");
    return (int)(((unsigned)lo >> 16) | ((unsigned)hi << 16));
}
```

**Divides are the enemy**: 36–38 cycles each, and a perspective-correct mapper wants one
per pixel. Standard mitigations, all used here:

- **Subdivide spans** (8 or 16 pixels) and divide once per subdivision, interpolating
  linearly between — the classic Quake approach. AirGT's
  `Cut per-span 64-bit divides` commit is exactly this.
- **Reciprocal tables** for `1/z` over a limited range.
- **Cheap magnitude/reciprocal approximations for rejection tests only**, keeping exact
  arithmetic for final geometry — descent-pcfx's top recommendation.
- Remember: a load right after a `mul`/`div` pays **no** load-use penalty. Schedule a
  dependent load there.

## 5. The rasterizer

Write spans, not pixels, into KRAM. See [pcfx-king-framebuffer] for the layout
(one word = two horizontal pixels, left pixel in the **high** byte).

- **Set the KRAM write address once per span**, then burst direct inline `out.h` stores
  through the framebuffer helpers. Never call `king_kram_write()` or re-address per pixel.
- **Work in pixel pairs.** The natural unit is a word = 2 pixels. Rasterize to even
  boundaries where you can; it halves your I/O writes.
- **Batch texture+colormap loads 4 pixels at a time** to avoid the 2 KiB DRAM page
  thrash — the single biggest per-pixel win found here (§4 of [pcfx-v810-performance]).
- **Keep the inner loop under 1 KB** or it evicts itself from the icache every iteration.
- Painter's algorithm with a sort is usually cheaper than a Z-buffer: a Z-buffer costs a
  read-modify-write per pixel and 60 KB of RAM you probably need elsewhere.
- Skip the screen clear if the scene covers the screen anyway.

## 6. Where the time actually goes

From descent-pcfx's profile (2 fps build), which is the most detailed 3D profile here:

| Cost | Share of field |
|---|---|
| DRAM page penalties | **24.96%** |
| I-cache misses (20.3% miss rate) | 2 cyc each + refill |
| Conditional branches | 6.26% |
| Flag-use stalls | 4.98% |
| `LD_W` alone | 17.4% of opcode cycles |
| `MUL` / `DIV` | 4.96% / 2.51% |

**Loads and memory locality dominate, not arithmetic.** The lesson recorded there:
"reducing memory/page pressure is at least as important as replacing another multiply".
Profile before assuming your divides are the problem — usually they are not.

## 7. Process

1. Get a **static** scene on screen first (one triangle, flat shaded). Screenshot it.
2. Add transform, then texturing, then lighting — screenshotting each step.
3. Profile (`PROFILE=1`) and find the real cost; do not guess.
4. Attack pixel count first, then memory locality, then instructions.
5. A/B every change with `make clean`, and reject results inside ±3%.
6. Compare screenshots to catch silent visual regressions — AirGT tracks "0 changed
   pixels" for bit-exact stages and bounds the rest ("≤1.3% of each frame").

## 8. Dynamic character rendering and predetermined animation acceleration

For skinned characters, separate three concerns:

```text
authoring base: mesh + UVs + skin controller + inverse binds + skeleton
animation clip: compatible matrix tracks converted to object-space vertex frames
renderer: live world transform + projection + cull + sort + texture + outline
```

Preserve vertices that share a bind position but have different influence signatures.
Position-only deduplication creates cracks when those vertices deform differently.

Object-space pre-skinned clips are not screen-pose caching: translation, yaw, zoom, camera,
projection, clipping, sorting and pixels remain live. For predetermined clips, an optional
face-schedule cache may precompute only visible painter order per animation frame. It must
fall back to dynamic culling/sorting whenever yaw or visibility assumptions change.

Do not show “live FPS” from raster wraps sampled only between long renderer stages. Use the
emulator profiler and RAM `nframe` deltas. A build-stamped decimal HUD value is acceptable
when timer/IRQ code is deliberately forbidden.

## Related

[pcfx-v810-performance] (read first) · [pcfx-king-framebuffer] · [pcfx-emulator-testing].
Reference projects: `AirGT/verification/`, `descent-pcfx/PERFORMANCE.md`,
`3DCharacterSpinning/README.md`. For the full-character, no-decimation workflow, read
[pcfx-character-8bpp].
