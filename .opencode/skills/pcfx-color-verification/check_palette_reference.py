#!/usr/bin/env python3
"""Verify on-screen colour against the palette you *think* you wrote.

This closes the loop pcfx-yuv-palette and pcfx-vision-assets both leave open: baking
a palette correctly and looking at a screenshot are not the same as proving the two
agree. A vision model cannot catch a wrong colour-format assumption (see
pcfx-vision-assets §3 -- "YUV conversion errors are exactly the subtle kind it
misses"), but a numeric decode can, deterministically.

The concrete failure this exists for: an agent assumes the 16-bit palette word is
RGB332 (or RGB555/RGB444) instead of the HuC6261's actual Y8U4V4, and every colour
comes out "plausible but wrong" -- e.g. a guessed 0x8030 renders pure green instead of
blue. A vision model calls that "looks fine" or invents an unrelated complaint. This
script instead decodes the palette word FOUR ways (the real hardware way, plus the
three wrong ways an agent commonly assumes) and reports which decode the actual pixel
matches -- so a colour-format bug names itself instead of hiding as "muddy colours".

Usage:
    # Sample specific screenshot pixels against the palette words you wrote:
    python3 check_palette_reference.py shot.png \\
        --sample 10,10=0x506F 40,10=0x9730 --tolerance 12

    # Or from a CSV of "x,y,word" (one sample per line, '#' comments allowed):
    python3 check_palette_reference.py shot.png --samples-file samples.csv

    # Compare a whole screenshot to a known-good reference (exact pixel diff,
    # same idea as PCFX_Skills/eval/repo-cases/verify_reference.py):
    python3 check_palette_reference.py shot.png --reference known_good.png
"""
import argparse
import csv
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Needs Pillow: pip install pillow")


def yuv_word_to_rgb(word):
    """The real HuC6261 reconstruction. Bit-identical to rgb_to_yuv.py."""
    y = (word >> 8) & 0xFF
    u = (((word >> 4) & 0xF) << 4) - 128
    v = ((word & 0xF) << 4) - 128
    r = y + (1167 * v) // 1024
    g = y + (-404 * u - 594 * v) // 1024
    b = y + (2081 * u - v) // 1024
    clamp = lambda c: 0 if c < 0 else (255 if c > 255 else c)
    return clamp(r), clamp(g), clamp(b)


def wrong_decodes(word):
    """The wrong colour-format guesses seen in the wild for a 16-bit palette
    word. None of these are what the PC-FX does -- they exist so a mismatch can
    be *named* instead of left as "colours look off"."""
    out = {}

    # RGB332 packed into the low byte (a common wrong guess: "8-bit palette
    # entry, must be RGB332"). Two placements are both plausible misreadings.
    lo = word & 0xFF
    r3 = (lo >> 5) & 0x7
    g3 = (lo >> 2) & 0x7
    b2 = lo & 0x3
    out["RGB332 (low byte)"] = (r3 * 255 // 7, g3 * 255 // 7, b2 * 255 // 3)

    hi = (word >> 8) & 0xFF
    r3h = (hi >> 5) & 0x7
    g3h = (hi >> 2) & 0x7
    b2h = hi & 0x3
    out["RGB332 (high byte)"] = (r3h * 255 // 7, g3h * 255 // 7, b2h * 255 // 3)

    # RGB555 / RGB565 across the full 16-bit word.
    r5 = (word >> 11) & 0x1F
    g6 = (word >> 5) & 0x3F
    b5 = word & 0x1F
    out["RGB565"] = (r5 * 255 // 31, g6 * 255 // 63, b5 * 255 // 31)

    r5b = (word >> 10) & 0x1F
    g5b = (word >> 5) & 0x1F
    b5b = word & 0x1F
    out["RGB555"] = (r5b * 255 // 31, g5b * 255 // 31, b5b * 255 // 31)

    # RGB444 in the low 12 bits (another seen-in-the-wild guess).
    r4 = (word >> 8) & 0xF
    g4 = (word >> 4) & 0xF
    b4 = word & 0xF
    out["RGB444"] = (r4 * 255 // 15, g4 * 255 // 15, b4 * 255 // 15)

    return out


def closest(rgb, candidates):
    def dist2(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))
    return min(candidates.items(), key=lambda kv: dist2(rgb, kv[1]))


def check_sample(img, x, y, word, tolerance):
    actual = img.getpixel((x, y))[:3]
    expected = yuv_word_to_rgb(word)
    err = sum((a - e) ** 2 for a, e in zip(actual, expected)) ** 0.5
    ok = err <= tolerance

    result = {
        "x": x, "y": y, "word": word,
        "actual": actual, "expected_yuv": expected,
        "error": round(err, 1), "ok": ok,
    }

    if not ok:
        candidates = dict(wrong_decodes(word))
        candidates["Y8U4V4 (correct)"] = expected
        name, rgb = closest(actual, candidates)
        result["closest_decode"] = name
        result["closest_decode_rgb"] = rgb

    return result


def parse_sample_arg(s):
    coord, word = s.split("=")
    x, y = (int(v) for v in coord.split(","))
    return x, y, int(word, 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("screenshot")
    ap.add_argument("--sample", action="append", default=[],
                    help="x,y=word (hex or decimal), repeatable")
    ap.add_argument("--samples-file", help="CSV: x,y,word per line")
    ap.add_argument("--reference", help="known-good screenshot for a full pixel diff")
    ap.add_argument("--tolerance", type=float, default=10.0,
                    help="max Euclidean RGB error before flagging a mismatch (default 10)")
    a = ap.parse_args()

    img = Image.open(a.screenshot).convert("RGB")

    if a.reference:
        ref = Image.open(a.reference).convert("RGB")
        if img.size != ref.size:
            print(f"SIZE MISMATCH: {a.screenshot} is {img.size}, "
                  f"{a.reference} is {ref.size}")
            sys.exit(1)
        pa, pb = img.load(), ref.load()
        w, h = img.size
        diffs = sum(1 for yy in range(h) for xx in range(w) if pa[xx, yy] != pb[xx, yy])
        total = img.size[0] * img.size[1]
        print(f"{diffs}/{total} pixels differ from reference "
              f"({100.0 * diffs / total:.2f}%)")
        sys.exit(0 if diffs == 0 else 1)

    samples = [parse_sample_arg(s) for s in a.sample]
    if a.samples_file:
        with open(a.samples_file) as f:
            for row in csv.reader(f):
                if not row or row[0].strip().startswith("#"):
                    continue
                x, y, word = row[:3]
                samples.append((int(x), int(y), int(word, 0)))

    if not samples:
        sys.exit("Give --sample x,y=word (repeatable), --samples-file, or --reference.")

    failed = False
    for x, y, word in samples:
        r = check_sample(img, x, y, word, a.tolerance)
        if r["ok"]:
            print(f"OK   ({x:3d},{y:3d}) word=0x{word:04X} "
                  f"expected={r['expected_yuv']} actual={r['actual']} "
                  f"err={r['error']}")
        else:
            failed = True
            print(f"FAIL ({x:3d},{y:3d}) word=0x{word:04X} "
                  f"expected(YUV)={r['expected_yuv']} actual={r['actual']} "
                  f"err={r['error']}")
            print(f"     closest match: {r['closest_decode']} "
                  f"-> {r['closest_decode_rgb']}")
            if r["closest_decode"] != "Y8U4V4 (correct)":
                print(f"     *** on-screen colour matches a {r['closest_decode']} "
                      f"decode, not Y8U4V4. The palette word is very likely being "
                      f"interpreted with the wrong colour format somewhere in the "
                      f"pipeline (art bake, palette upload, or emulator/backend "
                      f"decode). See pcfx-yuv-palette.")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
