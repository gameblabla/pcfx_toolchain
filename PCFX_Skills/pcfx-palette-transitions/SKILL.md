---
name: pcfx-palette-transitions
description: Fast 60 Hz palette fades for indexed KING/VDC screens, blanking-safe updates, startup display order, and when a fade cannot be done by palette alone.
---

# Palette transitions on PC-FX

**Never write HuC6261 palette RAM during active display.** The manual says
active-display palette reads or writes produce visible noise. Schedule every
palette burst at the leading edge of vertical blanking, including the first
palette upload if video output is already enabled. A clean emulator screenshot
does not prove this timing safe on real hardware.

Use this for a full-screen title fade or a dip to black. Read
`pcfx-frame-timing`, `pcfx-yuv-palette`, and `pcfx-king-framebuffer` first.
The HuC6261 manual (`DOCUMENTATION/ENGLISH_TRANSLATION/C6261/C6261.md`,
§2.2) says palette RAM is 512 entries, its address increments on writes, and
palette RAM writes during active display produce visible noise. Check the
original Japanese C6261 manual for any disputed register or timing detail.

## Fast path

1. Build or load the *final indexed pixels* once. Draw them into an undisplayed
   KING page; keep that page stable throughout the fade. A fade should change
   palette words, not re-quantize and upload 256×240 pixels per step.
2. Prepare the palette words for every fade step offline, using the RGB→Y8U4V4
   converter in `pcfx-yuv-palette`. For a fade from black, convert each source
   RGB channel times the ease fraction, then quantize to Y8U4V4. This is closer
   to the source fade than scaling just the Y byte of the packed YUV word.
   **Do not scale the Y byte and leave U/V unchanged.** A low Y with nonneutral
   chroma can remain visibly colored; a tested Y-only fade produced dark
   blue/red shapes instead of black.
3. At the *leading edge* of each blanking interval, write the changed palette
   entries and switch the displayed page if required. The canonical double-read
   raster wait in `pcfx-frame-timing` returns at that edge in 262-line mode.
   A 256-entry upload has fit in blanking in the measured wolf-pcfx setup; still
   measure your combined palette/page/VDC work.
   A game-core `FadeComposite()` called after a full render is **not** a safe
   place to call `tetsu_set_palette()`, even if the loop began with a frame
   wait. Store the requested fade step there. After rendering, wait for the
   *next* blanking edge and then flush the palette and page selection.
4. Advance the fade step once per field. At 60 Hz, 32 steps take about 0.53 s.
   This is a 60-updates-per-second transition; it cannot exceed the 60 Hz field
   rate. Count fields, not emulator wall time, to substantiate the result.

If the image is dynamically redrawn each field, continue drawing its normal
unfaded indexed frame, then change only the palette for the fade. If two
simultaneously visible planes need independent brightness, give them distinct
palette ranges or use a different presentation path: HuC6261 palette RAM is
shared by KING and the two VDCs. A palette fade cannot express an arbitrary
per-pixel crossfade between two unrelated images on one indexed plane.

For a black midpoint between scenes: show outgoing pixels while its palette
descends to black; at black, prepare/switch the incoming indexed page and its
palette; then ascend. Do not switch to uninitialized KRAM or restore the full
palette before the page switch. If the image data needs a long CD load, hold
black while loading and resume on a blanking edge.

## Startup order and corruption checklist

- Initialize KING/Tetsu and choose KRAM layout; clear or upload every page that
  will be displayed. Initialize VDC tile/sprite memory and hide unintended
  overlays before enabling them. Set palette entry 0 to the desired backdrop.
- `king_set_bat_cg_addr()` takes its CG base in **1024-word units**: pass
  `page_base >> 10`, as in `examples/hello/src/main.c`. For an 8bpp bitmap,
  address the BG0 and BG0SUB registers consistently. A raw word address here
  selects the wrong region and can show garbage.
- Enable the visible layers only after their memory, palette, microprogram,
  and affine registers are ready. Change display selection during blanking.
- If source black must be opaque over a VDC plane, use a nonzero KING pixel
  index whose palette word is black. Pixel index 0 is transparent.
- A frame loop that waits for blanking, then renders for many milliseconds,
  then flips has lost its blanking window. Render first, wait for the next
  blanking edge, then publish the page and palette immediately.

## Correctness and speed gate

Capture a known fade start, midpoint, and full-brightness frame from the same
disc and input script. Confirm the initial page contains the intended indexed
image, the black midpoint is black, and the final palette matches the source
colors numerically (`pcfx-color-verification`). Use a presented-step counter
or fixed field captures to show one step per field; profile if any step misses
a field. Check that a known-bad old build fails the same gate. An emulator
capture cannot prove absence of real-hardware active-display palette noise,
so keep the blanking sequence justified by the manual and real-hardware notes.

For any program, read a fresh presented-update counter from two RAM captures
using the current ELF/map symbol; divide its delta by the emulator field count.
`measure_presented.py` automates this for any named 32-bit counter, ELF, and
disc image. The runnable command is in `examples/palette-fade/README.md`.
A tested palette-only rewrite still measured **4/400 = 0.6 fps** because it
left the full title redraw, 30,720-word KRAM upload, and flip in every frame.
A fade is fast only when its image stays resident and the field loop can
advance without rebuilding that image.

`examples/palette-fade` is the small runnable reference. It keeps its indexed
bitmap unchanged while fading its palette and logs no per-pixel work in the
transition loop.
