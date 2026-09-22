# Task: reach 5 FPS without changing any native character frame

A PC-FX demo renders a textured character at 3.017 presented FPS. The full source asset
contains 5,563 vertices and 10,628 faces and must remain unchanged. Output must remain
256×240 8bpp through a 512×256 affine KING BG0 source, with the existing two-pixel black
outline. The linked runtime must remain freestanding: no newlib/libc/libgcc, float,
64-bit helper, software divide helper, timer, or IRQ handler.

The profiler reports:

```text
DRAM penalty cycles/field: 46,447
I-cache misses/field:       4,502
```

The only animation state is an eight-bit Y angle advanced by two after each completed
render. Camera, projection, textures, palette, lighting, background, and outline are
fixed. Intermediate geometry optimizations reach only 4.1 FPS.

Produce an implementation and verification plan that reaches at least 5 FPS with no
visual concession. The plan must:

1. recognize the exact finite visible-state count;
2. keep every native indexed output pose byte-identical to the full renderer;
3. explain a compact transition-row format that erases stale pixels without a full clear;
4. include representative V810 decode assembly that respects immediate widths and ABI;
5. retain the original model asset and a geometry-regeneration fallback;
6. use emulator RAM captures, not screenshot similarity, for fidelity acceptance;
7. require two warmed profiler runs and report FPS, DRAM penalties, and i-cache misses;
8. state when this technique is invalid because visible state is not finite.

Do not propose half-resolution rendering, polygon reduction, pose reduction, 4bpp, 16bpp,
or an approximate sprite conversion.
