---
name: pcfx-liberis-port
description: Porting a PC-FX program from liberis (eris_* / eris_low_*) to this toolkit's libpcfx - the API mapping table, the calls whose semantics differ (VDC control read-modify-write, KRAM page layout, SCSI teardown), header collisions, and the baseline-first porting procedure. Use when a project includes <eris/...> headers or links -leris, when moving code between the two libraries, or when a program that worked on liberis is black, silent or hung after the port.
---

# Porting liberis → libpcfx

This toolkit builds against `vendor/libpcfx` (`-lpcfx`). Older workspace projects use
liberis (`-leris`, `#include <eris/king.h>` etc.). Most calls are renames, but a port
that only renames can compile, link, boot and still be a **black screen**: the
RAINBOW player's port did exactly that (2026-09-22). This module lists the renames
and, more importantly, the calls that are **not** equivalent.

## 1. Procedure — baseline first, then port, then compare

1. **Build the unported code first, as it was.** The bundled toolchain still ships
   `liberis.a` and `include/eris/` (`$V810_GCC/lib/liberis.a`), so the original can be
   rebuilt with its old Makefile flags (`-leris`, liberis `crt0.o`). Run it in
   `pcfx-headless` and keep the disc: it is your known-good baseline.
2. Port with the table in §2. Grep for everything the table does not cover:
   `grep -n 'eris_\|0x8000[0-9a-f]\{4\}\|in\.h\|out\.h' src/*.c` — raw port pokes and
   memory-mapped I/O often depended on state the old library left behind.
3. Build, then run **both** discs at the same `--frames` values and compare the
   program's own counters (RAM dump + linker map, [pcfx-emulator-testing] §9) and
   screenshots. Any difference is the port's fault until proven otherwise.
4. Only then change behaviour (fixes, cleanups). Keep the port commit semantic-free.

## 2. Mapping

| liberis | libpcfx | Notes |
|---|---|---|
| `eris_king_init()` | `king_init()` | identical code |
| — | `king_set_kram_mode(1)` | 4-Mbit KRAM before any KRAM access ([pcfx-kram-layout]) |
| `eris_tetsu_init()` | `tetsu_init()` | leaves the RAINBOW chroma key disabled (max < min) |
| `eris_king_set_kram_pages(s,b,r,a)` | `king_set_kram_pages(s,b,r,a)` | libpcfx packs REG.0F as nibbles (SCSI D0, BG D4, ADPCM D8, RAINBOW D12); old libpcfx used a wrong byte layout — Doom keeps a raw `0x0F` write for that reason |
| `eris_king_set_bg_prio/_mode` | `king_set_bg_prio/_mode` | same arguments |
| `eris_tetsu_set_7up_palette` | `tetsu_set_vdc_palette` | "7up" = HuC6270 VDC |
| `eris_tetsu_set_king_palette`, `_rainbow_palette`, `_priorities`, `_video_mode` | `tetsu_set_*` same names | same argument order; priorities must be **unique** (C6261 R08–R09) |
| `eris_tetsu_get_raster()` | `tetsu_get_raster()` | returns the **decoded** line; still read twice ([pcfx-frame-timing]) |
| `eris_low_sup_set_control(chip, inc, bg, spr)` | **no equivalent** — see §3 | `vdc_setreg(chip, VDC_REG_CR, …)` overwrites the whole register |
| `eris_pad_init(0)` / `eris_pad_read(0)` | `contrlr_pad_init(0)` / `contrlr_pad_read(0)` | same bit layout (`JOY_RUN` = 0x80 = START) |
| `eris_low_scsi_reset()` | `scsi_reset()` | in `<eris/scsi.h>` |
| `eris_low_scsi_abort()` | `eris_scsi_abort()` | in `<eris/scsi.h>` |
| `eris_cd_read*` | `eris_cd_read*` (libpcfx `<eris/cd.h>`) | libpcfx versions verify the destination and disarm REG.0B at teardown |
| `eris_low_adpcm_set_control/_volume` | `adpcm_set_control/_volume` | `<pcfx/sound.h>` |
| `eris_low_cdda_set_volume` | `cdda_set_volume` | |
| `eris_timer_init/_set_period/_start` | `timer_init/_set_period/_start` | `<pcfx/timer.h>` |
| `<eris/types.h>`, `<eris/v810.h>` | `<pcfx/types.h>`, `<pcfx/v810.h>` | `irq_disable()/irq_restore()` same names, **different behaviour**: in liberis the pair always enables IRQs and clears the PSW interrupt level; fixed `vendor/libpcfx` restores them. A port can expose bugs liberis hid (next row) |
| (IRQ side effects) | — | After porting, IRQs that liberis switched on by accident stay off. `pcfx_rainbow_mp2` had unmasked VDC-A with `irq_set_mask(0x37)`; liberis serviced its pending IRQ early and the bug was invisible, while with IRQs really off until audio start it blacked the RAINBOW. Unmask only the sources you handle (timer only = `0x3F`) |

Link line: `-T$(LIBPCFX)/ldscripts/v810.x -L$(LIBPCFX) $(LIBPCFX)/src/crt0.o …
-lpcfx -lc -lsim -lnosys -lgcc` (see the player package Makefile).

## 3. The calls that are NOT renames

### VDC control register (the black-screen port)

liberis `eris_low_sup_set_control()` selects VDC register 5, **reads the data port**,
masks with `0xE73F`, ORs in increment/BG/sprite bits and writes it back. It looks like
a read-modify-write of CR, but reading the VDC data port returns the **VRAM read
latch**, not CR (`vendor/pcfxemu` `VDC_Read16`). So the bits it "preserved" were
whatever the read latch held — and that evidently included CR bit 3 (vblank IRQ
enable), since the liberis build's VD wait returned.

libpcfx `vdc_setreg(chip, VDC_REG_CR, VDC_CR_BB)` writes CR = `0x0080` exactly, which
clears bit 3. Any code that then waits on the VDC status VD flag (`0x80000400` bit 5)
hangs forever, because VD is only raised while CR bit 3 is set.

**Port rule:** write the full CR value you mean, bit by bit, and never depend on a
VDC status flag for frame timing — use the Tetsu raster wait ([pcfx-frame-timing],
"ANTI-PATTERN: waiting on the VDC status VD bit"). If you really want the VDC
vblank interrupt, set CR bit 3 deliberately in the value you write and install a
handler and interrupt mask for it; do not inherit it by accident. (libpcfx's
`vdc.h` declares `vdc_set_interrupts()` but `src/vdc.S` does not implement it — calling
it is a link error. `vdc_init_5MHz()` writes CR = 0: no IRQ, nothing displayed.)

### Header collisions

`<eris/scsi.h>` defines `SCSI_PHASE_*` enumerators. A program with its own SCSI state
machine (the PCFV player) cannot include it; declare only what you call:

```c
/* From libpcfx <eris/scsi.h>; its SCSI_PHASE_* enumerators collide with ours. */
void scsi_reset(void);
void eris_scsi_abort(void);
```

### SCSI DMA teardown

libpcfx clears KING REG.0B (SCSI DMA enable) at every teardown
(`vendor/libpcfx` commit `3b1f449`); liberis left it armed, which broke later CD-DA
commands. Hand-written DMA code should do the same:
`king_write_reg16(0x0B, 0)` before the REG.02/03 release ([pcfx-cd-assets]).

## 4. After the port: the checks that caught real bugs

- Boots, **and** the counters that prove progress move (`frames presented > 0`).
- Same picture as the baseline at the same frame counts (allow a few frames of drift
  if boot timing changed; compare content, not frame index).
- Audio present and in sync (WAV capture, A/V counters).
- Any loop/replay mode run **past** its first wrap — per-run state that the old code
  never reset shows up only there.

## Related

[pcfx-regression-triage] (worked before, broken now) · [pcfx-frame-timing] ·
[pcfx-emulator-testing] §8–9 · [pcfx-rainbow] §7 · [pcfx-bringup] (link line,
templates).
