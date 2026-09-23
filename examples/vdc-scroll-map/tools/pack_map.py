#!/usr/bin/env python3
"""Make 8x8 VDC tiles and the source-column index for map_test's PNG map."""
import os
import sys
from PIL import Image

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "PCFX_Skills/pcfx-yuv-palette"))
from rgb_to_yuv import rgb_to_yuv

TILE_WORDS = 16


def pack_tile(tile):
    words = []
    for plane_pair in (0, 2):
        for y in range(8):
            word = 0
            for x in range(8):
                index = tile[y * 8 + x]
                for p in (plane_pair, plane_pair + 1):
                    if (index >> p) & 1:
                        word |= 1 << ((p - plane_pair) * 8 + (7 - x))
            words.append(word)
    return words


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: pack_map.py map.png patterns.bin cells.bin meta.h")
    im = Image.open(sys.argv[1]).convert("RGB")
    if im.size != (4112, 192):
        raise SystemExit("expected map_test's 4112x192 (514x24 8x8-cell) preview")
    colors = sorted(set(im.getdata()), key=lambda c: (c[0] + c[1] + c[2], c))
    if len(colors) > 15:
        raise SystemExit("map needs more than one 16-colour VDC group")
    color_index = {c: i + 1 for i, c in enumerate(colors)}
    px = [color_index[im.getpixel((x, y))] for y in range(192) for x in range(4112)]

    blank = bytes(64)
    tile_by_data = {blank: 0}
    tiles = [blank]
    cells = bytearray()
    for ty in range(24):
        for tx in range(514):
            tile = bytearray()
            for y in range(8):
                start = (ty * 8 + y) * 4112 + tx * 8
                tile.extend(px[start:start + 8])
            key = bytes(tile)
            tid = tile_by_data.get(key)
            if tid is None:
                tid = len(tiles)
                tile_by_data[key] = tid
                tiles.append(key)
            cells.append(tid)

    patterns = []
    for tile in tiles:
        patterns.extend(pack_tile(tile))
    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)
    with open(sys.argv[2], "wb") as f:
        for word in patterns:
            f.write(word.to_bytes(2, "little"))
    with open(sys.argv[3], "wb") as f:
        f.write(cells)

    palette = [rgb_to_yuv(0, 0, 0)] + [rgb_to_yuv(*c) for c in colors]
    with open(sys.argv[4], "w", encoding="ascii") as f:
        f.write("#ifndef MAP_META_H\n#define MAP_META_H\n")
        f.write("#define MAP_SOURCE_COLS 514u\n#define MAP_SOURCE_ROWS 24u\n")
        f.write("#define MAP_UNIQUE_TILES %du\n" % len(tiles))
        f.write("extern const unsigned short map_tile_patterns[];\n")
        f.write("extern const unsigned char map_cell_ids[];\n")
        f.write("static const unsigned short map_palette[16] = {\n")
        f.write("  " + ", ".join("0x%04Xu" % c for c in palette) + "\n};\n#endif\n")
    print("packed %d unique 8x8 tiles from the 514x24 scrolling map" % len(tiles))


if __name__ == "__main__":
    main()
