#!/usr/bin/env python3
"""Fit the reference picture to 256x240 and pack a KING BG0 still."""
import os
import sys
from PIL import Image, ImageOps

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "PCFX_Skills/pcfx-yuv-palette"))
from rgb_to_yuv import rgb_to_yuv

W, H = 256, 240


def yuv888(r, g, b):
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    u = round(128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b)
    v = round(128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b)
    return tuple(max(0, min(255, c)) for c in (y, u, v))


def quantize(im, ncolors):
    q = im.quantize(colors=ncolors, method=Image.Quantize.MEDIANCUT,
                    dither=Image.Dither.FLOYDSTEINBERG)
    indices = list(q.getdata())
    pal = q.getpalette() or []
    colors = []
    for i in range(ncolors):
        c = pal[i * 3:i * 3 + 3]
        colors.append(tuple(c) if len(c) == 3 else (0, 0, 0))
    return indices, colors


def write_words(path, words):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        for word in words:
            f.write(int(word).to_bytes(2, "little"))


def pack(mode, image, out, header):
    words = []
    palette = []
    if mode == "4bpp":
        idx, colors = quantize(image, 15)
        indexed = [i + 1 for i in idx]
        palette = [rgb_to_yuv(0, 0, 0)] + [rgb_to_yuv(*c) for c in colors]
        for y in range(H):
            row = indexed[y * W:(y + 1) * W]
            for x in range(0, W, 4):
                words.append((row[x] << 12) | (row[x + 1] << 8) |
                             (row[x + 2] << 4) | row[x + 3])
    elif mode == "8bpp":
        idx, colors = quantize(image, 255)
        indexed = [i + 1 for i in idx]
        palette = [rgb_to_yuv(0, 0, 0)] + [rgb_to_yuv(*c) for c in colors]
        for y in range(H):
            row = indexed[y * W:(y + 1) * W]
            for x in range(0, W, 2):
                words.append((row[x] << 8) | row[x + 1])
    elif mode == "hicolor":
        for r, g, b in image.getdata():
            words.append(rgb_to_yuv(r, g, b))
    elif mode == "16m":
        rgb = list(image.getdata())
        for y in range(H):
            row = rgb[y * W:(y + 1) * W]
            for x in range(0, W, 2):
                y0, _, _ = yuv888(*row[x])
                y1, _, _ = yuv888(*row[x + 1])
                # HuC6272's 16M emulator layout: Y0:Y1, followed by shared U:V.
                u0, v0 = yuv888(*row[x]) [1:]
                u1, v1 = yuv888(*row[x + 1])[1:]
                u = (u0 + u1 + 1) // 2
                v = (v0 + v1 + 1) // 2
                words.extend(((max(y0, 1) << 8) | max(y1, 1), (u << 8) | v))
    else:
        raise SystemExit("unknown image mode: " + mode)

    write_words(out, words)
    with open(header, "w", encoding="ascii") as f:
        f.write("#ifndef STILL_META_H\n#define STILL_META_H\n")
        f.write("#define STILL_WORDS %du\n" % len(words))
        f.write("#define STILL_BYTES %du\n" % (len(words) * 2))
        f.write("#define STILL_MODE_4BPP %d\n" % (mode == "4bpp"))
        f.write("#define STILL_MODE_8BPP %d\n" % (mode == "8bpp"))
        f.write("#define STILL_MODE_HICOLOR %d\n" % (mode == "hicolor"))
        f.write("#define STILL_MODE_16M %d\n" % (mode == "16m"))
        if palette:
            f.write("static const unsigned short still_palette[%d] = {\n" % len(palette))
            for i in range(0, len(palette), 8):
                f.write("  " + ", ".join("0x%04Xu" % c for c in palette[i:i + 8]) + ",\n")
            f.write("};\n")
        f.write("#endif\n")


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: pack_still.py MODE source.png output.bin meta.h")
    mode = sys.argv[1]
    if mode not in ("4bpp", "8bpp", "hicolor", "16m"):
        raise SystemExit("MODE must be 4bpp, 8bpp, hicolor, or 16m")
    image = ImageOps.fit(Image.open(sys.argv[2]).convert("RGB"), (W, H),
                         method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    pack(mode, image, sys.argv[3], sys.argv[4])
    print("packed 256x240 %s KING still (%d bytes)" % (mode, os.path.getsize(sys.argv[3])))


if __name__ == "__main__":
    main()
