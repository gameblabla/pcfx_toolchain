#!/usr/bin/env python3
"""Map a V810 profiler PC-histogram CSV to function names via the linked ELF.

The profiler (pcfxemu built with PROFILE=1) writes a per-bucket CSV when the
env var V810_PROF_OUT is set:  addr,count,cycles,misses  (see v810_profile.c).
This aggregates those 32-byte buckets up to functions using `v810-nm -nS`, so
you get a flat per-function profile: where cycles go and where the 1 KB icache
thrashes.

Usage:
  V810_PROF_OUT=hist.csv pcfx-headless-prof ... doom_pcfx.cue
  tools/v810_prof_symbols.py hist.csv [--elf build/doom_pcfx.elf] [--sort cycles|misses|count] [--top 40]
"""
import argparse, bisect, csv, subprocess, sys, os

NM = os.environ.get("V810_NM", "/opt/v810-gcc/bin/v810-nm")


def load_symbols(elf):
    """Return (addrs_sorted, [(addr, size, name), ...]) for text symbols."""
    out = subprocess.check_output([NM, "-nS", elf], text=True, errors="replace")
    syms = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4:
            addr, size, typ, name = parts
        elif len(parts) == 3:
            addr, typ, name = parts
            size = "0"
        else:
            continue
        if typ not in ("t", "T", "w", "W"):
            continue
        try:
            syms.append((int(addr, 16), int(size, 16), name))
        except ValueError:
            continue
    syms.sort()
    return [s[0] for s in syms], syms


def resolve(addr, addrs, syms):
    i = bisect.bisect_right(addrs, addr) - 1
    if i < 0:
        return "(below .text)"
    a, size, name = syms[i]
    if size and addr >= a + size:
        return "(gap after %s)" % name
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--elf", default="build/doom_pcfx.elf")
    ap.add_argument("--sort", default="cycles", choices=["cycles", "misses", "count"])
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()

    if not os.path.exists(args.elf):
        sys.exit("ELF not found: %s (pass --elf)" % args.elf)
    addrs, syms = load_symbols(args.elf)

    agg = {}  # name -> [count, cycles, misses]
    tot = [0, 0, 0]
    with open(args.csv) as f:
        for row in csv.DictReader(f):
            a = int(row["addr"], 16)
            c, cy, m = int(row["count"]), int(row["cycles"]), int(row["misses"])
            name = resolve(a, addrs, syms)
            e = agg.setdefault(name, [0, 0, 0])
            e[0] += c; e[1] += cy; e[2] += m
            tot[0] += c; tot[1] += cy; tot[2] += m

    key = {"count": 0, "cycles": 1, "misses": 2}[args.sort]
    rows = sorted(agg.items(), key=lambda kv: kv[1][key], reverse=True)

    print("# per-function V810 profile  (RAM-resident code only; BIOS/libc not symbolised here)")
    print("# totals: count=%d  cycles=%d  misses=%d" % (tot[0], tot[1], tot[2]))
    print("%-34s %13s %6s %14s %6s %12s %6s" %
          ("function", "count", "%cnt", "cycles", "%cyc", "icache-miss", "%miss"))
    for name, (c, cy, m) in rows[:args.top]:
        print("%-34s %13d %5.1f%% %14d %5.1f%% %12d %5.1f%%" % (
            name[:34], c, 100.0 * c / (tot[0] or 1), cy, 100.0 * cy / (tot[1] or 1),
            m, 100.0 * m / (tot[2] or 1)))


if __name__ == "__main__":
    main()
