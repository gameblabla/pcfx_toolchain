#!/usr/bin/env python3
"""Read the DEV_FRAME_TRACE per-frame time ring from pcfx-headless RAM dumps.

Reports average fps plus 1% / 0.1% lows over the frames recorded between an
optional --before dump and the main dump (or the last N frames in the ring).
Each record is (frame, tic, display, blit) in ITU-ticks>>4 units.
"""

import argparse
import pathlib
import struct
import sys

TICKS_PER_MS = 1432.0
UNIT_MS = 16.0 / TICKS_PER_MS          # one >>4 quantum in ms
CAP = 1024
FIELD_MS = 1000.0 / 60.09       # one NTSC field: frame times quantize to this
MARKER = b"PCFXFTR!"


def load_trace(path):
    ram = path.read_bytes()
    base = ram.find(MARKER)
    if base < 0:
        sys.exit(f"{path}: no PCFXFTR! marker; build with -DDEV_FRAME_TRACE")
    n = struct.unpack_from("<I", ram, base + 8)[0]
    recs = []
    for i in range(CAP):
        recs.append(struct.unpack_from("<4H", ram, base + 12 + i * 8))
    return n, recs


def window(n_after, recs, n_before):
    """Return the records for frames (n_before, n_after], newest last."""
    count = n_after - n_before
    if count <= 0:
        sys.exit("no frames recorded in the window")
    if count > CAP:
        print(f"warning: window {count} frames exceeds ring capacity {CAP}; "
              f"using the newest {CAP}", file=sys.stderr)
        count = CAP
    return [recs[(n_after - count + i) & (CAP - 1)] for i in range(count)]


def low_avg_ms(times_ms, fraction):
    """Mean of the slowest max(1, fraction*len) frames, as ms."""
    k = max(1, int(len(times_ms) * fraction))
    worst = sorted(times_ms, reverse=True)[:k]
    return sum(worst) / k


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ram", type=pathlib.Path)
    parser.add_argument("--before", type=pathlib.Path,
                        help="earlier RAM dump bounding the analysis window")
    parser.add_argument("--worst", type=int, default=10,
                        help="list the N slowest frames with phase breakdown")
    parser.add_argument("--render", action="store_true",
                        help="dump built with -DDEV_FRAME_TRACE_RENDER "
                             "(fields are frame, bsp, plane, sprites)")
    parser.add_argument("--counts", action="store_true",
                        help="dump built with -DDEV_FRAME_TRACE_COUNTS "
                             "(fields are frame, drawsegs, visplanes, sprites; "
                             "counts are raw, not ms)")
    parser.add_argument("--work", action="store_true",
                        help="dump built with -DDEV_FRAME_TRACE_WORK "
                             "(fields are frame, work, vsync spin, tic spin); "
                             "reports the compute/idle split per field class")
    args = parser.parse_args()

    n_after, recs = load_trace(args.ram)
    n_before = load_trace(args.before)[0] if args.before else max(0, n_after - CAP)
    recs = window(n_after, recs, n_before)

    frame_ms = [r[0] * UNIT_MS for r in recs]
    total_s = sum(frame_ms) / 1000.0
    avg_fps = len(frame_ms) / total_s
    print(f"frames: {len(frame_ms)}  ({total_s:.1f} s of gameplay)")
    print(f"avg:      {avg_fps:6.2f} fps  ({sum(frame_ms)/len(frame_ms):6.2f} ms)")
    for label, frac in (("1% low", 0.01), ("0.1% low", 0.001)):
        ms = low_avg_ms(frame_ms, frac)
        print(f"{label:9s} {1000.0/ms:6.2f} fps  ({ms:6.2f} ms)")
    print(f"max:      {1000.0/max(frame_ms):6.2f} fps  ({max(frame_ms):6.2f} ms worst frame)")

    order = sorted(range(len(recs)), key=lambda i: recs[i][0], reverse=True)

    if args.work:
        # Whole-frame time is snapped up to a field multiple, so it hides how
        # much real work a frame did.  work = frame - vsync spin recovers it,
        # and "headroom" is how far work sits above the field boundary below it
        # -- i.e. exactly what a saving must beat to drop the frame a class.
        work_ms = [r[1] * UNIT_MS for r in recs]
        spin_ms = [r[3] * UNIT_MS for r in recs]
        comp_ms = [max(0.0, w - s) for w, s in zip(work_ms, spin_ms)]
        n = len(recs)
        print(f"\ncompute (work - tic spin): mean {sum(comp_ms)/n:6.2f} ms   "
              f"max {max(comp_ms):6.2f} ms")
        print(f"idle: tic spin {sum(spin_ms)/n:5.2f} ms/frame   "
              f"vsync spin {sum(r[2]*UNIT_MS for r in recs)/n:5.2f} ms/frame")
        # A frame spinning for a tic is tic-bound: it renders faster than the
        # 35 Hz game clock, so cheaper compute only lengthens its spin.  Only
        # the render-bound frames convert saved cycles into fps.
        print(f"\n  {'fields':>6} {'frames':>7} {'%':>6} {'compute':>9} "
              f"{'tic spin':>9}  bound by")
        buckets = {}
        for f_ms, c, s_ in zip(frame_ms, comp_ms, spin_ms):
            k = max(1, round(f_ms / FIELD_MS))
            buckets.setdefault(k, []).append((c, s_))
        tic_bound = 0
        for k in sorted(buckets):
            b = buckets[k]
            c = sum(x[0] for x in b) / len(b)
            s_ = sum(x[1] for x in b) / len(b)
            if s_ > 0.5:
                tic_bound += len(b)
            print(f"  {k:6d} {len(b):7d} {100*len(b)/n:5.1f}% {c:8.2f}ms "
                  f"{s_:8.2f}ms  {'35Hz tic' if s_ > 0.5 else 'render'}")
        print(f"\n{100*tic_bound/n:.0f}% of frames are tic-bound: a compute saving "
              f"there buys nothing.\nCycles cut from the render-bound tail are "
              f"worth several times the same\ncycles cut everywhere -- see "
              f"MICRO-OPT-NEXT-STEPS.md.")
        return

    if args.counts:
        # Fields 1..3 are raw scene counts, not times: show each long frame's
        # scene state next to the all-frame mean so the difference is readable.
        cols = ("drawsegs", "visplns", "sprites")
        mean = [sum(r[k] for r in recs) / len(recs) for k in (1, 2, 3)]
        print(f"\nslowest {args.worst} frames vs scene counts:")
        print(f"  {'frame#':>7s} {'total':>8s} " + " ".join(f"{c:>8s}" for c in cols))
        for i in order[:args.worst]:
            r = recs[i]
            print(f"  {i:7d} {r[0]*UNIT_MS:8.2f} " +
                  " ".join(f"{r[k]:8d}" for k in (1, 2, 3)))
        print(f"  {'mean':>7s} {sum(frame_ms)/len(frame_ms):8.2f} " +
              " ".join(f"{m:8.1f}" for m in mean))
        return

    print(f"\nslowest {args.worst} frames (ms):  [frame# is window-relative]")
    cols = ("bsp", "plane", "sprites") if args.render else ("tic", "display", "blit")
    print(f"  {'frame#':>7s} {'total':>8s} " +
          " ".join(f"{c:>8s}" for c in cols) + f" {'other':>8s}")
    for i in order[:args.worst]:
        f, a, b_, c = (v * UNIT_MS for v in recs[i])
        other = f - a - b_ - c if args.render else max(0.0, f - a - b_)
        print(f"  {i:7d} {f:8.2f} {a:8.2f} {b_:8.2f} {c:8.2f} {other:8.2f}")


if __name__ == "__main__":
    main()
