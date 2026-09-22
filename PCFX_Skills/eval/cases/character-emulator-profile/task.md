# Task: produce an authoritative PC-FX renderer profile

A native 256×240 8bpp PC-FX character renderer has been optimized, but the only known
number is an old user-reported 3 FPS baseline. The release build must keep black
outlines and the full 5,563-vertex / 10,628-face asset. The engineer asks for current
FPS, 2 KiB DRAM-page penalties, and 1 KiB i-cache misses from the emulator profiler.

The program has a global 32-bit `nframe` counter that increments only when a completed
rendered buffer is presented. The headless emulator supports warmed savestates and RAM
dumps. The custom `pcfx-headless-prof` prints a `V810 PROFILE` block to stderr at exit.
In the current environment the V810 toolchain, instrumented profiler binary, and BIOS
may be missing.

Give a concrete, automatable measurement procedure and report contract that:

1. clean-builds and audits the fresh ELF/map for forbidden runtime dependencies;
2. proves the renderer was reached before capture;
3. computes presented FPS from `nframe` RAM deltas and profiler video fields;
4. parses total/code/data DRAM penalties and tag/subblock i-cache misses;
5. starts two captures from the same warmed savestate and enforces a 3% gate;
6. refuses to treat an ordinary headless emulator as the instrumented profiler;
7. reports missing metrics as unavailable/null instead of zero or estimates.

Include representative command lines and parser/validation behavior.
