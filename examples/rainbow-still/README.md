# RAINBOW still image with endless horizontal pan

The smallest complete RAINBOW (HuC6271) program: a 256×240 PNG is encoded with
`tools/rainbow/rainbow.py image`, appended to the disc, DMA'd into KRAM by the KING
SCSI engine, decoded once per field, and panned 1 px per field with the endless
scroll mode.

```sh
make cd                                   # generated test card
make cd IMAGE=title.png                   # your 256x240 PNG
make cd IMAGE=photo.jpg FIT=stretch       # resize to 256x240 first
PCFX_BIOS_DIR=/path/to/bios make validate # emulator gate
```

`make validate` runs `tools/rainbow/validate_still.py`: it screenshots two frame
counts, finds the pan shift against the source image, and fails on a black or wrong
picture, a pan that did not move by the expected amount, or a macroblock that
decodes far worse than a correct stream can (strip starvation/desync). Measured
(2026-09-22): pan 100 px over 100 fields, MAE 6.7, worst macroblock 26.7; the same
card with legacy strip framing fails at 60.2.

## What each piece is for

| Piece | Why |
|---|---|
| `--max-bytes 16384` | `eris_cd_read_kram` is hardware-confirmed for one 16 KiB arm at KRAM word `0x08000`; larger arms are unmeasured |
| `king_set_kram_pages(0,0,0,0)` | SCSI DMA must land on the page the RAINBOW reads |
| `0x204 = 3` | decode enable + endless scroll; without bit 1 a pan shows black past column 256 |
| re-arm at raster 248..261, once per field | one arm decodes one field; arming earlier aborts the running decode |
| `tetsu_get_raster()` read twice | HuC6261 raster latch bug |
| unique priorities, plane-enable bit to hide | C6261 R08–R09: priority 0 is the bottom, not hidden |
| `irq_disable()` around the arm | a timer IRQ inside a KING select/data pair corrupts it on silicon |

Everything above is explained, with sources, in `PCFX_Skills/pcfx-rainbow`.
Emulator evidence only: confirm on real hardware before release claims.
