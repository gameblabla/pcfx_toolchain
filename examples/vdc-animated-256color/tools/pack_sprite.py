#!/usr/bin/env python3
"""Pack a transparent 24x34 strip for Doom-style paired-VDC sprite colour."""
import os
import sys
from PIL import Image

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "PCFX_Skills/pcfx-yuv-palette"))
from rgb_to_yuv import rgb_to_yuv


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: pack_sprite.py sheet.png vdc0.bin vdc1.bin meta.h")
    sheet = Image.open(sys.argv[1]).convert("RGBA")
    if sheet.size != (24, 374):
        raise SystemExit("expected the supplied 24x34, eleven-frame strip")
    opaque = [(r, g, b) for r, g, b, a in sheet.getdata() if a >= 128]
    quant_input = Image.new("RGB", (len(opaque), 1))
    quant_input.putdata(opaque)
    qimage = quant_input.quantize(colors=240, method=Image.Quantize.MEDIANCUT,
                                  dither=Image.Dither.NONE)
    qpixels = list(qimage.getdata())
    rgbpal = qimage.getpalette() or []
    safe = [i for i in range(1, 256) if (i & 15) != 0]
    palette = [rgb_to_yuv(0, 0, 0)] * 256
    for i in range(240):
        c = rgbpal[i * 3:i * 3 + 3]
        if len(c) == 3:
            palette[safe[i]] = rgb_to_yuv(*c)

    indexed = [[0] * 24 for _ in range(374)]
    q = 0
    for y in range(374):
        for x in range(24):
            r, g, b, a = sheet.getpixel((x, y))
            if a >= 128:
                indexed[y][x] = safe[qpixels[q]]
                q += 1

    planes = [[], []]
    for frame in range(11):
        top = frame * 34
        for cell_y in range(3):
            for cell_x in range(2):
                packed = [[], []]
                for chip in (0, 1):
                    for plane in range(4):
                        for row in range(16):
                            value = 0
                            for x in range(16):
                                px = cell_x * 16 + x
                                py = top + cell_y * 16 + row
                                index = indexed[py][px] if px < 24 and py < 374 else 0
                                nibble = (index >> 4) & 15 if chip == 0 else index & 15
                                if (nibble >> plane) & 1:
                                    value |= 1 << (15 - x)
                            packed[chip].append(value)
                planes[0].extend(packed[0])
                planes[1].extend(packed[1])

    for path, words in zip(sys.argv[2:4], planes):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            for value in words:
                f.write(value.to_bytes(2, "little"))
    with open(sys.argv[4], "w", encoding="ascii") as f:
        f.write("#ifndef SPRITE256_META_H\n#define SPRITE256_META_H\n")
        f.write("#define SPRITE256_FRAME_COUNT 11u\n#define SPRITE256_CELL_COUNT 6u\n")
        f.write("extern const unsigned short sprite256_vdc0_patterns[];\n")
        f.write("extern const unsigned short sprite256_vdc1_patterns[];\n")
        f.write("static const unsigned short sprite256_palette[256] = {\n")
        for i in range(0, 256, 8):
            f.write("  " + ", ".join("0x%04Xu" % c for c in palette[i:i + 8]) + ",\n")
        f.write("};\n#endif\n")
    print("packed eleven 24x34 frames into paired VDC nibble planes")


if __name__ == "__main__":
    main()
