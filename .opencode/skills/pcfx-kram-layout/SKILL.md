---
name: pcfx-kram-layout
description: Planning the KING KRAM memory map - the 2-page structure, per-engine page routing, framebuffer/RAINBOW/ADPCM/SCSI-DMA coexistence, the "all backgrounds in one page" rule, and diagnosing corruption where two subsystems overwrite each other. Use when adding or growing anything in KRAM, or when a bug looks like two subsystems fighting over memory.
---

# KRAM layout

KING owns **1 MB of KRAM**, structured as **2 pages × 262144 words** (a word is 16 bits,
addresses masked to `0x3FFFF` within a page). Every KING engine reads or writes KRAM:

| Consumer | Typical use |
|---|---|
| **BG / CG** | your framebuffer or tile data (usually the biggest) |
| **RAINBOW** | YUV/DCT background stream (sky, FMV) |
| **ADPCM** | sample banks for sound effects |
| **SCSI / CD DMA** | landing zone for data read off the disc |

They share the same memory. **KRAM collisions are one of the classic PC-FX bug families**:
audio garbling the sky, the sky decoding from the framebuffer, a CD read stomping graphics.

## 1. Page routing

Each engine is independently pointed at page 0 or page 1 via KING register `0x0F`
(`KRAM_PAGE`):

```c
king_set_kram_pages(scsi, bg, rainbow, adpcm);   /* each 0 or 1 */
```

Bit positions in the raw register: DMA = bit 0, BG/CG = bit 4, ADPCM = bit 8,
RAINBOW = bit 12. **A wrong page bit makes audio play garbage or the sky decode from your
framebuffer** — if a subsystem is showing another subsystem's data, check this first.

Routing CD-DMA to the page your framebuffer is *not* on is the simplest way to make disc
loads safe during gameplay.

## 2. The one-page rule for backgrounds

**All backgrounds must fit in the same KRAM page.** They cannot be split across pages; if
they don't fit, not all of them display.

That is a real budget. A page is 262144 words:

| Surface | Words |
|---|---|
| 256×240 8bpp framebuffer | 30,720 |
| double buffered | 61,440 |
| triple buffered | 92,160 |
| 512×512 4-colour BG | 65,536 |
| 256×256 16-colour BG | 32,768 |

So you can have one 512×512 4-colour and one 256×256 16-colour background, but **not two
512×512 16-colour backgrounds**.

## 3. Plan the map explicitly, and assert it

Write the map down as constants in one header, and make overflow a **compile-time error**.
doom-pcfx does this and it caught real bugs:

```c
#define KFB_PAGE_WORDS   (256 * 240 / 2)          /* 30720 */
#define KRAM_FB0          0x00000
#define KRAM_FB1          (KRAM_FB0 + KFB_PAGE_WORDS)
#define KRAM_SFX_BANK     (KRAM_FB1 + KFB_PAGE_WORDS)
#define KRAM_SFX_WORDS    (PCFX_SFX_BANK_BYTES / 2)

_Static_assert(KRAM_SFX_BANK + KRAM_SFX_WORDS <= 0x40000,
               "KRAM page overflow");
```

Without an assert, growing a sample bank silently overruns the next buffer and you spend
hours debugging "random" graphical corruption.

## 4. Diagnosing a suspected collision

The emulator's KING profiler (`PROFILE=1`) has an **exact per-word, same-field collision
detector**: it flags only when the CPU writes and ADPCM/RAINBOW *reads* the same KRAM word
within one field. That distinguishes a genuine hazard from harmless region sharing.

- **0 exact collisions** = your double buffering is correct, even if a coarse contention
  map shows overlap. doom-pcfx and descent-pcfx both confirmed their layouts this way.
- Non-zero = a real hazard. Move the buffer or re-time the write.

It also reports KRAM bandwidth per engine per field, which tells you whether you are
near the memory bandwidth limit rather than CPU-bound. See [pcfx-emulator-testing].

## 5. Other rules

- **Program KRAM into 4-Mbit mode** (register `0x61`, `king_set_kram_mode()`) before any
  other KING/KRAM access. doom-pcfx found addressing defects without it — a phantom
  "A16 hole" that turned out to be unprogrammed mode. The emulator is more forgiving here
  than real silicon.
- **Keep bulk KRAM bursts interrupt-atomic.** An IRQ landing in the middle of a
  select-address/write-data pair leaves KING's auto-increment stream pointing somewhere
  else. Both doom-pcfx and descent-pcfx shipped fixes for real-hardware text garble caused
  by exactly this: mask interrupts around the burst, or have the handler save and restore
  KING's KRAM-data selector.
- **The CD engine writes KRAM directly.** A DMA in flight during gameplay is a live writer
  in your address space — descent-pcfx's answer was `pcfx: keep the CD idle during
  gameplay`. See [pcfx-cd-assets].
- RAINBOW must be fed **through KING SCSI/CD DMA**; CPU KRAM writes do not reliably reach
  the decoder.

## Related

[pcfx-king-framebuffer] · [pcfx-audio] · [pcfx-cd-assets] · [pcfx-emulator-testing].
Register reference: `vendor/doompcfx/platform/pcfx_kram.h`, `vendor/libpcfx/docs/KING_REGS.md`.
