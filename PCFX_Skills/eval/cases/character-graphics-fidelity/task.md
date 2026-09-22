# Task: fix a PC-FX character that became graphically corrupted after optimization

A dense textured character previously rendered coherently. After a performance pass,
a new host montage shows repeated/noisy textures, holes in the hair and dress, and
missing facial/limb detail. The asset generator still reports exactly 5,563 vertices
and 10,628 faces. The runtime target remains native 256×240 8bpp with a black outline
and a 512×256 affine KING presentation surface.

Relevant code and configuration:

```python
# Host diagnostic renderer. Model UV components are integers from 0 through 255.
# Each generated texture tile is 64x64.
texel_u = interpolated_u.astype(int) & 63
texel_v = interpolated_v.astype(int) & 63
```

```asm
/* Runtime V810 sampler; interpolated UVs are fixed-point values derived from
   the same 0..255 model UVs. The runtime atlas has a 256-byte row stride. */
andi    0x3f00,r19,r23
andi    0x3f00,r17,r24
shr     8,r24
add     r24,r23
add     r21,r23
ld.b    0[r23],r25
```

```make
MIN_TRIANGLE_AREA2 ?= 4
```

```asm
/* signed double-area in r15 */
movea   SCENE_MIN_TRIANGLE_AREA2,r0,r10
cmp     r10,r15
ble     .Lskip
```

At four fixed angles, the area threshold submits only about 1,300–1,650 faces. With the
threshold disabled, about 4,800–5,600 front-facing nondegenerate faces are submitted.
The full asset must remain intact and output resolution must not be reduced.

Diagnose which defect is only in the host diagnostic and which defect changes the
release image. Produce precise patches and regression checks that:

1. match the V810 texture-address calculation for 0..255 UVs and 64×64 tiles;
2. verify the four-lane runtime atlas with a 256-byte row stride;
3. preserve all front-facing nondegenerate projected triangles by default;
4. retain a nonzero area threshold only as a clearly labeled profiling A/B;
5. prevent a future agent from blaming or decimating the source mesh;
6. do not claim emulator/hardware correctness without a V810 build and capture.
