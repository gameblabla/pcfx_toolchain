# Task: the floor/ceiling drawer is the hottest thing in a PC-FX Doom port

## What we know

Profiling a gameplay benchmark shows the flat-span drawer is **21.6% of all V810
cycles**. The relevant parts of the profile:

```
Cycles attributed : 645381643  (358545 / field = 100.17% of a field)
CPI (mean)        : 2.726 cyc/instr

-- slow ops --
MUL   count=17964 (10/field)  cycles=275332 (153/field, 0.04%)
MULU  count=48527 (27/field)  cycles=640545 (356/field, 0.10%)
DIV   count=2312 (1/field)  cycles=87878 (49/field, 0.01%)
DIVU  count=4042 (2/field)  cycles=146354 (81/field, 0.02%)

-- opcodes by cycles (top 6) --
op                count   %cnt         cycles   %cyc    CPI
BE             36321102  15.3%      171789684  26.6%   4.73
BNE            18172066   7.7%       91605566  14.2%   5.04
LD_B           25545167  10.8%       77808420  12.1%   3.05
OUT_H           2274574   1.0%        9206184   1.4%   4.05
CMP_I          33991055  14.4%       34335031   5.3%   1.01

-- flag-use stalls --
flag-readers/field=33431  stalled=33299 (99.6%)

-- 2 KiB DRAM page penalties (+3 cyc each) --
penalty cyc/field=9263 (2.59% of a field)   code-refill=515  data=8748
```

## The drawer

Roughly 10,400 span pixels are drawn per frame. `flat` is a 4 KiB texture
(2 KiB-aligned); `colormap` is a separate 512-byte light table.

```c
void R_DrawSpan32(unsigned count, const draw_span_vars_t *dsv)
{
    uint32_t pos = dsv->position, step = dsv->step;
    const uint8_t  *flat     = dsv->source;     /* the 64x64 flat   */
    const uint16_t *colormap = dsv->colormap;   /* 256 YUV words    */

    while (count--) {
        unsigned texel = ((pos >> 5) & 0x07e0) | (pos >> 27);
        out_h(0x604, colormap[flat[texel]]);    /* KING KRAM write cursor */
        pos += step;
    }
}
```

A colleague proposes: "replace the shift/mask texel computation with a precomputed
lookup table, and get rid of the multiplies — multiplies and divides are slow on the
V810 (13 and 38 cycles)."

## What to produce

1. Is the colleague's proposal a good idea? Answer from the numbers above, and give
   the number that decides it.
2. What is actually costing the most in this loop? Name the mechanism, with the
   hardware reason and the relevant figure from the profile.
3. Give the concrete restructuring of the loop that addresses it, as C code.
4. Say how you would verify the change worked — which specific profiler number should
   move, and in which direction.
5. Name one further optimization to the loop tail, and what it is worth.

Be specific and terse.
