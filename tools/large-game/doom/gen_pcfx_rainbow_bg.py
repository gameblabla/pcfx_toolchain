#!/usr/bin/env python3
"""Encode 256x240 PNG backgrounds into PC-FX RAINBOW YUV/DCT streams."""

import argparse
import math
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

# HuC6271 quantization tables, lifted verbatim from Team Innocent.
#
# These are the 128 bytes that disc's FF FF block header carries, read straight
# out of its live RAINBOW source in KRAM (save state, KING.RAINBOWKRAMA =
# 0x227FF, KRAM_Mode = 1). All four frames resident at the time carry the same
# 128 bytes, and reshaping them 8x8 raster gives a table that is monotonic along
# both axes and symmetric about the diagonal -- which is what settles the
# storage order as NATURAL, not zigzag.
#
# The tables the encoder used before these were the baseline JPEG ones run
# through a quality scaler, which is a different curve entirely: JPEG spends its
# precision evenly and rolls off gently, while this one holds the low
# frequencies very fine (3..7) and then slams the high corner to the 254
# ceiling. That is a video table -- keep the DC and the first few AC terms,
# throw the rest away.
#
# What these tables do NOT settle is the transform normalization; see IDCT_GAIN
# below for why the argument that they did was wrong.
LUMA_Q_RETAIL = [
      4,   3,   4,   5,   6,   6,   7,   7,
      3,   3,   4,   5,   6,   7,   7,  35,
      4,   4,   5,   5,   6,   7,  11,  59,
      4,   4,   5,   6,   7,  11,  23, 254,
      5,   5,   6,   7,  11,  35,  67, 254,
      5,   5,   6,   7,  27,  55, 254, 254,
      6,   6,   7,  11,  59,  75, 254, 254,
      7,   7,  11,  63, 119, 254, 254, 254,
]

CHROMA_Q_RETAIL = [
      8,   4,   5,   7,  19, 131, 254, 254,
      4,   4,   5,   7,  27, 254, 254, 254,
      4,   5,   7,  11,  99, 254, 254, 254,
      5,   6,   7,  19, 131, 254, 254, 254,
      7,   7,  11,  99, 254, 254, 254, 254,
      7,  11,  67, 254, 254, 254, 254, 254,
     11,  99, 254, 254, 254, 254, 254, 254,
    254, 254, 254, 254, 254, 254, 254, 254,
]

# Team Innocent's tables are tuned for a bandwidth its FMV had to live inside:
# every frame streams off the disc in real time. The sky does not -- it is DMA'd
# into KRAM once at level load and re-armed from there, so its only size limits
# are the KRAM page-1 reserve (SKY_RESERVE_WORD * 2 = 20480 bytes, enforced in
# gen_pcfx_sky.py) and however many bits the decoder can chew through inside one
# 16-line raster window. Retail's ~16 KB/frame is the demonstrated ceiling for
# the latter, since Team Innocent hits the same 15-strip geometry we do.
#
# Halving every step -- so the whole curve gets one more bit of precision,
# including the 254 high-frequency ceiling that becomes 127 -- costs 11953 bytes
# against those two ceilings and buys +1.5 dB (RGB 32.29 -> 33.79, luma 32.98 ->
# 34.81), measured through tools/rainbow_refdec.py. That shows up as the DOOM
# sky's dither grain surviving instead of being smeared into visible 8x8 block
# structure across the mountain faces.
#
# Finer is available and still fits the KRAM reserve (1/4 = 17377 B, RGB 34.94)
# but pushes past retail's proven per-strip decode load for the last 1.2 dB, and
# there is no way to test a raster-deadline overrun short of a burn. 1/2 keeps a
# 4.5 KB margin under retail. Chroma is nearly free either way (2x2 subsampling
# caps RGB near 39.9 dB no matter how fine the chroma table is), so it is scaled
# with luma rather than tuned separately.
Q_REFINE = 2


def _refine(table):
    return [min(254, max(1, (v + Q_REFINE - 1) // Q_REFINE)) for v in table]


LUMA_Q = _refine(LUMA_Q_RETAIL)
CHROMA_Q = _refine(CHROMA_Q_RETAIL)

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


def quant_table(base):
    """The retail table, verbatim. No quality scaler.

    There used to be a JPEG-style quality knob multiplying these. It has no
    meaning here: the numbers above are not a quality-50 reference curve to be
    scaled off, they are the HuC6271 table one shipping title actually feeds the
    chip, and the block header hands them to the decoder as-is. Scaling them
    changes the encoder's idea of the picture and the decoder's idea in lockstep
    only as long as both stay in the range the Huffman symbol set can express --
    and the DC/AC category argument above shows how little headroom there is.
    """
    return np.array(base, dtype=np.float64).reshape((8, 8))


def fdct_matrix():
    mat = np.zeros((8, 8), dtype=np.float64)
    for u in range(8):
        c = math.sqrt(1.0 / 8.0) if u == 0 else math.sqrt(2.0 / 8.0)
        for x in range(8):
            mat[u, x] = c * math.cos(((2 * x + 1) * u * math.pi) / 16.0)
    return mat


DCT = fdct_matrix()


def pcfx_yuv(rgb):
    r = rgb[:, :, 0].astype(np.float64)
    g = rgb[:, :, 1].astype(np.float64)
    b = rgb[:, :, 2].astype(np.float64)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = (b - y) / 2.032 + 128.0
    v = (r - y) / 1.140 + 128.0
    return np.stack([y, u, v], axis=2)


def category(value):
    if value == 0:
        return 0
    return min(11, int(abs(value)).bit_length())


def signed_bits(value, size):
    if size == 0:
        return 0
    if value >= 0:
        return value
    return value - 1 + (1 << size)


# The HuC6271's inverse transform is not orthonormal: it returns FOUR TIMES the
# orthonormal IDCT, so the forward transform that matches it must be scaled by
# 1/4. Both of pcfxemu's independent decoder models agree on the factor:
#
#   * the fast backend's jrevdct ends its second pass at
#     DESCALE(..., CONST_BITS + PASS1_BITS + 1). Stock IJG ends at +3. Two bits
#     fewer of descale is exactly 4x.
#   * the 2019 hardware-accurate backend (idct.c, integer Loeffler with the
#     chip's own coefficients) lands ((D << 5) + 32) >> 6 = D/2 in every sample
#     of a DC-only block, where an orthonormal IDCT lands D/8. Also 4x.
#
# With the factor the chain is an identity: a flat block of value V has
# orthonormal DC 8*(V-128); quantizing by the luma DC step 4 with this scale
# gives (V-128)/2; the decoder dequantizes back to 2*(V-128) and its IDCT lands
# (V-128) per sample, +128 = V.
#
# Dropping the factor (commit c3522f1) overdrove the chip 4x. Measured through
# tools/rainbow_refdec.py, the resulting sky put 80.5% of its samples on a clip
# rail at 13.5 dB PSNR -- the soft grey mountain backdrop decoded as a
# black-and-white silhouette. That is what "the sky doesn't look very good" is.
#
# The category argument that justified removing it does not survive contact with
# the Huffman tables. Symbol sizes 2..7 carry 3-bit DC codes while 8 and 9 cost
# 6 and 7 bits, so the table is built for DC magnitudes under ~128 -- which is
# where 1/4 scaling puts them (+/-64), not where full scale puts them (+/-256).
IDCT_GAIN = 4.0


def quantized_block(block, qtable):
    coeff = (DCT @ (block - 128.0) @ DCT.T) / IDCT_GAIN
    return np.rint(coeff / qtable).astype(np.int32).reshape(64)


def write_huff(writer, table, symbol):
    code, length = table[symbol]
    writer.write(code, length)


def encode_block(writer, coeffs, qtable, last_dc, dc_table, ac_table, chroma):
    q = np.empty(64, dtype=np.int32)
    for i, src in enumerate(ZIGZAG):
        q[i] = coeffs[src]

    dc = int(q[0])
    diff = dc - last_dc
    max_dc_size = 9
    size = min(category(diff), max_dc_size)
    if size != category(diff):
        diff = max(-(1 << size) + 1, min((1 << size) - 1, diff))
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
        ac = max(-511, min(511, ac))
        size = min(category(ac), 9)
        symbol = (run << 4) | size
        if symbol not in ac_table:
            ac = max(-255, min(255, ac))
            size = min(category(ac), 8)
            symbol = (run << 4) | size
        write_huff(writer, ac_table, symbol)
        writer.write(signed_bits(ac, size), size)
        run = 0
    if run:
        writer.write(0x1F, 5)
    return dc


# Dummy data between blocks. C6272_2 section 3.4.2 only says "insert the
# specified dummy words/blocks at stream boundaries" without giving the count;
# the retail stream settles it. Team Innocent's live RAINBOW source in KRAM
# (save state, KING.RAINBOWKRAMA = 0x227FF, KRAM_Mode = 1, BlockCount = 15)
# puts exactly four zero words after every block, in all 45 blocks of the three
# frames resident at the time. The HuC6271 needs them to flush its input buffer
# between blocks, and section 3.4.2 warns they count toward the KRAM address.
BLOCK_PAD = b"\x00" * 8

# Every block begins on a 16-bit KRAM word boundary, and the way that is held is
# by making the size field even -- the advance from one block start to the next
# is `size_field + 10`, so an even size keeps a word-aligned stream word-aligned
# forever.
#
# This is measured, not inferred. Scanning KRAM1 of all three resident Team
# Innocent save states and following every FF FF frame header through its 15
# blocks gives 92 frames / 1380 blocks, and of those:
#
#     odd block sizes: 0        odd block start offsets: 0
#
# Zero out of 1380 on both counts. A stream whose sizes were merely whatever the
# entropy coder happened to emit would be odd about half the time, so this is the
# chip's rule (the same "dummy WORDS" quantization C6272_2 3.4.2 talks about for
# BLOCK_PAD), not an accident of their encoder.
#
# We were violating it: the entropy length was left as-is, so 9 of our 15 blocks
# started on an odd byte. The HuC6271 fetches KRAM a word at a time and serves
# the decoder bytes out of that word, so an odd block start puts every fetch for
# that block on the wrong half -- and whether the decoder recovers depends on
# where its input FIFO happens to be, which is why the damage showed up as PART
# of the sky FLICKERING rather than as a stream that simply never decodes.
#
# Padding is a single zero byte inside the size field. The decoder stops on the
# 16-column count, not on running out of bytes, so a trailing byte it never reads
# costs nothing; 0x00 is chosen because 0xFF would read as a block marker.
def align_entropy(entropy):
    return entropy + b"\x00" if len(entropy) & 1 else entropy


def encode_frame(path):
    """Encode one 256x240 frame as a HuC6271 block stream.

    Layout, taken byte for byte from Team Innocent's in-KRAM stream (see
    BLOCK_PAD above) rather than inferred:

        block 0     FF FF <size16> <128 bytes qtables> <entropy> <8 zero bytes>
        block 1..14 FF F8 <size16>                     <entropy> <8 zero bytes>

    Four things here used to be wrong, and each one alone desynchronises the
    decoder after the first 16 raster lines -- which is exactly the "sky only
    partially visible" symptom:

      * every block carried the FF FF marker. FF FF starts a FRAME; the
        continuation marker is FF F8.
      * every block carried a copy of the quantization tables. Only the FF FF
        block does.
      * the size field counted UNSTUFFED entropy bytes while the stream stores
        stuffed ones, so it under-ran every block by the number of FF 00 pairs
        in it.
      * block sizes were left odd, so blocks started mid-KRAM-word. Retail never
        does this in 1380 measured blocks -- see align_entropy() above.
    """
    img = Image.open(path).convert("RGB")
    if img.size != (256, 240):
        img = img.resize((256, 240), Image.Resampling.LANCZOS)
    yuv = pcfx_yuv(np.asarray(img, dtype=np.uint8))
    qy = quant_table(LUMA_Q)
    qc = quant_table(CHROMA_Q)
    qtables = bytes(int(qy.flat[i]) for i in range(64)) + bytes(int(qc.flat[i]) for i in range(64))
    out = bytearray()

    for block_y in range(0, 240, 16):
        writer = BitWriter()
        dc_y = 0
        dc_u = 0
        dc_v = 0
        for block_x in range(0, 256, 16):
            macro = yuv[block_y:block_y + 16, block_x:block_x + 16, :]
            yplane = macro[:, :, 0]
            for y0, x0 in ((0, 0), (8, 0), (0, 8), (8, 8)):
                coeffs = quantized_block(yplane[y0:y0 + 8, x0:x0 + 8], qy)
                dc_y = encode_block(writer, coeffs, qy, dc_y, HUFF_DC_Y, HUFF_AC_Y, False)

            uplane = macro[:, :, 1].reshape(8, 2, 8, 2).mean(axis=(1, 3))
            vplane = macro[:, :, 2].reshape(8, 2, 8, 2).mean(axis=(1, 3))
            dc_u = encode_block(writer, quantized_block(uplane, qc), qc, dc_u, HUFF_DC_UV, HUFF_AC_UV, True)
            dc_v = encode_block(writer, quantized_block(vplane, qc), qc, dc_v, HUFF_DC_UV, HUFF_AC_UV, True)

        entropy, _unstuffed_len = writer.finish()
        entropy = align_entropy(entropy)   # keep every block word-aligned
        first = block_y == 0
        tables = qtables if first else b""
        # size counts the size field itself, the quantization tables when
        # present, and the entropy bytes AS STORED (stuffing included).
        size_field = 2 + len(tables) + len(entropy)
        out.extend([0xFF, 0xFF if first else 0xF8,
                    (size_field >> 8) & 0xFF, size_field & 0xFF])
        out.extend(tables)
        out.extend(entropy)
        out.extend(BLOCK_PAD)
    return bytes(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--header", required=True)
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
        stream = encode_frame(src)
        dst.write_bytes(stream)
        records.append((sym, len(stream)))

    header = Path(args.header)
    header.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#ifndef WAIFU_PCFX_RAINBOW_BG_ASSETS_H",
        "#define WAIFU_PCFX_RAINBOW_BG_ASSETS_H",
        "",
        "#define WAIFU_PCFX_RAINBOW_BG_KRAM_WORD_ADDR 0u",
        "#define WAIFU_PCFX_RAINBOW_BG_TRANSFER_START 6u",
        "#define WAIFU_PCFX_RAINBOW_BG_BLOCK_COUNT 15u",
    ]
    for sym, size in records:
        lines.append(f"#define {sym}_BYTES {size}u")
    lines.extend(["", "#endif /* WAIFU_PCFX_RAINBOW_BG_ASSETS_H */", ""])
    header.write_text("\n".join(lines), encoding="ascii")


if __name__ == "__main__":
    main()
