---
name: pcfx-rainbow
description: PC-FX RAINBOW (HuC6271) video - YUV/DCT stream format, still-image and PCFV video authoring with tools/rainbow, horizontal/vertical scrolling, KING transfer setup, and the Doom PC-FX runtime example. Use for any RAINBOW background, sky, FMV, scrolling RAINBOW layer, or RAINBOW encoder/decoder bug.
---

# RAINBOW (HuC6271)

The RAINBOW is the HuC6271 motion-picture decoder: a full-screen YUV/DCT
background layer **behind** the KING planes. Typical uses: Doom's scrolling
sky, title backgrounds, FMV. It is **not** the HuC6273 — that chip exists only
on the PC-FXGA board. RAINBOW transfer/scroll behaviour lives in the KING
(HuC6272) manuals: `DOCUMENTATION/ORIGINAL_JPN/C6272_2.WRI` §3.4.2 and the
`C6272_1` register descriptions (`DOCUMENTATION/ENGLISH_TRANSLATION/C6272_1/`,
`C6272_2/` are a search aid; the Japanese WRI wins on conflicts).

## 1. Stream format (what the chip eats)

A 256×240 frame is **15 strips ("blocks") × 16 rasters**. Each strip holds 16
macroblock columns; each macroblock is four 8×8 Y blocks in A/B/C/D order
(top-left, bottom-left, top-right, bottom-right) plus one 8×8 U and one 8×8 V
block (2×2 subsampled).

Framing, measured from retail streams and MPCONV2:

```text
strip 0:     FF FF <size16 BE> <128B qtables> <entropy+alignment> <2B inner dummy> | 6B guard
strips 1-14: FF F8 <size16 BE> <entropy+alignment> <2B inner dummy>               | 6B guard
```

- `size` counts bytes **after** the 4-byte header: 128 table bytes on strip 0,
  entropy **as stored** (every entropy `FF` is stuffed as `FF 00` and both bytes
  count), zero alignment to a 16-bit boundary, and the **2-byte inner dummy**.
- The **6-byte guard** (three `0000H` words, C6272_2 §3.4.2(4)) is a KING
  transport guard **outside** the size. It makes prefetched KRAM data harmless;
  the decoder ignores `0000H`.
- Every strip starts on a **word boundary** (even size). An odd block start puts
  every KRAM fetch for that block on the wrong half-word — the classic
  right-side-of-screen glitch (§6).
- Block end (EOB) is the 5-bit code `0x1F`, not a JPEG `0x00` symbol.

Quality selection is a **rescale control**, not a table choice. The stream
carries MPCONV's **base** tables unchanged (data offsets `0x0902`/`0x0942`):

```text
luma base (natural order):
   4  3  4  5  6  6  7  7
   3  3  4  5  6  7  7 35
   4  4  5  5  6  7 11 59
   4  4  5  6  7 11 23 254
   5  5  6  7 11 35 67 254
   5  5  6  7 27 55 254 254
   6  6  7 11 59 75 254 254
   7  7 11 63 119 254 254 254
chroma base (natural order), note element 0 = 12:
  12  4  5   7  19 131 254 254
   4  4  5   7  27 254 254 254
   4  5  7  11  99 254 254 254
   5  6  7  19 131 254 254 254
   7  7 11  99 254 254 254 254
   7 11 67 254 254 254 254 254
  11 99 254 254 254 254 254 254
 254 254 254 254 254 254 254 254
```

DC-Y symbols `0x10..0x1F` rescale both working tables in place
(`Ywork = clamp((Ybase*s)>>2)`, `UVwork` likewise except UV DC stays
`base>>2` regardless of scale). Per `MPCONV2.HLP`, scale **0 is finest, 15 is
coarsest**. State persists across `FF F8` strip boundaries; a trailing rescale
after column 15 belongs to the next strip. DC-Y `0x0F` is the **null-run**
escape: current-frame black/neutral macroblocks filled with the programmed
null colour (not previous-frame hold). Coefficients beyond category 9 are an
encoder error — never silently clip them.

## 2. Authoring stills and video (`tools/rainbow`)

All authoring is host-side Python. `rainbow.py` is the single entry point
(see `tools/rainbow/PROVENANCE.md` for derivation and limits):

```bash
# Still image: strict 256xHx → RAINBOW stream + C header + host preview.
# --scale auto (default) keeps the finest MPCONV scale 0..15 that is legal
# and fits the budgets. --max-strip-bytes takes a MEASURED hardware/workload
# limit; default 0 means no invented ceiling.
python3 tools/rainbow/rainbow.py image title.png title.bin \
    --header build/title_rainbow.h --preview build/title_host.png \
    --report build/title.json

# Scrolling source: taller than one screen, strips independently decodable
# so vertical source-address scrolling (§4) can start at any 16-line boundary.
python3 tools/rainbow/rainbow.py image tall.png tall.bin \
    --height 384 --independent-strips --header build/tall_rainbow.h

# Video: ffmpeg → per-frame RAINBOW → PCFV0001 container (≤4096 frames,
# ≤4 sectors/frame). Audio contract is MP2 mono 16 kHz 32 kbit/s only.
python3 tools/rainbow/rainbow.py video clip.mkv clip.pcfv \
    --fps 15 --audio mp2 --max-frame-sectors 4 --jobs 8 \
    --report build/clip.json

# Validate any stream or PCFV without re-encoding (strict framing + full
# entropy decode of every strip's 16 columns):
python3 tools/rainbow/rainbow.py inspect clip.pcfv --frame 0 \
    --preview build/f0_host.png

# Migrate a legacy (pre-MPCONV) PCFV to correct framing WITHOUT re-encoding:
# entropy bits are preserved, sizes/alignment/dummy/guard are rewritten.
python3 tools/rainbow/rainbow.py repair-legacy old.pcfv fixed.pcfv
```

Rules:

- `inspect` passing means the stream is syntactically strict. The `--preview`
  PNG is an **approximation** (floating IDCT, host chroma upsampling), good for
  "is the right picture there at all", never for colour fidelity or timing.
- A stream can be strict yet too large for its 16-raster transfer window under
  load. Report per-strip KRAM spans (the `--report` JSON has them); confirm
  motion + sound with `pcfx-headless` captures and real hardware for release
  claims ([pcfx-emulator-testing] §7).
- Black/flat areas must encode as **null runs**. If your frame is small but a
  black frame is not nearly free, the encoder is not emitting them (§6).

## 3. Runtime programming (Doom PC-FX reference)

Copy this shape from `vendor/doompcfx/platform/i_system_pcfx.c` — it is the
measured-working setup, including two bugs already found for you.

**Feed it only via KING SCSI/CD DMA.** The decoder does not reliably accept
CPU KRAM writes; Doom DMA's the stream off the disc straight into KRAM
(`eris_cd_read_kram`), with SCSI routed to the RAINBOW's page for the read.

**KRAM pages** use the HuC6272 nibble layout in KING register `0x0F`
(DMA = bit 0, BG = bit 4, ADPCM = bit 8, RAINBOW = bit 12); program 4-Mbit
mode first. Doom parks BG+SCSI on page 0 and RAINBOW+ADPCM on page 1:

```c
king_set_page_setting(KPS_SCSI1 | KPS_RAINBOW1 | KPS_ADPCM1);  /* DMA -> page 1 */
eris_cd_read_kram(SKY_LBA, KRAM_RAINBOW_WORD | 0x80000000u, bytes);
king_set_page_setting(KPS_RAINBOW1 | KPS_ADPCM1);              /* bg/scsi page 0 */
```

**Decoder control** is RAINBOW ports `0x200..0x214`. Control `0x204 = 3`, not 1:
bit 0 enables the decoder, bit 1 selects **endless-scroll** mode. Without bit 1
the horizontal scroll is a 9-bit counter that emits BLACK past the 256px line —
any pan drops the picture to black.

```c
static void rainbow_setup(void)
{
    uint16_t zero = 0, control = 3;
    __asm__ volatile (
        "out.b %[z],0x200[r0]\n"
        "out.b %[z],0x202[r0]\n"
        "movea -128,r0,r10\n"
        "out.h r10,0x208[r0]\n"
        "out.h %[z],0x20c[r0]\n"
        "out.h %[z],0x210[r0]\n"
        "out.h %[z],0x214[r0]\n"
        "out.h %[c],0x204[r0]\n"
        : : [z] "r" (zero), [c] "r" (control) : "r10", "memory");
}

static void rainbow_set_hscroll(int hscroll)
{
    uint16_t lo = (uint16_t)(hscroll & 0xff);
    uint16_t hi = (uint16_t)((hscroll >> 8) & 0x01);
    __asm__ volatile (
        "out.b %[lo],0x200[r0]\n"
        "out.b %[hi],0x202[r0]\n"
        : : [lo] "r" (lo), [hi] "r" (hi) : "memory");
}
```

**Re-arm every field.** The HuC6271 decodes exactly one frame per arm (KING
`REG.40` control, `REG.41` KRAM start, `REG.42` start raster, `REG.43` block
count, `REG.44` raster monitor). Doom uses start raster 6, 15 blocks,
re-armed once per field after the visible area (restart raster 248). A
once-at-init arm leaves the layer blank — that was a real bug here.

```c
static void rainbow_rearm(void)
{
    uint32_t psw = pcfx_irq_save();
    king_reg16(0x40, 0x0000);
    king_reg32(0x41, (uint32_t)RB_SRC_ADDR);
    king_reg16(0x42, (uint16_t)PCFX_SKY_TRANSFER_START);  /* 6 */
    king_reg16(0x43, (uint16_t)PCFX_SKY_BLOCK_COUNT);     /* 15 */
    king_reg16(0x44, 0x0000);
    king_reg16(0x40, 0x0001);
    pcfx_irq_restore(psw);
}
```

Three rules around that block, all measured on hardware:

1. **Interrupt-atomic.** A timer IRQ inside a KING `0x600`/`0x604`
   select/data pair corrupts the access on silicon (the emulator does it
   atomically, so it cannot catch this). Guard every KING run — this one runs
   once per field, forever.
2. **Decode before enabling the plane.** An idle HuC6271 shows its last output;
   enabling the Tetsu plane first flashes stale content for a field.
3. **Layer mix on Tetsu.** RAINBOW is the rearmost plane; show it where the
   KING framebuffer is transparent (256-colour index 0). If the decoder is
   unfed, **hide the plane** — unfed RAINBOW is garbage on hardware.

## 4. Scrolling

**Horizontal.** With endless mode (`0x204 = 3`) the scroll counter wraps at 256
and a 256px-wide stream pans seamlessly — Doom scrolls its sky with the view
angle for free via `rainbow_set_hscroll()`. Without bit 1, columns past 256
decode as black.

**Vertical** is not a scroll register — it is transfer addressing
(`C6272_2.WRI` スクロール再生, asymmetric by direction):

- **Upward, 0–15 lines:** change only the transfer-start raster (`REG.42`).
- **Upward, ≥16 lines:** move the start address (`REG.41`) by whole 16-line
  blocks **and** adjust the start raster for the remainder. Example from the
  manual: 23 lines up = start address of the next 16-line block, start raster
  = normal − 7.
- **Downward:** start raster (`REG.42`) only, normal + N.
- **Per-field changes** must respect the 22.5-line inter-field blanking: a
  downward-N field followed by an upward-M field has an N+M bound (changing
  direction across fields is the constrained case). Re-check the WRI figure
  before implementing per-field direction changes.
- Reprogram at the documented frame/raster boundary and use the raster monitor
  (`REG.44`) so the source never changes while a block is being consumed.

**Split playback** divides one frame into regions with different streams:
program the first transfer, watch the split raster, then stage source/count for
the next region, leaving time for HuC6271 input buffering.

**Scrolling asset encoding:** `--independent-strips` makes every strip an
`FF FF` header with its own tables/scale, so any 16-line boundary is a valid
vertical-scroll start address. Cost: ~128 extra bytes per strip.

## 5. KRAM/transfer budget

- A 240-line frame is always 15 blocks; the transfer starts 16 rasters before
  the display interval and the chip displays on the 16th HSYNC after the
  header. Size the stream for the KRAM page reserve **and** the per-strip
  decode load inside one 16-line window — retail's ~16 KB/frame is the
  demonstrated ceiling, not a guarantee under your BG/SCSI/ADPCM load.
- There is **no universal per-strip byte ceiling** in the manual (K-R bus
  arbitration depends on the active workload). `--max-strip-bytes` exists for
  a ceiling **you measured** on your hardware/workload.
- `analyze_stream` / `inspect` report each strip's stored KRAM span
  (`4 + size + 6` bytes). Print and keep them; "largest strip" is the number
  that meets (or misses) the raster deadline.

## 6. ANTI-PATTERNS (the fixed encoder bugs — do not reintroduce)

The pre-MPCONV C encoder (`rainbow_yuvdct_encode.c` lineage: JPEG tables,
float math, `logical_bytes` sizes) produced streams that decoded "mostly fine"
with two signature defects. Every item below was a real bug:

| Symptom | Cause | Fix (in `tools/rainbow`) |
|---|---|---|
| Glitched tiles on the **right side** | size counted **unstuffed** bytes, so every `FF 00` pair under-ran the block; odd sizes broke word alignment; no inner dummy/guard, so the next block started mid-word | `size = tables + stuffed entropy + alignment + 2`; even sizes only; `BLOCK_INNER_DUMMY` + `BLOCK_GUARD` explicit |
| Poor compression, large blacks | JPEG quality-scaled tables transmitted directly; no null runs; no rescale controls | transmit base tables; `0x0F` null runs; `0x10+s` scale control; `auto` searches 0 (finest) first |
| Washed/clipped picture | float RGB→YUV, float chroma average, float FDCT driving a chip whose IDCT has **4× gain** | MPCONV integer YUV/FDCT (`0x15F2` first-pass asymmetry), `sum>>2` chroma, signed `±(q>>1)` quantize-then-truncate |
| Decoder desync mid-strip | JPEG `0x00` EOB symbol; clipped coefficients to force fit | 5-bit `0x1F` EOB; category > 9 is an error, pick a coarser scale instead |

If a new stream shows the right-side glitch, check in order: even sizes
(`analyze_stream` enforces), stuffed-byte accounting, dummy/guard presence,
then KRAM page routing (decoder reading another engine's page looks similar
but is a `0x0F` routing bug — see [pcfx-kram-layout]).

## Related

[pcfx-kram-layout] (pages, coexistence, collision detector) ·
[pcfx-yuv-palette] (YUV colour) · [pcfx-cd-assets] (getting the stream off the
disc) · [pcfx-emulator-testing] (captures, what they cannot prove) ·
`tools/rainbow/PROVENANCE.md` (tool derivation and limits) ·
`vendor/doompcfx/platform/i_system_pcfx.c` (runtime reference) ·
`tools/large-game/doom/gen_pcfx_rainbow_bg.py` (static-sky encoder twin).
