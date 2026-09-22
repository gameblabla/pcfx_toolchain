#!/usr/bin/env python3
"""Encode 256x240 PNG backgrounds into PC-FX RAINBOW YUV/DCT streams."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


ZIGZAG = [
    0, 1, 8, 16, 9, 2, 3, 10,
    17, 24, 32, 25, 18, 11, 4, 5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13, 6, 7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
]

# MPCONV2 base tables (data offsets 0x0902 / 0x0942), in natural order.
# Send these unchanged; DC-Y controls 0x10..0x1F select the working scale.
LUMA_Q_BASE = [
      4,   3,   4,   5,   6,   6,   7,   7,
      3,   3,   4,   5,   6,   7,   7,  35,
      4,   4,   5,   5,   6,   7,  11,  59,
      4,   4,   5,   6,   7,  11,  23, 254,
      5,   5,   6,   7,  11,  35,  67, 254,
      5,   5,   6,   7,  27,  55, 254, 254,
      6,   6,   7,  11,  59,  75, 254, 254,
      7,   7,  11,  63, 119, 254, 254, 254,
]

CHROMA_Q_BASE = [
     12,   4,   5,   7,  19, 131, 254, 254,
      4,   4,   5,   7,  27, 254, 254, 254,
      4,   5,   7,  11,  99, 254, 254, 254,
      5,   6,   7,  19, 131, 254, 254, 254,
      7,   7,  11,  99, 254, 254, 254, 254,
      7,  11,  67, 254, 254, 254, 254, 254,
     11,  99, 254, 254, 254, 254, 254, 254,
    254, 254, 254, 254, 254, 254, 254, 254,
]

# Baseline JPEG tables kept here for reference while comparing against the
# RAINBOW decoder. The generated stream below uses the HuC6271 tables.
DC_LUMA_BITS = [0, 0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
DC_LUMA_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
DC_CHROMA_BITS = [0, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
DC_CHROMA_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
AC_LUMA_BITS = [0, 0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d]
AC_LUMA_VALS = [
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
    0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
    0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08,
    0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
    0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16,
    0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
    0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
    0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
    0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
    0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
    0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
    0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
    0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
    0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4,
    0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
    0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea,
    0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
    0xf9, 0xfa,
]
AC_CHROMA_BITS = [0, 0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77]
AC_CHROMA_VALS = [
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
    0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
    0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
    0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
    0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34,
    0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
    0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38,
    0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
    0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
    0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
    0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
    0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96,
    0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
    0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
    0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
    0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2,
    0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
    0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9,
    0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
    0xf9, 0xfa,
]


def build_huffman(bits, vals):
    table = {}
    code = 0
    idx = 0
    for length in range(1, 17):
        for _ in range(bits[length]):
            table[vals[idx]] = (code, length)
            code += 1
            idx += 1
        code <<= 1
    return table


def build_rainbow_huffman(base, codes, minimum, maximum):
    table = {}
    for length in range(1, 17):
        lo = minimum[length]
        hi = maximum[length]
        if hi == 0xFFFF:
            continue
        start = base[length]
        for code in range(lo, hi + 1):
            table[codes[start + code - lo]] = (code, length)
    return table


RB_DC_Y_BASE = [0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x08, 0x09, 0x00, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
RB_DC_Y_CODES = [0x00, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x01, 0x08, 0x09, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F]
RB_DC_Y_MIN = [0x0000, 0x0000, 0x0000, 0x0000, 0x000E, 0x0000, 0x003C, 0x007A, 0x0000, 0x01F0, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000]
RB_DC_Y_MAX = [0xFFFF, 0xFFFF, 0xFFFF, 0x0006, 0x000E, 0xFFFF, 0x003C, 0x007B, 0xFFFF, 0x01FF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

RB_DC_UV_BASE = [0x00, 0x00, 0x00, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
RB_DC_UV_CODES = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09]
RB_DC_UV_MIN = [0x0000, 0x0000, 0x0000, 0x0006, 0x000E, 0x001E, 0x003E, 0x007E, 0x00FE, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000]
RB_DC_UV_MAX = [0xFFFF, 0xFFFF, 0x0002, 0x0006, 0x000E, 0x001E, 0x003E, 0x007E, 0x00FF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

RB_AC_Y_BASE = [0x00, 0x00, 0x00, 0x02, 0x03, 0x05, 0x09, 0x0D, 0x00, 0x10, 0x00, 0x12, 0x22, 0x00, 0x00, 0x00, 0x00]
RB_AC_Y_CODES = [
    0x01, 0x02, 0x03, 0x04, 0x11, 0x05, 0x12, 0x21, 0x00, 0x06, 0x31, 0x41,
    0x51, 0x13, 0x22, 0x61, 0x07, 0x71, 0x09, 0x19, 0x29, 0x39, 0x49, 0x59,
    0x69, 0x79, 0x89, 0x99, 0xA9, 0xB9, 0xC9, 0xD9, 0xE9, 0xF9, 0x08, 0x14,
    0x15, 0x16, 0x17, 0x18, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x32, 0x33,
    0x34, 0x35, 0x36, 0x37, 0x38, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x62, 0x63, 0x64, 0x65, 0x66,
    0x67, 0x68, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x81, 0x82, 0x83,
    0x84, 0x85, 0x86, 0x87, 0x88, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
    0x98, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xB1, 0xB2, 0xB3,
    0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC8, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xE1, 0xE2, 0xE3,
    0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0x10,
]
RB_AC_Y_MIN = [0x0000, 0x0000, 0x0000, 0x0004, 0x000A, 0x0018, 0x0036, 0x0074, 0x0000, 0x01DC, 0x0000, 0x0778, 0x0F10, 0x0000, 0x0000, 0x0000, 0x0000]
RB_AC_Y_MAX = [0xFFFF, 0xFFFF, 0x0001, 0x0004, 0x000B, 0x001A, 0x0039, 0x0076, 0xFFFF, 0x01DD, 0xFFFF, 0x0787, 0x0F7F, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

RB_AC_UV_BASE = [0x00, 0x00, 0x00, 0x02, 0x03, 0x05, 0x0A, 0x0B, 0x00, 0x10, 0x00, 0x12, 0x22, 0x00, 0x00, 0x00, 0x00]
RB_AC_UV_CODES = [
    0x01, 0x02, 0x11, 0x03, 0x21, 0x04, 0x12, 0x31, 0x41, 0x00, 0x51, 0x05,
    0x13, 0x22, 0x61, 0x71, 0x32, 0x81, 0x09, 0x19, 0x29, 0x39, 0x49, 0x59,
    0x69, 0x79, 0x89, 0x99, 0xA9, 0xB9, 0xC9, 0xD9, 0xE9, 0xF9, 0x06, 0x07,
    0x08, 0x14, 0x15, 0x16, 0x17, 0x18, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
    0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47,
    0x48, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x62, 0x63, 0x64, 0x65,
    0x66, 0x67, 0x68, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x82, 0x83,
    0x84, 0x85, 0x86, 0x87, 0x88, 0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
    0x98, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xB1, 0xB2, 0xB3,
    0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC8, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xE1, 0xE2, 0xE3,
    0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0x10,
]
RB_AC_UV_MIN = [0x0000, 0x0000, 0x0000, 0x0004, 0x000A, 0x0018, 0x0038, 0x0072, 0x0000, 0x01DC, 0x0000, 0x0778, 0x0F10, 0x0000, 0x0000, 0x0000, 0x0000]
RB_AC_UV_MAX = [0xFFFF, 0xFFFF, 0x0001, 0x0004, 0x000B, 0x001B, 0x0038, 0x0076, 0xFFFF, 0x01DD, 0xFFFF, 0x0787, 0x0F7F, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

HUFF_DC_Y = build_rainbow_huffman(RB_DC_Y_BASE, RB_DC_Y_CODES, RB_DC_Y_MIN, RB_DC_Y_MAX)
HUFF_DC_UV = build_rainbow_huffman(RB_DC_UV_BASE, RB_DC_UV_CODES, RB_DC_UV_MIN, RB_DC_UV_MAX)
HUFF_AC_Y = build_rainbow_huffman(RB_AC_Y_BASE, RB_AC_Y_CODES, RB_AC_Y_MIN, RB_AC_Y_MAX)
HUFF_AC_UV = build_rainbow_huffman(RB_AC_UV_BASE, RB_AC_UV_CODES, RB_AC_UV_MIN, RB_AC_UV_MAX)


class BitWriter:
    def __init__(self):
        self.data = bytearray()
        self.cur = 0
        self.nbits = 0
        self.unstuffed = 0

    def write(self, code, length):
        for bit in range(length - 1, -1, -1):
            self.cur = (self.cur << 1) | ((code >> bit) & 1)
            self.nbits += 1
            if self.nbits == 8:
                self.data.append(self.cur)
                self.unstuffed += 1
                if self.cur == 0xFF:
                    self.data.append(0x00)
                self.cur = 0
                self.nbits = 0

    def finish(self):
        if self.nbits:
            self.cur <<= 8 - self.nbits
            self.data.append(self.cur)
            self.unstuffed += 1
            if self.cur == 0xFF:
                self.data.append(0x00)
            self.cur = 0
            self.nbits = 0
        return bytes(self.data), self.unstuffed


def working_qtables(scale):
    """MPCONV2 0x5014: UV DC deliberately ignores the scale multiplier."""
    if not 0 <= scale <= 15:
        raise ValueError("RAINBOW scale must be in 0..15")
    y = np.array(LUMA_Q_BASE, dtype=np.int64) * scale >> 2
    uv = np.array(CHROMA_Q_BASE, dtype=np.int64) * scale >> 2
    uv[0] = CHROMA_Q_BASE[0] >> 2
    return (np.clip(y, 1, 254).reshape(8, 8),
            np.clip(uv, 1, 254).reshape(8, 8))


def pcfx_yuv(rgb):
    """MPCONV2 0x3D29: round/clip to bytes before chroma reduction."""
    r, g, b = np.asarray(rgb, dtype=np.int64).transpose(2, 0, 1)
    y = (4898 * r + 9617 * g + 1867 * b + 8192) >> 14
    u = -2762 * r - 5424 * g + 8187 * b
    v = 8188 * r - 6856 * g - 1332 * b
    u = ((u + np.where(u < 0, -8192, 8192)) >> 14) + 128
    v = ((v + np.where(v < 0, -8192, 8192)) >> 14) + 128
    return np.clip(np.stack([y, u, v], axis=2), 0, 255).astype(np.uint8)


def category(value):
    size = abs(int(value)).bit_length()
    if size > 9:
        raise ValueError(f"coefficient {value} exceeds RAINBOW category 9")
    return size


def signed_bits(value, size):
    if size == 0:
        return 0
    if value >= 0:
        return value
    return value - 1 + (1 << size)


def _fdct_pass(samples, first):
    x = [int(v) for v in samples]
    a0, a1, a2, a3 = (x[i] + x[7 - i] for i in range(4))
    b0, b1, b2, b3 = (x[i] - x[7 - i] for i in range(4))
    e0, e1, e2, e3 = a0 + a3, a0 - a3, a1 + a2, a1 - a2
    out = [0] * 8
    if first:
        out[0] = (((e0 + e2) << 4) + 1) >> 1
        out[4] = (((e0 - e2) << 4) + 1) >> 1
    else:
        out[0] = (e0 + e2 + 0x80) >> 8
        out[4] = (e0 - e2 + 0x80) >> 8
    sums = {
        2: e1 * 0x14E8 + e3 * 0x08A9,
        6: e1 * 0x08A9 - e3 * 0x14E8,
        1: b0 * 0x1631 + b1 * 0x12D0 + b2 * 0x0C92 + b3 * 0x046A,
        3: b0 * 0x12D0 - b1 * 0x046A - b2 * 0x1631 - b3 * 0x0C92,
        5: b0 * 0x0C92 - b1 * 0x1631 + b2 * 0x046A + b3 * 0x12D0,
        # The first-pass 0x15F2 asymmetry is present in the executable.
        7: b0 * 0x046A - b1 * 0x0C92 + b2 * 0x12D0
           - b3 * (0x15F2 if first else 0x1631),
    }
    for i, value in sums.items():
        if first:
            out[i] = (value + 0x100) >> 9
        else:
            value = (value + 0x80000) >> 16
            value = ((value + 0x8000) & 0xFFFF) - 0x8000
            out[i] = value >> 4
    return out


def mpconv_fdct(centered):
    """MPCONV2 0x4A18: columns then rows; a flat d produces DC = 2*d."""
    centered = np.asarray(centered, dtype=np.int64).reshape(8, 8)
    tmp = np.empty((8, 8), dtype=np.int64)
    for col in range(8):
        tmp[:, col] = _fdct_pass(centered[:, col], True)
    return np.array([_fdct_pass(row, False) for row in tmp], dtype=np.int64)


def quantized_block(block, qtable):
    coeff = mpconv_fdct(np.asarray(block, dtype=np.int64) - 128)
    # Signed half-step bias followed by division truncating toward zero.
    magnitude = (np.abs(coeff) + (qtable >> 1)) // qtable
    return np.where(coeff < 0, -magnitude, magnitude).reshape(64)


def write_huff(writer, table, symbol):
    if symbol not in table:
        raise ValueError(f"unrepresentable RAINBOW Huffman symbol 0x{symbol:02X}")
    code, length = table[symbol]
    writer.write(code, length)


def encode_block(writer, coeffs, last_dc, dc_table, ac_table):
    q = np.empty(64, dtype=np.int32)
    for i, src in enumerate(ZIGZAG):
        q[i] = coeffs[src]

    dc = int(q[0])
    diff = dc - last_dc
    size = category(diff)
    write_huff(writer, dc_table, size)
    if size:
        writer.write(signed_bits(diff, size), size)

    run = 0
    for i in range(1, 64):
        ac = int(q[i])
        if ac == 0:
            run += 1
            continue
        while run > 15:
            write_huff(writer, ac_table, 0x10)
            run -= 16
        size = category(ac)
        symbol = (run << 4) | size
        write_huff(writer, ac_table, symbol)
        writer.write(signed_bits(ac, size), size)
        run = 0
    if run:
        writer.write(0x1F, 5)
    return dc


# MPCONV2 0x50D9 puts one dummy word INSIDE the declared payload.
# C6272_2 section 3.4.2(4) requires three further guard words OUTSIDE it.
BLOCK_INNER_DUMMY = b"\x00" * 2
BLOCK_GUARD = b"\x00" * 6
TRANSFER_START = 6
BLOCK_COUNT = 15


def align_entropy(entropy):
    """Complete the 0..15 zero alignment bits after BitWriter.finish()."""
    return entropy + b"\x00" if len(entropy) & 1 else entropy


def is_null_macroblock(macro):
    return (np.all(macro[:, :, 0] <= 10)
            and np.all((macro[:, :, 1:] >= 0x76) & (macro[:, :, 1:] <= 0x8A)))


def write_null_run(writer, run):
    write_huff(writer, HUFF_DC_Y, 0x0F)
    write_huff(writer, HUFF_AC_Y, ((run - 1) << 4) | 1)
    writer.write(1, 1)


def encode_frame(path, scale=0):
    """Encode a fixed MPCONV scale, finest 0 through coarsest 15.

    Each size counts physical bytes AFTER the four-byte header: first-strip
    base tables, stuffed/aligned entropy, and the two-byte inner dummy.
    The six external HuC6272 guard bytes do not contribute to that size.
    """
    img = Image.open(path).convert("RGB")
    if img.size != (256, 240):
        img = img.resize((256, 240), Image.Resampling.LANCZOS)
    yuv = pcfx_yuv(np.asarray(img, dtype=np.uint8))
    qy, qc = working_qtables(scale)
    qtables = bytes(LUMA_Q_BASE) + bytes(CHROMA_Q_BASE)
    out = bytearray()
    emitted_scale = None

    for block_y in range(0, 240, 16):
        writer = BitWriter()
        dc_y = 0
        dc_u = 0
        dc_v = 0
        null_run = 0
        for block_x in range(0, 256, 16):
            macro = yuv[block_y:block_y + 16, block_x:block_x + 16, :]
            if is_null_macroblock(macro):
                null_run += 1
                continue
            if null_run:
                write_null_run(writer, null_run)
                null_run = 0
                dc_y = dc_u = dc_v = 0
            if emitted_scale != scale:
                write_huff(writer, HUFF_DC_Y, 0x10 + scale)
                emitted_scale = scale
            yplane = macro[:, :, 0]
            for y0, x0 in ((0, 0), (8, 0), (0, 8), (8, 8)):
                coeffs = quantized_block(yplane[y0:y0 + 8, x0:x0 + 8], qy)
                dc_y = encode_block(writer, coeffs, dc_y, HUFF_DC_Y, HUFF_AC_Y)

            uplane = macro[:, :, 1].reshape(8, 2, 8, 2).sum(axis=(1, 3)) >> 2
            vplane = macro[:, :, 2].reshape(8, 2, 8, 2).sum(axis=(1, 3)) >> 2
            dc_u = encode_block(writer, quantized_block(uplane, qc), dc_u, HUFF_DC_UV, HUFF_AC_UV)
            dc_v = encode_block(writer, quantized_block(vplane, qc), dc_v, HUFF_DC_UV, HUFF_AC_UV)

        if null_run:
            write_null_run(writer, null_run)
            dc_y = dc_u = dc_v = 0

        entropy, _unstuffed_len = writer.finish()
        entropy = align_entropy(entropy)   # keep every block word-aligned
        first = block_y == 0
        tables = qtables if first else b""
        payload = tables + entropy + BLOCK_INNER_DUMMY
        size_field = len(payload)
        if size_field > 0xFFFF:
            raise ValueError(f"strip {block_y // 16}: payload exceeds 16-bit size")
        out.extend([0xFF, 0xFF if first else 0xF8,
                    (size_field >> 8) & 0xFF, size_field & 0xFF])
        out.extend(payload)
        out.extend(BLOCK_GUARD)
    return bytes(out)


def analyze_stream(stream):
    """Validate physical frame layout; return each stored strip's KRAM span."""
    spans = []
    offset = 0
    for strip in range(BLOCK_COUNT):
        marker = b"\xff\xff" if strip == 0 else b"\xff\xf8"
        if offset & 1 or stream[offset:offset + 2] != marker:
            raise ValueError(f"strip {strip}: invalid marker or word alignment")
        if offset + 4 > len(stream):
            raise ValueError(f"strip {strip}: truncated header")
        size = int.from_bytes(stream[offset + 2:offset + 4], "big")
        table_bytes = 128 if strip == 0 else 0
        end = offset + 4 + size
        if size & 1 or size < table_bytes + 4 or end + 6 > len(stream):
            raise ValueError(f"strip {strip}: invalid declared payload size")
        if strip == 0 and stream[offset + 4:offset + 132] != bytes(LUMA_Q_BASE + CHROMA_Q_BASE):
            raise ValueError("first strip: incorrect MPCONV base tables")
        if stream[end - 2:end] != BLOCK_INNER_DUMMY or stream[end:end + 6] != BLOCK_GUARD:
            raise ValueError(f"strip {strip}: missing inner dummy or external guard")
        pos = offset + 4 + table_bytes
        while pos < end - 2:
            if stream[pos] == 0xFF:
                if pos + 1 >= end - 2 or stream[pos + 1] != 0:
                    raise ValueError(f"strip {strip}: unstuffed entropy FF")
                pos += 1
            pos += 1
        spans.append(4 + size + len(BLOCK_GUARD))
        offset = end + len(BLOCK_GUARD)
    if offset != len(stream):
        raise ValueError("unexpected data after the 15th strip")
    return spans


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", required=True)
    parser.add_argument("--scale", type=int, choices=range(16), default=0,
                        help="MPCONV compression rate, 0 (finest) through 15")
    parser.add_argument("triples", nargs="+", help="input.png output.bin SYMBOL triplets")
    args = parser.parse_args()
    if len(args.triples) % 3:
        raise SystemExit("expected input/output/symbol triplets")

    records = []
    for i in range(0, len(args.triples), 3):
        src = Path(args.triples[i])
        dst = Path(args.triples[i + 1])
        sym = args.triples[i + 2]
        dst.parent.mkdir(parents=True, exist_ok=True)
        stream = encode_frame(src, args.scale)
        spans = analyze_stream(stream)
        dst.write_bytes(stream)
        records.append((sym, len(stream)))
        print(f"{sym}: scale {args.scale}, {len(stream)} bytes, "
              f"largest strip {max(spans)} bytes")

    header = Path(args.header)
    header.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#ifndef WAIFU_PCFX_RAINBOW_BG_ASSETS_H",
        "#define WAIFU_PCFX_RAINBOW_BG_ASSETS_H",
        "",
        "#define WAIFU_PCFX_RAINBOW_BG_KRAM_WORD_ADDR 0u",
        f"#define WAIFU_PCFX_RAINBOW_BG_TRANSFER_START {TRANSFER_START}u",
        f"#define WAIFU_PCFX_RAINBOW_BG_BLOCK_COUNT {BLOCK_COUNT}u",
    ]
    for sym, size in records:
        lines.append(f"#define {sym}_BYTES {size}u")
    lines.extend(["", "#endif /* WAIFU_PCFX_RAINBOW_BG_ASSETS_H */", ""])
    header.write_text("\n".join(lines), encoding="ascii")


if __name__ == "__main__":
    main()
