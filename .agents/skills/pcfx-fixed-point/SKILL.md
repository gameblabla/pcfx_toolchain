---
name: pcfx-fixed-point
description: Fixed-point arithmetic on the V810 - why there is no FPU, the 16.16 and 8.8 conventions used here, safe multiply/divide/normalize idioms, reciprocal and LUT tables, overflow rules, and converting float algorithms to integer without drift. Use whenever a float or double appears in PC-FX code, for any math in a renderer or physics step, or when values overflow, drift, or jitter.
---

# Fixed point on the V810

## 1. There is no FPU — a `float` is a disaster, not a slowdown

The V810 in the PC-FX has **no floating-point unit**. Every `float` or `double`
becomes a call into libgcc's soft-float routines: tens to hundreds of cycles, a
function call that trashes registers, and a large code footprint that **evicts your
hot loop from the 1 KB icache** ([pcfx-v810-profiling] §4). The cache damage is
usually worse than the arithmetic cost.

**Rule: no `float`, no `double`, anywhere in a PC-FX build.** Not in the renderer, not
in "cold" setup code, not in a debug path. Enforce it — the failure is silent
otherwise, because it compiles fine:

```make
CFLAGS += -Wdouble-promotion -Werror=double-promotion
```

```bash
# catch soft-float creeping back in — should print nothing
v810-none-elf-nm game.elf | grep -iE "__(add|sub|mul|div|fix|float)[sd]f" && \
  echo "SOFT FLOAT LINKED IN -- find it and remove it"
```

Watch for the sneaky sources: `1.0/x` in a macro, `M_PI`, `sinf`, integer division
"fixed" by a cast to float, and `printf("%f")`.

## 2. The conventions used here

Pick a format per quantity and **write it in the type name** — mixing scales silently
is the single most common bug in this code.

| Format | Type | Range | Resolution | Used for |
|---|---|---|---|---|
| **16.16** | `int32_t` | ±32768 | 1/65536 | world coords, texture u/v, camera, general |
| **8.8** | `int16_t` | ±128 | 1/256 | small deltas, per-pixel steps, sin/cos |
| **2.30** | `int32_t` | ±2 | 1/2³⁰ | normalized vectors, dot products |
| **0.16** | `uint16_t` | [0,1) | 1/65536 | fractions, interpolation t |

```c
typedef int32_t fx16_16;   /* Q16.16 */
typedef int16_t fx8_8;     /* Q8.8   */

#define FX_SHIFT   16
#define FX_ONE     (1 << FX_SHIFT)
#define FX_HALF    (FX_ONE >> 1)

#define FX_FROM_INT(i)   ((fx16_16)((i) << FX_SHIFT))
#define FX_TO_INT(f)     ((int)((f) >> FX_SHIFT))          /* floors; see §5 */
#define FX_FRAC(f)       ((f) & (FX_ONE - 1))

/* Compile-time only — a literal here is folded by the compiler and never
 * reaches the V810 as a float. NEVER use this on a runtime value. */
#define FX_C(x)          ((fx16_16)((x) * 65536.0 + ((x) < 0 ? -0.5 : 0.5)))
```

`FX_C(3.14159)` is fine and costs nothing: it is constant-folded. `FX_C(some_var)`
links soft-float. That distinction matters.

## 3. Multiply and divide

A 16.16 × 16.16 product has 32 fractional bits and **must go through 64-bit** or it
overflows almost immediately:

```c
static inline fx16_16 fx_mul(fx16_16 a, fx16_16 b)
{
    return (fx16_16)(((int64_t)a * (int64_t)b) >> FX_SHIFT);
}

static inline fx16_16 fx_div(fx16_16 a, fx16_16 b)
{
    return (fx16_16)((((int64_t)a) << FX_SHIFT) / b);      /* guard b != 0 */
}
```

**Cost check before you optimize these.** The V810's `MUL` is 13 cycles and `DIV` is
38 — slow per op, but a real profile of `wolf-pcfx` showed all multiplies and divides
together were **0.17% of the frame**. Do not replace a multiply with a lookup table
unless the profile says multiplies are actually costing you: an extra cache-missing
load is usually a net loss. See [pcfx-v810-profiling] §2.

What *is* always worth doing is **hoisting divides out of inner loops** — one divide
per span, not per pixel. That is an algorithmic change, not a micro-optimization:

```c
/* WRONG: a 38-cycle divide per pixel */
for (x = x0; x < x1; x++)
    u = fx_div(u_over_z[x], one_over_z[x]);

/* RIGHT: one divide per span, then add a constant step */
fx16_16 u    = fx_div(u0_over_z, inv_z0);
fx16_16 uend = fx_div(u1_over_z, inv_z1);
fx16_16 du   = (uend - u) / (x1 - x0);         /* one more divide */
for (x = x0; x < x1; x++, u += du)
    plot(x, u >> FX_SHIFT);
```

This is affine (linear) interpolation across the span rather than true perspective.
It is what every software renderer of this era did, and at PC-FX span lengths the
error is invisible. Subdivide long spans into 16- or 32-pixel runs if it isn't.

### When 64-bit is too slow

`int64_t` multiply is a libgcc call on the V810. If a profile shows it hurting, and
you can bound the inputs, use the narrower forms:

```c
/* Both operands fit in 16.0 and the result in 16.16: a plain 32-bit multiply. */
static inline fx16_16 fx_mul_int(fx16_16 a, int b) { return a * b; }

/* 8.8 × 8.8 -> 8.8 stays inside 32 bits with no 64-bit help. */
static inline fx8_8 fx88_mul(fx8_8 a, fx8_8 b)
{
    return (fx8_8)(((int32_t)a * (int32_t)b) >> 8);
}
```

**State the bound in a comment and assert it in a host test.** Silent overflow here
produces geometry that flips inside out at certain angles — a bug that is very hard to
find later.

## 4. Reciprocal and trig tables

Divides you cannot hoist become table lookups. Sin/cos always do:

```c
/* 1024-entry sine table, 8.8, one quadrant reused. Generate at BUILD time with a
 * host script -- never call sinf() on the target. */
#define SIN_BITS  10
#define SIN_MASK  ((1 << SIN_BITS) - 1)
extern const fx8_8 g_sin[1 << SIN_BITS];     /* angle is 0..1023, not radians */

#define fx_sin(a)  (g_sin[(a) & SIN_MASK])
#define fx_cos(a)  (g_sin[((a) + (1 << (SIN_BITS - 2))) & SIN_MASK])
```

Use a **binary angle** (0..1023 = full turn) so wrapping is a free `AND` instead of a
modulo. Never store angles in degrees or radians.

Generate tables with a Python script at build time and emit a `.h`. That keeps floats
on the host where they belong:

```python
# tools/gen_tables.py
import math
n = 1024
print("const short g_sin[%d] = {" % n)
print(",".join(str(int(round(math.sin(2*math.pi*i/n) * 256))) for i in range(n)))
print("};")
```

**Table size is a cache decision, not a precision decision.** A 4096-entry 16.16
reciprocal table is 16 KB and will evict everything. 1024 entries of 8.8 is 2 KB and
usually enough. Measure it as a knob ([pcfx-optimize-loop]).

## 5. The three bugs that always happen

**a. Shifting a negative number right is a floor, not a truncation.**
`-1 >> 16` is `-1`, not `0`. So `FX_TO_INT()` floors, which is what a rasterizer
wants — but it means `FX_TO_INT(a) - FX_TO_INT(b) != FX_TO_INT(a-b)`. Round explicitly
when you mean rounding:

```c
#define FX_ROUND_TO_INT(f)  ((int)(((f) + FX_HALF) >> FX_SHIFT))
```

**b. Mixing scales.** Adding an 8.8 to a 16.16 compiles silently and is wrong by a
factor of 256. Convert explicitly at every boundary, and never store two formats in
the same array:

```c
#define FX88_TO_FX1616(v)  ((fx16_16)(v) << 8)
#define FX1616_TO_FX88(v)  ((fx8_8)((v) >> 8))
```

**c. Accumulated drift.** Stepping `u += du` across 256 pixels accumulates the error
in `du` 256 times. For anything where endpoints must land exactly (a texture seam, a
polygon edge shared by two triangles), **recompute from the endpoints** rather than
accumulating, or compute `du` so it lands exactly. Cracks between adjacent triangles
are almost always this bug.

## 6. Converting a float algorithm

Do it in this order, and test on the host after each step:

1. Get it **correct in float on the host first**, with a reference image.
2. Choose a format per variable from §2 and **write the range each one can reach** in
   a comment. This is the step people skip, and it is the one that prevents overflow.
3. Replace operations with the `fx_*` idioms, keeping the host build compiling both
   ways behind a `#ifdef` so you can diff outputs.
4. Compare host float vs host fixed on a fixed input set; the difference should be
   ≤1 unit in the last place of your format.
5. Only then build for the target, and check `nm` for soft-float symbols (§1).

Keeping a host build that runs the same math is what makes this tractable — every one
of these projects has one, and it is how the fixed-point conversions were validated.

## Related

[pcfx-software-3d] for the renderer that consumes this · [pcfx-v810-performance] for
instruction costs · [pcfx-v810-profiling] to check whether the math is actually your
bottleneck (it usually isn't) · [pcfx-optimize-loop] for sizing tables.
