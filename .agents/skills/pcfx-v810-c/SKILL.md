---
name: pcfx-v810-c
description: Write and optimize ordinary C for the PC-FX V810 GCC 4.9.4 toolchain. Covers C integer promotions, signed and unsigned code generation, narrow loads, arithmetic, division, shifts, loops, helper calls, code-size and memory effects, and a reproducible compiler probe. Does not cover inline V810 assembly or .S files.
---

# Optimized C for V810 GCC

This module is for **ordinary C compiled by the bundled V810 GCC**. It does not teach
inline V810 assembly or `.S` programming. For handwritten assembly, use
`pcfx-v810-performance` and the V810 CPU manual.

The target is the workspace's GCC **4.9.4** with the V810 backend. Modern GCC advice,
host-CPU intuition, and advice for the Virtual Boy or V830 are not substitutes for
checking this compiler's output. Treat every code-shape statement below as a starting
point for the pinned compiler and flags, not a promise for every expression or build.

## 1. Before changing code

For performance work, read `pcfx-v810-profiling` first. Optimize the work that the
profile identifies, then compare clean builds and preserve output. A shorter assembly
listing is not automatically a faster frame: the V810 has a small instruction cache,
and PC-FX DRAM page changes and device traffic also matter. The cycle model and measured
catalogue are in `pcfx-v810-performance`.

The standard SDK C flags are:

```text
-O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function
```

They come from `vendor/libpcfx/examples/example.mk`. Inspect the flags in the actual
build rather than assuming they match. For a first code-generation look:

```sh
toolchain/v810-gcc/bin/v810-gcc \
    -O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function \
    -S source.c -o /tmp/source.v810.s
```

Inspect a linked binary as well when helpers, call overhead, or final placement matter:

```sh
toolchain/v810-gcc/bin/v810-objdump -dr build/game.elf
toolchain/v810-gcc/bin/v810-nm build/game.elf
```

`-S` shows what the compiler emitted for that translation unit. It does not show link-time
placement, the final library implementations, or cycles under PC-FX memory traffic.

## 2. The rule for signed and unsigned C

**Choose signedness for the value's meaning and range, not from a blanket speed rule.**
V810 signedness costs are operation-specific. These are three different questions:

1. What behavior does C require, including integer promotions and overflow rules?
2. What instruction sequence does this GCC version emit for this expression?
3. What does the complete program's profile say is expensive?

Do not answer question 3 from question 2 alone.

### RAM loads: the real narrow-type advantage

V810 `LD.B` and `LD.H` sign-extend their byte or halfword into a 32-bit register. GCC can
therefore use one load for a signed `int8_t`/`int16_t` read. For an unsigned RAM read, GCC
commonly adds `ANDI 255` or `ANDI 65535` to clear the sign-extended upper bits. The
reproducible probe in `tests/codegen_probe.c` shows this with this toolchain.

That is a **load-and-conversion** difference. It does not mean unsigned arithmetic is
generally slower. I/O `IN.B` and `IN.H` are different: the CPU zero-extends their results,
so do not apply the RAM `LD.B`/`LD.H` rule to port reads.

If byte/halfword data is consumed repeatedly in a hot loop, consider widening it once
outside the loop or storing a wider representation. Only do so when memory use, input
format, DRAM page locality, and profiling support it. A wider table uses more of PC-FX's
2 MB main RAM and can change page behavior.

### Integer promotions and 8-/16-bit expressions

The V810's general registers and integer arithmetic are 32-bit. C's integer promotions
still apply: `int8_t`, `uint8_t`, `int16_t`, and `uint16_t` operands promote to `int` on
this target because 32-bit `int` can represent all their values. There is no general
8-bit or 16-bit ALU mode to make a narrow temporary intrinsically faster.

Narrow function arguments, loads, casts, and return values can need normalization. The
normalization depends on the expression and ABI boundary: in the included test, signed
16-bit arguments need sign-normalizing shifts before an addition, while unsigned
16-bit arguments use masks. That one case makes **unsigned** shorter. Other code shapes
can differ. Inspect the output; do not extrapolate a single example to all `char` or
`short` code.

For hot calculations, a 32-bit local often avoids repeatedly narrowing and widening
values. Keep a narrow type at storage or API boundaries when it expresses the format or
saves memory; widen at a deliberate boundary if the profile justifies it.

### 32-bit arithmetic, comparisons, shifts, and division

- Ordinary 32-bit add, subtract, and bitwise operations use word operations for either
  signedness. Signed overflow is undefined in C; use unsigned arithmetic when wraparound
  is part of the algorithm.
- Comparisons must preserve signed or unsigned ordering. GCC emits different condition
  tests for signed and unsigned comparisons. For example, `(unsigned)y >= height` can be
  a compact bounds test that also rejects negative `y`, but use it only when that is the
  intended C behavior and `height` has the matching unsigned type.
- Right shift of a negative signed value is implementation-defined in C; this compiler
  uses arithmetic shift for signed values and logical shift for unsigned values. Use
  unsigned masks/shifts for bit-field manipulation. Do not use signed left shift where
  the C standard makes it undefined.
- The V810 has hardware signed `DIV` and unsigned `DIVU`. The V810 manual lists 38 clocks
  for `DIV` and 36 for `DIVU` in its no-hazard/cache-hit timing table. This small base
  difference is not grounds to change a value's meaning. Variable 32-bit division in the
  test compiles to the corresponding instruction; constant divisors may be strength-
  reduced. Check the actual expression and the linked symbols before asserting either.
- The V810 has signed and unsigned multiply instructions. For a function returning only
  the low 32 bits of a 32×32 product, the signed and unsigned C forms can compile to the
  same `MUL`, since those low bits are identical modulo 2^32. In the included GCC 4.9.4
  probe, both a 32×32-to-64 C product and a 64×64 product call libgcc's `__muldi3`
  helper (spelled `___muldi3` in this target's assembly); do not assume GCC will use the
  CPU's high multiply result for a C widening multiply.

These rules do **not** make division cheap. Its documented latency is much higher than a
basic ALU operation. Avoid repeated division in hot loops when the profile shows it is a
cost, but do not replace it with a hand-derived approximation without a correctness test.

## 3. Common C patterns: avoid folklore

| Pattern | Use this reasoning |
|---|---|
| `uint8_t`/`uint16_t` array in a hot loop | Expect a zero-extension cost on RAM loads in many code shapes. Verify; consider widening or restructuring only after profiling. |
| Narrow loop accumulator | Accumulate in a 32-bit type when its range permits. This avoids repeatedly applying narrow-result semantics; confirm the emitted loop. |
| Signed versus unsigned counters | Pick the type whose range and comparisons match the logic. Signed and unsigned comparisons differ; do not change a type just to chase a condition mnemonic. |
| `x / constant` or `x % constant` | Inspect `-O2` output. Constant folding/strength reduction depends on divisor, signedness, and GCC version. |
| Variable `/` and `%` | V810 has `DIV`/`DIVU`; it is wrong to claim the CPU has no hardware divide. Check emitted code and zero-divisor/range assumptions. |
| 64-bit math or `float`/`double` | Often expands to runtime helpers or software floating point. Read `pcfx-fixed-point` and `pcfx-freestanding-runtime`; inspect the final ELF for helpers. |
| `memcpy`, `memset`, or a small helper in a pixel loop | GCC may inline, emit a loop, or call a helper depending on size and context. Inspect `-S` and the linked ELF; don't assume. |
| Pointer loop versus index loop | Let GCC optimize clear C first. Compare the emitted code and benchmark; source spelling alone proves nothing. |
| `volatile` data | Reserve it for observable device/concurrency behavior. It can force repeated loads/stores and block useful optimization. Use SDK I/O APIs for hardware. |
| `restrict`, `inline`, unrolling, or branchless tricks | Use only when the contract is true, inspect the code-size/cache effect, and measure. These are not universal speed switches. |

Never use signed overflow as a wraparound trick. Never cast a pointer to a different
integer type just to force a load width without proving alignment, aliasing, and object
representation. C undefined behavior is not a stable optimization technique.

## 4. Helpers and the 64-bit boundary

The V810 is a 32-bit CPU, but GCC can still use its 32-bit instructions for many
ordinary C operations. The danger is hidden work at widths or formats the core does not
handle directly. In the included probe, both `uint64_t(uint32_t * uint32_t)` and
`int64_t(int64_t * int64_t)` call libgcc's `__muldi3` helper, shown as `___muldi3` in
the assembly. Check each source expression in the exact compiler build instead of
inferring code generation from the operand widths alone.

For a freestanding or size-constrained program, inspect the map and symbols as well as
the C assembly. `pcfx-freestanding-runtime` gives the audit procedure. Do not remove
libraries blindly: make the required runtime contract explicit, then prove it in the
linked output.

## 5. PC-FX performance still depends on memory and code shape

This is a C guide, so use the compiler before considering assembly:

1. Profile the real PC-FX workload with `pcfx-v810-profiling`.
2. Reduce unnecessary work and memory traffic first.
3. Inspect C compiler output for the hot functions and helper calls.
4. Check the V810 icache and PC-FX DRAM-page effects described by
   `pcfx-v810-performance`.
5. Make one C-level change, clean-build, compare the same workload and output, and
   reject changes inside the documented measurement noise.

Don't apply generic advice such as "all multiplication is slow", "use the smallest C
type", "unsigned is always slower", "make every loop branchless", or "unroll every hot
loop". The PC-FX V810 has hardware 32-bit multiply/divide, a small icache, a paged RAM
model, and a compiler whose decisions must be inspected.

## 6. Reproducible evidence

Run the C corpus shipped with this module:

```sh
PCFX_V810_GCC="$PWD/toolchain/v810-gcc" \
    PCFX_PROBE_OUT=/tmp/pcfx-v810-c-probe.s \
    PCFX_Skills/pcfx-v810-c/tests/run_codegen_probe.sh
```

The script compiles `tests/codegen_probe.c` with the standard SDK C flags and checks
stable instruction-level expectations. The exact register allocation is not part of the
contract. Review `/tmp/pcfx-v810-c-probe.s` for complete output. The tested GCC version,
source cases, and observed patterns are recorded in `tests/README.md`.

## Related

`pcfx-v810-performance` (cycle/memory model and measured catalogue) ·
`pcfx-v810-profiling` (measure hot functions) · `pcfx-fixed-point` (replace float) ·
`pcfx-freestanding-runtime` (audit helpers) · the NEC V810 manual at
`RE1PCFX/3DPCFX/docs/v810-cpu-doc.pdf` (instruction semantics and documented timing).
