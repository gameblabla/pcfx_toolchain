#!/usr/bin/env python3
"""Generate a 40-second procedural tune encoded for KING's 8 kHz ADPCM."""
import math
import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, os.path.join(root, "vendor/doompcfx/tools"))
from gen_pcfx_sfx import encode_adpcm

RATE = 8000
SECONDS = 40
CHUNK_BYTES = 16384
SCALE = [0, 2, 4, 7, 9, 7, 4, 2]
ROOT_HZ = 220.0


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: make_theme.py output.adp meta.h")
    samples = []
    step_samples = RATE // 4
    for n in range(RATE * SECONDS):
        step = n // step_samples
        semitone = SCALE[step % len(SCALE)]
        octave = 2 if (step // len(SCALE)) & 1 else 1
        freq = ROOT_HZ * (2.0 ** ((semitone + 12 * (octave - 1)) / 12.0))
        local = (n % step_samples) / step_samples
        envelope = min(1.0, local * 12.0) * (0.78 + 0.22 * math.cos(local * math.pi))
        melody = math.sin(2.0 * math.pi * freq * n / RATE)
        bass = math.sin(2.0 * math.pi * (ROOT_HZ / 2.0) * n / RATE)
        samples.append(int((melody * 0.72 + bass * 0.22) * 8000.0 * envelope))

    encoded = encode_adpcm(samples)
    padded_size = ((len(encoded) + CHUNK_BYTES - 1) // CHUNK_BYTES) * CHUNK_BYTES
    data = encoded + bytes(padded_size - len(encoded))
    os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
    with open(sys.argv[1], "wb") as f:
        f.write(data)
    with open(sys.argv[2], "w", encoding="ascii") as f:
        f.write("#ifndef THEME_META_H\n#define THEME_META_H\n")
        f.write("#define THEME_BYTES %du\n" % len(data))
        f.write("#define THEME_SECTORS %du\n#endif\n" % (len(data) // 2048))
    print("wrote %d-byte (%.1f sec) streaming ADPCM track" % (len(data), SECONDS))


if __name__ == "__main__":
    main()
