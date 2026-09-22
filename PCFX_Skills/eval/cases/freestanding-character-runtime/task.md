# Task: remove hidden runtime dependencies from a PC-FX character renderer

A native 256×240 V810 software renderer must not depend on newlib/libc, libsim,
soft-float, 64-bit arithmetic, software divide/modulo helpers, timer IRQs, registered
interrupt handlers, or out-of-line compiler prolog helpers. The current Makefile links
`-leris -lc -lsim -lgcc` and uses `-mprolog-function`. `main.c` includes `<string.h>`
and `<eris/timer.h>`, calls `memset`, constructs a 1,024-entry reciprocal table at
runtime with C division, and installs a timer handler for the FPS HUD.

The V810 has 32-bit `DIV`/`DIVU`. The target environment is temporarily missing the
cross-toolchain and profiler-enabled emulator. The last user-reported baseline is
3 FPS, but no current profile exists.

Produce a concrete source/build patch plan and representative code that:

1. removes the forbidden runtime dependencies without introducing float or int64;
2. uses explicit V810 hardware signed/unsigned division, including the remainder
   register constraint;
3. moves reciprocal-table generation offline with DRAM-aware alignment;
4. removes timer/IRQ-handler measurement without claiming a replacement HUD is exact;
5. audits both source intent and the final map/ELF for compiler-generated helpers;
6. reports current FPS, DRAM penalties, and i-cache misses honestly when no profiler
   report is available.
