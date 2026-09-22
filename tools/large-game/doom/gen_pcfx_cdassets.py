#!/usr/bin/env python3
"""gen_pcfx_cdassets.py — build the CD-streamed asset blob + catalog.

Bulk full-screen pictures (the intermission map, the episode-end finale screen)
must NOT live in the RAM program image — baking them in starves Doom's zone heap
and hangs the boot on a 2 MB PC-FX. Instead they live on the CD and are read into
a transient buffer only while their screen is on, then freed (see docs/cd-streaming-plan.md).

This tool takes named 320x200 Doom picture lumps from a source WAD, renders each
into the PC-FX native 256x240 (stretched to fill — no runtime stretch), packs it
into the KING 8bpp framebuffer word layout (2 px/word, BIG-ENDIAN: high byte =
even/left column), remaps index 0 (transparent) to an opaque black twin,
LZ4-compresses it (2-byte LE length header + raw block, decoded on the V810 by
platform/lz4_depack.S), pads each asset to a whole 2048-byte CD sector, and writes:

  <out>.bin : the concatenated, sector-aligned blob (cdlink `append`s it)
  <out>.h   : the catalog — a stable table of {name, sector-offset, compressed
              byte length, uncompressed framebuffer word count}

A lump prefixed `raw:` (e.g. `raw:TITLEPIC`) is stored UNCOMPRESSED (no LZ4) so it can
be streamed straight from CD into the KING framebuffer by a KING SCSI DMA (no decode,
no per-word CPU blit — platform/pcfx_cdasset.c pcfx_cd_background_dma). Its catalog
`raw` flag is 1 and `clen` is the full framebuffer byte length.

Usage: gen_pcfx_cdassets.py <src.wad> <out.h> [raw:]LUMP1 [[raw:]LUMP2 ...]
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lz4_block

FB_W, FB_H = 256, 240          # native screen
SRC_W, SRC_H = 320, 200        # Doom picture space
SECTOR = 2048


def read_dir(d):
    magic, n, off = struct.unpack('<4sII', d[:12])
    lumps = {}
    for i in range(n):
        fp, sz = struct.unpack('<II', d[off + i * 16:off + i * 16 + 8])
        nm = d[off + i * 16 + 8:off + i * 16 + 16].split(b'\0')[0].decode('latin1')
        lumps.setdefault(nm, (fp, sz))
    return lumps


def playpal(d, lumps):
    fp, _ = lumps['PLAYPAL']
    return d[fp:fp + 768]


def opaque_black(pal):
    """Darkest non-zero PLAYPAL index (index 0 is the transparent colour)."""
    return min(range(1, 256), key=lambda i: pal[i * 3] + pal[i * 3 + 1] + pal[i * 3 + 2])


def decode_patch(p):
    """Decode a Doom column/post picture to a row-major w*h index buffer."""
    w, h, _lo, _to = struct.unpack_from('<hhhh', p, 0)
    img = bytearray(w * h)
    colofs = struct.unpack_from('<%dI' % w, p, 8)
    for x in range(w):
        o = colofs[x]
        while p[o] != 0xff:
            top = p[o]; length = p[o + 1]; o += 3
            for k in range(length):
                y = top + k
                if 0 <= y < h:
                    img[y * w + x] = p[o + k]
            o += length + 1
    return w, h, img


def to_fb_words(idx320, w, h, black):
    """Stretch a w*h index picture to 256x240 and pack into framebuffer words
    (128 words/row, BIG-ENDIAN pixel pair). Index 0 -> opaque black twin."""
    words = bytearray(FB_W // 2 * FB_H * 2)
    wp = 0
    for y in range(FB_H):
        sy = y * h // FB_H
        row = sy * w
        for x2 in range(0, FB_W, 2):
            sx0 = (x2) * w // FB_W
            sx1 = (x2 + 1) * w // FB_W
            a = idx320[row + sx0] or black
            b = idx320[row + sx1] or black
            # KING framebuffer word = even<<8 | odd. Store LITTLE-ENDIAN so the
            # V810 blitter reads a u16 and write_kram()s it straight (no swap).
            struct.pack_into('<H', words, wp, (a << 8) | b)
            wp += 2
    return bytes(words)


def png_to_fb_words(path, pal, black):
    """Load a PNG asset and pack it into 256x240 framebuffer words. Its pixels are
    mapped to Doom PLAYPAL indices (used directly when the PNG is already paletted with
    PLAYPAL — the doom256.png case, lossless; otherwise nearest-RGB). Index 0 ->
    opaque black twin (framebuffer index 0 is the transparent/RAINBOW key)."""
    from PIL import Image
    im = Image.open(path)
    # `pal` is flat 768 bytes (r,g,b per index), as opaque_black() indexes it.
    idxmap = None
    if im.mode == 'P':
        pp = im.getpalette() or []
        if len(pp) >= 768 and all(pp[i] == pal[i] for i in range(768)):
            idxmap = list(im.getdata())        # palette == PLAYPAL -> indices are direct
    if idxmap is None:
        rgb = im.convert('RGB')
        px = list(rgb.getdata())
        nearest = {}
        idxmap = []
        for c in px:
            j = nearest.get(c)
            if j is None:
                j = min(range(256), key=lambda i: (pal[i * 3] - c[0]) ** 2 +
                        (pal[i * 3 + 1] - c[1]) ** 2 + (pal[i * 3 + 2] - c[2]) ** 2)
                nearest[c] = j
            idxmap.append(j)
    w, h = im.size
    if (w, h) != (FB_W, FB_H):
        sys.exit(f'{path}: expected {FB_W}x{FB_H}, got {w}x{h}')
    words = bytearray(FB_W // 2 * FB_H * 2)
    wp = 0
    for y in range(FB_H):
        row = y * FB_W
        for x2 in range(0, FB_W, 2):
            a = idxmap[row + x2] or black
            b = idxmap[row + x2 + 1] or black
            struct.pack_into('<H', words, wp, (a << 8) | b)
            wp += 2
    return bytes(words)


def emit(out_h, blob, catalog):
    out_bin = os.path.splitext(out_h)[0] + '.bin'
    os.makedirs(os.path.dirname(out_bin) or '.', exist_ok=True)
    # Always emit at least one sector so the CD `append` has a body.
    if not blob:
        blob = bytes(SECTOR)
    with open(out_bin, 'wb') as f:
        f.write(blob)
    with open(out_h, 'w') as f:
        f.write('/* Generated by tools/gen_pcfx_cdassets.py — do not edit. */\n')
        f.write('#ifndef PCFX_CDASSETS_H\n#define PCFX_CDASSETS_H\n\n')
        f.write('/* One CD-streamed full-screen picture: sector offset from the blob\'s\n'
                ' * base LBA, the compressed byte length to read (2-byte LZ4 header + block),\n'
                ' * and the uncompressed size in framebuffer words (128 words/row). */\n')
        f.write('typedef struct { const char *name; unsigned short sector; unsigned short clen; unsigned short words; unsigned char raw; } pcfx_cdasset_t;\n\n')
        f.write(f'#define PCFX_CDASSET_COUNT {len(catalog)}\n')
        f.write(f'#define PCFX_CDASSET_FB_WORDS {FB_W // 2 * FB_H}u  /* 256x240 packed */\n\n')
        if catalog:
            f.write('static const pcfx_cdasset_t pcfx_cdassets[PCFX_CDASSET_COUNT] = {\n')
            for nm, sec, clen, words, raw in catalog:
                f.write(f'    {{ "{nm}", {sec}, {clen}, {words}, {raw} }},\n')
            f.write('};\n')
        else:
            f.write('static const pcfx_cdasset_t pcfx_cdassets[1];  /* none available */\n')
        f.write('\n#endif\n')
    print(f'CD assets: {len(catalog)} pictures, {len(blob)} bytes ({len(blob)//SECTOR} sectors) '
          f'-> {out_bin}  ({", ".join(c[0] for c in catalog) or "none"})')


def main():
    if len(sys.argv) < 3:
        sys.exit('usage: gen_pcfx_cdassets.py <src.wad> <out.h> [LUMP1 LUMP2 ...]')
    src, out_h, names = sys.argv[1], sys.argv[2], sys.argv[3:]
    # No source WAD / no lumps requested (e.g. building without doom1.wad): emit an
    # empty catalog + a 1-sector placeholder so the tree still builds and boots.
    if not names or not os.path.exists(src):
        emit(out_h, bytearray(), [])
        return
    d = open(src, 'rb').read()
    if d[:4] not in (b'IWAD', b'PWAD'):
        sys.exit(f'{src}: not a WAD')
    lumps = read_dir(d)
    pal = playpal(d, lumps)
    black = opaque_black(pal)

    blob = bytearray()
    catalog = []   # (name, sector_offset, clen, word_count, raw)
    for spec in names:
        raw = spec.startswith('raw:')
        nm = spec[4:] if raw else spec
        # `raw:NAME=path.png` sources the picture from a PNG asset (already native
        # 256x240, mapped to PLAYPAL) instead of the WAD lump — the enhanced title art.
        png = None
        if '=' in nm:
            nm, png = nm.split('=', 1)
        if png:
            fb = png_to_fb_words(png, pal, black)
        else:
            if nm not in lumps:
                sys.exit(f'{src}: missing lump {nm!r}')
            fp, sz = lumps[nm]
            w, h, img = decode_patch(d[fp:fp + sz])
            fb = to_fb_words(img, w, h, black)
        sector = len(blob) // SECTOR
        if raw:
            # Uncompressed: the exact framebuffer-word image, DMA'd straight to KRAM.
            stored = fb
            catalog.append((nm, sector, len(stored), len(fb) // 2, 1))
            print(f'  {nm}: {len(fb)} bytes RAW (DMA){" from " + png if png else ""} @ sector {sector}')
        else:
            block = lz4_block.compress(fb)
            stored = struct.pack('<H', len(block)) + block   # 2-byte LE length + block
            catalog.append((nm, sector, len(stored), len(fb) // 2, 0))
            print(f'  {nm}: {len(fb)} -> {len(stored)} bytes '
                  f'({100.0 * len(stored) / len(fb):.0f}%) @ sector {sector}')
        blob += stored
        while len(blob) % SECTOR:
            blob += b'\x00'

    emit(out_h, blob, catalog)


if __name__ == '__main__':
    main()
