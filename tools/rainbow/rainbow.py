#!/usr/bin/env python3
"""Author, validate, preview and repair PC-FX RAINBOW images and PCFV videos."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

import pcfv
import rainbow_codec as codec
from rainbow_decode import decode_stream, to_rgb


def encode(rgb, scale='auto', max_bytes=0, max_strip_bytes=0, independent=False):
    prepared = codec.prepare_image(rgb)
    choices = range(16) if scale == 'auto' else (int(scale),)
    failures = []
    for value in choices:
        try:
            stream = codec.encode_prepared(prepared, value, independent)
            spans = codec.analyze_stream(stream, len(prepared), independent)
            if max_bytes and len(stream) > max_bytes:
                raise ValueError(f'{len(stream)} bytes exceeds {max_bytes}')
            if max_strip_bytes and max(spans) > max_strip_bytes:
                raise ValueError(f'largest strip {max(spans)} exceeds {max_strip_bytes}')
            # Strict entropy validation catches truncated final columns, not just headers.
            decode_stream(stream, len(rgb))
            return stream, dict(scale=value, bytes=len(stream), strip_bytes=spans,
                                strip_word_offsets=list(np.cumsum([0] + spans[:-1]) // 2))
        except ValueError as exc:
            failures.append(f'scale {value}: {exc}')
    raise ValueError('no legal encoding fits; increase the budget or change the source\n' + '\n'.join(failures))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name, delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(data)
            out.close()
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)


def report(path, info):
    text = json.dumps(info, indent=2, default=int) + '\n'
    if path:
        atomic_write(path, text.encode())
    print(text, end='')


def image_command(a):
    with Image.open(a.input) as img:
        img = img.convert('RGB')
        if a.fit == 'strict' and img.size != (256, a.height):
            raise ValueError(f'image is {img.size}; supply 256x{a.height} or choose --fit stretch')
        if img.size != (256, a.height):
            img = img.resize((256, a.height), Image.Resampling.LANCZOS)
        rgb = np.asarray(img)
    data, info = encode(rgb, a.scale, a.max_bytes, a.max_strip_bytes, a.independent_strips)
    atomic_write(a.output, data)
    if a.preview:
        Image.fromarray(to_rgb(*decode_stream(data, a.height))).save(a.preview)
    if a.header:
        offsets = ', '.join(str(int(x)) + 'u' for x in info['strip_word_offsets'])
        text = ('#ifndef RAINBOW_ASSET_H\n#define RAINBOW_ASSET_H\n'
                f'#define RAINBOW_ASSET_BYTES {len(data)}u\n'
                f'#define RAINBOW_ASSET_SECTORS {pcfv.sectors(len(data))}u\n'
                f'#define RAINBOW_ASSET_BLOCKS {a.height // 16}u\n'
                f'#define RAINBOW_ASSET_INDEPENDENT_STRIPS {int(a.independent_strips)}u\n'
                f'static const unsigned int rainbow_strip_words[] = {{{offsets}}};\n#endif\n')
        atomic_write(a.header, text.encode())
    report(a.report, info)


def encode_job(job):
    raw, scale, budget, strip_budget = job
    return encode(np.frombuffer(raw, dtype=np.uint8).reshape(240, 256, 3), scale, budget, strip_budget)


def video_command(a):
    fps = Fraction(a.fps)
    if not 0 < fps <= 60 or fps.numerator > 65535 or fps.denominator > 65535:
        raise ValueError('fps must be 0..60, representable by two 16-bit integers')
    if not 0 <= a.frames <= pcfv.MAX_FRAMES or not 1 <= a.max_frame_sectors <= 4 or not 1 <= a.jobs <= 32:
        raise ValueError('frames: 0..4096; max-frame-sectors: 1..4; jobs: 1..32')
    target = Path(a.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rainbow-', dir=target.parent) as scratch:
        scratch = Path(scratch)
        filters = {'stretch': 'scale=256:240',
                   'contain': 'scale=256:240:force_original_aspect_ratio=decrease,pad=256:240:(ow-iw)/2:(oh-ih)/2',
                   'crop': 'scale=256:240:force_original_aspect_ratio=increase,crop=256:240'}
        cmd = [a.ffmpeg, '-nostdin', '-v', 'error', '-i', str(Path(a.input).resolve()),
               '-map', '0:v:0', '-an', '-vf', f'fps={fps},' + filters[a.fit],
               '-frames:v', str(a.frames or (pcfv.MAX_FRAMES + 1)),
               '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        frames, stats = [], []
        # Keep at most jobs*2 raw frames/futures resident, regardless of movie length.
        with (scratch / 'ffmpeg.log').open('wb') as log, ProcessPoolExecutor(max_workers=a.jobs) as pool:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)
            pending = []
            try:
                while True:
                    raw = proc.stdout.read(256 * 240 * 3)
                    if not raw:
                        break
                    if len(raw) != 256 * 240 * 3:
                        raise ValueError('ffmpeg returned a partial video frame')
                    pending.append(pool.submit(encode_job, (raw, a.scale, a.max_frame_sectors * 2048, a.max_strip_bytes)))
                    if len(pending) >= a.jobs * 2:
                        data, info = pending.pop(0).result()
                        frames.append(data)
                        stats.append(info)
                        if len(frames) % 30 == 0:
                            print(f'encoded {len(frames)} frames', file=sys.stderr)
                for future in pending:
                    data, info = future.result()
                    frames.append(data)
                    stats.append(info)
                if proc.wait():
                    raise ValueError((scratch / 'ffmpeg.log').read_text())
            finally:
                proc.stdout.close()
                if proc.poll() is None:
                    proc.terminate()
                proc.wait()
        if not frames or len(frames) > pcfv.MAX_FRAMES:
            raise ValueError('video must have 1..4096 frames; split longer movies into clips')
        audio = b''
        if a.audio == 'mp2':
            audio_path = scratch / 'audio.mp2'
            # Pad a short source audio track, trim to the selected video timeline.
            duration = str(float(len(frames) / fps))
            subprocess.run([a.ffmpeg, '-nostdin', '-v', 'error', '-i', str(Path(a.input).resolve()),
                            '-map', '0:a:0', '-vn', '-af', 'apad', '-t', duration,
                            '-ac', '1', '-ar', '16000', '-b:a', '32k', '-c:a', 'mp2', str(audio_path)], check=True)
            audio = audio_path.read_bytes()
        output = scratch / 'stream.pcfv'
        info = pcfv.write(output, frames, fps.numerator, fps.denominator, audio)
        pcfv.read(output)
        output.replace(target)
        info.update(fps=str(fps), scale_counts=dict(Counter(str(s['scale']) for s in stats)),
                    max_strip_bytes=max(max(s['strip_bytes']) for s in stats),
                    frames_detail=stats)
        report(a.report or str(target) + '.json', info)


def repair_frame(frame):
    """Explicit migration of the old C encoder; preserve every entropy bit."""
    # Its entropy is stuffed, so FF F8 is unambiguously a continuation marker.
    if frame[:2] != b'\xff\xff':
        raise ValueError('legacy frame lacks initial FF FF header')
    positions = [0] + [m.start() for m in re.finditer(b'\xff\xf8', frame[132:])]
    positions[1:] = [p + 132 for p in positions[1:]]
    if len(positions) != 15:
        raise ValueError('legacy migration expects exactly 15 strips')
    output = bytearray()
    for i, (start, end) in enumerate(zip(positions, positions[1:] + [len(frame)])):
        tables = frame[start + 4:start + 132] if i == 0 else b''
        entropy = frame[start + 4 + len(tables):end]
        logical = len(entropy) - entropy.count(b'\xff\x00')
        declared = int.from_bytes(frame[start + 2:start + 4], 'big')
        if declared != 2 + len(tables) + logical:
            raise ValueError(f'strip {i}: not the known legacy unstuffed-length layout')
        payload = tables + codec.align_entropy(entropy) + b'\0\0'
        output.extend(frame[start:start + 2] + len(payload).to_bytes(2, 'big') + payload + bytes(6))
    return bytes(output)


def repair_command(a):
    source = pcfv.read(a.input)
    fixed = [repair_frame(f) for f in source['frames']]
    for i, frame in enumerate(fixed):
        try:
            decode_stream(frame)
        except ValueError as exc:
            raise ValueError(f'frame {i}: {exc}') from exc
    target = Path(a.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rainbow-repair-', dir=target.parent) as scratch:
        tmp = Path(scratch) / 'stream.pcfv'
        info = pcfv.write(tmp, fixed, source['fps_num'], source['fps_den'], source['audio'])
        tmp.replace(target)
    info.update(repair='lossless entropy/framing migration', old_payload_bytes=sum(map(len, source['frames'])))
    report(a.report, info)


def inspect_command(a):
    if Path(a.input).read_bytes()[:8] == b'PCFV0001':
        source = pcfv.read(a.input)
        frames = source['frames']
    else:
        source, frames = {}, [Path(a.input).read_bytes()]
    for i, frame in enumerate(frames):
        try:
            planes = decode_stream(frame, a.height)
        except ValueError as exc:
            raise ValueError(f'frame {i}: {exc}') from exc
        if a.preview and i == a.frame:
            Image.fromarray(to_rgb(*planes)).save(a.preview)
    if not 0 <= a.frame < len(frames):
        raise ValueError('preview frame index out of range')
    report(a.report, dict(validated_frames=len(frames), max_bytes=max(map(len, frames)),
                          payload_bytes=sum(map(len, frames)), audio_bytes=len(source.get('audio', b''))))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('image', 'video', 'inspect', 'repair-legacy'):
        q = sub.add_parser(name)
        q.add_argument('input')
        if name in ('image', 'video', 'repair-legacy'):
            q.add_argument('output')
        q.add_argument('--report', help='machine-readable JSON report')
        if name in ('image', 'video'):
            q.add_argument('--scale', choices=['auto'] + list(map(str, range(16))), default='auto',
                           help='MPCONV scale: 0 finest, 15 coarsest; auto finds finest legal fit')
            q.add_argument('--max-strip-bytes', type=int, default=0, help='optional measured hardware/workload limit')
        if name in ('image', 'inspect'):
            q.add_argument('--height', type=int, default=240)
            q.add_argument('--preview', help='approximate host PNG (not a hardware validation)')
        if name == 'image':
            q.add_argument('--max-bytes', type=int, default=0)
            q.add_argument('--header')
            q.add_argument('--fit', choices=['strict', 'stretch'], default='strict')
            q.add_argument('--independent-strips', action='store_true', help='each strip initializes tables/scale for vertical source-address scrolling')
        elif name == 'video':
            q.add_argument('--ffmpeg', default='ffmpeg')
            q.add_argument('--fps', default='15')
            q.add_argument('--frames', type=int, default=0, help='0: whole clip, maximum 4096 frames')
            q.add_argument('--jobs', type=int, default=min(os.cpu_count() or 1, 8))
            q.add_argument('--audio', choices=['none', 'mp2'], default='none')
            q.add_argument('--fit', choices=['contain', 'crop', 'stretch'], default='contain')
            q.add_argument('--max-frame-sectors', type=int, default=4)
        elif name == 'inspect':
            q.add_argument('--frame', type=int, default=0)
    args = p.parse_args()
    try:
        {'image': image_command, 'video': video_command, 'inspect': inspect_command,
         'repair-legacy': repair_command}[args.command](args)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'rainbow: {exc}\n')


if __name__ == '__main__':
    main()
