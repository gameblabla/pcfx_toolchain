---
name: pcfx-vdc-tiles-sprites
description: 2D graphics on PC-FX using the two HuC6270 VDC chips - tilemaps (BAT), tile/sprite pattern data in VRAM, hardware scrolling, the sprite attribute table and its DMA, 16-colour palette groups, and layering the two chips plus KING. Use for any 2D game (platformer, shmup, RPG), tile/sprite corruption, sprites in the wrong order, or scrolling problems.
---

# 2D with the VDC chips

The PC-FX has **two HuC6270 VDCs** — the same tile/sprite chip as the PC Engine, with
**64 KB VRAM each** (not 32 KB). For a 2D game these give you hardware scrolling and
hardware sprites essentially for free at 60 fps, which is far cheaper than software
blitting into a KING bitmap.

**Choose your surface first:** VDC tiles/sprites for 2D games; KING BG0 bitmap for
software rendering ([pcfx-king-framebuffer]). You can use both — they are separate layers
mixed by Tetsu.

## 1. Bring-up

```c
vdc_init_5MHz(VDC0);         /* 256-wide; vdc_init_7MHz for 320 */
vdc_init_5MHz(VDC1);
vdc_set_satb_address(VDC0, 0x7000);   /* sprite attribute table in VRAM */

king_init();
tetsu_init();
tetsu_set_priorities(0, 0, 1, 0, 0, 0, 0);  /* vdcbg, vdcspr, bg0..3, rainbow */
tetsu_set_vdc_palette(0, 0);                /* palette base for bg / sprites  */
tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                     TETSU_COLORS_16, TETSU_COLORS_16,
                     1 /*vdc bg on*/, 1 /*vdc spr on*/, 0,0,0,0, 0);
```

`vendor/libpcfx/examples/020_vdc_simple_background`, `021_vdc_simple_sprite`,
`022_vdc_raster` and `023_vdc_multi_sprite` are the working references. Start there.

## 2. VRAM access

Like KING, VDC VRAM is reached through an address register plus auto-incrementing data:

```c
vdc_set_vram_write(VDC0, addr);
vdc_vram_write(VDC0, word);      /* address auto-increments */
```

The increment step is set in the control register (`VDC_CR_IW_01/20/40/80`) — the `0x20`
/`0x40`/`0x80` steps exist for writing column-wise. Raw registers: `vdc_setreg(chip, reg, val)`.

## 3. Tilemap (BAT) and scrolling

Virtual map size is chosen with `VDC_MWR_SCREEN_*`:

| Constant | Map |
|---|---|
| `VDC_MWR_SCREEN_32x32` | 32×32 cells |
| `VDC_MWR_SCREEN_64x32` | 64×32 |
| `VDC_MWR_SCREEN_128x32` | 128×32 |
| `VDC_MWR_SCREEN_32x64` / `64x64` / `128x64` | taller variants |

Cells are 8×8 pixels. A BAT entry packs the **tile number** and a **4-bit palette group**.
The map **wraps**, which is what makes scrolling cheap: scroll registers (BXR/BYR) move
the window, and you only rewrite the column or row entering the screen.

For a platformer: pick a map wider than the screen (e.g. 64×32), write the visible region
plus a margin, update the scroll register each frame, and rewrite only the newly exposed
column. Do **not** rebuild the whole BAT every frame — emeraldpcfx explicitly stopped
doing that (`Stop rebuilding the attribute table on frames nothing wrote to it`).

Write scroll registers **during blanking, before the attribute tables** — emeraldpcfx
shipped that ordering as a fix (`Write the scroll registers in blanking, before the
attribute tables`). See [pcfx-frame-timing].

## 4. Sprites

Sprites are described by a **SATB** (sprite attribute table) in VRAM, at the address given
to `vdc_set_satb_address()`. libpcfx wraps entry editing:

```c
vdc_set(VDC0);                        /* select chip  */
vdc_spr_set(n);                       /* select sprite n */
vdc_spr_create(x, y, pattern, ctrl);  /* or the individual setters below */
vdc_spr_xy(x, y);
vdc_spr_pattern(pat);
vdc_spr_ctrl(val);                    /* size, flip, priority */
vdc_spr_pal(pal);                     /* which 16-colour group */
```

**The chip does not notice SATB changes by itself.** Either re-trigger the SATB register
every frame, or set up SATB DMA once so it reloads automatically (see the `022`/`023`
examples). doom-pcfx hit visible tearing from doing the SATB upload at the wrong moment —
do it in blanking.

Two pattern-address traps, both of which produced real, confusing bugs in emeraldpcfx:

- A sprite's pattern field addresses VRAM in **32-word units and the chip discards the
  bottom bit** — a cell at an odd multiple of 32 words is read 32 words below where you
  wrote it, drawing as two overlapping copies. Keep cell bases at **multiples of 64 words**.
- A **256-colour** sprite's tiles are **64 bytes**, while the pattern number is still in
  32-byte units. Getting this wrong halves or doubles your addressing.

## 5. Palettes: 16-colour groups

VDC tiles and sprites use **16-colour sub-palettes**. A tile or sprite names a palette
*group*, and **every pixel in that cell must fall inside that group's 16 entries**. A cell
whose pixels span two groups cannot be drawn as-is — emeraldpcfx leaves such cells
undrawn. Plan art around 16-colour groups from the start.

Group bases are set with `tetsu_set_vdc_palette(vdcbg, vdcspr)`. See [pcfx-yuv-palette]
for the colour format and the layer palette layout.

**Pixel value zero is transparent even if palette entry zero contains a visible
colour.** An imported atlas may use source palette slot zero as an opaque colour;
writing that slot as VDC pixel zero makes holes. Dirty Pair's Stage 1 atlas uses
all 16 source slots, but no 8x8 tile contains both slots zero and one. Its
VDC path uses two BAT palette groups: tiles containing slot zero encode it as
pixel one and use a group whose entry one has slot zero's colour; the other
tiles use the ordinary group whose entry one has slot one's colour. Check this
per-tile disjointness before using that mapping on a changed atlas. Keep the
NES background-priority/opacity mask separate from the source colour slot:
clearing a visible pixel because its priority bit is clear destroys the map.

## 4bpp planar cells, BATs, and cache timing

The HuC6270 4bpp cell is planar, not KING-style nibble-packed. One 8x8 cell is
16 16-bit VRAM words: the first eight words are plane-01 rows, the next eight are
plane-23 rows. For a word, the low byte is plane 0/2 and the high byte is plane
1/3; bit 7 is the leftmost pixel. The emulator's `VDC_FixTileCache()` is the
decoding reference:

```c
bitplane01 = VRAM[y + charname * 16];
bitplane23 = VRAM[y + 8 + charname * 16];
raw_pixel = ((bitplane01 >> x) & 1)
          | (((bitplane01 >> (x + 8)) & 1) << 1)
          | (((bitplane23 >> x) & 1) << 2)
          | (((bitplane23 >> (x + 8)) & 1) << 3);
```

`VDC_CHRREF(palette, word_address)` stores `word_address >> 4` in the BAT; it does
not store a raw word address. BAT addresses are row-major: for a 64-cell-wide
map, cell `(x,y)` is VRAM word `y * 64 + x`. A 16x16 metatile made from four
8x8 cells therefore uses four consecutive BAT tile numbers, while its pattern
storage uses four consecutive 16-word cells. Keep sprite pattern bases 64-word
aligned.

When a background is written while CR bit `0x80` is clear and enabled later,
rebuild the emulator's decoded tile cache on the clear-to-set transition. The
local `pcfxemu` source applies this in both 8-bit and 16-bit VDC write paths.
A VRAM byte comparison alone is insufficient: verify the decoded cache or the
actual displayed pixels as well.

For a 256x128 atlas of 16x16 metatiles, the compact source position is:

```text
atlas_position = (ref >> 4) * 4096 + (ref & 15) * 256
               + local_y * 16 + local_x
```

For a 32x12 map of 16x16 semantic cells, each cell becomes a 2x2 block of
8x8 BAT entries. The result is **64x24 BAT cells**; there is no second
horizontal duplication. For semantic `(column,row)` in a 64-wide BAT:

```c
for (unsigned row = 0; row < 12u; ++row) { /* semantic rows, not 24 BAT rows */
    unsigned top = (row * 2u) * 64u + column * 2u;
    vdc_set_vram_write(chip, top);
    vdc_vram_write(chip, bat[top]);
    vdc_vram_write(chip, bat[top + 1u]);
    vdc_set_vram_write(chip, top + 64u);
    vdc_vram_write(chip, bat[top + 64u]);
    vdc_vram_write(chip, bat[top + 65u]);
}
```

The 2026-09-24 Dirty Pair port wrote the bottom pair at `row*64 +
column*2 + 32` instead of `(row*2+1)*64 + column*2`. That overwrote
neighbouring cells and crossed BAT rows, producing horizontal bands even
though **all 7,808 pattern words and the VCE palette matched the source**.
Changing only the second write address while retaining a 24-iteration loop
reads past the 64x24 shadow. The loop visits **12 semantic rows** and writes
two BAT rows per iteration.
Compare the entire live BAT against its RAM shadow (1,536 words here), then
decode the displayed 256x192 pixels against the source atlas. The corrected
capture matched all 49,152 source palette slots. A correct pattern check
alone cannot certify the displayed map.

A final emulator screenshot and a serialized VDC/RAM state can be one frame
apart around a map update. For acceptance, capture a stable state, resolve
symbols from the current ELF, and compare the VDC palette words, **all BAT
entries**, and decoded pattern pixels to the same logical map.

## 6. Layering the two chips

**Tetsu mixes VDC1 over VDC0 on transparency, and that is the whole ordering between
them**: a non-transparent pixel from the front chip wins, background or sprite alike. So
a sprite on the back chip is **behind the front chip's background**, whatever priority you
gave it.

That gives four depth slots for an object:

1. in front of the front chip's background (front chip sprite, priority bit set)
2. behind it, in front of the back chip's background (front chip sprite, no priority bit)
3. behind the back chip's background (back chip sprite, priority bit)
4. behind that (back chip sprite)

emeraldpcfx put every object on the back chip first and got opaque background pixels
punching holes through its foreground text — the fix was giving **both** chips sprites.
If your sprites are mysteriously behind a background, this is why.

KING backgrounds are mixed in by Tetsu priorities too, so you can put a KING BG0 bitmap
(or a rotating/scaling plane) behind or in front of the VDC layers —
`tetsu_set_priorities(vdcbg, vdcspr, bg0, bg1, bg2, bg3, rainbow)`.

**A rotating/scaling background has no VDC equivalent** — use KING BG0, which has the
right shape (one tile index per cell, 8bpp tiles, colour 0 transparent) and affine
registers. That is how emeraldpcfx does the GBA's mode-7-style plane.

## 7. Sprite limits

The VDC has per-scanline sprite and pixel limits (as on the PC Engine). Exceeding them
drops sprites on that line. With two chips you have two budgets; splitting a busy scene
across both chips is a legitimate technique — emeraldpcfx falls back to "draw it on the
other chip" rather than dropping a sprite, accepting the wrong order over a missing object.

## Related

[pcfx-yuv-palette] · [pcfx-frame-timing] · [pcfx-input] · [pcfx-king-framebuffer].
Best worked example in this workspace: `emeraldpcfx/README.md` §Graphics.
