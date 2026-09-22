#!/usr/bin/env python3
"""pcfx_sum32.py -- the build side of the CD asset integrity check.

Imperfect CD burns hand the runtime data that READS FINE (good SCSI status) but is
wrong -- the reported symptom was garbled enemy sprites on real hardware. So every
CD-streamed asset carries a 32-bit checksum computed here, and every on-disc region
is written TWICE (see bake_wad.py / gen_pcfx_packs.py); the runtime verifies each
read and re-reads the duplicate copy when the check fails (src/w_wad.c).

The check is WORD-wise, not a byte-wise CRC32, because the V810 pays for every byte:
a level load verifies ~500 KB, which is ~40 ms this way and ~0.5 s as a table CRC32.
Corruption from a bad burn is gross (dropped/repeated sectors, open-bus fill), and
this catches any single differing word, plus any length change (the length seeds it).

Keep this bit-identical to pcfx_sum32() in platform/pcfx_sum32.h.
"""

M32 = 0xffffffff


def sum32(b):
    """32-bit checksum of `b`, read as a little-endian word stream."""
    n = len(b)
    h = (0x811c9dc5 ^ n) & M32
    nw = n >> 2
    for i in range(nw):
        v = int.from_bytes(b[i * 4:i * 4 + 4], 'little')
        h ^= v
        h = ((h << 5) | (h >> 27)) & M32
        h = (h + v) & M32
    tail = n & 3
    if tail:
        v = int.from_bytes(bytes(b[n - tail:]) + b'\x00' * (4 - tail), 'little')
        h ^= v
        h = ((h << 5) | (h >> 27)) & M32
        h = (h + v) & M32
    # Final avalanche: one multiply per REGION (not per word), so the cheap per-word
    # mixing above still spreads a single-bit difference across the whole result.
    h ^= h >> 15
    h = (h * 0x2545f491) & M32
    h ^= h >> 17
    return h
