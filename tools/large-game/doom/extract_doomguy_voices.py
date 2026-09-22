#!/usr/bin/env python3
"""Extract Doomguy voice samples from doom1.wad and stitch into doomguy_voices.wav."""

import struct
import wave

LUMPS = ['DSPLPAIN', 'DSPLDETH', 'DSPDIEHI', 'DSOOF']
LABELS = ['plpain (pain)', 'pldeth (death)', 'pdiehi (gib death)', 'oof (bump)']
GAP_SEC = 1.0
OUTFILE = 'doomguy_voices.wav'

def read_wad(path):
    d = open(path, 'rb').read()
    mg, n, off = struct.unpack('<4sII', d[:12])
    lumps = {}
    for i in range(n):
        e = d[off + i * 16:off + i * 16 + 16]
        fp, sz = struct.unpack('<II', e[:8])
        nm = e[8:16].split(b'\0')[0].decode('latin1')
        lumps[nm] = d[fp:fp + sz]
    return lumps

def main():
    import sys
    wad_path = sys.argv[1] if len(sys.argv) > 1 else '../doom1.wad'
    lumps = read_wad(wad_path)

    # Collect all samples at source rates, then resample to a common rate
    common_rate = 11025
    all_samples = []  # list of list of signed 16-bit samples

    for ln, label in zip(LUMPS, LABELS):
        raw = lumps.get(ln)
        if not raw or len(raw) < 8:
            print(f'WARNING: {ln} not found or too small')
            continue
        fmt, rate, nsamp = struct.unpack('<HHI', raw[:8])
        pcm = raw[8:8 + nsamp]
        if not pcm:
            print(f'WARNING: {ln} has no sample data')
            continue
        src_rate = rate or 11025
        # Convert u8 to signed 16-bit
        pcm_s16 = [(b - 128) << 8 for b in pcm]

        # Simple linear resample to common_rate if needed
        if src_rate != common_rate:
            n_out = max(1, round(len(pcm_s16) * common_rate / src_rate))
            out = []
            for i in range(n_out):
                pos = i * src_rate / common_rate
                ip = int(pos)
                frac = pos - ip
                if ip >= len(pcm_s16) - 1:
                    out.append(pcm_s16[-1])
                else:
                    a, b = pcm_s16[ip], pcm_s16[ip + 1]
                    out.append(int(a * (1 - frac) + b * frac))
            pcm_s16 = out

        print(f'{ln}: fmt={fmt}, rate={src_rate} Hz, {nsamp} src samples, {len(pcm_s16)} @ {common_rate} Hz, '
              f'duration={len(pcm_s16)/common_rate:.2f}s')
        all_samples.append(pcm_s16)

    # Build the final interleaved audio with 1s gaps
    gap_samples = [0] * int(common_rate * GAP_SEC)
    combined = []
    for i, samples in enumerate(all_samples):
        if i > 0:
            combined.extend(gap_samples)
        combined.extend(samples)

    print(f'\nTotal duration: {len(combined)/common_rate:.2f}s ({len(all_samples)} clips)')

    # Write WAV
    with wave.open(OUTFILE, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(common_rate)
        wf.writeframes(struct.pack(f'<{len(combined)}h', *combined))

    print(f'Wrote {OUTFILE} ({len(combined) * 2} bytes)')

if __name__ == '__main__':
    main()
