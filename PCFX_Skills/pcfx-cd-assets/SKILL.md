---
name: pcfx-cd-assets
description: Getting data onto and off a PC-FX disc - the bincat/lbas.h LBA mechanism, CD to RAM and CD to KRAM reads, DMA vs PIO, when CD access is safe, RAM budgeting in 2 MB, and asset build pipelines. Use when adding assets, loading levels or graphics at runtime, when a load hangs or returns garbage, or when the program no longer fits in RAM.
---

# Assets and the CD

## 1. How data gets on the disc

`bincat` concatenates your program and any extra files into `out.bin` and emits
**`lbas.h`**, a generated header giving each file's **LBA** (sector number) on the disc:

```make
cd: $(NAME).bin
	bincat out.bin lbas.h $(NAME).bin $(ADD_FILES)
	pcfx-cdlink cdlink.txt $(NAME)
```

```c
/* lbas.h — generated, do not edit */
typedef enum {
    BINARY_LBA_GAME_BIN   = 2,
    BINARY_LBA_LEVEL1_DAT = 34,
} bincat_lbas;
```

Your code `#include "lbas.h"` and reads from those LBAs at runtime. Sectors are 2048 bytes.

**The chicken-and-egg problem:** the program needs `lbas.h` to compile, but `lbas.h`
depends on the compiled program's size. The fix in `vendor/libpcfx/examples/example.mk` is to
run `bincat` **twice** — once to generate LBAs, then rebuild with them, then `bincat`
again so the final image matches:

```
bincat ... ; make clean ; make all ; bincat ... ; pcfx-cdlink ...
```

If assets load from the wrong sector after you changed code size, this two-pass dance is
what went wrong. doom-pcfx has a whole skill about the same bug class
(`sky loads from the wrong sector`).

## 2. Reading at runtime

libpcfx (`pcfx/cd.h`) provides both destinations:

- **CD → main RAM** — for level data, code overlays, anything the CPU parses.
- **CD → KRAM** — for graphics, straight into the framebuffer/BG memory without a bounce
  through RAM. `eris_cd_read_kram_retail()` is the documented shape that retail discs use.

Prefer the library calls. The CD path is the single most hardware-sensitive area on this
machine, and libpcfx's implementation is the product of a long real-hardware debugging
campaign:

- DMA vs PIO, and count-0 (phase-driven) vs count-bounded arming, behave differently on
  silicon than in emulation. libpcfx's history contains several revert commits here.
- **Verify every DMA destination** rather than trusting SCSI status
  (`cd: verify every DMA destination instead of trusting SCSI status`) — the drive can
  report success having written nothing. libpcfx now gives *every sector* its own verify probe.
- **Full SCSI bus reset (not SEEK) between read retries.**
- **Disarm KING SCSI DMA (register `0x0B`) at every teardown.**
- **Pause the interval timer across every CD operation** — a timer IRQ inside a CD/KING
  sequence corrupts it.

`vendor/libpcfx/docs/CD_DMA_MATRIX_RESULTS.md` records an actual hardware test matrix; read it
before changing a CD path, and `vendor/pcfxemu/docs/king-dma-erratum.md` /
`king-pio-read-erratum.md` for where the emulator deliberately models hardware faults.

## 3. When CD access is safe

**The CD is a live writer into KRAM and a source of IRQs.** Reading during gameplay can
corrupt graphics and cost unpredictable frame time.

The pattern that worked: **load at defined points** (level start, screen transitions) and
**keep the CD idle during gameplay** (descent-pcfx shipped exactly that commit). If you
must stream, route CD-DMA to a KRAM page your renderer is not using ([pcfx-kram-layout]),
and gate the transfer to vertical blanking.

Also: you cannot stream data and play a CD-DA track at the same time — one drive.

## 4. The 2 MB RAM budget

Code, data, heap and stack share **2 MB**. `pcfx-cdlink` prints your position:

```
Code+data Size: 4096
Stack+heap Free Space: 2058240
```

Watch that number. Techniques used here when it got tight:

- **`-Os` for cold code**, `-O2`/`Ofast` islands only for hot loops.
- **`-ffunction-sections -fdata-sections` + `--gc-sections`** so unused library entry
  points are dropped (libpcfx builds this way).
- **No float, no 64-bit math** — each drags ~1 KB of libgcc helpers in
  ([pcfx-v810-performance]).
- **Overlays**: emeraldpcfx could not fit Pokémon Emerald resident, so it partitioned into
  a resident core plus explicitly paged overlay arenas, routing cross-overlay calls
  through veneers. That is a large architectural commitment — only go there if you must.
- **Keep assets on the disc and page them in** rather than baking everything into the image.
- descent-pcfx added a **build-time memory budget report and gate**
  (`tools: report and gate the PC-FX memory budget`) so an overrun fails the build instead
  of failing to boot. Worth copying.

## 5. Asset pipelines

Convert art offline, in Python, into headers or raw files. Rules learned here:

- **Bake the KING pixel-pair byte order at build time** (`swap_pixel_pairs`), never per
  frame — see [pcfx-king-framebuffer].
- **Bake palettes as YUV**, using the same converter the runtime would
  ([pcfx-yuv-palette]). If a Python tool and the C runtime both convert, they must be
  bit-identical or colours drift.
- **Remap index 0** if the art uses it as a real colour — it is transparent.
- Keep the generated headers **in the repo** and regenerate deterministically, so a build
  is reproducible and diffs are reviewable.
- Checksum the outputs (several projects here keep `SHA256SUMS`) so you can tell whether
  an asset actually changed.

## 6. Large animation archives: append after the boot image

Do not use ordinary `bincat` asset concatenation when a large archive would become part of
the BIOS-loaded executable image. A 1.7 MiB animation archive can consume nearly all 2 MiB
main RAM before the program starts.

Use this layout instead:

```text
pcfx-cdlink base image: boot program only
asset start LBA:        base image sector count
final disc:             base image followed by sector-padded archive
runtime header:         generated asset LBA
```

If the generated LBA changes after recompilation, rebuild the program and package again.
The final packager must verify sector alignment and that the generated header matches the
actual appended location.

For the character animation viewer, the verified base image is 300 sectors and the PCA1
archive begins at LBA 300. The BIOS loads 237,568 bytes rather than the 1.72 MiB archive.

### Page-qualified KRAM DMA bounce addresses

When `eris_cd_read_dma` uses a KRAM page-1 scratch window, include bit 31 in the scratch
word address:

```c
#define KRAM_PHYS_PAGE1 0x80000000u

int ok = eris_cd_read_dma(lba, ram_dst, byte_count,
                          KRAM_PHYS_PAGE1 | scratch_word,
                          scratch_words);
```

Without `KRAM_PHYS_PAGE1`, the DMA engine can write page 1 while the SDK verification
probe reads page 0. The read then appears to fail and retry forever even though the data
reached KRAM. Route SCSI, RAINBOW and ADPCM pages deliberately, restore the normal page
setting after the transfer, and choose a bounce range that cannot overlap a live display,
ADPCM, RAINBOW or renderer allocation.

For the complete shared-rig animation pipeline, read `pcfx-character-animation`.

## Related

[pcfx-bringup] for the disc build · [pcfx-kram-layout] · [pcfx-audio] ·
[pcfx-emulator-testing] · [pcfx-character-animation]. Reference:
`descent-pcfx/docs/CD_TO_KRAM_ASSETS.md`, `descent-pcfx/docs/MEMORY_BUDGET.md`.
