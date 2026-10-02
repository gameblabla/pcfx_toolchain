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

### VDC palette ranges and native palette slots

A 4bpp VDC cell contains palette slots 0..15, while a native game may keep a
larger source palette array and a per-frame `bg_palette_index[16]` state. The
source slot is not a unified 256-colour palette index. Convert the native RGB
first, then write the selected fade-step word:

```c
const u32 rgba = game_palette[bg_palette_index[i] & 0x3Fu];
const u8 mapped = dp_pcfx_quant_rgb((rgba >> 24) & 0xFFu,
                                   (rgba >> 16) & 0xFFu,
                                   (rgba >> 8) & 0xFFu);
tetsu_set_palette(16u + i, active_fade_palette[mapped]);
```

Use `tetsu_set_vdc_palette(16, 0)` when the world uses entries 16..31 and the
sprite/text plane uses entries 0..15. Do not upload the active unified palette
at the VDC base and assume the native slot numbers already match. During a
fade, read the same active fade table used by the word upload; changing only
Y or mixing a fade table from another step produces valid-looking but wrong
colours. Verify the serialized VCE words and sample the resulting PNG with
`pcfx-color-verification`.

### A static screen with a blinking prompt

A title with two blink states is still a static screen. Compose each state
once into a 61,440-byte indexed buffer, upload each to a separate KING page
once, and switch the BG0 and BG0SUB CG addresses on blink edges. Keep a
`page_ready[2]` flag and invalidate both flags when a dynamic scene overwrites
either page. On ordinary fields, only the palette changes. If the software
composite also needs the current picture for a scene transition, copy the
cached indexed state only when the blink state changes.

Do not upload all 30,720 KRAM words on every blink: one measured program
reached 364 updates in 400 fields after caching composition but before
keeping both blink images resident. The two-page change reached 400/400.
Also avoid an O(screen-size) checksum in the field loop. A sampled XOR can
miss changes, while a stronger hash can itself cost a field. Increment a
composite generation counter when pixels actually change, and compare that
counter before choosing whether to upload or flip.

Prepare the incoming static scene before the input trigger when it is known
in advance. If its first 30,720-word KING upload occurs inside the transition,
that one field can still be missed even though the fade table is fast. Spare
KRAM in the same routed background page can hold one or more prepared 8bpp
surfaces; load them during startup, then select their CG base at the blanking
edge. In one measured title-to-menu route, caching the incoming composite
gave 97/100 updates, and preloading its two selection variants into KRAM
gave 100/100. Check the KRAM map before reserving pages and invalidate any
page that later becomes a dynamic framebuffer.

**Keep the memory budgets separate.** Two 256×240 8bpp pages occupy 61,440
16-bit words, or 122,880 bytes, of **KRAM**. They consume no additional main
RAM unless you also keep software copies. Each cached 256×240 indexed
composite in main RAM costs 61,440 bytes. Check both the KRAM page map and the
ELF `.bss` end. A model answer that says “two KING pages use 122,880 bytes of
main RAM” has mixed up the budgets.

**Acceptance for a prepared transition:** the full input-triggered window
must reach one game update per video field. A settled-screen 400/400 gate
does not cover the first upload. Cache the incoming composite *and* preload
its KING surface before the trigger; then require 100/100 over a 100-field
window that includes the trigger. Also inspect a midpoint and settled image.

For a KING-only title, clear stale VDC sprites once when entering it. Rebuilding
ROM-font sprites and uploading SATB on every otherwise static title field can
consume a field on its own. If VDC graphics remain visible, cache or update
them on change and keep their palette ranges separate from the fading KING
range.

For an illustrated menu, perform the same cache check on the *finished*
background, character, and text composite. A palette-only change still
requires no per-pixel work. If a software slide makes every transition frame
unique and the V810 cannot draw it within one field, choose a hardware layer
scroll or a static composition with the palette fade; do not claim that a fast
palette loop makes the full transition 60 Hz. Measure the actual scene route
with `measure_presented.py --commands input.txt` after both states have been
entered. A tested static title and menu reached 400 updates in 400 fields
each; before the menu cache, the same menu route delivered only 8/400.

Watch RAM when adding caches. The CD linker's “Code+data Size” can look safe
while `.bss` crosses the 2 MiB main RAM limit. Check `__end` in the fresh ELF
map or `v810-nm -n` and leave room below the stack at `0x200000`. One extra
61,440-byte indexed image caused a black screen even though the disc linked;
reusing the existing background plane fixed the layout.

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
- Clear both visible KRAM pages to an **opaque** generated dark index before
  enabling a patterned VDC backdrop. A clear to index 0 exposes that VDC
  pattern and can look like full-screen startup garbage even though KRAM was
  initialized. Derive the nonzero dark index from the generated palette; do
  not embed the current palette slot number in source.
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
