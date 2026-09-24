#!/usr/bin/env python3
"""Measure a V810 counter over a fixed number of emulator video fields."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def symbol_address(nm, elf, name):
    output = subprocess.check_output([nm, "-n", str(elf)], text=True)
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2].lstrip("_") == name:
            return int(fields[0], 16)
    raise SystemExit("symbol %s missing in %s" % (name, elf))


def capture(headless, bios_dir, cue, fields, path):
    cmd = [str(headless), "--bios-dir", str(bios_dir), "--pcfx",
           "--frames", str(fields), "--dump", "ram", str(path), str(cue)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", required=True, type=Path)
    parser.add_argument("--bios-dir", required=True, type=Path)
    parser.add_argument("--cue", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--nm", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", type=int, default=1800)
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--minimum", type=int, default=60)
    args = parser.parse_args()
    if args.window <= 0 or args.start < 0:
        parser.error("start must be nonnegative and window must be positive")
    address = symbol_address(args.nm, args.elf, args.symbol)
    with tempfile.TemporaryDirectory(prefix="pcfx_cadence_") as folder:
        first = Path(folder) / "first.ram"
        second = Path(folder) / "second.ram"
        capture(args.headless, args.bios_dir, args.cue, args.start, first)
        capture(args.headless, args.bios_dir, args.cue,
                args.start + args.window, second)
        a = int.from_bytes(first.read_bytes()[address:address + 4], "little")
        b = int.from_bytes(second.read_bytes()[address:address + 4], "little")
    delta = (b - a) & 0xFFFFFFFF
    fps = 60.0 * delta / args.window
    print("%s: %d updates / %d fields = %.2f updates/s" %
          (args.symbol, delta, args.window, fps))
    if delta < args.minimum:
        raise SystemExit("FAIL: expected at least %d updates" % args.minimum)
    print("PASS")


if __name__ == "__main__":
    main()
