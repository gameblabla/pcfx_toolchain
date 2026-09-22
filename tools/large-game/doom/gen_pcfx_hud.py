#!/usr/bin/env python3
"""gen_pcfx_hud.py — build the PC-FX 256px status-bar background.

Source is the finished GBADoom-derived status bar asset STBAR.png (256x32,
8-bit palette-indexed, whose palette is exactly Doom's PLAYPAL). It was authored
from the 240px GBADoom bar shifted +8px in X and padded to the PC-FX's 256px
screen width, so the printed labels line up with the engine's widget positions
(see include/st_stuff.h, ST_X=8). We take its raw palette indices verbatim and
emit them as the STBARFX lump:
  - a one-lump PWAD (STBARFX) holding the raw 256x32 8bpp image, merged into the
    baked IWAD and drawn 1:1 at runtime (no stretch), and
  - optionally a PNG preview for inspection.

The dynamic HUD widgets (face, numbers, keys) are drawn on top by the engine.

Usage: gen_pcfx_hud.py <stbar.png> <out.wad> [--png out.png]
"""
import sys, struct, argparse

OUT_W = 256          # PC-FX screen width
OUT_H = 32           # status-bar height
LUMP  = 'STBARFX'


def read_bar_png(path):
    """Return the raw 8bpp palette indices of a 256x32 paletted PNG."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit('gen_pcfx_hud.py needs Pillow (PIL) to read ' + path)
    im = Image.open(path)
    if im.mode != 'P':
        sys.exit(f'{path}: expected an 8bpp palette-indexed image, got {im.mode}')
    if im.size != (OUT_W, OUT_H):
        sys.exit(f'{path}: expected {OUT_W}x{OUT_H}, got {im.width}x{im.height}')
    data = im.tobytes()                       # W*H palette indices, row-major
    if len(data) != OUT_W * OUT_H:
        sys.exit(f'{path}: unexpected raw size {len(data)} (want {OUT_W * OUT_H})')
    return data, im.getpalette()


def make_pwad(lump_name, data):
    """A minimal PWAD holding one lump."""
    hdr = b'PWAD' + struct.pack('<II', 1, 12 + len(data))
    diren = struct.pack('<II', 12, len(data)) + lump_name.encode('latin1')[:8].ljust(8, b'\0')
    return hdr + data + diren


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stbar_png')
    ap.add_argument('out_wad')
    ap.add_argument('--png', default=None)
    a = ap.parse_args()

    img, pal = read_bar_png(a.stbar_png)

    open(a.out_wad, 'wb').write(make_pwad(LUMP, img))
    print(f'HUD: {a.stbar_png} -> lump {LUMP} {len(img)}B ({OUT_W}x{OUT_H}) -> {a.out_wad}')

    if a.png:
        try:
            from PIL import Image
        except ImportError:
            print('  (PIL not available, skipping PNG)')
            return
        im = Image.frombytes('P', (OUT_W, OUT_H), img)
        if pal:
            im.putpalette(pal)
        im.convert('RGB').resize((OUT_W * 2, OUT_H * 2), Image.NEAREST).save(a.png)
        print(f'  preview -> {a.png}')


if __name__ == '__main__':
    main()
