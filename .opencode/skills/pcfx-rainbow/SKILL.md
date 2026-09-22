---
name: pcfx-rainbow
description: PC-FX RAINBOW (HuC6271) video - start-from templates for stills and FMV, YUV/DCT stream format, authoring with tools/rainbow, KING transfer setup and per-field re-arm, horizontal/vertical scrolling, layer mixing, and the emulator gates that prove a RAINBOW build works. Use for any RAINBOW background, sky, FMV, scrolling RAINBOW layer, RAINBOW encoder/decoder bug, right-edge glitch, or black screen in a RAINBOW player.
---

# RAINBOW (HuC6271)

The RAINBOW is the HuC6271 motion-picture decoder: a full-screen YUV/DCT
background layer composited by the HuC6261. Typical uses: Doom's scrolling sky,
title backgrounds, FMV. It is **not** the HuC6273 — that chip exists only on the
PC-FXGA board. Transfer/scroll behaviour lives in the KING (HuC6272) manuals:
`DOCUMENTATION/ORIGINAL_JPN/C6272_2.WRI` §3.4.2 and the `C6272_1` register pages;
layer mixing in `C6261`. The English translations are a search aid; the Japanese
WRI wins on conflicts.

## 0. Start from a template, never from a blank file

| You want | Start from | Gate that proves it works |
|---|---|---|
| A still image or a panning background | `examples/rainbow-still/` | `PCFX_BIOS_DIR=… make validate` |
| FMV with sound (PCFV + MP2) | `pcfx_rainbow_mp2_startup_sync_package/` | `PCFX_BIOS_DIR=… make validate VIDEO_IN=movie.mkv` |
| A sky behind a KING framebuffer | `vendor/doompcfx/platform/i_system_pcfx.c` | Doom's own captures + hardware |
| Only the asset | `tools/rainbow/rainbow.py image|video` | `rainbow.py inspect`, `test_rainbow.py` |

Both templates build with `libpcfx` from the toolkit and were validated on
2026-09-22 with a freshly rebuilt `pcfx-headless` (§6). Copy their runtime code
verbatim; every line of it exists because a simpler version failed.

## 1. Stream format (what the chip eats)

A 256×240 frame is **15 strips ("blocks") × 16 rasters**. Each strip holds 16
macroblock columns; each macroblock is four 8×8 Y blocks in A/B/C/D order
(top-left, bottom-left, top-right, bottom-right) plus one 8×8 U and one 8×8 V
block (2×2 subsampled).

Framing, from `MPCONV2.HLP`, C6272_2 §3.4.2(4), and retail streams:

```text
strip 0:     FF FF <size16 BE> <128B qtables> <entropy+alignment> <2B inner dummy> | 6B guard
strips 1-14: FF F8 <size16 BE> <entropy+alignment> <2B inner dummy>               | 6B guard
```

- `size` counts bytes **after** the 4-byte header: 128 table bytes on strip 0,
  entropy **as stored** (every entropy `FF` is stuffed as `FF 00` and **both
  bytes count**), zero alignment to a 16-bit boundary, and the 2-byte inner dummy.
- The **6-byte guard** (three `0000H` words, C6272_2 §3.4.2(4)) is outside the
  size. KING may have prefetched KRAM data when a block ends; the guard makes that
  prefetch harmless because the HuC6271 ignores `0000H`.
- Every strip starts on a **word boundary** (even size).
- Block end (EOB) is the 5-bit code `0x1F`, not a JPEG `0x00` symbol.

Quality is a **rescale control**, not a table choice. The stream carries
MPCONV's **base** tables unchanged (MPCONV2.EXE data offsets `0x0902`/`0x0942`):

```text
luma base (natural order):          chroma base (natural order), element 0 = 12:
   4  3  4  5  6  6  7  7             12  4  5   7  19 131 254 254
   3  3  4  5  6  7  7 35              4  4  5   7  27 254 254 254
   4  4  5  5  6  7 11 59              4  5  7  11  99 254 254 254
   4  4  5  6  7 11 23 254             5  6  7  19 131 254 254 254
   5  5  6  7 11 35 67 254             7  7 11  99 254 254 254 254
   5  5  6  7 27 55 254 254            7 11 67 254 254 254 254 254
   6  6  7 11 59 75 254 254           11 99 254 254 254 254 254 254
   7  7 11 63 119 254 254 254        254 254 254 254 254 254 254 254
```

DC-Y symbols `0x10..0x1F` rescale both working tables in place
(`Ywork = clamp((Ybase*s)>>2)`, `UVwork` likewise except UV DC stays `base>>2`).
Per `MPCONV2.HLP` the compression rate is 0..15 and **smaller is higher quality
and larger output**. State persists across `FF F8` strip boundaries; a trailing
rescale after column 15 belongs to the next strip. DC-Y `0x0F` is the **null-run**
escape: black/neutral macroblocks filled with the programmed null colour. A
coefficient beyond category 9 is an encoder error — pick a coarser scale, never
clip. Arithmetic details (YUV constants, integer FDCT, quantizer) are
MPCONV2.EXE reverse engineering, not manual text; see
`DoomPCFX/rainbow_findings/` notes when you need them.

## 2. Authoring (`tools/rainbow`)

`rainbow_codec.py` is **byte-identical** to Doom PC-FX's MPCONV-conformant
`gen_pcfx_rainbow_bg.py` (pinned by `tools/rainbow/test_rainbow.py`).

```bash
# Still: 256x240 PNG -> stream + C header (sizes, block count) + host preview.
python3 tools/rainbow/rainbow.py image title.png build/title.bin \
    --max-bytes 16384 --header build/title_rainbow.h \
    --preview build/title_host.png --report build/title.json

# Taller scrolling source, every strip independently decodable (§4):
python3 tools/rainbow/rainbow.py image tall.png build/tall.bin \
    --height 384 --independent-strips --header build/tall_rainbow.h

# Video -> PCFV0001 (<=4096 frames, fixed 4-sector slot per frame), MP2 audio:
python3 tools/rainbow/rainbow.py video clip.mkv clip.pcfv --fps 15 \
    --audio mp2 --audio-gain-db 8 --fit stretch --jobs 8

# Strict check of any stream/PCFV (framing + full entropy decode of all 16 columns):
python3 tools/rainbow/rainbow.py inspect clip.pcfv --frame 0 --preview build/f0.png

# Migrate a legacy (pre-MPCONV) PCFV without re-encoding (entropy bits kept):
python3 tools/rainbow/rainbow.py repair-legacy old.pcfv fixed.pcfv
```

- `--scale auto` (default) picks the **finest** scale that is legal and fits the
  budget: `--max-bytes` for a still (16384 = the hardware-confirmed single
  `eris_cd_read_kram` arm), the 4-sector slot for video. A PCFV frame always
  occupies its slot, so finer scales cost no bandwidth — only quality changes.
- 256×240 pixels are displayed as a **4:3 picture** (they are not square).
  `--fit stretch` is right for 4:3 sources; `contain`/`crop` fit against a 4:3
  frame. Fitting straight into 256×240 squashes a 4:3 movie to 256×192.
- MP2 is mono 16 kHz 32 kbit/s only; the player's 10-bit PSG output is quiet, so
  the shipped asset uses `--audio-gain-db 8`.
- `--max-strip-bytes` is for a limit **you measured**. The manuals give no
  universal per-strip ceiling (K-R bus arbitration depends on the workload).
- The `--preview` PNG uses a floating IDCT: good for "is the right picture
  there", never for colour sign-off or timing.

## 3. Runtime programming

Copy from the templates in §0. The rules, and why:

**Load only with KING SCSI DMA** (`eris_cd_read_kram`, or the player's own
count-0 DMA state machine). Doom and waifu observed that CPU KRAM writes do not
feed the decoder (the layer stays blank). `eris_cd_read_kram` is
hardware-confirmed for **one 16 KiB arm at KRAM word `0x08000`**
(`vendor/libpcfx/include/eris/cd.h`); larger arms/regions are unmeasured.

**Route pages first.** KING register `0x0F` uses a nibble per engine (SCSI D0,
BG D4, ADPCM D8, RAINBOW D12). The SCSI engine must write the page the RAINBOW
reads: `king_set_kram_pages(0,0,0,0)` in the templates; Doom parks RAINBOW+ADPCM
on page 1 and flips SCSI to page 1 only for the load. Program 4-Mbit KRAM mode
(`king_set_kram_mode(1)`) before any KRAM access. See [pcfx-kram-layout].

**Decoder ports `0x200..0x214`. Control `0x204`:** bit 0 enables the decoder, bit 1
selects **endless scroll**. Without bit 1 the horizontal counter is 9-bit and every
column past the 256-px line decodes black — so any layer that pans needs `3`. A
non-scrolling FMV (the PCFV player) runs with `1`; do not "fix" that.

```c
static void rainbow_setup(void)
{
    out_b(0x200, 0);        /* hscroll low  */
    out_b(0x202, 0);        /* hscroll bit 8 */
    out_h(0x208, 0xFF80);
    out_h(0x20C, 0);
    out_h(0x210, 0);
    out_h(0x214, 0);
    out_h(0x204, 3);        /* enable + endless scroll */
}
```

**Re-arm once per field, in raster 248..261, interrupt-atomic.** One arm decodes
exactly one field (`REG.40` control, `REG.41` KRAM word, `REG.42` start raster,
`REG.43` block count, `REG.44` raster monitor). The transfer starts 16 rasters
before display (start raster 6 for 240 lines, 15 blocks). An arm issued while the
field is still decoding aborts it (`REG.40 = 0` first). A timer IRQ inside any
KING `0x600`/`0x604` select/data pair corrupts the access on silicon; the
emulator performs KING accesses atomically and cannot show it.

```c
static void rainbow_rearm(void)
{
    int irq = irq_disable();
    king_reg16(0x40, 0x0000);
    king_reg32(0x41, RB_KRAM_WORD);
    king_reg16(0x42, 6);            /* transfer start raster */
    king_reg16(0x43, 15);           /* 16-raster blocks */
    king_reg16(0x44, 0x0000);
    king_reg16(0x40, 0x0001);
    irq_restore(irq);   /* needs vendor/libpcfx with the fix below */
}

/* Detect a new field by the raster counter WRAPPING, never by a threshold. */
unsigned r = raster_stable();                 /* double read, pcfx-frame-timing §1 */
if (r < last) armed = 0;
last = r;
if (!armed && r >= 248 && r <= 261) { rainbow_rearm(); armed = 1; }
```

`irq_restore(irq_disable())` is only a critical section with the fixed
`vendor/libpcfx` (`examples/012_irq_save_restore` prints PASS). liberis and older
libpcfx builds (including a stale `$V810GCC/lib/libpcfx.a`) return the raw
`0x1000` bit, so the pair always **enables** IRQs and clears the interrupt level:
a program with no handler starts taking interrupts at its first arm. Check with
`v810-objdump -d your.elf | grep -A6 '<_irq_disable>:'`: a `shr 12` means fixed.

**Layer mixing (C6261, R08–R09 and R0A–R0C):**

1. Every plane needs a **unique** priority 0..7 ("Do not assign the same value to
   multiple planes"). Priority 0 is the **bottom of the stack, not "hidden"**: a
   RAINBOW at priority 0 shows through every transparent pixel above it.
2. To hide the layer, clear its **plane-enable bit** (`tetsu_set_video_mode(...,
   rainbow_disp)`), and stop the decoder (`REG.40 = 0`).
3. `tetsu_init()` programs chroma-key max below min, which per C6261 disables the
   HuC6271 key: every RAINBOW pixel is opaque. Put it rearmost and let the KING
   plane's index-0 transparency reveal it (Doom's sky).
4. **Decode a field before enabling the plane.** An idle HuC6271 shows its last
   output; unfed RAINBOW is garbage on hardware.

**Frame waits come from the Tetsu raster counter** (port `0x300`, double read).
Never wait on the VDC status VD bit — see §7 and [pcfx-frame-timing].

## 4. Scrolling

**Horizontal.** With endless mode, `rainbow_set_hscroll(x)` (`0x200` low byte,
`0x202` bit 8) wraps at 256 and a 256-px stream pans seamlessly — measured in
`examples/rainbow-still` (1 px/field, 100 px over 100 fields) and Doom's sky.

**Vertical** is transfer addressing (`C6272_2.WRI` スクロール再生, asymmetric;
manual-derived, not yet exercised by a template here):

- **Upward, 0–15 lines:** change only the transfer-start raster (`REG.42`).
- **Upward, ≥16 lines:** move `REG.41` by whole 16-line blocks **and** adjust
  `REG.42` for the remainder (manual example: 23 lines up = next block's address,
  start raster = normal − 7).
- **Downward:** `REG.42` only, normal + N.
- **Changing direction between fields** is constrained by the 22.5-line
  inter-field blanking (N + M ≤ 22 for a downward-N field followed by upward-M).
  Re-read the WRI figure before implementing it.
- Use `--independent-strips` so any 16-line boundary is a valid start address
  (costs ~128 bytes per strip).

**Split playback:** program the first region, watch the split raster with
`REG.44`, then stage source/count for the next region.

## 5. KRAM and transfer budget

- 15 blocks per 240-line frame. Size the stream for the KRAM reserve **and** for
  the per-strip decode inside one 16-line window under your BG/SCSI/ADPCM load.
- The `image`/`video` `--report` JSON lists each strip's stored KRAM span
  (`strip_bytes` = `4 + size + 6`) and word offsets; the largest strip is the one that
  meets or misses the raster deadline.

## 6. Verification ladder — do every rung, in order

| Rung | Command | Catches |
|---|---|---|
| 1 | `python3 tools/rainbow/test_rainbow.py` | encoder drift from MPCONV/Doom, framing, repair |
| 2 | `rainbow.py inspect <stream>` (and the template's `make cd`, which refuses a non-strict stream) | legacy/garbled streams before they reach a disc |
| 3 | **Fresh emulator**: `scripts/build-headless.sh` whenever `vendor/pcfxemu` changed (compare `ls -l toolchain/bin/pcfx-headless` with `git -C vendor/pcfxemu log -1 --format=%ci`) | validating against old decoder bugs |
| 4 | `make validate` in the template | black screen, hung boot, strip starvation, wrong pan, underflows, A/V drift |
| 5 | Real hardware | IRQ-in-KING-pair, bus timing, anything in [pcfx-emulator-testing] §7 |

Rung 4 reads the player's own counters (`g_video_frames_presented`, underflows,
`g_done`) from a RAM dump via the **linker map** (`tools/extract_pcfv_stats.py`)
— never hand-compute a global's address. A gate is only trusted after it has
**failed on a known-bad build** (a legacy stream, the old vblank wait); both
package gates were proven that way.

## 7. ANTI-PATTERNS — each one shipped here at least once

| Symptom | Cause | Fix |
|---|---|---|
| Glitched tiles on the **right side**, worse in busy scenes | Strip size counted **unstuffed** bytes (`size = 2 + logical_bytes`, comment "decoder consumes stuffed byte without counting it"), no word alignment, no inner dummy/guard. The decoder's byte budget runs out before the last macroblock columns | `size = tables + stuffed entropy + alignment + 2`; 6-byte guard after; re-encode with `tools/rainbow`, or `repair-legacy` |
| "It looked fine in the emulator" | old pcfxemu charged a stuffed `FF 00` as one byte (as lenient as the bug); the installed binary predated the fix | rebuild `pcfx-headless` (§6 rung 3), then re-test |
| Poor compression; black frame not much smaller | JPEG quality-scaled tables sent directly, no null runs, no rescale controls | MPCONV base tables + `0x10+s`, `0x0F` null runs, finest-scale search |
| Washed/clipped picture | float RGB→YUV/FDCT against a chip whose IDCT has 4× gain | MPCONV integer pipeline (`rainbow_codec.py`) |
| **Black screen after porting liberis → libpcfx**, CD DMA "stuck" | `wait_vblank()` polled VDC status `0x80000400` bit 5 (VD); VD is only raised while VDC CR bit 3 is set, and `vdc_setreg(chip, VDC_REG_CR, VDC_CR_BB)` wrote CR = 0x0080. The CD state machine only looked stuck because the loop that polls it never came back | Tetsu raster waits ([pcfx-frame-timing]); [pcfx-liberis-port] |
| Layer visible while "hidden", or noise band on hardware | priority 0 used as "hide"; duplicate priorities | unique priorities + plane-enable bit (§3) |
| Layer blank | armed once at init; or arm lands before the field's decode finished | per-field re-arm at 248..261 |
| Pan goes black past 256 | `0x204 = 1` | `0x204 = 3` |
| Loop pass 2 black for seconds, then 2× speed, silent | reopen kept per-pass state (`g_mp2_enabled`, `g_video_frames_presented`) | reset per-pass state in the open path; test `LOOP=1` past the first clip end |

If a new stream shows the right-side glitch, check in order: `rainbow.py
inspect`, emulator freshness, KRAM page routing (the decoder reading another
engine's page looks similar), then the per-strip deadline (§5).

## Related

[pcfx-frame-timing] (raster waits) · [pcfx-kram-layout] (pages) ·
[pcfx-liberis-port] (API mapping traps) · [pcfx-regression-triage] (worked
before, broken now) · [pcfx-cd-assets] · [pcfx-emulator-testing] ·
[pcfx-yuv-palette] · `tools/rainbow/PROVENANCE.md` ·
`tools/large-game/doom/gen_pcfx_rainbow_bg.py` (Doom's encoder, same bytes).
