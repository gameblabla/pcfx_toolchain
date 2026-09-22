# Task: speed up a full PC-FX character without reducing its asset

A PC-FX demo renders one textured character at about 3 FPS in an 8bpp KING BG0
software framebuffer. The generated asset contains exactly 5,563 vertices and 10,628
faces. Product requirements say those asset counts must not change. The target is 10
FPS with a black outline enabled.

Current frame pipeline:

```text
transform/project all vertices
build a 28-byte unsorted record for every accepted face
sort by mean depth
copy every selected record to a second 28-byte sorted array
rasterize at 256x240
redraw inflated geometry for a black outline
compare/upload the 8bpp buffer to KING
```

The profiler is not currently available in this environment, but project notes say the
V810 has a 1 KB direct-mapped icache and a shared 2 KiB DRAM open page. A colleague
suggests regenerating the mesh at half the polygon count and trying a 4bpp mode.

Produce a concrete implementation plan and representative C/V810 code that:

1. preserves all 5,563 vertices and 10,628 faces;
2. removes unnecessary face-record traffic;
3. keeps the software raster at native 256×240 and uses a 512×256 affine KING
   source as presentation packing rather than half-resolution output;
4. keeps black outlines on without a second full geometry pass;
5. explains how DRAM-page and icache behavior affect the layout;
6. provides an efficient affine KRAM delta-upload strategy;
7. states when a separate KING 2bpp outline surface is worth testing;
8. gives a clean A/B and profiler acceptance matrix and does not claim 10 FPS
   without measurement.

Be precise enough that another engineer can implement it without inventing hardware
constants or data layouts.
