#!/usr/bin/env python3
"""Report the adjustable PC-FX renderer instruction-cache layout.

The V810 has a direct-mapped 1 KiB instruction cache.  Absolute addresses are
less useful than each routine's address modulo 0x400, so this tool reports both,
plus the generated R_RenderSegLoop body found directly in linked disassembly.
"""

import argparse
import os
import re
import subprocess
import sys


DEFAULT_NM = "/opt/v810-gcc/bin/v810-nm"
DEFAULT_OBJDUMP = "/opt/v810-gcc/bin/v810-objdump"
CACHE_BYTES = 0x400

ROUTINES = (
    "_R_RenderSegLoop",
    "_pcfx_span_lit32",
    "_pcfx_column_lit64",
    "_R_DrawSegTextureColumn",
    "_pcfx_span32",
)

ANCHORS = (
    "__pcfx_renderhot_start",
    "__pcfx_renderseg_slot",
    "__pcfx_span_lit_slot",
    "__pcfx_column_lit_slot",
    "__pcfx_walldispatch_slot",
    "__pcfx_hot_core_end",
    "__pcfx_span32_slot",
    "__pcfx_renderhot_end",
)


def read_symbols(elf, nm):
    output = subprocess.check_output(
        [nm, "-nS", elf], text=True, errors="replace"
    )
    symbols = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 4:
            address, size, kind, name = fields
        elif len(fields) == 3:
            address, kind, name = fields
            size = "0"
        else:
            continue
        if not re.fullmatch(r"[0-9a-fA-F]+", address):
            continue
        symbols[name] = (int(address, 16), int(size, 16), kind)
    return symbols


def cache_range(address, size):
    first = address & (CACHE_BYTES - 1)
    if not size:
        return f"{first:03x}"
    last = (address + size - 1) & (CACHE_BYTES - 1)
    if first <= last and size <= CACHE_BYTES:
        return f"{first:03x}-{last:03x}"
    return f"{first:03x}-3ff,000-{last:03x}"


def require(symbols, names):
    missing = [name for name in names if name not in symbols]
    if missing:
        sys.exit("missing symbols in ELF: " + ", ".join(missing))


def find_outer_back_edge(elf, objdump, function, size):
    output = subprocess.check_output(
        [objdump, "-d", elf], text=True, errors="replace"
    )
    instruction = re.compile(
        r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s+)+)\s*(.*)$"
    )
    edges = []
    for line in output.splitlines():
        match = instruction.match(line)
        if not match:
            continue
        address = int(match.group(1), 16)
        if not (function <= address < function + size):
            continue
        target_match = re.search(r"\b([0-9a-f]+)\s+<_R_RenderSegLoop\+", match.group(3))
        if not target_match:
            continue
        target = int(target_match.group(1), 16)
        if function <= target < address:
            instruction_bytes = len(match.group(2).split())
            edges.append((address, target, address + instruction_bytes))
    if not edges:
        sys.exit("could not find R_RenderSegLoop backwards branch")
    return max(edges)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", default="build/doom_pcfx.elf")
    parser.add_argument("--nm", default=os.environ.get("V810_NM", DEFAULT_NM))
    parser.add_argument(
        "--objdump", default=os.environ.get("V810_OBJDUMP", DEFAULT_OBJDUMP)
    )
    args = parser.parse_args()

    symbols = read_symbols(args.elf, args.nm)
    require(symbols, ROUTINES + ANCHORS)
    base = symbols["__pcfx_renderhot_start"][0]

    print("PC-FX hot layout (1 KiB direct-mapped instruction cache)")
    print("routine                         address  offset  size  cache indices")
    for name in ROUTINES:
        address, size, _ = symbols[name]
        print(
            f"{name:31} {address:08x}  {address - base:05x}"
            f"  {size:04x}  {cache_range(address, size)}"
        )

    function, function_size, _ = symbols["_R_RenderSegLoop"]
    _, loop_start, loop_end = find_outer_back_edge(
        args.elf, args.objdump, function, function_size
    )
    loop_size = loop_end - loop_start
    suggested = (-(loop_start - function)) & (CACHE_BYTES - 1)

    print()
    print(
        "R_RenderSegLoop generated loop:"
        f" function+0x{loop_start - function:x}, {loop_size} bytes,"
        f" cache {cache_range(loop_start, loop_size)}"
    )
    print(
        "Geometric boundary candidate (benchmark before adopting):"
        f" PCFX_HOT_RENDERSEG_OFFSET=0x{suggested:x}"
    )
    if loop_size > CACHE_BYTES:
        print("ERROR: generated loop exceeds the 1 KiB cache", file=sys.stderr)
        return 1

    print()
    print("linker anchors                    address  offset  cache index")
    for name in ANCHORS:
        address, _, _ = symbols[name]
        print(
            f"{name:31} {address:08x}  {address - base:05x}"
            f"  {address & (CACHE_BYTES - 1):03x}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
