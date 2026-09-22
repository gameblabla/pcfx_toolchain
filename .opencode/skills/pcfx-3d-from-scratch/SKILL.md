---
name: pcfx-3d-from-scratch
description: Build a complete PC-FX software-3D program from nothing - choose a renderer class for the scene, convert an arbitrary mesh/texture asset into V810 headers or a CD blob, write the fixed-point transform/cull/sort/raster/present chain, and bring it up through ordered verification gates. Use when starting a new 3D project, when you have an asset (OBJ/COLLADA/PNG) and no code yet, or when an existing 3D program must be rebuilt from its pipeline up rather than patched.
---

# Building a PC-FX 3D program from zero

This skill is the **generic construction procedure**. It does not assume any particular
model, texture, frame rate or project. Everything is parameterized by an *output
contract* you write down first (§1) and never silently violate later.

Order of reading: this skill decides the shape of the program; [pcfx-software-3d] gives
the budget; [pcfx-3d-pipeline] has a verified working cube you should copy rather than
retype; [pcfx-3d-rasterizer] is the inner loop; [pcfx-v810-profiling] is how you find
out whether any of it was worth it.

**Never start from a blank file.** Copy `pcfx-3d-pipeline/template/` (rotating cube,
measured 60 fps) or the nearest `vendor/libpcfx/examples/` program, get it booting, and mutate
it toward your scene. Every from-blank attempt in this workspace lost a day to a boot
failure that the template does not have.

---

## 1. Write the output contract before any code

Before choosing a technique, fix these in a header the whole project includes. They are
the things an optimizer is forbidden to change without the user's consent — the single
most common failure here is an agent "achieving" a frame rate by quietly rendering
fewer pixels or fewer triangles than asked for.

```c
/* scene_contract.h — edit these numbers; do not scatter copies of them. */
#define SCENE_W            256   /* logical software raster width, pixels   */
#define SCENE_H            240   /* logical software raster height          */
#define SCENE_BPP            8   /* 8bpp paletted is the default; see below */
#define SCENE_TARGET_FPS    10   /* what the user asked for                 */
#define SCENE_VERTEX_COUNT  ...  /* from your asset builder, not guessed    */
#define SCENE_FACE_COUNT    ...
#define SCENE_MIN_TRIANGLE_AREA2 0  /* 0 = draw every projected face        */
```

Then generate the counts from the asset rather than typing them:

```python
# tools/emit_contract.py — run at build time, never hand-edit the output
verts, faces = load_mesh(sys.argv[1])
print(f"#define SCENE_VERTEX_COUNT {len(verts)}")
print(f"#define SCENE_FACE_COUNT   {len(faces)}")
```

A validator in the build (§7) then fails the build if the raster dimensions, the bit
depth, or the mesh counts move. This is how a generic project gets the guarantees that
[pcfx-character-8bpp] states for one specific asset.

**Contract rules that hold for every project:**

- Presentation packing (a 512-wide KING affine surface, a 2× KING stretch) is *not* a
  resolution change. Rendering 128×120 and letting KING stretch it is a legitimate
  design **only when the user agreed to the lower logical raster**.
- Decimating the mesh, dropping small faces, or shrinking the viewport are scene
  changes. Propose them; do not perform them silently.
- No `float`/`double` anywhere ([pcfx-fixed-point]). There is no FPU.

---

## 2. Choose a renderer class

Pick from measured reality ([pcfx-software-3d] has the table), not from ambition.

| Scene | Class | Realistic fps | Skill |
|---|---|---|---|
| Corridor/maze, axis-aligned walls | Raycaster, column drawer | **60** | [pcfx-3d-rasterizer] §5 |
| Static level, precomputed visibility | BSP + span drawer | 15–20 | [pcfx-3d-rasterizer] |
| Few hundred flat-shaded triangles | Painter's triangle raster | 30–60 | [pcfx-3d-pipeline] |
| Textured world + a model | Affine texture spans | ~10 | [pcfx-3d-rasterizer] §2 |
| One 5–15k-face textured mesh | Full-mesh painter | 2–4 | [pcfx-character-8bpp] |
| Free 6-DOF polygon engine | Clip + transform per frame | ~2 | [pcfx-software-3d] |

Two structural questions decide most of the design:

1. **Is the visible state set finite and small?** A turntable with N discrete angles, a
   fixed camera, fixed lighting — then the fastest legal renderer may be a *baked output
   stream*, not a renderer at all ([pcfx-character-8bpp] §10A). This is invalid the
   moment the camera, zoom, lighting or animation becomes free.
2. **Does the camera move through the geometry?** If yes you need near-plane clipping
   (§5) and cannot rely on "reject if any vertex is off-screen".

---

## 3. Assets: get them into the target as flat, immutable arrays

The asset pipeline is host-side Python. Nothing here parses OBJ/COLLADA on the V810.

```text
model.obj / model.dae  ─┐
texture.png            ─┼─► tools/build_assets.py ─► src/mesh_data.h  (small assets)
palette                ─┘                          └► assets/mesh.bin (large assets)
```

Rules that come from the hardware, not taste:

- **Emit pre-scaled byte offsets, not indices.** If a projected vertex is 8 bytes, store
  `index * 8` in the face record so the runtime does an add instead of a shift-and-add.
  Assert the maximum fits your field width:
  ```python
  STRIDE = 8
  offsets = [i * STRIDE for i in face_indices]
  assert max(offsets) <= 0xffff, "vertex count needs a wider offset field"
  ```
- **Interleave what is read together.** One packed record per face beats parallel arrays;
  main RAM has a single open 2 KiB page and alternating arrays reopens it constantly
  ([pcfx-v810-performance]).
- **Quantize positions to fixed point offline.** Choose the scale so the largest
  coordinate times the largest matrix entry cannot overflow 32 bits. `int16_t` model
  space with a Q16.16 matrix is the usual safe pairing.
- **Convert the palette to Y8U4V4** with `pcfx-yuv-palette/rgb_to_yuv.py`. RGB555 does
  not exist on this machine.
- **Textures: power-of-two, and match the sampler to the UV domain.** If the exporter
  wrote 0–255 UVs and your tiles are 64×64, the texel index is `(uv >> 2) & 63` — *not*
  `uv & 63`, which tiles the texture four times per axis and looks like asset corruption.
  Write a host test asserting the two expressions you use (C and Python) agree over the
  whole signed range.
- Anything above a few tens of KB goes on the disc, not in a header ([pcfx-cd-assets]).
  A 2 MB RAM budget includes your code.

If the task needs artwork the repository does not contain, **ask the user for it** and
state the constraints — see [pcfx-vision-assets] §5. Do not invent placeholder art and
then optimize against it.

---

## 4. The math layer: fixed point, tables, no divides in loops

Copy this verbatim from the verified template; do not re-derive it.

```c
typedef int32_t fx;                         /* Q16.16 */
#define FX_SHIFT 16
#define FX_ONE   (1 << FX_SHIFT)

/* V810 `mul` puts the low 32 bits in the destination and the HIGH 32 bits in
 * r30. GCC 4.9.4 will not emit this from (int64)a*b — it calls __muldi3.
 * The "=&r" early-clobber matters: without it `hi` can alias input `b`. */
static inline fx fx_mul(fx a, fx b)
{
#ifdef HOST_TEST
    return (int)(((int64_t)a * b) >> FX_SHIFT);
#else
    int lo, hi;
    __asm__ ("mul %2, %0\n\t"
             "mov r30, %1"
             : "=r"(lo), "=&r"(hi)
             : "r"(b), "0"(a)
             : "r30");
    return (int)(((unsigned)lo >> 16) | ((unsigned)hi << 16));
#endif
}
```

Getting `fx_mul` wrong is the classic "everything projects off-screen, the renderer is
black, yet every isolated piece works" bug ([pcfx-3d-pipeline] §1b).

**Angles are BAM, not degrees.** Use a power-of-two turn (1024 or 256 steps) so
wrapping is a mask and the sine table index needs no modulo:

```c
#define BAM_MASK 1023
static inline fx fx_sin(int a) { return g_sin[a & BAM_MASK]; }
static inline fx fx_cos(int a) { return g_sin[(a + 256) & BAM_MASK]; }
```

Bake `g_sin` offline (`tools/gen_sin.py`) as `const` data. Never compute trig at runtime.

**Divides.** One perspective divide per *vertex* is affordable; one per pixel is not.
The V810 has real 32-bit `DIV`/`DIVU` — use them explicitly when a strict build must not
pull in `__divsi3` ([pcfx-freestanding-runtime]). Inside a span, step precomputed deltas
instead ([pcfx-3d-rasterizer] §2). If you need many reciprocals of a bounded range, bake
a reciprocal table offline.

**Do not "optimize away" multiplies.** On this machine multiplies are cheap; all slow
arithmetic together measured 0.17% of a frame in a real profile. Compares, taken
branches and I/O port reads are the expensive things. Let the profiler decide.

---

## 5. The frame: transform → cull → sort → raster → present

Write it in this order and verify after each stage (§6).

```c
void scene_frame(int yaw, int pitch)
{
    mat3 m; mat_rot_y(&m, yaw); mat_rot_x_post(&m, pitch);

    /* 1. transform + project every vertex once, into a compact array */
    for (i = 0; i < SCENE_VERTEX_COUNT; i++)
        project(v_transform(&m, g_verts[i]), &g_projected[i]);

    /* 2. cull: emit a 4-byte key per accepted face, nothing else */
    n = 0;
    for (f = 0; f < SCENE_FACE_COUNT; f++) {
        const face_t *fc = &g_faces[f];
        const pt2 *a = PROJ(fc->off0), *b = PROJ(fc->off1), *c = PROJ(fc->off2);
        int area2 = (b->x - a->x) * (c->y - a->y) - (c->x - a->x) * (b->y - a->y);
        if (area2 <= SCENE_MIN_TRIANGLE_AREA2) continue;     /* backface */
        g_keys[n].depth  = (int16_t)((a->z + b->z + c->z) >> 2);
        g_keys[n].source = (uint16_t)f;
        n++;
    }

    /* 3. sort keys only (radix on depth), never whole face records */
    radix_sort_keys(g_keys, n);

    /* 4. expand accepted faces ONCE into the draw array, in painter order,
     *    then enter the rasterizer for the whole batch */
    scene_expand(g_keys, n, g_faces, g_projected, g_draw);
    scene_draw_batch(g_draw, n);

    /* 5. present: flip the KING page, having cleared this page's previous
     *    dirty rect and not the whole 30,720 words */
    scene_present();
}
```

Five structural rules, each of which was a measured win:

1. **One 4-byte sort key per face** (`{int16 depth; uint16 index;}`), not a 28-byte draw
   record copied twice. Interleave the two fields; separate arrays cost DRAM pages.
2. **Expand accepted faces once**, after sorting, into contiguous draw records.
3. **Cross the C↔assembly boundary once per batch**, never once per triangle.
4. **Clear only the dirty rectangle of the page you are about to reuse.** With double
   buffering a page comes back two rendered frames later; track a rect per page.
5. **Keep each stage a separate compact function.** The icache is 1 KB direct-mapped;
   one merged mega-loop evicts itself every iteration ([pcfx-v810-performance]).

**Clipping.** If the camera can approach geometry, clip in view space against the near
plane *before* projecting — a vertex with `z <= 0` projects to garbage and a screen-space
area test then disagrees with the true facing ([pcfx-3d-pipeline] §4.3). If the camera
cannot, it is enough to reject faces whose projected bounds leave the raster, and to
clamp spans to `[0, SCENE_W)` and `[0, SCENE_H)`. Use unsigned compares for the double
bound: `if ((unsigned)y >= SCENE_H) skip;`.

**Presentation.** Two KRAM pages, flipped every rendered frame. The BG0 CG-base register
is an **8-bit field in 1024-word units** and the sub-layer must track it:

```c
king_set_bat_cg_addr(KING_BG0,    0, base >> 10);
king_set_bat_cg_addr(KING_BG0SUB, 0, base >> 10);
```

Writing a raw word address here truncates to 0 and the flip silently never happens —
the second classic black-screen bug. Start rendering into page 1; page 0 is displayed
first. Details and the KRAM burst-write idiom: [pcfx-king-framebuffer].

---

## 6. Bring-up gates: never debug more than one stage at a time

Run these in order. Each has a cheap, unambiguous pass condition. Do not proceed past a
failing gate by adding more code.

| # | Gate | How | Pass condition |
|---|---|---|---|
| 0 | It boots | template unchanged, `--frames 1800` screenshot | your colour, not the BIOS logo |
| 1 | Math is right | build `-DHOST_TEST`, run on x86 against a geometric oracle | every face's visibility matches the oracle at every orientation |
| 2 | KRAM path | draw a static checkerboard once, no transform, no flip | checkerboard on screen |
| 3 | Rasterizer | draw one literal triangle with hard-coded screen coords | triangle on screen, correct pixel count |
| 4 | Transform | draw the real mesh, no flip, one frame | recognisable silhouette |
| 5 | Flip | fill page 0 with a checker, page 1 black, flip each frame | screenshot at **odd and even** `--frames` shows different pages |
| 6 | Steady state | savestate after it is running, resume 600 fields, diff the rendered-frame counter | counter delta / fields = your fps |

Gate 1 is the one agents skip and should not. Host-testing the transform caught a face
winding bug in minutes that took hours to chase on target.

**But know what gate 1 does not cover.** The host build replaces the V810 asm — `fx_mul`
takes an `int64` path under `-DHOST_TEST` — so a broken inline-asm multiply passes the
oracle and still draws nothing on target. When the host test passes and the screen is
black, that combination is *evidence*: the bug is in something the host build stubs out
(the asm, the I/O ports, the page flip), not in the geometry. Disassemble the target
build rather than re-checking the maths. The oracle is: rotate the
face's outward normal by the same matrix, dot with the view-space centroid, and require
the sign to agree with your screen-space area test.

Two on-target debugging tools worth remembering:

- **Read KRAM back** (`king_set_kram_read` + `--dump ram`) to separate "not drawn" from
  "drawn but not displayed".
- **Encode state into pixels.** A build that cycles fixed orientations and writes the
  orientation index into the background grey lets a screenshot tell you exactly which
  frame you are looking at — boot timing varies per emulator run, so "frame N" does not
  pin the animation phase.

All harness mechanics — the ~1200-frame BIOS boot delay, savestates, input files — are in
[pcfx-emulator-testing]. A screenshot before frame ~1200 is the BIOS logo, and mistaking
it for a broken program is the single most common error in this workspace.

---

## 7. Guard the contract in the build

```make
check: $(TARGET)
	python3 tools/validate_contract.py src/ $(TARGET).map
```

```python
# tools/validate_contract.py — fail the build, do not warn
assert grep("#define SCENE_W 256", src)          # requested raster preserved
assert grep("#define SCENE_H 240", src)
assert vertex_count == manifest["vertices"]      # asset not decimated
assert face_count   == manifest["faces"]
assert not grep(r"\b(float|double)\b", src)      # no FPU
assert make_default("SCENE_MIN_TRIANGLE_AREA2") == "0"
forbidden = ["RENDER_SCALE_SHIFT", "expand_raster_2x"]   # silent downscales
assert not any(grep(f, src) for f in forbidden)
```

A source grep is necessary but not sufficient: GCC can synthesize libcalls (`__muldi3`,
`__divsi3`, soft-float, block copies) that no grep sees. For a strict runtime, audit the
final map and ELF symbols — [pcfx-freestanding-runtime] has the procedure.

---

## 8. Only now, make it fast

Do not optimize a program that has not reached gate 6. When it has, the order is fixed
and is in [pcfx-self-improve] §2, summarised:

1. **Profile** ([pcfx-v810-profiling]). Every unprofiled guess made in this workspace
   was wrong.
2. **Do less work** — cull earlier, reduce overdraw, cut record traffic. Not resolution,
   unless the contract permits it.
3. **Fix memory behaviour** — compact interleaved streams, cluster loads by DRAM page,
   then chase icache conflicts between hot functions.
4. **Search the knobs** ([pcfx-optimize-loop]) — placement effects are not predictable.
5. **Hand-schedule assembly** last, and only for a profiler-proven >10% hot loop
   ([pcfx-3d-rasterizer] §4).

And report honestly: a delta under ~3% is inside this emulator's layout noise floor and
is not a speedup ([pcfx-v810-performance]).

## Related

[pcfx-bringup] (project skeleton, disc build) · [pcfx-3d-pipeline] (verified template and
its two black-screen traps) · [pcfx-software-3d] (budgets, LOD, feasibility) ·
[pcfx-3d-rasterizer] (inner loops) · [pcfx-fixed-point] · [pcfx-king-framebuffer] ·
[pcfx-character-8bpp] (one big textured mesh) · [pcfx-character-animation] (rigs and
clips) · [pcfx-self-improve] (the measure/iterate loop) · [pcfx-emulator-testing]
