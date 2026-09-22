#!/usr/bin/env python3
"""Gate a RAINBOW still/pan disc on emulator evidence, not on "it built".

Runs pcfx-headless to two frame counts, aligns each screenshot with the source
image over every horizontal shift (the endless-scroll pan wraps at 256), and
fails when:

  * the screen is black or the picture does not match the source at any shift
    (loader, KRAM page routing, arm or plane-enable bug);
  * the pan did not advance by the expected pixels per field;
  * one 16x16 macroblock decodes far worse than a correct decode can (strip
    starvation/desync: sizes that miss stuffed FF 00 bytes, missing guard
    words, a bad null run).  Measured on the test card: correct decode worst
    macroblock 26.7, legacy-framed stream 60.2.

pcfx-headless shows what pcfxemu implements; retail claims still need hardware.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

TOOLKIT = Path(os.environ.get('PCFX_TOOLKIT_ROOT') or Path(__file__).resolve().parents[2])


def shoot(emu, bios, cue, frames, png):
    proc = subprocess.run([str(emu), '--bios-dir', str(bios), '--pcfx', '--frames', str(frames),
                           '--screenshot', str(png), str(cue)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode or not png.exists():
        raise SystemExit(f'emulator failed at {frames} frames:\n{proc.stdout[-2000:]}')
    return np.asarray(Image.open(png).convert('RGB'), dtype=np.float64)


def load_source(path, fit):
    img = Image.open(path).convert('RGB')
    if img.size != (256, 240):
        if fit != 'stretch':
            raise SystemExit(f'{path} is {img.size}; pass --fit stretch or supply 256x240')
        img = img.resize((256, 240), Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def align(shot, src):
    errs = [np.abs(shot - np.roll(src, -s, axis=1)).mean() for s in range(256)]
    s = int(np.argmin(errs))
    # Undo the pan so errors stay attached to the source's strips/columns.
    diff = np.abs(np.roll(shot, s, axis=1) - src).mean(axis=2)
    mb = diff.reshape(15, 16, 16, 16).mean(axis=(1, 3))
    worst = np.unravel_index(int(mb.argmax()), mb.shape)
    return s, float(errs[s]), float(mb.max()), (int(worst[0]), int(worst[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cue', required=True)
    ap.add_argument('--image', required=True, help='the PNG that was encoded')
    ap.add_argument('--fit', choices=['strict', 'stretch'], default='strict')
    ap.add_argument('--frames', default='1000,1100', help='two emulated frame counts after the picture is up')
    ap.add_argument('--pan', type=float, default=1.0, help='expected pixels per field; 0 for a static image')
    ap.add_argument('--max-mae', type=float, default=20.0)
    ap.add_argument('--max-mb-mae', type=float, default=45.0,
                    help='worst 16x16 macroblock error allowed; raise only for very detailed art')
    ap.add_argument('--bios-dir', default=os.environ.get('PCFX_BIOS_DIR'))
    ap.add_argument('--emu', default=os.environ.get('PCFX_HEADLESS') or str(TOOLKIT / 'toolchain/bin/pcfx-headless'))
    ap.add_argument('--out', default='build/validate')
    a = ap.parse_args()
    if not a.bios_dir:
        raise SystemExit('set PCFX_BIOS_DIR or pass --bios-dir (a BIOS is never bundled)')

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    src = load_source(a.image, a.fit)
    f0, f1 = (int(x) for x in a.frames.split(','))
    failures, rows = [], []
    for n in (f0, f1):
        shot = shoot(a.emu, a.bios_dir, a.cue, n, out / f'frame_{n}.png')
        lit = float((shot.sum(axis=2) > 24).mean())
        shift, mae, mb_max, where = align(shot, src)
        rows.append(dict(frames=n, nonblack=lit, shift=shift, mae=mae, worst_mb_mae=mb_max, worst_mb=where))
        print(f'{n:5d} frames: shift={shift:3d}px mae={mae:.1f} worst macroblock {mb_max:.1f} '
              f'at strip {where[0]} column {where[1]} nonblack={lit:.2f}')
        if mae > a.max_mae:
            failures.append(f'{n}: picture does not match source at any pan (MAE {mae:.1f}); '
                            'check the CD->KRAM load, REG.0F page routing and the per-field arm')
        if mb_max > a.max_mb_mae:
            failures.append(f'{n}: strip {where[0]} column {where[1]} decodes badly (MAE {mb_max:.1f}); '
                            'strip starvation or desync: run rainbow.py inspect on the stream')
    moved = (rows[1]['shift'] - rows[0]['shift']) % 256
    want = round(a.pan * (f1 - f0)) % 256
    if abs(moved - want) > 2:
        failures.append(f'pan moved {moved}px over {f1 - f0} fields, expected {want}px')
    (out / 'report.json').write_text(json.dumps(dict(pass_=not failures, failures=failures, checks=rows), indent=2))
    if failures:
        print('FAIL\n  ' + '\n  '.join(failures))
        raise SystemExit(1)
    print(f'PASS: pan {moved}px over {f1 - f0} fields ({out})')


if __name__ == '__main__':
    main()
