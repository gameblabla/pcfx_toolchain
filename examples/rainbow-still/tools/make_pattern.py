#!/usr/bin/env python3
"""Write a 256x240 RAINBOW test card: colour bars, ramps, a grid and markers.

The left and right halves differ on purpose so a horizontal pan is visible in
two screenshots, and the black band exercises null-run encoding.
"""
import sys

from PIL import Image, ImageDraw


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'pattern.png'
    img = Image.new('RGB', (256, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    bars = [(235, 235, 235), (235, 235, 16), (16, 235, 235), (16, 235, 16),
            (235, 16, 235), (235, 16, 16), (16, 16, 235), (16, 16, 16)]
    for i, c in enumerate(bars):
        d.rectangle([i * 32, 0, i * 32 + 31, 95], fill=c)
    for x in range(256):
        d.line([x, 96, x, 127], fill=(x, x, x))
        d.line([x, 128, x, 143], fill=(x, 0, 255 - x))
    d.rectangle([0, 144, 255, 175], fill=(0, 0, 0))  # null-run band
    for x in range(0, 256, 32):
        d.line([x, 176, x, 239], fill=(90, 90, 90))
    for y in range(176, 240, 16):
        d.line([0, y, 255, y], fill=(90, 90, 90))
    d.ellipse([20, 184, 76, 236], outline=(255, 255, 0), width=4)
    d.polygon([(180, 236), (236, 236), (208, 184)], outline=(0, 255, 255), fill=(200, 40, 40))
    d.text((96, 150), 'RAINBOW', fill=(255, 255, 255))
    d.text((92, 200), 'HuC6271', fill=(255, 200, 0))
    img.save(out)


if __name__ == '__main__':
    main()
