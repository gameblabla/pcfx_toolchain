"""lz4_block.py — produce a raw LZ4 *block* decodable by platform/lz4_depack.S.

The V810 decoder expects one raw LZ4 block (no frame header/tail), <= 64 KB, of
the *compressed* variety. `lz4 -12 -B4` gives the best ratio; we parse its frame
to extract the single block. If lz4 decides the data is incompressible and stores
it as an *uncompressed* frame block, we instead synthesise a literals-only LZ4
block (still the compressed on-wire format, so the same decoder handles it).

compress(data) -> the raw block bytes (prepend a 2-byte LE length header before
storing it on the CD; see gen_pcfx_cdassets.py).
"""
import struct, subprocess, shutil

LZ4_MAGIC = 0x184D2204


def _literal_only_block(data: bytes) -> bytes:
    """A valid LZ4 block that is a single all-literals sequence (no match). The
    decoder copies the literals then sees src==end and stops — exactly the
    'last sequence is literals only' end-of-block rule."""
    out = bytearray()
    n = len(data)
    tok = 0xF0 if n >= 15 else (n << 4)
    out.append(tok)
    if n >= 15:
        r = n - 15
        while r >= 255:
            out.append(255); r -= 255
        out.append(r)
    out += data
    return bytes(out)


def _extract_frame_block(frame: bytes) -> bytes | None:
    """Return the raw compressed block from an lz4 frame, or None if the frame's
    (single) block is stored uncompressed."""
    if struct.unpack_from('<I', frame, 0)[0] != LZ4_MAGIC:
        raise ValueError('not an lz4 frame')
    flg = frame[4]
    off = 6                                   # magic(4) + FLG(1) + BD(1)
    if (flg >> 3) & 1:                        # content-size present
        off += 8
    off += 1                                  # header checksum (HC)
    bsize = struct.unpack_from('<I', frame, off)[0]
    off += 4
    if bsize & 0x80000000:                    # uncompressed block -> caller falls back
        return None
    return frame[off:off + bsize]


def compress(data: bytes) -> bytes:
    if len(data) > 0x10000:
        raise ValueError('LZ4 block input must be <= 64 KB (got %d)' % len(data))
    lz4 = shutil.which('lz4')
    block = None
    if lz4:
        frame = subprocess.run(
            [lz4, '-12', '-B4', '--no-frame-crc', '-f', '/dev/stdin', '/dev/stdout'],
            input=data, stdout=subprocess.PIPE, check=True).stdout
        block = _extract_frame_block(frame)
    if block is None:                         # no lz4, or incompressible -> literals
        block = _literal_only_block(data)
    # Never store something larger than the plain literal encoding.
    lit = _literal_only_block(data)
    if len(lit) < len(block):
        block = lit
    if len(block) > 0xFFFF:
        raise ValueError('compressed block %d exceeds 16-bit length header' % len(block))
    return block
