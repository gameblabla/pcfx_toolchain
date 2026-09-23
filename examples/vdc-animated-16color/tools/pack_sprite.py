#!/usr/bin/env python3
"""Quantize the supplied 24x34 RGBA animation and pack VDC 16x16 cells."""
import os
import sys
from PIL import Image

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "PCFX_Skills/pcfx-yuv-palette"))
from rgb_to_yuv import rgb_to_yuv


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: pack_sprite.py sheet.png patterns.bin meta.h")
    sheet = Image.open(sys.argv[1]).convert("RGBA")
    if sheet.size != (24, 374) or sheet.height % 34:
        raise SystemExit("expected the supplied 24x34, eleven-frame strip")

    opaque = [(r, g, b) for r, g, b, a in sheet.getdata() if a >= 128]
    quant_input = Image.new("RGB", (len(opaque), 1))
    quant_input.putdata(opaque)
    quantized = quant_input.quantize(colors=15, method=Image.Quantize.MEDIANCUT,
                                     dither=Image.Dither.NONE)
    qpixels = list(quantized.getdata())
    qpalette = quantized.getpalette() or []
    colors = []
    for i in range(15):
        p = qpalette[i * 3:i * 3 + 3]
        if len(p) < 3:
            p = [0, 0, 0]
        colors.append(tuple(p))

    indexed = [[0] * 24 for _ in range(374)]
    q = 0
    for y in range(374):
        for x in range(24):
            r, g, b, a = sheet.getpixel((x, y))
            if a >= 128:
                indexed[y][x] = qpixels[q] + 1
                q += 1

    words = []
    for frame in range(11):
        top = frame * 34
        for cell_y in range(3):
            for cell_x in range(2):
                for plane in range(4):
                    for row in range(16):
                        value = 0
                        for x in range(16):
                            px = cell_x * 16 + x
                            py = top + cell_y * 16 + row
                            index = indexed[py][px] if px < 24 and py < 374 else 0
                            if (index >> plane) & 1:
                                value |= 1 << (15 - x)
                        words.append(value)

    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)
    with open(sys.argv[2], "wb") as f:
        for value in words:
            f.write(value.to_bytes(2, "little"))
    palette = [rgb_to_yuv(0, 0, 0)] + [rgb_to_yuv(*c) for c in colors]
    with open(sys.argv[3], "w", encoding="ascii") as f:
        f.write("#ifndef SPRITE16_META_H\n#define SPRITE16_META_H\n")
        f.write("#define SPRITE16_FRAME_COUNT 11u\n#define SPRITE16_CELL_COUNT 6u\n")
        f.write("extern const unsigned short sprite16_patterns[];\n")
        f.write("static const unsigned short sprite16_palette[16] = {\n")
        f.write("  " + ", ".join("0x%04Xu" % c for c in palette) + "\n};\n#endif\n")
    print("packed eleven 24x34 frames as 16-colour, 16x16 VDC sprite cells")


if __name__ == "__main__":
    main()
