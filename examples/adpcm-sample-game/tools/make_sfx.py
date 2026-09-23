#!/usr/bin/env python3
"""Create a short 8 kHz KING ADPCM coin pickup using Doom's local encoder."""
import math
import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "vendor/doompcfx/tools"))
from gen_pcfx_sfx import encode_adpcm


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: make_sfx.py output.adp meta.h")
    rate = 8000
    count = int(rate * 0.42)
    samples = []
    for n in range(count):
        t = n / rate
        freq = 500.0 + 850.0 * (t / 0.42)
        envelope = max(0.0, 1.0 - t / 0.42) ** 1.6
        sample = int(math.sin(2.0 * math.pi * freq * t) * 10000.0 * envelope)
        samples.append(sample)
    encoded = encode_adpcm(samples)
    actual_bytes = len(encoded)
    padded = encoded + bytes((-len(encoded)) % 2048)
    os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
    with open(sys.argv[1], "wb") as f:
        f.write(padded)
    with open(sys.argv[2], "w", encoding="ascii") as f:
        f.write("#ifndef SFX_META_H\n#define SFX_META_H\n")
        f.write("#define SFX_WORDS %du\n" % (actual_bytes // 2))
        f.write("#define SFX_BYTES_PADDED %du\n#endif\n" % len(padded))
    print("wrote %d-byte, 8 kHz one-shot ADPCM sample" % actual_bytes)


if __name__ == "__main__":
    main()
