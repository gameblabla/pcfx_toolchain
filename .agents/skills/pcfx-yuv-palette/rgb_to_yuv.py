#!/usr/bin/env python3
"""RGB888 -> PC-FX HuC6261 Y8U4V4 palette word, and back.

This is the converter used by doom-pcfx / wolf-pcfx. Keep it bit-exact if you
regenerate baked palettes, or colours will drift between tools and runtime.

    python3 rgb_to_yuv.py 255 0 0        -> one colour
    python3 rgb_to_yuv.py --table        -> a ready-to-paste 16-colour palette
"""
import sys


def yuv_to_rgb(word):
    """Exactly the reconstruction the hardware performs."""
    y = (word >> 8) & 0xFF
    u = (((word >> 4) & 0xF) << 4) - 128
    v = ((word & 0xF) << 4) - 128
    r = y + (1167 * v) // 1024
    g = y + (-404 * u - 594 * v) // 1024
    b = y + (2081 * u - v) // 1024
    clamp = lambda c: 0 if c < 0 else (255 if c > 255 else c)
    return clamp(r), clamp(g), clamp(b)


def rgb_to_yuv(r, g, b):
    """Closest-representable Y8U4V4, seeded analytically then refined in a
    +/-3 window. `forbid_grey` stops saturated-but-dark colours collapsing to
    neutral grey, which is the single most common colour-quality complaint."""
    y0 = (77 * r + 150 * g + 29 * b) >> 8
    u4c = 8 + (b - y0) // 32
    v4c = 8 + (r - y0) // 18
    u4lo, u4hi = max(0, u4c - 3), min(15, u4c + 3)
    v4lo, v4hi = max(0, v4c - 3), min(15, v4c + 3)

    forbid_grey = (max(r, g, b) - min(r, g, b)) >= 8

    best_err, best = 1 << 30, (1, 8, 8)
    for u4 in range(u4lo, u4hi + 1):
        u = (u4 << 4) - 128
        for v4 in range(v4lo, v4hi + 1):
            if forbid_grey and u4 == 8 and v4 == 8:
                continue
            v = (v4 << 4) - 128
            ro = (1167 * v) // 1024
            go = (-404 * u - 594 * v) // 1024
            bo = (2081 * u - v) // 1024
            # Best Y for this chroma, then score with a green-weighted metric
            # (the eye is most sensitive to green error).
            ysum = (r - ro) + (g - go) + (b - bo)
            for y in range(max(1, ysum // 3 - 2), min(256, ysum // 3 + 3)):
                dr, dg, db = (y + ro) - r, (y + go) - g, (y + bo) - b
                err = 2 * dr * dr + 4 * dg * dg + db * db
                if err < best_err:
                    best_err, best = err, (y, u4, v4)
    y, u4, v4 = best
    return (y << 8) | (u4 << 4) | v4


if __name__ == "__main__":
    if "--table" in sys.argv:
        pal = [
            ("black",       0,   0,   0),
            ("dark grey",  64,  64,  64),
            ("grey",      128, 128, 128),
            ("light grey",192, 192, 192),
            ("white",     255, 255, 255),
            ("red",       255,   0,   0),
            ("dark red",  128,   0,   0),
            ("green",       0, 255,   0),
            ("dark green",  0, 128,   0),
            ("blue",        0,   0, 255),
            ("light blue",100, 160, 255),
            ("yellow",    255, 255,   0),
            ("orange",    255, 140,   0),
            ("magenta",   255,   0, 255),
            ("cyan",        0, 255, 255),
            ("brown",     140,  90,  40),
        ]
        for i, (name, r, g, b) in enumerate(pal):
            w = rgb_to_yuv(r, g, b)
            rr, gg, bb = yuv_to_rgb(w)
            print("    tetsu_set_palette(%2d, 0x%04X);  /* %-10s "
                  "rgb(%3d,%3d,%3d) -> (%3d,%3d,%3d) */"
                  % (i, w, name, r, g, b, rr, gg, bb))
    else:
        r, g, b = (int(x) for x in sys.argv[1:4])
        w = rgb_to_yuv(r, g, b)
        print("0x%04X  (reconstructs to %s)" % (w, yuv_to_rgb(w)))
