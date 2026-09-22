---
name: pcfx-3d-pipeline
description: A verified end-to-end PC-FX software-3D pipeline - V810 fixed-point transform, backface cull, triangle span raster into a double-buffered KING BG0 256-colour bitmap, and the page flip. Use when wiring any 3D renderer to the screen (double buffering, page flipping, on-target transform bugs), or when a software-3D program renders black on pcfxemu despite working on the host.
---

# The 3D pipeline template: transform -> rasterize -> flip

`template/` is a **verified 60 fps** rotating-cube program: V810 fixed-point transform,
backface cull, painter's-order triangle raster, per-page dirty clearing, a 128x120 logical
canvas stretched to 256x240 by KING, and a double-buffered page flip. A saved-state test
rendered **600 frames in 600 video fields** on pcfxemu.

Read `pcfx-software-3d` (budgets) and `pcfx-king-framebuffer` (BG0 bitmap basics) first.
This skill documents the parts that bite: the two bugs every port hits, and the
verification workflow that caught them.

## 1. Two traps that made the cube render black

### 1a. The CG-base register takes 1024-word units, and BG0SUB must track BG0

`king_set_bat_cg_addr(KING_BG0, 0, base)` with a raw word address does NOT work for page
flipping: the KING BG0_CG register (0x21) is an **8-bit field** and the hardware multiplies
it by 1024. In pcfxemu (`mednafen/pcfx/king.c`, `cg_offset = king->BGCGAddr[n] * 1024`),
writing `0x7800` truncates to `0x00` and the flip silently always shows page 0. Correct
flip:

```c
king_set_bat_cg_addr(KING_BG0,   0, base >> 10);   /* 1024-word units!   */
king_set_bat_cg_addr(KING_BG0SUB, 0, base >> 10);  /* sub layer too      */
```

wolf-pcfx's `king_set_display_page` (`wolf_video.c`) does the same `base / 1024` (its
`KRAM_CG_UNIT`) and also updates BG0SUB every flip. Pages of 30,720 words (128 words/row
x 240 rows, 256x240 8bpp) land at word offsets 0 and 0x7800 -> CG values 0 and 0x1E.

### 1b. The V810 MUL high word must be read out of r30 explicitly

V810 `mul a, b` writes the **low** 32 bits to `b` and the **high** 32 bits to `r30`. A
fixed-point multiply written like this:

```c
__asm__ ("mul %2, %0" : "=r"(lo), "=r"(hi) : "r"(b), "0"(a) : "r30"); // WRONG
```

declares `hi` as an output register the asm never writes - GCC allocates some unrelated
register and every product's top 16 bits are garbage. Result: all transforms produce
off-screen coordinates, the clear wipes the page, and the renderer is **black while every
isolated piece (clear, triangle fill, flip) demonstrably works**. The verified fix (same
shape as wolf-pcfx `WallFixedMul`):

```c
int lo, hi;
__asm__ ("mul %2, %0\n\t"
         "mov r30, %1"
         : "=r"(lo), "=&r"(hi)
         : "r"(b), "0"(a)
         : "r30");
return (int)(((unsigned)lo >> 16) | ((unsigned)hi << 16));
```

**ANTI-PATTERN — the near-miss that keeps the screen black.** A local model given this
symptom found the right line and then retyped the fix from memory, producing:

```c
    __asm__ ("mul %2, %0\n\tmov r30, %1"
             : "=r"(lo), "=r"(hi)          /* WRONG: no `&` */
             : "r"(b), "0"(a)
             : );                          /* WRONG: r30 clobber dropped */
```

That still fails, and it fails *identically* to the original bug, so the next hour goes
into disassembling the rasterizer. **Copy the block above verbatim.** Both details are
load-bearing: without `"=&r"`, GCC may allocate `hi` to the same register as input `b`,
so `mul` destroys `b` before it is read; without the `"r30"` clobber, GCC believes r30
still holds whatever it put there.

Note `"=&r"` (early clobber) so `hi` cannot alias the input `b`. GCC 4.9.4 will not
produce this from `(int64)a*b` - it calls `__muldi3`, far slower - so keep the asm.

## 2. How the template is organised

- `src/cube3d.c` - everything. `HOST_TEST` guards swap I/O and math for host execution:
  `fx_mul` takes the int64 path, `king_reg16`/`wait_frame` become no-ops, `main` is
  replaced by a frame-loop test harness in `hosttest.c`. `g_rendered_frames` is an
  on-target counter for saved-state fps checks.
- `hosttest.c` - host verification: transform/project/cull/sort/raster run on x86 and
  checked against expected screen coordinates. **Build from the toolkit root with
  `gcc -O2 -w -I"$V810GCC/v810/include" -I"$LIBPCFX/include" -o hosttest hosttest.c`**;
  expect `PASS (every face agrees with geometry, all verts projected)`.
- `tools/gen_sin.py` - bakes `src/sin_table.h` (Q16.16 sine table; runs on host).
- Makefile: `make cd` builds `cube3d.cue` via bincat + pcfx-cdlink.

Layout: BG0 remains a 256x240 8bpp surface with a 128-word hardware row stride; the
renderer uses only a 128x120 logical canvas. KING affine `A=D=0x0080` stretches it 2x
in each axis. Pages remain at word 0 and 0x7800, both in KING hardware page 0. Palette
entry 8 is the grey cube face shade.

## 3. The changes that make 60 fps possible

Three structural changes were required; none is optional if you copy the fast path.

1. **Inline the KRAM burst path.** Encode the address and increment into the KRAM_AWR
   control word and emit it with an inline `out.w`; then emit one `out.h 0x000e,
   0x600[r0]` to select KRAM_DATA and stream data directly to port `0x604`. Calling
   libpcfx's out-of-line `king_set_kram_write()` or `king_kram_write()` from a hot
   span/word loop pays avoidable call/latch overhead. Keep those wrappers for cold
   setup paths or the `HOST_TEST` fallback only.
2. **Keep one dirty rectangle per KRAM page.** A page is reused two rendered frames
   later, so clear that page's previous cube bounds, not all 30,720 words. Align the
   horizontal bounds to complete two-pixel words.
3. **Render 128x120 and scale in KING.** BG0 is still configured as 256x256, so its
   row stride stays 128 words; do not compact rows to 64 words. With `A=D=0x0080`,
   source coordinate steps are one half per display pixel and the logical canvas fills
   256x240. This quarters rasterized pixel traffic while retaining full-screen output.

Start with the hidden page (`back = 1`) because page 0 is initially displayed. Starting
on page 0 creates a first-frame read/write hazard even if every later flip is correct.

## 4. Verification workflow (what actually caught the bugs)

1. **Host test first.** The cube transform/winding/culling is C and can be validated on
   x86 with expected outputs per frame. It caught the face-winding bug immediately.
2. **Verify winding in BAM, not degrees.** This engine's angles are BAM (1024 = full
   turn), not degrees - a "yaw = 90" test is actually 32.19 turns. `mat_rot_y(bam)` maps
   +x -> (c, 0, -s) and +z -> (s, 0, c); `mat_rot_x(bam)` maps +y -> (0, c, s). So with
   the camera looking down +z, face 0 (+z) faces the camera at yaw 512, face 1 (-z) at
   yaw 0, face 2 (-x) at 768, face 3 (+x) at 256, face 4 (+y) at pitch 768, face 5 (-y)
   at pitch 256. The hosttest oracle (rotated outward axis dotted with the face-centroid
   view coords < 0) checks `face_visible()` against geometry at every frame; with the
   wrong winding it reports mismatches and fails.
3. **The screen-space cross sign is not the 3D visibility sign.** `face_visible` tests
   the sign of the projected triangle area. When a face's centroid passes behind the
   camera (z < 0), projection inverts and the cross flips while the 3D outward normal
   still points at the camera - the two disagree for a band of orientations. Hand-
   deriving windings "on paper" produces wrong tables; always verify against the oracle.
   The verified face table (matches geometry at all six orientations):

   ```c
   static const int cube_faces[6][4] = {
       { 4, 7, 6, 5 },  /* +z front */
       { 0, 1, 2, 3 },  /* -z back  */
       { 0, 3, 7, 4 },  /* -x left  */
       { 1, 5, 6, 2 },  /* +x right */
       { 3, 2, 6, 7 },  /* +y top   */
       { 0, 4, 5, 1 },  /* -y bottom*/
   };
   ```

   The original table had the front, right and top faces inverted, which culled them
   when they faced the camera - the "missing right and bottom faces" bug.
4. **Confirm on-target with a marker build.** Screenshot-to-geometry comparison is
   confounded by run-to-run boot timing (each pcfx-headless run boots the disc
   separately; the program's start frame varies, so "frame N" does not pin yaw/pitch).
   Make a test build that cycles fixed orientations every 120 frames, gives each face a
   unique colour, and encodes the orientation index into the background grey. Read the
   background to learn the exact yaw/pitch of the frame, then check the drawn face
   colours against the oracle. Verified on pcfxemu: all six orientations draw exactly
   the geometrically visible face.
5. **Bisect the pipeline on-target with static draws.** When the emulator shows black:
   draw a checkerboard once (KRAM path), then per-row seeks, then with `wait_frame`,
   then a single literal triangle (no transform, no flip). A literal triangle drawn once
   rendering **9,922 px of rgb(32,32,32)** proved KRAM fill + tri_fill + display init.
6. **Verify the flip with page contents, and at BOTH frame parities.** Fill page 0 with a
   checker, leave page 1 black, flip every frame. Screenshots at `--frames 1800` (even)
   showed the checker and made the flip look broken, when the app was simply flipping on
   every field: **odd frame counts caught page 1, even caught page 0**. Always screenshot
   at odd and even frame counts when diagnosing double buffering.
7. **Read back KRAM.** `king_set_kram_read(addr, 1)` + `king_kram_read()` into main RAM,
   then `--dump ram` - the triangle showed up as `0x0808` words at the expected span
   positions even when the screen was black. This is the fastest way to separate
   "not drawn" from "drawn but not displayed".
8. **Instrument the emulator when stuck.** A one-line `printf` in `king.c` `case 0x21`
   proved the flip values (`0x00`/`0x1e` alternating, ~447/443 per 1800 fields) actually
   reached the register - ruling out the write path and isolating the math.
9. **Measure steady state from a savestate, not across BIOS boot.** Save after the cube
   is running, dump RAM, resume the state for 600 fields, and dump again. Read
   `g_rendered_frames` at its ELF symbol address from both dumps. The verified build
   advances by exactly **600**, proving 60 fps independently of variable disc boot time.

## 5. Measured performance (pcfxemu, PROFILE build, 600-field running savestate)

| Metric | Value |
|---|---|
| Animation rate | **60 fps** (600 rendered frames / 600 fields) |
| Instructions per field (render + wait) | 108,201 |
| KRAM data writes per field | 4,608 words |
| KRAM address writes per field | 528 (span/dirty-row cursors) |
| Exact same-field CPU/engine KRAM collisions | 0 |
| Logical / displayed canvas | 128x120 / 256x240 |

The profiler remains near 100% CPU because `wait_frame()` intentionally spins for the
unused portion of each field; `IN_H` is 36% of attributed cycles in the saved-state run.
That is headroom, not renderer cost. The rendered-frame counter is the fps authority.

## 6. Emulator facts used here

- KING register access: 16-bit register index via port `0x600`, 16-bit data via `0x604`.
  KRAM data is also `0x604`/`0x606`. In pcfxemu, `KING_Write16` uses bit 2 of the port
  address to distinguish AR write (`0x600`) from data write (`0x604`).
- CPU KRAM writes go to `KRAM[page][KRAMWA & 0x3FFFF]` where page is bit 31 of KRAMWA -
  with page 0 you have word addresses 0..0x3FFFF, enough for two 30,720-word buffers.
- Every KING 16-bit port write adds `KING_KRAMWriteContentionCycles` - writing the page
  the display is reading stalls the CPU.
- Build hygiene: `make cd 2>&1 | tail -1 && <emulator>` hides a failed build (the
  pipeline's exit code is tail's) and runs a stale disc. Check `make`'s exit status
  separately before trusting a screenshot.

## 7. Cross-references

- Budgets and levers: `pcfx-software-3d`
- BG0 bitmap details: `pcfx-king-framebuffer`
- Fixed point and divide avoidance: `pcfx-fixed-point`
- Span rasteriser specifics: `pcfx-3d-rasterizer`
- Profiling: `pcfx-v810-profiling`, `pcfx-v810-performance`
- Screenshots and the ~1200-frame boot delay: `pcfx-emulator-testing`
