---
name: pcfx-freestanding-runtime
description: Build and audit a performance-critical PC-FX V810 program with no newlib/libc, libsim, soft-float, 64-bit helpers, software divide helpers, timer IRQ, or registered interrupt handler. Covers freestanding flags, explicit V810 DIV/DIVU, offline reciprocal tables, memory clears, map/symbol audits, and honest FPS/DRAM/icache reporting when the profiler is unavailable.
---

# Freestanding V810 runtime audit

Use this module when a PC-FX program must not depend on general-purpose runtime code.
This is stricter than the normal SDK template. It is appropriate for a small renderer
whose hot code and RAM layout are sensitive to every linked object.

## 1. Define the contract before editing

A strict target should state all of these explicitly:

```text
- no newlib/libc or libsim
- no float or double
- no int64_t, uint64_t, or long long
- no compiler software divide/modulo helpers
- no timer IRQ
- no registered interrupt handler
- no out-of-line compiler prolog helpers
- only 32-bit integer runtime arithmetic
- DRAM and icache numbers must come from the profiler, not estimates
```

Do not translate “no software divide” into “never use division.” The V810 has hardware
`DIV` and `DIVU`. The rule is to prevent calls such as `__divdi3`, `__udivsi3`, or a
newlib/libgcc helper.

## 2. Freestanding build shape

A direct `v810-ld` link already avoids GCC's automatic default libraries, but an
explicit library list can still pull them back. For a project that uses liberis device
routines but no libc services:

```make
CFLAGS += -O3 -ffreestanding -fno-builtin -fomit-frame-pointer \
          -fno-stack-protector -fno-unwind-tables \
          -fno-asynchronous-unwind-tables -ffunction-sections \
          -fdata-sections -std=gnu99 -mv810 -mno-prolog-function -msda=0

# Select -mno-prolog-function explicitly; -mprolog-function pulls libgcc save/restore helpers.
LIBS := -leris

$(ELF): $(OBJS)
	$(LD) $(CRT0) $(OBJS) $(LIBS) --gc-sections -Map $(MAP) -o $@
	python3 tools/audit_runtime_dependencies.py --elf $@ --map $(MAP)
```

Forbidden release libraries for this contract:

```text
-lc -lm -lsim -lgcc
```

`-lgcc` is not universally wrong. It is forbidden here because the point of the link
is to fail immediately if GCC emitted a hidden arithmetic or prolog helper.

## 3. Explicit 32-bit V810 division

Keep variable division visible and target-specific:

```c
static inline __attribute__((always_inline))
uint32_t pcfx_divu32(uint32_t numerator, uint32_t denominator)
{
#if defined(__v810__)
    __asm__ volatile (
        "divu %1,%0"
        : "+r" (numerator)
        : "r" (denominator)
        : "r30");
    return numerator;
#else
    return numerator / denominator; /* host-only test fallback */
#endif
}

static inline __attribute__((always_inline))
int32_t pcfx_divs32(int32_t numerator, int32_t denominator)
{
#if defined(__v810__)
    __asm__ volatile (
        "div %1,%0"
        : "+r" (numerator)
        : "r" (denominator)
        : "r30");
    return numerator;
#else
    return numerator / denominator;
#endif
}
```

The quotient replaces the numerator register. `r30` receives the remainder and must be
listed as clobbered. Do not write `(int64_t)a * b / c`; that defeats the contract even
if the final result is 32-bit.

Use the wrappers for rare exact divides such as:

```c
mean_depth = pcfx_divs32(z0 + z1 + z2, 3);
```

Constant powers of two should remain shifts.

## 4. Generate reciprocal tables offline

Do not spend startup time filling a reciprocal table with hundreds of divides. Generate
it on the host and compile it as read-only data:

```python
values = []
for index in range(1024):
    d = index - 512
    if d == 0:
        d = 1
    q = 65536 // abs(d)
    values.append(-q if d < 0 else q)  # C99 truncation toward zero
```

```c
const int32_t divTab[1024] __attribute__((aligned(4096))) = {
    /* generated values */
};
```

Why 4 KiB alignment matters here:

- the table occupies 4 KiB;
- main RAM has 2 KiB open pages;
- the positive-denominator half begins at byte `0x800`;
- a 4 KiB-aligned base therefore puts that hot half exactly on a 2 KiB page boundary.

This does not prove fewer page penalties. It removes an avoidable alignment ambiguity;
profile afterward.

## 5. Remove libc memory operations deliberately

Deleting `<string.h>` is not enough. Replace every target call:

```c
static inline void clear_words(uint32_t *dst, uint32_t words)
{
#if defined(__v810__)
    while (words--) {
        __asm__ volatile ("st.w r0,0[%0]" :: "r" (dst) : "memory");
        ++dst;
    }
#else
    while (words--) *dst++ = 0;
#endif
}
```

For hot clears, unroll the V810 loop and keep it inside a measured cache footprint.
For cold startup code, clarity matters more than one branch per word.

Search for all of these, not only `memset`:

```text
memcpy memmove memset malloc calloc realloc free
printf sprintf snprintf puts abort exit
```


GCC can create a dependency even when none of those names appears in source. With the
supplied GCC 4.9.4, selecting rows from a block-scope compound-literal table such as
`(const uint8_t[7]){...}` generated a call to `memcpy`. Put such immutable tables in
file-scope `static const` storage and inspect the fresh ELF/map after every clean build.

## 6. No timer or IRQ handler

A renderer can avoid handler infrastructure completely:

```c
static inline void pcfx_disable_interrupts(void)
{
#if defined(__v810__)
    uint32_t psw;
    /* GNU V810 as in the supplied GCC 4.9.4 toolchain has no `di` mnemonic. */
    __asm__ volatile (
        "stsr 5,%0\n\t"
        "ori 0x1000,%0,%0\n\t"   /* PSW.ID */
        "ldsr %0,5"
        : "=&r" (psw)
        :
        : "memory"
    );
#endif
}
```

Then remove:

```text
<eris/timer.h>
eris_timer_*
irq_set_handler
__attribute__((interrupt))
```

Do not pretend a sparsely polled raster counter is an exact low-FPS clock. A long
rasterizer may cross many fields between polls. A no-handler HUD may be retained as a
sanity indicator, but release FPS must come from external unique-frame capture or the
profiler harness.

This is a trade-off. Other projects may correctly choose a timer IRQ for real-time game
clocks. The no-handler rule applies only when the project contract explicitly requires
it.

## 7. Source audit and link audit are separate

A source grep cannot prove the final ELF is clean. GCC and archives can introduce code
that never appears in the C file.

### Source checks

Verify:

```text
- no forbidden headers/calls/types
- explicit DIV/DIVU wrappers exist
- reciprocal table is const and generated offline
- Makefile has -ffreestanding
- Makefile explicitly uses -mno-prolog-function
- LIBS is exactly the intended device library set
```

### Map checks

Reject any inclusion of:

```text
libc.a libm.a libsim.a libgcc.a
```

Also reject `liberis.a(v810.o)` when the sole reason it would be linked is IRQ helper
use. Static archives are object-granular: one `irq_disable()` reference can bring in the
whole handler table object.

### Symbol checks

Use `readelf -Ws` or `v810-nm` and reject:

```text
memcpy memmove memset malloc free printf
_irq_handlers irq_set_handler eris_timer_*
__divdi3 __udivdi3 __moddi3 __umoddi3 __muldi3
soft-float conversion/arithmetic helpers
```

Example:

```bash
python3 tools/audit_runtime_dependencies.py
python3 tools/audit_runtime_dependencies.py \
  --elf build/pcfx/game.elf --map build/pcfx/game.map
```

The first pass checks intent. The second proves the linked result.

## 8. Performance reporting without inventing numbers

A valid report distinguishes evidence levels. Before a profiler run, use:

```text
Original baseline: 3.0 FPS (user-reported)
Current source: unmeasured
Current DRAM penalty cycles/field: unavailable
Current icache tag/subblock misses: unavailable
Reason: no current ELF/profiler run
```

After a valid repeated capture, replace those fields with the measured result. For the
current exact-output `3DCharacterSpinning` release, the evidence is 30.117 presented
FPS, 23,996 DRAM penalty cycles/field, and 132 i-cache misses/field. Its clean linked ELF
still contains no newlib/libc/libgcc, float, int64 helper, software divide helper, timer,
or IRQ handler. Never turn structural changes into numeric claims. Statements such as
“the packed key should reduce page changes” are hypotheses until the profiler reports
the DRAM block.

For the current build, collect:

```bash
V810_PROF_CSV=prof.csv pcfx-headless-prof --frames 3600 game.cue 2> prof.txt
sed -n '/V810 PROFILE/,/^####################/p' prof.txt
```

Record at minimum:

```text
FPS / unique presented frames
cycles per field and CPI
i-cache tag misses
i-cache subblock misses
misses per field
fixed miss cycles per field
DRAM penalty cycles per field
DRAM code-refill cycles per field
DRAM data cycles per field
per-symbol cycle and miss totals
```

If those fields are absent, report `unavailable`, not zero.

## 9. Qwen-oriented implementation checklist

```text
[ ] Read the Makefile and final map, not only main.c.
[ ] Remove string.h, stdio.h, stdlib.h, math.h, and eris/timer.h.
[ ] Replace every libc memory/string/format call used by the target.
[ ] Remove float, double, int64_t, uint64_t, and long long.
[ ] Remove timer IRQ setup and every registered handler.
[ ] Disable CPU interrupts locally if the runtime contract requires no ISR.
[ ] Replace variable C division with explicit V810 DIV/DIVU wrappers.
[ ] Declare r30 clobbered for DIV/DIVU inline assembly.
[ ] Generate reciprocal tables offline and make them const.
[ ] Use -ffreestanding and -mno-prolog-function.
[ ] Link only the required device library; do not add -lc/-lsim/-lgcc.
[ ] Fail the build if the map or ELF contains forbidden archives/symbols.
[ ] Report FPS/DRAM/icache as unavailable only when no valid profiler report exists.
[ ] Never report an estimated FPS as measured.
```

## Related

`pcfx-v810-performance` · `pcfx-v810-profiling` · `pcfx-fixed-point` ·
`pcfx-frame-timing` · `pcfx-character-8bpp`
