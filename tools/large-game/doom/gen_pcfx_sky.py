#!/usr/bin/env python3
"""gen_pcfx_sky.py — build the PC-FX RAINBOW sky asset from a Doom sky texture.

Decodes the SKY1 patch (256x128) to RGB via PLAYPAL, expands it to a 256x240
image (the RAINBOW plane), encodes it to a HuC6271 RAINBOW YUV/DCT stream with
tools/gen_pcfx_rainbow_bg.py, and emits a CD asset plus a C header containing
its size and transfer parameters. At runtime the stream is copied
into KRAM page 1 and decoded by the RAINBOW hardware to form the sky, shown behind
the KING framebuffer wherever the renderer leaves transparent (index-0) pixels.

Usage: gen_pcfx_sky.py <wad> <out.h> [--patch SKY1]
"""
import sys, struct, re, argparse
from pathlib import Path

from gen_pcfx_rainbow_bg import encode_frame, analyze_stream, TRANSFER_START, BLOCK_COUNT
from gen_pcfx_sfx import BANK_END_WORD, CD_SECTOR_BYTES

HERE = Path(__file__).resolve().parent


def wad_lump(path, name):
    d = open(path, 'rb').read()
    _, n, off = struct.unpack('<4sII', d[:12])
    for i in range(n):
        e = d[off + i * 16:off + i * 16 + 16]
        fp, sz = struct.unpack('<II', e[:8])
        nm = e[8:16].split(b'\0')[0].decode('latin1')
        if nm == name:
            return d[fp:fp + sz]
    return None


def decode_patch(data):
    w, h, lo, to = struct.unpack('<HHhh', data[:8])
    colofs = struct.unpack('<%dI' % w, data[8:8 + 4 * w])
    img = bytearray([0]) * (w * h)
    for x in range(w):
        o = colofs[x]
        while data[o] != 0xff:
            top = data[o]; ln = data[o + 1]
            src = o + 3
            for y in range(ln):
                yy = top + y
                if 0 <= yy < h:
                    img[yy * w + x] = data[src + y]
            o = src + ln + 1
    return w, h, bytes(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wad')
    ap.add_argument('out_h')
    ap.add_argument('--patch', default='SKY1')
    ap.add_argument('--rainbow-scale', choices=['auto'] + [str(n) for n in range(16)],
                    default='auto', help='MPCONV rate; auto picks the finest legal fit')
    ap.add_argument('--rainbow-max-strip-bytes', type=int, default=0,
                    help='measured hardware strip-span ceiling; 0 means no extra limit')
    ap.add_argument('--sfx-header', type=Path,
                    help='generated SFX header (default: pcfx_sfx.h beside out.h)')
    a = ap.parse_args()
    if a.rainbow_max_strip_bytes < 0:
        ap.error('--rainbow-max-strip-bytes must be nonnegative')

    sfx_header = a.sfx_header or Path(a.out_h).with_name('pcfx_sfx.h')
    try:
        defs = sfx_header.read_text()
    except OSError as exc:
        sys.exit(f'SKY: generate the SFX bank/header first: {exc}')
    match = re.search(r'^#define\s+PCFX_SFX_KRAM_BASE_WORD\s+(0x[0-9A-Fa-f]+|[0-9]+)u?\s*$',
                      defs, re.MULTILINE)
    if not match:
        sys.exit(f'SKY: PCFX_SFX_KRAM_BASE_WORD missing from {sfx_header}')
    base_word = int(match.group(1), 0)
    if not 0 < base_word <= BANK_END_WORD or base_word % (CD_SECTOR_BYTES // 2):
        sys.exit(f'SKY: invalid sector-aligned ADPCM base 0x{base_word:X}')
    budget = base_word * 2

    from PIL import Image

    patch = wad_lump(a.wad, a.patch)
    if not patch:
        sys.exit(f'{a.patch} not found in {a.wad}')
    pal = wad_lump(a.wad, 'PLAYPAL')[:768]
    w, h, idx = decode_patch(patch)

    im = Image.frombytes('P', (w, h), idx)
    im.putpalette(pal)
    im = im.convert('RGB')
    # Expand the 256x128 sky to the 256x240 RAINBOW plane: sky on top, the top
    # row extended upward is unnecessary — instead tile the sky down so the lower
    # (below-horizon) area is also filled with sky rather than black.
    sky = Image.new('RGB', (256, 240))
    src = im.resize((256, 128), Image.NEAREST)
    sky.paste(src, (0, 0))
    sky.paste(src, (0, 128))          # tiled continuation for rows 128..239
    tmp_png = HERE.parent / 'generated' / 'sky.png'
    tmp_bin = HERE.parent / 'generated' / 'sky.bin'
    tmp_png.parent.mkdir(parents=True, exist_ok=True)
    sky.save(tmp_png)

    # Lowest numerical MPCONV rate = highest quality. Reject a candidate on
    # category overflow, sector-rounded overlap, or a measured strip ceiling.
    scales = range(16) if a.rainbow_scale == 'auto' else [int(a.rainbow_scale)]
    failures = []
    for scale in scales:
        try:
            stream = encode_frame(tmp_png, scale)
        except ValueError as exc:
            failures.append(f'scale {scale}: {exc}')
            continue
        spans = analyze_stream(stream)
        load_bytes = (len(stream) + CD_SECTOR_BYTES - 1) // CD_SECTOR_BYTES * CD_SECTOR_BYTES
        max_strip = max(spans)
        if load_bytes > budget:
            failures.append(f'scale {scale}: sector load {load_bytes} > KRAM budget {budget}')
            continue
        if a.rainbow_max_strip_bytes and max_strip > a.rainbow_max_strip_bytes:
            failures.append(f'scale {scale}: strip {max_strip} > limit {a.rainbow_max_strip_bytes}')
            continue
        break
    else:
        sys.exit('SKY: no legal MPCONV scale fits:\n  ' + '\n  '.join(failures))
    tmp_bin.write_bytes(stream)

    # The RAINBOW stream is NOT linked into the program — it is embedded on the CD
    # and DMA'd into KRAM at runtime (the HuC6271 only decodes CD-DMA'd KRAM data).
    # Emit the raw stream next to the header for the CD `append`, and a header with
    # just the sizes/params the loader needs.
    import os
    out_bin = os.path.splitext(a.out_h)[0] + '.bin'
    with open(out_bin, 'wb') as f:
        f.write(stream)

    with open(a.out_h, 'w') as f:
        f.write('/* Generated by tools/gen_pcfx_sky.py — do not edit. */\n')
        f.write('#ifndef PCFX_SKY_H\n#define PCFX_SKY_H\n\n')
        f.write(f'#define PCFX_SKY_BYTES {len(stream)}u\n')
        f.write(f'#define PCFX_SKY_TRANSFER_START {TRANSFER_START}u\n')
        f.write(f'#define PCFX_SKY_BLOCK_COUNT {BLOCK_COUNT}u\n')
        f.write(f'#define PCFX_SKY_RAINBOW_SCALE {scale}u\n')
        f.write(f'#define PCFX_SKY_MAX_STRIP_KRAM_BYTES {max_strip}u\n')
        f.write('#endif\n')
    print(f'SKY: stream {len(stream)} bytes -> {out_bin} (CD-embedded) + {a.out_h}')

    print(f'SKY: {a.patch} {w}x{h}, MPCONV scale {scale}, '
          f'sector load {load_bytes}/{budget} bytes, largest strip {max_strip} bytes')
    print('SKY: strip spans (KRAM bytes): ' + ', '.join(map(str, spans)))


if __name__ == '__main__':
    main()
