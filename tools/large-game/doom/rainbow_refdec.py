#!/usr/bin/env python3
"""rainbow_refdec.py -- reference HuC6271 RAINBOW decoder, for checking the encoder.

This is a transcription of pcfxemu's decoder (mednafen/pcfx/rainbow_fast.c plus
jrevdct.c), not an independent design. Its only job is to answer "what picture
does the chip actually produce from the stream tools/gen_pcfx_rainbow_bg.py
emitted", so the encoder can be judged without a CD burn.

The one thing worth knowing about the chip is in the IDCT. Mednafen's jrevdct
ends its second pass at DESCALE(..., CONST_BITS + PASS1_BITS + 1); the stock IJG
routine ends at +3. Two bits fewer means the decoder's output is FOUR TIMES the
true orthonormal IDCT. The 2019 hardware-accurate backend (idct.c) agrees
exactly: with only DC = D present it lands ((D << 5) + 32) >> 6 = D/2 in every
sample, where an orthonormal IDCT gives D/8. So an encoder that feeds this chip
a plain orthonormal forward DCT overdrives it by 4x, and everything more than
~32 levels away from mid grey clips.

Usage:
    rainbow_refdec.py stream.bin out.png [--reference source.png]
"""
import argparse
import math
import sys

import numpy as np

# --- Huffman tables, verbatim from rainbow_fast.c -----------------------------

DC_Y_BASE = [0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x08, 0x09, 0x00, 0x0B,
             0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
DC_Y_CODES = [0x00, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x01, 0x08, 0x09,
              0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18,
              0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F]
DC_Y_MIN = [0x0000, 0x0000, 0x0000, 0x0000, 0x000E, 0x0000, 0x003C, 0x007A,
            0x0000, 0x01F0, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000]
DC_Y_MAX = [0xFFFF, 0xFFFF, 0xFFFF, 0x0006, 0x000E, 0xFFFF, 0x003C, 0x007B,
            0xFFFF, 0x01FF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

DC_UV_BASE = [0x00, 0x00, 0x00, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x00,
              0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
DC_UV_CODES = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09]
DC_UV_MIN = [0x0000, 0x0000, 0x0000, 0x0006, 0x000E, 0x001E, 0x003E, 0x007E,
             0x00FE, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000]
DC_UV_MAX = [0xFFFF, 0xFFFF, 0x0002, 0x0006, 0x000E, 0x001E, 0x003E, 0x007E,
             0x00FF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

AC_Y_BASE = [0x00, 0x00, 0x00, 0x02, 0x03, 0x05, 0x09, 0x0D, 0x00, 0x10,
             0x00, 0x12, 0x22, 0x00, 0x00, 0x00, 0x00]
AC_Y_CODES = [
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
AC_Y_MIN = [0x0000, 0x0000, 0x0000, 0x0004, 0x000A, 0x0018, 0x0036, 0x0074,
            0x0000, 0x01DC, 0x0000, 0x0778, 0x0F10, 0x0000, 0x0000, 0x0000, 0x0000]
AC_Y_MAX = [0xFFFF, 0xFFFF, 0x0001, 0x0004, 0x000B, 0x001A, 0x0039, 0x0076,
            0xFFFF, 0x01DD, 0xFFFF, 0x0787, 0x0F7F, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

AC_UV_BASE = [0x00, 0x00, 0x00, 0x02, 0x03, 0x05, 0x0A, 0x0B, 0x00, 0x10,
              0x00, 0x12, 0x22, 0x00, 0x00, 0x00, 0x00]
AC_UV_CODES = [
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
AC_UV_MIN = [0x0000, 0x0000, 0x0000, 0x0004, 0x000A, 0x0018, 0x0038, 0x0072,
             0x0000, 0x01DC, 0x0000, 0x0778, 0x0F10, 0x0000, 0x0000, 0x0000, 0x0000]
AC_UV_MAX = [0xFFFF, 0xFFFF, 0x0001, 0x0004, 0x000B, 0x001B, 0x0038, 0x0076,
             0xFFFF, 0x01DD, 0xFFFF, 0x0787, 0x0F7F, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF]

# rainbow_fast.c zigzag[63]: natural index of each AC position, in scan order.
ZIGZAG_AC = [
    0x01, 0x08, 0x10, 0x09, 0x02, 0x03, 0x0A, 0x11,
    0x18, 0x20, 0x19, 0x12, 0x0B, 0x04, 0x05, 0x0C,
    0x13, 0x1A, 0x21, 0x28, 0x30, 0x29, 0x22, 0x1B,
    0x14, 0x0D, 0x06, 0x07, 0x0E, 0x15, 0x1C, 0x23,
    0x2A, 0x31, 0x38, 0x39, 0x32, 0x2B, 0x24, 0x1D,
    0x16, 0x0F, 0x17, 0x1E, 0x25, 0x2C, 0x33, 0x3A,
    0x3B, 0x34, 0x2D, 0x26, 0x1F, 0x27, 0x2E, 0x35,
    0x3C, 0x3D, 0x36, 0x2F, 0x37, 0x3E, 0x3F,
]


def build_lut(base, codes, minimum, maximum, bitmax):
    """BuildHuffmanLUT(): symbol and bit-length per bitmax-wide raw peek."""
    lut = [0] * (1 << bitmax)
    lut_bits = [0] * (1 << bitmax)
    for numbits in range(2, bitmax + 1):
        if maximum[numbits] == 0xFFFF:
            continue
        for i in range(minimum[numbits], maximum[numbits] + 1):
            sym = codes[base[numbits] + (i - minimum[numbits])]
            span = 1 << (bitmax - numbits)
            start = i << (bitmax - numbits)
            for b in range(span):
                lut[start + b] = sym
                lut_bits[start + b] = numbits
    return lut, lut_bits


DC_Y_LUT = build_lut(DC_Y_BASE, DC_Y_CODES, DC_Y_MIN, DC_Y_MAX, 9)
DC_UV_LUT = build_lut(DC_UV_BASE, DC_UV_CODES, DC_UV_MIN, DC_UV_MAX, 8)
AC_Y_LUT = build_lut(AC_Y_BASE, AC_Y_CODES, AC_Y_MIN, AC_Y_MAX, 12)
AC_UV_LUT = build_lut(AC_UV_BASE, AC_UV_CODES, AC_UV_MIN, AC_UV_MAX, 12)


class Stream:
    """KING_RB_Fetch() over a flat byte image, plus the bit layer above it."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def fetch(self):
        if self.pos >= len(self.data):
            return 0
        b = self.data[self.pos]
        self.pos += 1
        return b

    # --- bit layer (InitBits/FetchWidgywabbit/GetBits/SkipBits) ---
    def init_bits(self, bcount):
        self.bits_left = bcount
        self.buf = 0
        self.nbits = 0

    def _widgy(self):
        if self.bits_left <= 0:
            return 0
        b = self.fetch()
        if b == 0xFF:
            self.fetch()          # discard the stuffed byte
        self.bits_left -= 1
        return b

    def get_bits(self, count, peek=False, funnysign=False):
        while self.nbits < count:
            self.buf = ((self.buf << 8) | self._widgy()) & 0xFFFFFFFF
            self.nbits += 8
        ret = (self.buf >> (self.nbits - count)) & ((1 << count) - 1) if count else 0
        if not peek:
            self.nbits -= count
        if funnysign and count:
            if ret < (1 << (count - 1)):
                ret += 1 - (1 << count)
        return ret

    def skip_bits(self, count):
        self.nbits -= count


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class Decoder:
    def __init__(self, stream):
        self.s = stream
        self.qtab = [[0] * 64, [0] * 64]
        self.qbase = [[0] * 64, [0] * 64]

    def get_ac(self, lut):
        lut_sym, lut_bits = lut
        raw = self.s.get_bits(12, peek=True)
        if (raw & 0xF80) == 0xF80:            # EOB
            self.s.skip_bits(5)
            return 0, 0
        code = lut_sym[raw]
        self.s.skip_bits(lut_bits[raw])
        return self.s.get_bits(code & 0xF, funnysign=True), code >> 4

    def get_dc_y(self):
        lut_sym, lut_bits = DC_Y_LUT
        while True:
            raw = self.s.get_bits(9, peek=True)
            code = lut_sym[raw]
            self.s.skip_bits(lut_bits[raw])
            if code < 0xF:
                return self.s.get_bits(code, funnysign=True), 0
            if code == 0xF:                   # null-run escape
                _, zeroes = self.get_ac(AC_Y_LUT)
                return 0, zeroes + 1
            # code >= 0x10: rescale both quantization tables in place
            code -= 0x10
            for i in range(64):
                c = (self.qbase[0][i] * code) >> 2
                self.qtab[0][i] = min(0xFE, max(1, c))
                c = ((self.qbase[1][i] * code) >> 2) if i else (self.qbase[1][0] >> 2)
                self.qtab[1][i] = min(0xFE, max(1, c))

    def get_dc_uv(self):
        lut_sym, lut_bits = DC_UV_LUT
        raw = self.s.get_bits(8, peek=True)
        code = lut_sym[raw]
        self.s.skip_bits(lut_bits[raw])
        return self.s.get_bits(code, funnysign=True)

    def decode_block(self, qt, dc, lut):
        """rainbow_fast.c decode(): dequantized natural-order coefficients."""
        dct = [0] * 64
        dct[0] = s16(qt[0] * dc)
        count = 0
        while count < 63:
            coeff, zeroes = self.get_ac(lut)
            if not coeff:
                if not zeroes:
                    break                     # EOB: the rest stays zero
                if zeroes == 1:
                    zeroes = 0xF              # 0x10 == run of 16
            while zeroes and count < 63:
                count += 1
                zeroes -= 1
            if count < 63:
                idx = ZIGZAG_AC[count]
                count += 1
                dct[idx] = s16(qt[idx] * coeff)
        return dct


# The chip's IDCT, as a scale factor on the orthonormal one. See the module
# docstring: both pcfxemu backends land D/2 per sample for a DC-only block where
# an orthonormal IDCT lands D/8.
IDCT_GAIN = 4.0


def _idct_matrix():
    m = np.zeros((8, 8))
    for u in range(8):
        c = math.sqrt(1.0 / 8.0) if u == 0 else math.sqrt(2.0 / 8.0)
        for x in range(8):
            m[u, x] = c * math.cos(((2 * x + 1) * u * math.pi) / 16.0)
    return m


DCTM = _idct_matrix()


def idct8(dct):
    a = np.array(dct, dtype=np.float64).reshape(8, 8)
    return (DCTM.T @ a @ DCTM) * IDCT_GAIN


def decode_stream(data, height=240):
    """Return (Y, U, V) planes, each 256 x height, uint8."""
    s = Stream(data)
    d = Decoder(s)
    Y = np.zeros((height, 256), dtype=np.int32)
    U = np.zeros((height // 2, 128), dtype=np.int32)
    V = np.zeros((height // 2, 128), dtype=np.int32)

    row = 0
    while row * 16 < height:
        # --- find a block header: scan for FF, then a valid type byte ---
        while True:
            b = s.fetch()
            if s.pos >= len(s.data):
                return _finish(Y, U, V)
            if b != 0xFF:
                continue
            btype = s.fetch()
            if btype in (0xF0, 0xF1, 0xF2, 0xF3, 0xF8, 0xFF):
                break
        size = (s.fetch() << 8) | s.fetch()
        size -= 2
        if btype == 0xFF:
            for q in range(2):
                for i in range(64):
                    v = s.fetch()
                    d.qtab[q][i] = v
                    d.qbase[q][i] = v
            size -= 128
        if btype not in (0xF8, 0xFF):
            raise SystemExit(f'block {row}: unsupported RLE type {btype:#04x}')

        s.init_bits(size)
        dc_y = dc_u = dc_v = 0
        for col in range(16):
            v, zeroes = d.get_dc_y()
            dc_y += v
            if zeroes:
                col += zeroes            # null-run columns: left at neutral grey
                dc_y = dc_u = dc_v = 0
                continue
            blocks = []
            for k in range(4):
                if k:
                    v, _ = d.get_dc_y()
                    dc_y += v
                blocks.append(d.decode_block(d.qtab[0], dc_y, AC_Y_LUT))
            dc_u += d.get_dc_uv()
            bu = d.decode_block(d.qtab[1], dc_u, AC_UV_LUT)
            dc_v += d.get_dc_uv()
            bv = d.decode_block(d.qtab[1], dc_v, AC_UV_LUT)

            # A = top-left, B = bottom-left, C = top-right, D = bottom-right
            a, b_, c, dd = (idct8(x) for x in blocks)
            mb = np.zeros((16, 16))
            mb[0:8, 0:8] = a
            mb[8:16, 0:8] = b_
            mb[0:8, 8:16] = c
            mb[8:16, 8:16] = dd
            Y[row * 16:row * 16 + 16, col * 16:col * 16 + 16] = np.rint(mb + 128)
            U[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = np.rint(idct8(bu) + 128)
            V[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = np.rint(idct8(bv) + 128)
        row += 1
    return _finish(Y, U, V)


def _finish(Y, U, V):
    return (np.clip(Y, 0, 255).astype(np.uint8),
            np.clip(U, 0, 255).astype(np.uint8),
            np.clip(V, 0, 255).astype(np.uint8))


def to_rgb(Y, U, V):
    """The chroma pair covers a 2x2 pixel cell (ChromaIP off)."""
    y = Y.astype(np.float64)
    u = np.repeat(np.repeat(U.astype(np.float64), 2, 0), 2, 1)[:y.shape[0], :y.shape[1]]
    v = np.repeat(np.repeat(V.astype(np.float64), 2, 0), 2, 1)[:y.shape[0], :y.shape[1]]
    r = y + 1.140 * (v - 128.0)
    g = y - 0.394 * (u - 128.0) - 0.581 * (v - 128.0)
    b = y + 2.032 * (u - 128.0)
    return np.clip(np.stack([r, g, b], axis=2), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stream')
    ap.add_argument('out_png')
    ap.add_argument('--reference', help='original PNG, to report PSNR against')
    ap.add_argument('--height', type=int, default=240)
    a = ap.parse_args()

    from PIL import Image

    data = open(a.stream, 'rb').read()
    Y, U, V = decode_stream(data, a.height)
    rgb = to_rgb(Y, U, V)
    Image.fromarray(rgb).save(a.out_png)

    if a.reference:
        ref = np.asarray(Image.open(a.reference).convert('RGB'), dtype=np.float64)
        if ref.shape != rgb.shape:
            print(f'reference is {ref.shape}, decoded is {rgb.shape}; not comparable')
            return
        mse = float(np.mean((ref - rgb.astype(np.float64)) ** 2))
        psnr = float('inf') if mse == 0 else 10.0 * math.log10(255.0 * 255.0 / mse)
        clipped = float(np.mean((rgb == 0) | (rgb == 255)) * 100.0)
        print(f'{a.stream}: {len(data)} bytes, RGB PSNR {psnr:.2f} dB, '
              f'{clipped:.1f}% of samples at a clip rail')
    else:
        print(f'{a.stream}: {len(data)} bytes -> {a.out_png}')


if __name__ == '__main__':
    main()
