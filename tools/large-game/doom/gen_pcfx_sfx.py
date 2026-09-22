#!/usr/bin/env python3
"""gen_pcfx_sfx.py — build a PC-FX KING ADPCM SFX bank from Doom DS* lumps.

Each Doom sound is a DS<NAME> lump: 8-byte header (u16 fmt, u16 rate, u32 nsamp)
+ nsamp bytes of 8-bit unsigned PCM (~11025 Hz). We resample each to 16 kHz and
encode it with the KING/SoundBox 4-bit ADPCM scheme (nibble order 0,4,8,12, same
step table as pcfxemu), 256-word aligning every sample so it can be addressed by
the hardware start register (SAL = start>>8).

The bank is indexed by Doom's sfx id (S_sfx[] order), so I_StartSound(id) plays
pcfx_sfx_meta[id]. Sources DS* from a full IWAD (doom1.wad) since the squashed
1-level WAD's sounds are stripped to near-silence.

Usage: gen_pcfx_sfx.py <sfx.wad> <sounds.c> <out.h>
"""
import sys, struct, re, argparse
from math import sin, cos, pi, ceil, gcd

# KING KRAM is 1 MB: two hardware pages of 0x40000 words (512 KB) each (see
# .claude/skills/pcfx-kram-layout). Page 1 holds the RAINBOW sky (from word 0)
# AND this ADPCM bank (from KRAM_BASE, just past the sky). The bank is NOT free
# to use the full 512 KB page, though: the KING engine's KRAM auto-increment
# (used for both the CD->KRAM DMA load and the ADPCM playback address) wraps
# within a 0x20000-word HALF, holding bit 17 fixed -- a bank (or a still-playing
# sound within it) that crosses word 0x20000 would wrap its address back to the
# start of that half instead of continuing, corrupting playback. So the real
# budget is KRAM_BASE + bank_words <= 0x20000, not <= 0x40000. That leaves
# 0x1D800 words = 238 KB for the bank, so the bank is capped in rate + duration
# to fit.
#
# The sky reserve was 0x2000 words (16 KB) against a ~6.8K-word stream. The
# RAINBOW encoder now uses Team Innocent's quantization tables and a correctly
# normalized forward DCT instead of a quality-scaled JPEG table and an
# emulator-tuned 0.25 gain, and the stream that produces is ~9K words -- past
# the old reserve and into the first sound in the bank. The reserve is 0x2800
# now, and tools/gen_pcfx_sky.py asserts the stream actually fits it rather than
# trusting the two numbers to stay in step by hand.
#
# DST_RATE MUST be one of the KING ADPCM hardware rates -- the rate field is two
# bits, so only 32000/16000/8000/4000 exist (libpcfx adpcm_rate).  A rate not in
# that set will silently mismatch the clocked channel and every sound will play
# back at the wrong pitch/speed.  Keep this in step with ADPCM_RATE in
# platform/i_sound_pcfx.c.
DST_RATE     = 8000          # must equal ADPCM_RATE in platform/i_sound_pcfx.c

# KING ADPCM control rate field (bits [3:2] of reg 0x50).  Indexing this dict
# also makes an illegal DST_RATE a generator error rather than a silent pitch
# bug.
ADPCM_RATE_FIELD = {32000: 0, 16000: 1, 8000: 2, 4000: 3}[DST_RATE]

# ---- encoder quality knobs ------------------------------------------------
# Set BOTH to False to restore the previous (pre-4 kHz-quality-pass) encoder
# exactly; they are independent and each is a measured win on its own.
#
#   ANTIALIAS_RESAMPLE  The old path decimated 11025 -> 4000 with bare linear
#       interpolation and NO anti-alias filter.  4 kHz Nyquist is 2 kHz, so all
#       source content above 2 kHz folded straight back into the band as
#       aliasing.  Windowed-sinc decimation removes it.        (+4.85 dB)
#   DECODER_EXACT  The old encoder searched against delta = step*(mag+1), but
#       the hardware runs with linear interpolation ON, which does
#       delta >>= ADPCM_RATE_FIELD and then applies it (1<<field) times,
#       clamping each sub-step.  Encoding against a decoder the hardware is not
#       running let the predictors drift apart.                (+1.62 dB)
#
# Measured on 10 voice/tonal DOOM sounds, segmental SNR against an ideal 4 kHz
# polyphase rendition (tools bench, see git log):
#     off/off 11.18 dB -> on/off 16.03 dB -> on/on 17.40 dB
# Noise shaping (delta-sigma error feedback) was tried and consistently LOST
# (17.65 -> 14.41 dB as it strengthened): at 4 kHz the whole 0-2 kHz band is
# perceptually important, so there is no spare band to push noise into.
# Encode gain was swept (96/110/128) and is flat to 0.13 dB -- ADPCM is
# adaptive, so SNR is level-independent.
ANTIALIAS_RESAMPLE = True
DECODER_EXACT      = True
SINC_LOBES         = 8       # windowed-sinc kernel half-width, in zero crossings
SINC_LPF_FRAC      = 0.95    # cutoff as a fraction of the output Nyquist (2 kHz)
# 128 makes 8-bit full scale (+/-128) land exactly on the decoder's predictor
# range (ENCODE_CLAMP_LO/HI below), so nothing is given away and nothing clips.
# This was 96 (+/-0x3000, i.e. 75% of the range) purely to "keep headroom", but
# headroom is not free here: it came straight off the SFX level, which the CD-DA
# soundtrack then buried by ~9 dB. The gain sweep above measured 96 vs 128 as
# quality-neutral (0.13 dB), because ADPCM's adaptive step makes SNR
# level-independent -- so the 2.5 dB is a pure win.
ENCODE_GAIN        = 128
# The hardware predictor saturates here (see _decode_step and pcfxemu's
# soundbox.c ADPCMPredictor clamp); encoding targets outside it are unreachable
# and would just clip.
ENCODE_CLAMP_LO    = -0x4000
ENCODE_CLAMP_HI    = 0x3fff
# Per-sound duration cap (ms), quantised, not free-choice: ADPCM_CH0SAL holds
# start>>8, so every sound MUST start on a 256-word boundary (hardware), and a
# word is always 4 samples (16 bits / 4-bit ADPCM) regardless of rate -- so at
# 8 kHz, 256 words is exactly 128 ms.  A sound therefore always costs
# ceil(ms/128) blocks; MAX_MS=1536 (12 blocks) is the nearest block-exact value
# to the requested ~1.5 s, so nothing is wasted to padding.
#
# This is well beyond what the shareware sound set uses in practice (most DOOM
# SFX run under half a second), so the actual bank size is driven by real
# content length, not this cap -- it only clips the handful of long ambient/
# door sounds. Overflow past the KRAM page 1 budget is a build error -- see
# pcfx_sfx_bank_fits_kram_page1 in platform/i_sound_pcfx.c.
#
# Trimming leading silence was measured and does not help: DOOM's DS lumps carry
# 0.04 s of leading silence across all 48 s (median 0.0 ms, worst 4.0 ms), so
# there is nothing to reclaim.
MAX_MS       = 1536
ALIGN_WORDS  = 256
ALIGN_BYTES  = ALIGN_WORDS * 2
# ---- KRAM placement: ONE contiguous run in page-1 bank A ------------------
# The bank sits at page-1 words 0x02000..0x1FFFF: past the sky reserve, and
# entirely inside BANK A (KRAM address bit 17 = the -A/B bank select, held 0),
# so no transfer crosses a bank or page boundary and the KING auto-increment
# (which wraps within the 17-bit address field) stays in range for the whole
# run. C6272_1 1.3.
#
# This was briefly split into two segments to dodge words 0x10000..0x1FFFF,
# which read back as open bus (0x5555) on the 2026-07-24 burns. That half is
# not missing silicon: the Hudson map draws it DOTTED only in the 1-MBIT map,
# and the console was in 1-Mbit mode because nothing ever wrote REG.61. It is
# solid in the 4-Mbit map, and platform/i_system_pcfx.c king_video_init() now
# programs 4-Mbit mode before any KRAM access -- so the run is contiguous again
# and no sample has to avoid a gap. The byte budget is unchanged (245760).
SKY_RESERVE_WORD = 0x02800   # sky stream lives at page-1 word 0, under this
KRAM_BASE    = SKY_RESERVE_WORD
BANK_END_WORD = 0x20000      # end of page-1 bank A (exclusive)
BANK_BUDGET_BYTES = (BANK_END_WORD - KRAM_BASE) * 2      # 243712 = 238 KB
assert KRAM_BASE % 256 == 0, \
    'ADPCM start register is SAL = word>>8: the bank base must be 256-word aligned'

STEP_SIZES = [
    16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50,
    55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157,
    173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552,
]
STEP_DELTAS = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def read_wad_lumps(path):
    d = open(path, 'rb').read()
    mg, n, off = struct.unpack('<4sII', d[:12])
    out = {}
    for i in range(n):
        e = d[off + i * 16:off + i * 16 + 16]
        fp, sz = struct.unpack('<II', e[:8])
        nm = e[8:16].split(b'\0')[0].decode('latin1')
        out[nm] = d[fp:fp + sz]
    return out


def parse_sfx_names(sounds_c):
    txt = open(sounds_c).read()
    m = re.search(r'S_sfx\s*\[\s*\]\s*=\s*\{(.*?)\n\};', txt, re.S)
    if not m:
        sys.exit('S_sfx[] not found in ' + sounds_c)
    # strip comments, then grab the first "..." of every { ... } entry
    body = re.sub(r'//[^\n]*', '', m.group(1))
    return re.findall(r'\{\s*"([^"]*)"', body)


def _sinc(x):
    if x == 0.0:
        return 1.0
    z = pi * x
    return sin(z) / z


def _sinc_kernels(src_rate):
    """Windowed-sinc polyphase kernels for src_rate -> DST_RATE decimation.

    Cutoff sits below the OUTPUT Nyquist, so source content that cannot be
    represented at DST_RATE is removed instead of folding back into the band.
    Output phases repeat every `period` samples, so only that many kernels
    exist -- precompute them once per source rate."""
    ratio = DST_RATE / src_rate
    fc = 0.5 * min(1.0, ratio) * SINC_LPF_FRAC      # cycles per input sample
    half = int(ceil(SINC_LOBES / (2.0 * fc)))
    step = src_rate / DST_RATE
    period = DST_RATE // gcd(int(src_rate), int(DST_RATE))
    kernels = []
    for p in range(period):
        frac = (p * step) % 1.0
        k = []
        for t in range(-half, half + 1):
            d = t - frac
            # Blackman window over the kernel support
            u = (d + half) / (2.0 * half)
            w = 0.42 - 0.5 * cos(2.0 * pi * u) + 0.08 * cos(4.0 * pi * u)
            k.append(2.0 * fc * _sinc(2.0 * fc * d) * w)
        tot = sum(k)
        kernels.append([v / tot for v in k] if tot else k)
    return kernels, half, step


def resample_u8(pcm, src_rate):
    """Resample 8-bit unsigned PCM to DST_RATE, returning signed samples scaled
    into the ADPCM predictor's range."""
    if not pcm:
        return []
    n_in = len(pcm)
    if not ANTIALIAS_RESAMPLE:
        # Legacy path: bare linear interpolation, no anti-alias filter.
        out_len = max(1, round(n_in * DST_RATE / src_rate))
        out = []
        for i in range(out_len):
            pos = i * src_rate
            ip = pos // DST_RATE
            frac = pos % DST_RATE
            if ip >= n_in - 1:
                s = pcm[-1]
            else:
                a, b = pcm[ip], pcm[ip + 1]
                s = (a * (DST_RATE - frac) + b * frac + DST_RATE // 2) // DST_RATE
            out.append(clamp((int(s) - 128) * ENCODE_GAIN, ENCODE_CLAMP_LO, ENCODE_CLAMP_HI))
        out.extend([0] * (DST_RATE // 100))
        return out

    kernels, half, step = _sinc_kernels(src_rate)
    period = len(kernels)
    out_len = max(1, round(n_in * DST_RATE / src_rate))
    out = []
    for i in range(out_len):
        base = int(i * step)
        ker = kernels[i % period]
        acc = 0.0
        for j, w in enumerate(ker):
            idx = base + j - half
            if idx < 0:
                idx = 0
            elif idx >= n_in:
                idx = n_in - 1
            acc += (pcm[idx] - 128) * w
        out.append(clamp(int(round(acc * ENCODE_GAIN)), ENCODE_CLAMP_LO, ENCODE_CLAMP_HI))
    out.extend([0] * (DST_RATE // 100))   # short silence tail (signed 0 == silence)
    return out


def _decode_step(pred, nib, idx):
    """One decoder step, bit-exact with pcfxemu (soundbox.c SoundBox_ADPCMUpdate,
    EmulateBuggyCodec=false) for the rate/interp mode i_sound_pcfx.c programs:

        delta = StepSizes[idx] * ((nib & 7) + 1)
        delta >>= ADPCM_RATE_FIELD          # linear interpolation is ON
        if nib & 8: delta = -delta
        idx += StepIndexDeltas[nib]; clamp 0..48
        repeat (1 << ADPCM_RATE_FIELD) times: pred += delta; clamp

    The >> and the repeated add do NOT cancel: the shift truncates first, so the
    predictor moves ((step*(mag+1)) >> f) << f, not step*(mag+1)."""
    delta = (STEP_SIZES[idx] * ((nib & 7) + 1)) >> ADPCM_RATE_FIELD
    if nib & 8:
        delta = -delta
    for _ in range(1 << ADPCM_RATE_FIELD):
        pred = clamp(pred + delta, -0x4000, 0x3fff)
    return pred, clamp(idx + STEP_DELTAS[nib], 0, 48)


def encode_adpcm(samples):
    pred = idx = 0
    nibbles = []
    for target in samples:
        best_err = 1 << 62
        best_nib, best_pred, best_idx = 0, pred, idx
        if DECODER_EXACT:
            for nib in range(16):
                cand, nidx = _decode_step(pred, nib, idx)
                err = (target - cand) ** 2
                if err < best_err:
                    best_err, best_nib, best_pred, best_idx = err, nib, cand, nidx
        else:
            step = STEP_SIZES[idx]
            for mag in range(8):
                delta = step * (mag + 1)
                for sign in (0, 8):
                    cand = clamp(pred - delta if sign else pred + delta, -0x4000, 0x3fff)
                    err = (target - cand) ** 2
                    if err < best_err:
                        nib = mag | sign
                        best_err = err
                        best_nib = nib
                        best_pred = cand
                        best_idx = clamp(idx + STEP_DELTAS[nib], 0, 48)
        nibbles.append(best_nib)
        pred, idx = best_pred, best_idx
    while len(nibbles) % 4:
        nibbles.append(0)
    out = bytearray()
    for i in range(0, len(nibbles), 4):
        hw = (nibbles[i] & 15) | ((nibbles[i+1] & 15) << 4) \
           | ((nibbles[i+2] & 15) << 8) | ((nibbles[i+3] & 15) << 12)
        out += struct.pack('<H', hw)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sfx_wad')
    ap.add_argument('sounds_c')
    ap.add_argument('out_h')
    ap.add_argument('out_bin', nargs='?',
                    help='raw ADPCM bank -> CD asset (keeps it out of the RAM image)')
    a = ap.parse_args()

    lumps = read_wad_lumps(a.sfx_wad)
    names = parse_sfx_names(a.sounds_c)

    bank = bytearray()
    metas = []          # (start_word, word_count, volume)
    n_encoded = 0
    for i, name in enumerate(names):
        ln = 'DS' + name.upper()
        lump = lumps.get(ln)
        if i == 0 or not lump or len(lump) < 8:
            metas.append((0, 0, 0))
            continue
        fmt, rate, nsamp = struct.unpack('<HHI', lump[:8])
        pcm = lump[8:8 + nsamp]
        if not pcm:
            metas.append((0, 0, 0))
            continue
        samples = resample_u8(pcm, rate or 11025)
        max_samples = DST_RATE * MAX_MS // 1000     # cap per-sound duration
        if len(samples) > max_samples:
            samples = samples[:max_samples]
        adpcm = encode_adpcm(samples)
        while len(bank) % ALIGN_BYTES:
            bank.append(0)
        if len(bank) + len(adpcm) > BANK_BUDGET_BYTES:
            metas.append((0, 0, 0))
            continue
        # Absolute KRAM word, so the player needs no base arithmetic.
        start_word = KRAM_BASE + len(bank) // 2
        bank += adpcm
        metas.append((start_word, len(adpcm) // 2, 63))
        n_encoded += 1

    with open(a.out_h, 'w') as f:
        f.write('/* Generated by tools/gen_pcfx_sfx.py — do not edit. */\n')
        f.write('#ifndef PCFX_SFX_H\n#define PCFX_SFX_H\n\n')
        f.write(f'#define PCFX_SFX_KRAM_BASE_WORD 0x{KRAM_BASE:X}u\n')
        f.write(f'#define PCFX_SFX_COUNT {len(names)}u\n')
        f.write(f'#define PCFX_SFX_BANK_BYTES {len(bank)}u\n\n')
        f.write('/* ONE contiguous disc blob, loaded to KRAM page-1 bank A with a\n'
                ' * single DMA at PCFX_SFX_KRAM_BASE_WORD. Requires 4-Mbit KRAM mode\n'
                ' * (REG.61=1, set in king_video_init). start_word below is an\n'
                ' * ABSOLUTE KRAM word. */\n')
        f.write(f'#define PCFX_SFX_BANK_END_WORD 0x{BANK_END_WORD:X}u\n\n')
        f.write('typedef struct { unsigned int start_word, word_count; '
                'unsigned char volume; } pcfx_sfx_meta_t;\n\n')
        f.write('static const pcfx_sfx_meta_t pcfx_sfx_meta[PCFX_SFX_COUNT] = {\n')
        for (sw, wc, vol), nm in zip(metas, names):
            f.write(f'  {{ {sw}u, {wc}u, {vol}u }}, /* {nm} */\n')
        f.write('};\n\n')
        if a.out_bin:
            # Bank lives on the CD (loaded to KRAM at boot); NOT baked into the RAM
            # image — reclaims ~80 KB of .rodata for the zone heap.
            f.write('/* pcfx_sfx_bank[] is on the CD (see platform/i_sound_pcfx.c). */\n')
        else:
            f.write('#pragma GCC optimize ("-O0")\n')
            f.write('static const unsigned char pcfx_sfx_bank[PCFX_SFX_BANK_BYTES ? PCFX_SFX_BANK_BYTES : 1] '
                    '__attribute__((aligned(4))) = {\n')
            for i in range(0, len(bank), 20):
                f.write(','.join(str(b) for b in bank[i:i + 20]) + ',\n')
            f.write('};\n')
        f.write('\n#endif\n')

    if a.out_bin:
        with open(a.out_bin, 'wb') as f:
            f.write(bank)

    print(f'SFX: {n_encoded} sounds encoded, bank {len(bank)} bytes '
          f'({len(bank)//1024} KB) -> {a.out_h}' + (f' + {a.out_bin}' if a.out_bin else ''))


if __name__ == '__main__':
    main()
