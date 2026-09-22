#!/usr/bin/env python3
"""gen_pcfx_title.py — build a 256x240 TITLEPIC patch from a PNG.

The PC-FX screen is 256x240, so a full-bleed title can be drawn 1:1 with no
stretching. Source is a 256x240 palette-indexed PNG whose palette is Doom's
PLAYPAL (so its bytes are already palette indices).

Palette index 0 is the engine's transparent colour (Y=0 shows the RAINBOW layer
through the framebuffer), so any index-0 pixel in the title would bleed the sky.
We remap index 0 -> the other pure-black PLAYPAL entry (247) so the title is
fully opaque.

Usage: gen_pcfx_title.py <title.png> <playpal.wad> <out.wad>
"""
import sys, struct

W, H = 256, 240
LUMP = 'TITLEPIC'


def read_playpal(wad):
    d = open(wad, 'rb').read()
    _, n, off = struct.unpack('<4sII', d[:12])
    for i in range(n):
        e = d[off + i * 16:off + i * 16 + 16]
        fp, sz = struct.unpack('<II', e[:8])
        nm = e[8:16].split(b'\0')[0].decode('latin1')
        if nm == 'PLAYPAL':
            return d[fp:fp + 768]
    sys.exit('PLAYPAL not found in ' + wad)


def opaque_black(pal):
    """Darkest PLAYPAL index that is not index 0 (used to replace transparent 0)."""
    return min(range(1, 256), key=lambda i: pal[i * 3] + pal[i * 3 + 1] + pal[i * 3 + 2])


def encode_patch(w, h, cols):
    """Fully-opaque patch: one post per column (top 0, full height)."""
    colofs = []
    coldata = bytearray()
    base = 8 + 4 * w
    for x in range(w):
        colofs.append(base + len(coldata))
        coldata += bytes([0, h, 0]) + bytes(cols[x]) + bytes([0, 0xff])
    return struct.pack('<hhhh', w, h, 0, 0) + struct.pack('<%dI' % w, *colofs) + bytes(coldata)


def make_pwad(name, data):
    hdr = b'PWAD' + struct.pack('<II', 1, 12 + len(data))
    diren = struct.pack('<II', 12, len(data)) + name.encode('latin1')[:8].ljust(8, b'\0')
    return hdr + data + diren


def main():
    if len(sys.argv) != 4:
        sys.exit('usage: gen_pcfx_title.py <title.png> <playpal.wad> <out.wad>')
    try:
        from PIL import Image
    except ImportError:
        sys.exit('gen_pcfx_title.py needs Pillow (PIL)')

    im = Image.open(sys.argv[1])
    if im.mode != 'P':
        sys.exit(f'{sys.argv[1]}: expected an 8bpp palette-indexed PNG, got {im.mode}')
    if im.size != (W, H):
        sys.exit(f'{sys.argv[1]}: expected {W}x{H}, got {im.width}x{im.height}')

    pal = read_playpal(sys.argv[2])
    black = opaque_black(pal)
    idx = bytearray(im.tobytes())
    for i, v in enumerate(idx):
        if v == 0:
            idx[i] = black

    # cols[x][y]
    cols = [[idx[y * W + x] for y in range(H)] for x in range(W)]
    open(sys.argv[3], 'wb').write(make_pwad(LUMP, encode_patch(W, H, cols)))
    print(f'TITLE: {sys.argv[1]} -> {LUMP} {W}x{H} (index 0 -> {black}) -> {sys.argv[3]}')


if __name__ == '__main__':
    main()
