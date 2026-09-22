---
name: pcfx-3d-rasterizer
description: Writing fast inner loops that put 3D pixels into KRAM on PC-FX - the KING write-cursor output model, span and column kernels in C and V810 assembly, DRAM-page load clustering, flag-stall-dodging loop tails, edge stepping without divides, and clipping. Use when writing or speeding up a triangle/span/column rasterizer, a texture mapper, or any per-pixel inner loop.
---

# Rasterizer inner loops

This is the code that actually burns the frame. [pcfx-software-3d] decides *what* to
draw; this skill is *how* the pixels get written. Read [pcfx-v810-profiling] first —
every technique here was adopted because a profile demanded it, and each one has a
measured cost that may not apply to your renderer.

## 1. The output model: a KING write cursor, not a pointer

You do not write pixels through a C pointer. You program KING's KRAM address once,
then **stream halfwords to a single I/O port**, and the address auto-increments:

```c
/* kram_set_write_inline() emits KRAM_AWR without a call. */
kram_set_write_inline(FB_span, 1);      /* set the cursor once, per span   */
kram_begin_burst();                     /* select KRAM_DATA once            */
for (i = 0; i < count; i++)
    kram_write_latched(pixel_pair);     /* each write advances the cursor  */
```

Consequences that shape every loop here:

- **One word holds two horizontal pixels** (`lo | hi << 8`) in 8bpp. A "256-pixel
  wide" framebuffer is 128 words. Getting this backwards swaps pixel pairs — the
  classic symptom in [pcfx-king-framebuffer].
- **Setting the cursor costs a port write**, so amortize it: set once per span, never
  per pixel. Horizontal spans are cheap; vertical columns need a stride and are why
  column drawers differ from span drawers.
- **`out.h` and `in.h` are the most expensive instructions on this machine** — a real
  profile measured `IN_H` at **CPI 6.23**. Never read back a port you could have kept
  in a register. Never re-read the raster you already sampled.
- Consecutive `out.h` writes pair badly; interleaving one ALU op between them costs
  nothing and can break the penalty (§4).

## 2. The C span kernel — write this first

Always start in C. It is correct, it is the reference for the asm, and on this
compiler it is often within a few percent.

```c
typedef struct {
    uint32_t position;      /* packed 16.16 u in high bits, v in low — see below */
    uint32_t step;
    const uint8_t *source;  /* the texture / flat                                */
    const uint16_t *colormap; /* light level -> YUV word                         */
} draw_span_vars_t;

void draw_span_c(unsigned count, const draw_span_vars_t *dsv)
{
    uint32_t pos = dsv->position, step = dsv->step;
    const uint8_t  *src = dsv->source;
    const uint16_t *cmap = dsv->colormap;

    while (count--) {
        /* one packed add steps both u and v — no per-axis bookkeeping */
        unsigned texel = ((pos >> 5) & 0x07e0) | (pos >> 27);
        out_h(0x604, cmap[src[texel]]);
        pos += step;
    }
}
```

The **packed coordinate** is the important trick: `u` and `v` live in one 32-bit word
at different shifts, so a single `add` steps both, and the texel index is extracted
with shifts and a mask instead of two multiplies. The masks above are for a 64×64
texture; adjust the shift/mask pair for other sizes and keep them powers of two.

Everything is integer — see [pcfx-fixed-point]. There are no divides in the loop: `du`
and `dv` were computed once per span by the caller.

## 3. The DRAM-page problem, and load clustering

This is the PC-FX-specific technique, and the reason the hottest drawer in `doom-pcfx`
is hand-written assembly. It is worth understanding even if you never write asm.

Main RAM is paged in **2 KiB** units with **one** globally-open page. Leaving the open
page costs **+3 cycles**. The C loop above does, per pixel:

1. `src[texel]` — a load from the 2 KiB-aligned flat
2. `cmap[...]` — a load from the 512-byte colormap, in a *different* page

So every single pixel changed the open page **twice**: **+6 cycles/pixel**, measured at
~2.2 ms per frame on a 10.4k-span-pixel frame. This does not show up as a "slow
instruction"; it shows up as inflated CPI on `LD_B`/`LD_H` and a large
`data=` figure in the DRAM block of the profile.

**The fix is to cluster loads from the same page.** Process four pixels at a time:
compute four texel addresses (ALU only), then four `ld.b` back to back, then four
colormap addresses, then four `ld.h` back to back, then four `out.h`. That is
**2 page changes per 4 pixels instead of 8**, and clustering also drops each load's own
penalty from +2 (a load after an ALU op) to +1 (a load after another load).

You can express this in C and often get most of the benefit:

```c
void draw_span_c4(unsigned count, const draw_span_vars_t *dsv)
{
    uint32_t pos = dsv->position, step = dsv->step;
    const uint8_t *src = dsv->source; const uint16_t *cmap = dsv->colormap;

    while (count >= 4) {
        unsigned t0,t1,t2,t3; unsigned b0,b1,b2,b3;
        t0 = ((pos>>5)&0x07e0)|(pos>>27); pos += step;   /* addresses first */
        t1 = ((pos>>5)&0x07e0)|(pos>>27); pos += step;
        t2 = ((pos>>5)&0x07e0)|(pos>>27); pos += step;
        t3 = ((pos>>5)&0x07e0)|(pos>>27); pos += step;
        b0 = src[t0]; b1 = src[t1]; b2 = src[t2]; b3 = src[t3];  /* clustered */
        out_h(0x604, cmap[b0]); out_h(0x604, cmap[b1]);
        out_h(0x604, cmap[b2]); out_h(0x604, cmap[b3]);
        count -= 4;
    }
    while (count--) { /* scalar tail, exactly as in §2 */ }
}
```

**Check it worked**: `data=` in the DRAM block should fall roughly 4×. If it did not,
the compiler re-ordered your loads back together with the uses — that is when you drop
to assembly.

## 4. The assembly kernel, and the two tricks in its tail

`vendor/doompcfx/platform/pcfx_span32.S` is the reference (**21.6% of all measured cycles**
in that game, so it earned the effort). The body is the four-at-a-time clustering
above. The instructive part is the loop tail:

```asm
    out.h   r11, 0x604[r0]
    out.h   r12, 0x604[r0]
    out.h   r13, 0x604[r0]
    /* The loop test sits between the third and fourth write: out.h neither
     * writes nor reads flags, so it both dodges the +2 flag-use stall on the
     * branch and breaks the consecutive-out pairing penalty on that write. */
    add     -4, r6
    cmp     4, r6
    out.h   r14, 0x604[r0]
    bnl     1b
```

Two separate wins from one placement:

- **The flag-use stall is dodged.** A `Bcc` immediately after the `cmp` that set the
  flags stalls +2 cycles. Putting the flag-neutral `out.h` between them reclaims it.
  A real profile showed 99.6% of branches stalling, costing **18.6% of the frame** —
  this is usually the biggest free win available ([pcfx-v810-profiling] §5).
- **The consecutive-`out.h` pairing penalty is broken** by separating the fourth write
  from the third.

Also note: `r6..r19` are caller-saved in the v810-gcc ABI, so a leaf kernel like this
needs **no stack frame** — no prologue, no epilogue, just `jmp [lp]`.

And the placement matters as much as the code: the kernel lives in its own
`.pcfx_span32hot` section because in ordinary `.text` it overlapped its own caller by
~290 bytes and the two evicted each other **15.2k times per frame** in the 1 KB
direct-mapped icache. Put hot kernels in a dedicated section and tune the offset as a
build knob ([pcfx-optimize-loop]).

**Bit-exactness is the acceptance test.** The asm drawer must produce output identical
to the C one — same texel index, same colormap word, same write order. Keep the C
version compiled in behind a flag and diff a screenshot; that is how you know a
scheduling change did not also change what you drew.

## 5. Edge stepping without divides

Per-edge setup does the division once; the loop only adds.

```c
/* One divide per edge, never per scanline. */
static inline fx16_16 edge_step(int y0, int y1, fx16_16 x0, fx16_16 x1)
{
    int dy = y1 - y0;
    return dy ? (fx16_16)((((int64_t)(x1 - x0)) << FX_SHIFT) / (dy << FX_SHIFT)) : 0;
}

for (y = y0; y < y1; y++) {
    int xl = FX_TO_INT(xleft), xr = FX_TO_INT(xright);
    if (xr > xl) draw_span_c4(xr - xl, &dsv);   /* set up dsv for this scanline */
    xleft += dxl; xright += dxr;
}
```

Two rules that prevent the classic artefacts:

- **Fill convention must be consistent** — top-left, everywhere. Otherwise adjacent
  triangles either double-draw shared edges (visible with any blending) or leave
  1-pixel cracks.
- **Recompute shared edges from endpoints, do not accumulate** across a long edge, or
  rounding drift opens seams between triangles ([pcfx-fixed-point] §5c).

## 6. Clip before you rasterize

The cheapest pixel is the one you never consider.

- **Reject whole triangles first**: backface (sign of the 2D cross product — no
  normalization, no divide), then bounding box against the viewport, then near plane.
- **Clip spans to the viewport in the caller**, so the inner loop has no per-pixel
  bounds test. A branch per pixel is 1–3 cycles plus a probable flag stall; at
  10k pixels/frame that is real money.
- **Near-plane clipping is mandatory** — a vertex at or behind the eye makes the
  perspective divide explode and writes garbage across KRAM. Clip in view space
  before projecting, always.

## 7. Order of work when the rasterizer is too slow

Do these in order; the early ones dominate:

1. **Draw fewer pixels.** LOD, smaller viewport, fewer subdivisions. Nothing below
   competes with this ([pcfx-software-3d] §3).
2. **Clip earlier** (§6).
3. **Cluster loads** for the DRAM page (§3) — check `data=` in the profile.
4. **Fix icache conflicts** — dedicated section, tuned offset
   ([pcfx-v810-profiling] §4).
5. **Dodge flag stalls** in the loop tail (§4).
6. **Hand-schedule the kernel** — last, and only for a drawer the profile shows is
   >10% of the frame.

Do not start at 6. Every project here that did, wasted the effort.

## Related

[pcfx-software-3d] for budgets and what to draw · [pcfx-fixed-point] for the math ·
[pcfx-v810-profiling] to find the hot drawer · [pcfx-king-framebuffer] for the KRAM
layout and pixel packing · [pcfx-optimize-loop] for tuning placement.
