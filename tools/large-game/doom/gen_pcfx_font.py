#!/usr/bin/env python3
"""gen_pcfx_font.py -- convert the DOOM small HUD font (STCFN033..STCFN095) into
PC-FX HuC6270 VDC BACKGROUND TILES in 256-COLOUR combined-VDC mode.

WHY: the port draws all message/menu/finale text by read-modify-writing individual
8bpp pixels into the KING KRAM framebuffer (src/v_video.c V_DrawPatchFull). Moving the
font to a VDC background-tile OVERLAY draws it above the KING scene by hardware, at full
256px res, and -- crucially -- lets it share the KING scene palette so it FADES with the
scene for free (platform/pcfx_text.c).

256-COLOUR BG TILES combine BOTH HuC6270 VDCs, exactly like the weapon sprites
(gen_pcfx_weapons.py / king.c VDC_PIXELMIX):
    combined_index = (VDC0.pixel4bpp << 4) | VDC1.pixel4bpp     (chip0=high, chip1=low)
    the pixel is TRANSPARENT iff VDC1's low nibble is 0 (KING shows through)
    the BG-combine only triggers when VDC1's BAT entry carries palette-bank bit3 (0x8);
    the C side sets that in the BAT. Here we only guarantee every OPAQUE glyph pixel
    lands on a palette index whose LOW NIBBLE is non-zero (index 0 is the sole
    transparent slot), remapping the rare offender to the nearest safe index.
The combined 8-bit index is the REAL Doom PLAYPAL index (BG palette offset is 0, so the
VDC BG reads VCE 0..255 == the KING scene palette), so no separate font palette exists
and a scene fade updates those VCE entries for the font too.

HuC6270 BG tile (8x8, 4bpp) VRAM layout (16 words/tile, verified in vdc_video.c:176):
    word[y]   (y 0..7) = planes 0,1  : low byte = plane0, high byte = plane1
    word[8+y] (y 0..7) = planes 2,3  : low byte = plane2, high byte = plane3
    pixel column x (0..7) uses BIT x of each plane byte.

Emits src/generated/pcfx_font.{h,c}: pat0/pat1 (VDC0/VDC1 tile CG, 16 words/glyph),
per-glyph width, and a trailing all-zero BLANK tile the runtime uses to clear cells.

Usage: tools/gen_pcfx_font.py [--wad doom1.wad] [--out src/generated] [--png assets]
"""
import argparse, os, struct

FONT_FIRST = 33            # '!'  (HU_FONTSTART)
FONT_COUNT = 63            # '!'..'_' (HU_FONTSIZE)
TILE_W = 8
TILE_H = 8
TILE_WORDS = 16            # per VDC: 8 words planes0/1 + 8 words planes2/3


def read_wad(path):
    d = open(path, 'rb').read()
    magic, num, off = struct.unpack('<4sII', d[:12])
    if magic not in (b'IWAD', b'PWAD'):
        raise SystemExit('not a WAD: %s' % path)
    L = {}
    for i in range(num):
        fp, sz, nm = struct.unpack('<II8s', d[off + i * 16:off + i * 16 + 16])
        L[nm.rstrip(b'\0').decode('latin1')] = (fp, sz)
    return d, L


def playpal(d, L):
    fp, _ = L['PLAYPAL']
    return [(d[fp + i * 3], d[fp + i * 3 + 1], d[fp + i * 3 + 2]) for i in range(256)]


def decode_patch(d, off):
    """DOOM patch_t -> (w, h, topoffset, idx[h][w]) with -1 transparent."""
    w, h, lx, ty = struct.unpack('<HHhh', d[off:off + 8])
    colofs = struct.unpack('<%dI' % w, d[off + 8:off + 8 + 4 * w])
    idx = [[-1] * w for _ in range(h)]
    for x in range(w):
        p = off + colofs[x]
        while d[p] != 0xFF:
            top = d[p]; cnt = d[p + 1]; p += 3
            for r in range(cnt):
                yy = top + r
                if 0 <= yy < h:
                    idx[yy][x] = d[p + r]
            p += cnt + 1
    return w, h, ty, idx


def build_remap(pal, used):
    """remap[idx] moves any OPAQUE index whose low nibble is 0 (would render
    transparent in the combine) to the nearest-RGB index with a non-zero low nibble.
    Index 0 stays transparent; all other indices map to themselves."""
    safe = [i for i in range(1, 256) if (i & 0x0F) != 0]
    remap = list(range(256))
    for idx in used:
        if idx != 0 and (idx & 0x0F) == 0:
            c = pal[idx]
            remap[idx] = min(safe, key=lambda i: (pal[i][0] - c[0]) ** 2 +
                             (pal[i][1] - c[1]) ** 2 + (pal[i][2] - c[2]) ** 2)
    return remap


def glyph_bitmap(w, h, topoffset, idx, remap):
    """8x8 index bitmap honoring Doom's vertical patch offset.

    The ordinary seven-pixel-tall letters have topoffset 0. Baseline punctuation
    uses a negative topoffset (period -4, comma -3, dash -2), and Doom's patch
    drawer subtracts that value from y. Preserve the same downward placement in
    the fixed VDC tile instead of making a period look like an apostrophe.
    """
    bmp = [[0] * TILE_W for _ in range(TILE_H)]
    yoff = max(0, -topoffset)
    for y in range(min(h, TILE_H - yoff)):
        for x in range(min(w, TILE_W)):
            v = idx[y][x]
            if v >= 0:
                bmp[yoff + y][x] = remap[v] if v else 0
    return bmp


def tile_cg(bmp, high):
    """Pack an 8x8 glyph into one VDC's 16-word tile CG. `high` selects the high
    nibble (VDC0) or low nibble (VDC1) of each pixel's palette index."""
    cg = [0] * TILE_WORDS
    for y in range(TILE_H):
        w01 = 0; w23 = 0
        for x in range(TILE_W):
            idx = bmp[y][x]
            if idx == 0:
                continue
            nib = (idx >> 4) & 0xF if high else idx & 0xF
            # Screen column x maps to plane bit (7-x): the HuC6270 stores tc[7-x] from
            # bit x (vdc_video.c:187), so the leftmost column is the MSB of each plane
            # byte (matches the weapon sprites' 15-x packing).
            if nib & 1: w01 |= 1 << (7 - x)
            if nib & 2: w01 |= 1 << (15 - x)
            if nib & 4: w23 |= 1 << (7 - x)
            if nib & 8: w23 |= 1 << (15 - x)
        cg[y] = w01
        cg[8 + y] = w23
    return cg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wad', default='doom1.wad')
    ap.add_argument('--out', default='src/generated')
    ap.add_argument('--png', default='assets')
    args = ap.parse_args()

    d, L = read_wad(args.wad)
    pal = playpal(d, L)
    os.makedirs(args.out, exist_ok=True)

    # Collect used indices to build the low-nibble-0 remap.
    used = set()
    glyphs = []           # (present, w, h, topoffset, idx)
    for i in range(FONT_COUNT):
        nm = 'STCFN%03d' % (FONT_FIRST + i)
        if nm in L:
            w, h, topoffset, idx = decode_patch(d, L[nm][0])
            for row in idx:
                for v in row:
                    if v >= 0:
                        used.add(v)
            glyphs.append((True, w, h, topoffset, idx))
        else:
            glyphs.append((False, 0, 0, 0, None))
    remap = build_remap(pal, used)
    moved = [i for i in used if remap[i] != i]
    print('font: %d glyphs, %d colours, low-nibble-0 remapped: %s'
          % (sum(1 for g in glyphs if g[0]), len(used),
             ', '.join('%d->%d' % (i, remap[i]) for i in sorted(moved)) or 'none'))

    pat0 = []; pat1 = []; widths = []
    for present, w, h, topoffset, idx in glyphs:
        if present:
            bmp = glyph_bitmap(w, h, topoffset, idx, remap)
            pat0 += tile_cg(bmp, True)
            pat1 += tile_cg(bmp, False)
            widths.append(min(w, TILE_W))
        else:
            pat0 += [0] * TILE_WORDS
            pat1 += [0] * TILE_WORDS
            widths.append(TILE_W)
    # Trailing BLANK tile (index FONT_COUNT): all-transparent, for clearing BAT cells.
    pat0 += [0] * TILE_WORDS
    pat1 += [0] * TILE_WORDS

    hpath = os.path.join(args.out, 'pcfx_font.h')
    with open(hpath, 'w') as h:
        h.write('/* GENERATED by tools/gen_pcfx_font.py -- do not edit. */\n')
        h.write('#ifndef PCFX_FONT_H\n#define PCFX_FONT_H\n\n')
        h.write('#define PCFX_FONT_FIRST     %d  /* ASCII of glyph 0 */\n' % FONT_FIRST)
        h.write('#define PCFX_FONT_COUNT     %d\n' % FONT_COUNT)
        h.write('#define PCFX_FONT_BLANK     %d  /* index of the all-transparent tile */\n' % FONT_COUNT)
        h.write('#define PCFX_FONT_NTILES    %d  /* glyphs + blank */\n' % (FONT_COUNT + 1))
        h.write('#define PCFX_FONT_TILE_W    %d\n' % TILE_W)
        h.write('#define PCFX_FONT_TILE_H    %d\n' % TILE_H)
        h.write('#define PCFX_FONT_TILE_WORDS %d  /* per VDC */\n\n' % TILE_WORDS)
        h.write('extern const unsigned short pcfx_font_pat0[PCFX_FONT_NTILES * PCFX_FONT_TILE_WORDS]; /* VDC0 high nibble */\n')
        h.write('extern const unsigned short pcfx_font_pat1[PCFX_FONT_NTILES * PCFX_FONT_TILE_WORDS]; /* VDC1 low nibble  */\n')
        h.write('extern const unsigned char  pcfx_font_width[PCFX_FONT_COUNT];\n\n')
        h.write('#endif\n')

    cpath = os.path.join(args.out, 'pcfx_font.c')
    with open(cpath, 'w') as c:
        c.write('/* GENERATED by tools/gen_pcfx_font.py -- do not edit. */\n')
        c.write('#include "pcfx_font.h"\n\n')

        def emit(name, words):
            c.write('const unsigned short %s[%d] = {\n' % (name, len(words)))
            for i in range(0, len(words), 12):
                c.write('  ' + ', '.join('0x%04x' % w for w in words[i:i + 12]) + ',\n')
            c.write('};\n\n')
        emit('pcfx_font_pat0', pat0)
        emit('pcfx_font_pat1', pat1)
        c.write('const unsigned char pcfx_font_width[PCFX_FONT_COUNT] = {\n')
        for i in range(0, len(widths), 16):
            c.write('  ' + ', '.join('%d' % w for w in widths[i:i + 16]) + ',\n')
        c.write('};\n')
    print('wrote %s and %s' % (hpath, cpath))

    # ---- self-check: reconstruct each glyph via the exact emulator combine ----
    try:
        from PIL import Image
    except ImportError:
        return
    ng = FONT_COUNT
    im = Image.new('RGB', (ng * (TILE_W + 1), TILE_H), (30, 30, 30))
    px = im.load()
    for gi in range(ng):
        base = gi * TILE_WORDS
        for y in range(TILE_H):
            w01_0 = pat0[base + y]; w23_0 = pat0[base + 8 + y]
            w01_1 = pat1[base + y]; w23_1 = pat1[base + 8 + y]
            for x in range(TILE_W):
                b = 7 - x                        # screen column x <- plane bit (7-x)
                hi = ((w01_0 >> b) & 1) | ((w01_0 >> (b + 8)) & 1) << 1 | \
                     ((w23_0 >> b) & 1) << 2 | ((w23_0 >> (b + 8)) & 1) << 3
                lo = ((w01_1 >> b) & 1) | ((w01_1 >> (b + 8)) & 1) << 1 | \
                     ((w23_1 >> b) & 1) << 2 | ((w23_1 >> (b + 8)) & 1) << 3
                if lo == 0:
                    continue                     # transparent (low nibble keyed)
                idx = (hi << 4) | lo
                px[gi * (TILE_W + 1) + x, y] = pal[idx]
    rp = os.path.join(args.png, 'font_recon.png')
    im.resize((im.size[0] * 4, im.size[1] * 4), Image.NEAREST).save(rp)
    print('self-check: recon strip -> %s' % rp)


if __name__ == '__main__':
    main()
