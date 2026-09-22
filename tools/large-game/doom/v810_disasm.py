#!/usr/bin/env python3
"""Disassemble a V810 function and annotate each instruction with the profiler's
per-address cycle / icache-miss data (32-byte-bucket resolution from the CSV that
pcfx-headless-prof writes via V810_PROF_OUT). Turns "R_RenderSegLoop is hot" into
"these exact instructions burn the cycles / miss the icache".

Usage:
  tools/v810_disasm.py _R_RenderSegLoop [--elf build/doom_pcfx.elf] [--csv hist.csv]
  tools/v810_disasm.py --top 5 --csv hist.csv          # disasm the 5 hottest functions
"""
import argparse, bisect, csv, re, subprocess, sys, os

OBJDUMP = os.environ.get("V810_OBJDUMP", "/opt/v810-gcc/bin/v810-objdump")
NM = os.environ.get("V810_NM", "/opt/v810-gcc/bin/v810-nm")
BSHIFT = 5  # must match v810_profile.h V810_PROF_BSHIFT (32-byte buckets)


def load_csv(path):
    """addr(bucket) -> (count, cycles, misses)"""
    d = {}
    if not path:
        return d
    with open(path) as f:
        for row in csv.DictReader(f):
            d[int(row["addr"], 16)] = (int(row["count"]), int(row["cycles"]), int(row["misses"]))
    return d


def top_functions(csv_path, n):
    """Aggregate CSV buckets to functions via nm, return the n hottest names."""
    out = subprocess.check_output([NM, "-nS", os.environ.get("ELF", "build/doom_pcfx.elf")],
                                  text=True, errors="replace")
    syms = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3 and p[-2] in ("t", "T", "w", "W"):
            try:
                syms.append((int(p[0], 16), p[-1]))
            except ValueError:
                pass
    syms.sort()
    addrs = [s[0] for s in syms]
    cyc = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            a = int(row["addr"], 16)
            i = bisect.bisect_right(addrs, a) - 1
            if i >= 0:
                cyc[syms[i][1]] = cyc.get(syms[i][1], 0) + int(row["cycles"])
    return [name for name, _ in sorted(cyc.items(), key=lambda kv: kv[1], reverse=True)[:n]]


def disasm(func, elf, cycmap):
    out = subprocess.check_output([OBJDUMP, "-d", elf], text=True, errors="replace")
    lines = out.splitlines()
    start = next((i for i, l in enumerate(lines) if re.search(r"<%s>:" % re.escape(func), l)), None)
    if start is None:
        print("!! function not found: %s" % func, file=sys.stderr)
        return
    print("\n===== %s =====" % func)
    print("  %-9s %-6s %-8s %s" % ("cyc/blk", "miss", "addr", "instruction"))
    line_re = re.compile(r"^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2} )+)\s*(.*)$")
    seen_bucket = None
    for l in lines[start + 1:]:
        if l.strip() == "" or re.match(r"^[0-9a-f]+ <", l):
            break
        m = line_re.match(l)
        if not m:
            continue
        addr = int(m.group(1), 16)
        bucket = (addr >> BSHIFT) << BSHIFT
        ann = "                  "
        if bucket != seen_bucket and bucket in cycmap:
            cnt, cyc, miss = cycmap[bucket]
            ann = "%9d %6d" % (cyc, miss)
            seen_bucket = bucket
        elif bucket != seen_bucket:
            seen_bucket = bucket
        print("  %s %-8x %s" % (ann, addr, m.group(3)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("func", nargs="?")
    ap.add_argument("--elf", default="build/doom_pcfx.elf")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--top", type=int, default=0)
    args = ap.parse_args()
    os.environ["ELF"] = args.elf
    cycmap = load_csv(args.csv)

    if args.top:
        if not args.csv:
            sys.exit("--top needs --csv")
        for fn in top_functions(args.csv, args.top):
            disasm(fn, args.elf, cycmap)
    elif args.func:
        disasm(args.func, args.elf, cycmap)
    else:
        sys.exit("give a function name or --top N --csv hist.csv")


if __name__ == "__main__":
    main()
