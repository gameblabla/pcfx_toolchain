---
name: pcfx-2d-picture
description: Put a still picture on the PC-FX screen, match colors to a PC/source palette, and choose the right path: KING BG0 indexed bitmap (2/4/8bpp), direct YUV 64K/16M, VDC 16-colour tiles and sprites, or the RAINBOW image decoder. Includes the verified 8bpp setup, pixel packing, palette offsets, transparency, and the boundary between palette and direct-colour modes.
---

# Put a 2D picture on screen

Start by deciding whether the source is a full-screen still, a tile/sprite game scene,
or photographic art. The pixel format and palette rules change with the hardware layer.

## Choose a path

| Picture | Use | Color representation | Start here |
|---|---|---|---|
| One still image, UI, or software-rendered 256×240 frame | KING BG0, `KING_BGMODE_256_PAL` | 8-bit palette index; 256 indices per plane | **Recommended first picture.** Copy the verified bitmap setup below and [pcfx-king-framebuffer]. |
| Pixel art with a small palette | KING BG0, `KING_BGMODE_16_PAL` or `KING_BGMODE_4_PAL` | 4bpp (16 entries) or 2bpp (4 entries) | Same bitmap path, with denser packing; see the mode table. |
| Scrolling map, many moving objects | VDC tiles and sprites | 16-color groups per tile/sprite, with optional dual-VDC 256-color mode | [pcfx-vdc-tiles-sprites] and [pcfx-2d-code-examples]. |
| Photo, gradient, or still background where lossy compression is acceptable | RAINBOW (HuC6271) | Compressed direct YUV; no Tetsu palette for the normal YUV stream | `examples/rainbow-still/` and [pcfx-rainbow]. |
| Exact high-color bitmap | KING BG0, `KING_BGMODE_64K` or `KING_BGMODE_16M` | Direct YUV; no palette lookup | Advanced path below. A mode enum alone does not configure the fetch schedule or pack the image. |

For the first visible picture, use KING BG0 8bpp. It is the simplest full-screen bitmap
path in the toolkit and has a verified bring-up template. A `TETSU_COLORS_256` argument
does **not** select KING BG0's pixel format: KING BG modes come from
`king_set_bg_mode()`. The `bg_depth` and `spr_depth` arguments to
`tetsu_set_video_mode()` select VDC background and sprite input depths.

In this guide, **HiColor** means KING's `KING_BGMODE_64K` direct-YUV mode (65,536
possible Y8U4V4 values). It is separate from `KING_BGMODE_16M`, which uses 8-bit Y, U,
and V components with horizontal chroma sharing.

## When to convert image data

Use this order for color conversion, quantization, and pixel packing:

1. **Offline during the asset build — preferred.** Convert and pack PNG/source art on the
   host, then ship the final palette and KRAM-ready pixel words. This avoids spending
   V810 time on image processing and lets the asset builder do color matching once.
2. **At load time — fallback.** Use this when the disc needs to keep a compact or source
   format. Convert once after loading, before gameplay; account for startup/load latency
   and the 2 MB main-RAM budget. If output is written into the displayed plane, use a
   hidden buffer and switch only after it is ready.
3. **At runtime — last resort.** Reserve this for colors or pixels that are genuinely
   generated or changed during play. Do not decode PNGs, quantize palettes, or search
   RGB-to-YUV candidates per frame. Cache converted results, bound the work, and profile
   it on the V810.

“Runtime” here means conversion during active game execution; one-time conversion during
asset loading is the separate second choice above. The V810 has no FPU, and palette
conversion/search already caused measured frame-time and freeze costs in local projects.
Keep palette writes themselves in vertical blanking even when the palette was prepared
offline or at load time; see [pcfx-yuv-palette] and [pcfx-frame-timing].

## First picture: KING BG0 8bpp

Copy [pcfx-bringup]'s `template/src/main.c` for the complete working setup. It already
configures KING, its BG0 microprogram, affine identity matrix, Tetsu display, and the
KRAM burst writer. Keep that setup and replace the sample fill/box with the image data.

For a 256×240 source image:

1. On the host, resize/crop the art to the intended 256×240 framebuffer and quantize it
   to at most 255 opaque colors. Keep an alpha mask separately if the picture has
   transparent areas. Do not run PNG decoding or RGB-to-YUV palette searches on the V810.
2. Assign transparent pixels palette index `0`; assign opaque pixels indices `1..255`.
   For a fully opaque full-screen image, still keep index `0` unused.
3. Pack each adjacent pixel pair into one 16-bit word: left pixel in bits `15..8`, right
   pixel in bits `7..0`. A row is 128 words; the whole image is 30,720 words / 61,440
   bytes.
4. Convert the 256 palette slots offline to Y8U4V4 words using
   [pcfx-yuv-palette]'s `rgb_to_yuv.py`. Index 0 is the transparent/backdrop slot; do not
   put a visible art pixel there.
5. Before enabling BG0 (or during vertical blanking), write the palette with
   `tetsu_set_palette()` and copy the packed words into KRAM with the one-address,
   many-word burst helper from [pcfx-king-framebuffer].

The pixel address for an 8bpp image is:

```c
word_address = image_base + y * 128u + x / 2u;
```

This expression names a **16-bit KRAM word**, not a CPU pointer. KRAM is accessed through
KING I/O ports. Do not write `((u16 *)0x80000000)[...]` or treat KRAM as main RAM.

The essential mode and palette setup, copied from the bring-up template, is:

```c
#define IMAGE_BASE 0u

king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                 KING_BGSIZE_256, KING_BGSIZE_256);
king_set_bat_cg_addr(KING_BG0, 0, IMAGE_BASE >> 10);
king_set_bat_cg_addr(KING_BG0SUB, 0, IMAGE_BASE >> 10);
king_set_scroll(KING_BG0, 0, 0);
king_set_scroll(KING_BG0SUB, 0, 0);
king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                 KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 1);

/* Palette base for KING BG0. The other planes are not used in this example. */
tetsu_set_king_palette(0, 0, 0, 0);
```

The offline asset should provide a `u16 image_words[30720]` array in the pair order
above and a `u16 image_palette[256]` array of Y8U4V4 words. With the burst helpers from
[pcfx-king-framebuffer], install it while BG0 is still disabled:

```c
static void upload_picture(const u16 *words, const u16 *palette)
{
    unsigned i;
    for (i = 0; i < 256; ++i)
        tetsu_set_palette((u16)i, palette[i]);

    kram_set_write_inline(IMAGE_BASE, 1);  /* address set once */
    kram_begin_burst();
    for (i = 0; i < 30720; ++i)
        kram_write_latched(words[i]);
}

/* Call after king_init()/tetsu_init(), before enabling BG0 in Tetsu. */
upload_picture(image_words, image_palette);

/* These depth arguments configure VDC inputs; KING BG0 was selected above. */
tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                     TETSU_COLORS_256, TETSU_COLORS_16,
                     0, 0, 1, 0, 0, 0, 0);
```

The snippet is not a complete KING initialization by itself. In particular, BG0 needs
the microprogram and affine coefficients in the copied template. Do not remove them when
replacing its moving box with a still image.

## KING bitmap modes and storage

These figures are for a linear 256×240 BG0 bitmap in internal dot-sequential mode. A
KRAM word is 16 bits.

| KING mode | Pixel depth | Pixels per KRAM word | Image storage | Palette use | Transparent pixel |
|---|---:|---:|---:|---|---|
| `KING_BGMODE_4_PAL` | 2bpp / 4 colors | 8 | 7,680 words / 15,360 bytes | 4 palette indices | index 0 |
| `KING_BGMODE_16_PAL` | 4bpp / 16 colors | 4 | 15,360 words / 30,720 bytes | 16 palette indices | index 0 |
| `KING_BGMODE_256_PAL` | 8bpp / 256 indices | 2 | 30,720 words / 61,440 bytes | 256 palette indices | index 0 |
| `KING_BGMODE_64K` | 16bpp / 65,536 YUV values | 1 | 61,440 words / 122,880 bytes | None | Y = 0 |
| `KING_BGMODE_16M` | 24-bit YUV, chroma shared by each horizontal pair | 2 pixels in 2 words | 61,440 words / 122,880 bytes | None | Y = 0 for that pixel |

For indexed bitmap modes, the first pixel is in the most-significant bits of the word:
8-bit-index pixels use high byte then low byte; 16-color pixels use high nibble to low
nibble; 4-color pixels use two-bit fields from high to low. The 16M YUV pair layout
implemented by `pcfxemu` stores `Y0:Y1` in the first word and `U:V` in the second. The
manual's high-color format description and emulator source agree on direct YUV and
horizontal U/V sharing; the emulator layout describes the emulator, not proof of retail
hardware behavior. Check the original Japanese `C6272_3.WRI` figures before making a
hardware-specific claim.

### Pack an indexed picture for 2bpp, 4bpp, or 8bpp

Quantize the source offline to local pixel values `0..3`, `0..15`, or `0..255`. Keep
local value 0 transparent. Convert the associated RGB palette entries to Y8U4V4 with
`pcfx-yuv-palette/rgb_to_yuv.py`, then load those words at the selected Tetsu palette
base. The per-row packer is the same for all three formats; it places the leftmost pixel
in the most-significant field:

```c
/* Host-side asset builder. Width must be a multiple of 16 / bpp. */
static void pack_index_row(const u8 *pixels, unsigned width, unsigned bpp,
                           u16 *out_words)
{
    const unsigned ppw = 16u / bpp;
    const unsigned mask = (1u << bpp) - 1u;
    unsigned x, lane;

    for (x = 0; x < width; x += ppw) {
        u16 word = 0;
        for (lane = 0; lane < ppw; ++lane)
            word |= (u16)((pixels[x + lane] & mask)
                          << (16u - bpp * (lane + 1u)));
        out_words[x / ppw] = word;
    }
}
```

Call it with `bpp=2`, `4`, or `8`. For a 256-pixel row, it writes respectively 32, 64,
or 128 KRAM words. Upload each packed row as consecutive words using the burst writer
from [pcfx-king-framebuffer]. `king_set_bg_mode()` must select the matching enum, and
the full BG0 setup still comes from [pcfx-bringup]. This function only packs pixels; it
does not quantize colors, write KRAM, or program the KING display.

Palette allocation depends on the selected format. 2bpp consumes a four-index window,
4bpp consumes a sixteen-index window, and 8bpp consumes a 256-index window. In each
window index 0 is transparent, leaving 3, 15, or 255 opaque colors respectively. Choose
even Tetsu base entries, reserve the whole window before assigning other layers, and
write the Y8U4V4 palette words before enabling the picture. See the 512-entry allocation
rules above.

The memory sizes above only describe pixel storage. Direct 64K/16M modes still need a
KING fetch microprogram appropriate to the selected plane format. The standard sample
is verified for indexed 8bpp; do not assume changing `KING_BGMODE_256_PAL` to `64K` or
`16M` makes the same code a verified high-color player. Start with the C6272 manuals,
then inspect `vendor/pcfxemu/mednafen/pcfx/king.c` for what the emulator implements.

## Palette handling: 512 shared entries

The HuC6261 has **512 palette RAM entries**, each a 16-bit Y8U4V4 word. A slot can hold
one of 65,536 Y8U4V4 values; that does not mean the palette has 65,536 simultaneous
entries. The 512 entries are shared by palette-based KING, VDC, and palette-mode RAINBOW
planes. Direct-color KING BG and the usual RAINBOW YUV stream bypass palette lookup.

For one palette-based pixel, the displayed address is the pixel's palette index plus
that plane's base offset (modulo 512). KING and VDC plane offsets are even entry
addresses because the HuC6261 stores the offset in two-entry units. For example:

```c
/* BG0 uses entries 0..255; BG1 starts at entry 256. */
tetsu_set_king_palette(0, 256, 0, 0);

/* VDC BG starts at 0; VDC sprites start at entry 256. */
tetsu_set_vdc_palette(0, 256);
```

`tetsu_set_king_palette()`, `tetsu_set_vdc_palette()`, and
`tetsu_set_rainbow_palette()` take the base entry number; libpcfx converts it to the
HuC6261's two-entry offset units. Keep each base even and in `0..510`, and allocate
non-overlapping ranges for layers that need distinct colors.
Index 0 remains transparent in indexed modes, independent of what YUV word is stored at
that palette address. For an opaque black picture pixel, quantize it to a nonzero index
whose Y value is near black.

The pixel depth and palette base are separate settings:

- `king_set_bg_mode(...KING_BGMODE_256_PAL...)` selects one byte of palette index per
  pixel for that KING plane.
- `tetsu_set_king_palette()` chooses which shared palette range the plane's indices use.
- `tetsu_set_video_mode()`'s `TETSU_COLORS_16/256` arguments select VDC depths; they do
  not allocate a KING palette range or change a KING bitmap to 4bpp/8bpp.

For a 16-color VDC tile/sprite scene, each tile or sprite selects a 16-entry group.
Every pixel in that cell must fit the selected group. Read
[pcfx-vdc-tiles-sprites] for BAT/SAT setup and the working VDC examples; do not model a
VDC scene as a single 16bpp bitmap.

## Matching colors from a PC version or source palette

Keep pixel indices separate from display colors. RGB332 is **not** the HuC6261 palette
format. A program could choose RGB332 values as software indices and then map each one
to a Y8U4V4 word, but quantizing the source art to RGB332 first throws away color detail
before the PC-FX conversion even starts.

For a game with an existing finite palette:

1. Read the colors from the game's palette data, not from an RGB332 approximation of the
   screenshot. If the combined visible source palette fits in 255 opaque entries, map
   each source color directly through `pcfx-yuv-palette/rgb_to_yuv.py` and keep the
   matching source-color-to-index table.
2. If more than 255 opaque colors are needed, build one shared palette offline and map
   source pixels to its entries using the **reconstructed YUV colors** as the final
   candidates. Preserve important UI/sprite colors explicitly before quantizing the
   background. Do not quantize to RGB332 and then convert that reduced palette to YUV.
3. Compare a screenshot against the same PC source frame/region. Use
   [pcfx-color-verification] for numeric palette-word checks; a vision model can describe
   gross layout, but it cannot reliably tell whether a YUV color is the right one.

For an existing game port, make that comparison a short, repeatable gate before
editing color code:

1. Name one stable scene and its PC source image or palette table. A title fade,
   menu transition, and gameplay frame are different references; comparing them
   produces a false color diagnosis.
2. Save the input script, exact frame number, disc build command, and screenshot
   together. Capture one no-input baseline first. A count of distinct RGB triples
   only detects a nearly blank frame; it does not measure color fidelity.
3. Trace one wrong source color through source RGBA -> palette selection/index ->
   Y8U4V4 word -> uploaded palette slot -> screen pixel. Check each value before
   changing quantization or KING mode. If the source uses more than 255 visible
   colors, report the indexed-mode loss explicitly and evaluate direct YUV using
   `examples/king-still-modes/`.
4. After two screenshots that do not distinguish hypotheses, stop varying input
   frame numbers. Inspect the relevant stage and add a small numeric check. If
   RAM state matters, resolve the current ELF/map symbol; a prior session's
   absolute address is not stable across builds.

Examples and transcripts copied from other workspaces may contain old relative
or absolute paths. Resolve tools and source assets in the current checkout
before interpreting a failed build as a hardware or image-format defect.

**Do not invent an inverse YUV formula.** For a numeric round trip use
`yuv_to_rgb(word)` from `pcfx-yuv-palette/rgb_to_yuv.py`, which models this
target's conversion. A generic BT.601 formula or manually expanded 4-bit
chroma can report large false errors for a correct palette word. Compare the
actual emulator pixel to this converter and `pcfx-color-verification` before
blaming YUV conversion. Also, a composed game frame can contain overlay text,
sprites, fades, and status art absent from a background PNG; compare a region
known to contain only the source background or use a native frame capture.
When reproducing a C palette lookup in NumPy, convert every sampled channel
with `int(channel)` before `<<`, `-`, or squared-error math. `numpy.uint8`
arithmetic can wrap and produce false palette indices or distances without
raising an error; a previous Dirty Pair comparison turned an exact index 100
into 226 this way.
For Pillow's flattened `getdata()` or a baked pixel byte array, `(x, y)` is
at `y * width + x`. Swapping it to `x * width + y` can make a correct bake
look as if it assigned the wrong palette index at the sampled coordinate.
For Pillow asset baking, `Image.convert("P", palette=...)` expects a palette
selector (`WEB` or `ADAPTIVE`), while `Image.MEDIANCUT` is a `quantize()`
method. Passing `Image.MEDIANCUT` as `convert`'s palette argument can select
the web-safe palette and change colors even in a 19-color source. Use
`im.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT,
dither=Image.Dither.NONE)` for an actual median-cut call, or build an exact
palette when the source has at most 255 opaque colors. Assert source-to-baked
RGB equality for that exact-palette case before accepting a screenshot.

If the frame uses more colors than an indexed palette can preserve, consider KING 64K
direct YUV for a pixel-precise bitmap, or RAINBOW for photographic art that can use its
compressed still-image format. Direct 64K still requires RGB-to-Y8U4V4 conversion; it is
not RGB565 and does not make RGB bytes display correctly by themselves. A game with a
small existing palette can often preserve its colors better by mapping that palette to
Y8U4V4 than by converting an RGB332 approximation.

## Direct high-color images

`KING_BGMODE_64K` and `KING_BGMODE_16M` are direct YUV modes. They do **not** use
`tetsu_set_palette()` or consume a palette range:

- 64K stores one Y8U4V4 word per pixel: `(Y << 8) | (U4 << 4) | V4`. Neutral chroma is
  `U4=V4=8`. This is **not RGB565**.
- 16M stores 8-bit Y, U, and V components, with U/V shared by two horizontally adjacent
  pixels. Neutral chroma is U=V=`0x80`. For an even-width row, `pcfxemu`'s internal-dot
  bitmap layout stores each pair as two consecutive KRAM words: `(Y0 << 8) | Y1`, then
  `(U << 8) | V`. The C6272 translation specifies the horizontal chroma subsampling;
  check the original Japanese figure before treating this emulator word order as proven
  retail hardware behavior.
- In either direct mode, Y=0 is transparent. Preserve black opaque pixels with a small
  nonzero Y value.

For a 64K asset, run the host RGB-to-Y8U4V4 conversion for every source pixel and write
one converted word per pixel in scan order. For 16M, convert each source pixel to
YUV888, retain each pixel's Y, and share one U/V pair across every two horizontal
pixels (normally by averaging the pair's chroma). Emit the two-word pair above. The
bundled `rgb_to_yuv.py` produces the 64K palette-word format; it does **not** produce a
full-resolution YUV888 asset for 16M. Use source YUV when the source game already stores
it, or provide a separate host converter whose reconstructed RGB has been checked with
[pcfx-color-verification]. Do not silently treat RGB888 bytes or the 64K palette word as
16M data.

Changing to a direct-color mode requires all of the following together: the BG format,
the data packer, the KRAM contents, a mode-compatible KING fetch microprogram, and the
right layer enable/priority. Disable the plane while changing its format. The bundled
SDK does not provide a one-call PNG-to-64K/16M BG0 path. For photo-like full-screen art
that needs a ready path today, use the validated [pcfx-rainbow] still-image encoder;
for pixel-exact direct-color KING work, build and verify the format-specific pipeline.

## Wrong approaches that look plausible

- **Treating the Tetsu palette as RGB565/RGB555/RGB332.** It is Y8U4V4. Convert source
  colors with `PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py` and use
  [pcfx-color-verification] to check sampled screenshot pixels numerically.
- **Using RGB332 as an intermediate source palette.** That is an optional software
  quantizer, not a PC-FX video mode, and it can discard the PC version's colors before
  the YUV mapping. Map original colors directly or quantize against the final YUV palette.
- **Assuming the HuC6261 has only 256 entries.** Its palette RAM has 512 entries; each
  KING/VDC input still has its own index width and base offset.
- **Writing RGB pixel values into an 8bpp KING framebuffer.** The bytes are palette
  indices. Convert colors offline and upload the palette separately.
- **Using index 0 as opaque artwork.** Indexed KING and VDC modes use zero as
  transparent/keyed data.
- **Changing only the enum for 64K/16M.** Pixel packing and the fetch schedule must also
  match the direct-color mode.
- **Uploading all palette entries during active display.** Install before enabling the
  layer or update during vertical blanking; see [pcfx-frame-timing].

## Source trail

- `vendor/libpcfx/include/pcfx/king.h`: KING indexed/direct mode names.
- `vendor/libpcfx/include/pcfx/tetsu.h` and `vendor/libpcfx/src/tetsu.S`:
  Tetsu setup API and the two-entry palette offset encoding.
- `DOCUMENTATION/ENGLISH_TRANSLATION/C6261/C6261.md` §§2.2.1–2.2.3: 512 palette
  entries and plane-offset formula. Check `DOCUMENTATION/ORIGINAL_JPN/C6261.WRI` when
  exact Japanese wording/figures matter.
- `DOCUMENTATION/ENGLISH_TRANSLATION/C6272_1/C6272_1.md` §3.6.3 and
  `DOCUMENTATION/ENGLISH_TRANSLATION/C6272_3/C6272_3.md` §CG: KING formats. The original
  Japanese C6272 WRI manuals take precedence over the translations.
- `vendor/pcfxemu/mednafen/pcfx/king.c`: emulator's current pixel decode, transparency,
  palette indexing, and direct-color packing.
- `PCFX_Skills/pcfx-bringup/template/src/main.c`: complete verified indexed 8bpp setup.

## Related

[pcfx-king-framebuffer] · [pcfx-yuv-palette] · [pcfx-color-verification] ·
[pcfx-vdc-tiles-sprites] · [pcfx-rainbow] · [pcfx-frame-timing]
