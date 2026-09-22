#!/usr/bin/env python3
"""Small, streaming-safe helpers for PC-FX large-game builds.

The enhanced `pcfx-cdlink` consumes a boot binary plus external `append` files.
This tool generates its plain-text input and deterministic test payloads without
loading large assets into a single Python or C buffer.  The actual CD image
writer remains the enhanced C implementation in tools/large-game/pcfxtools.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SECTOR_SIZE = 2048


def sectors(byte_count: int) -> int:
    return (byte_count + SECTOR_SIZE - 1) // SECTOR_SIZE


def macro_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", path).upper()


def write_cdlink(args: argparse.Namespace) -> None:
    if not args.boot.exists():
        raise SystemExit(f"boot binary not found: {args.boot}")
    for asset in args.asset:
        asset_path = Path(asset)
        if not asset_path.exists():
            raise SystemExit(f"asset not found: {asset_path}")

    lines = [
        f"binary {args.boot}",
        *[f"append {asset}" for asset in args.asset],
        f"lbaheader {args.lba_header}",
        f"name {args.name}",
        f"maker {args.maker}",
        f"makerid {args.makerid}",
        f"date {args.date}",
        f"country {args.country}",
        f"version {args.version}",
    ]
    args.output.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.output}")
    print(f"boot sectors: {sectors(args.boot.stat().st_size)}")
    for asset in args.asset:
        path = Path(asset)
        print(f"append sectors: {path} = {sectors(path.stat().st_size)}")


def make_fixture(args: argparse.Namespace) -> None:
    if args.bytes < 0:
        raise SystemExit("--bytes must be non-negative")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    remaining = args.bytes
    block_size = 1024 * 1024
    with args.output.open("wb") as output:
        block_index = 0
        while remaining:
            count = min(remaining, block_size)
            block = bytes(((i + block_index * 17) * 29 + 7) & 0xFF for i in range(count))
            output.write(block)
            remaining -= count
            block_index += 1
    print(f"wrote deterministic fixture: {args.output} ({args.bytes} bytes)")


def inspect_lbas(args: argparse.Namespace) -> None:
    text = args.header.read_text()
    values = re.findall(r"^#define\s+(BINARY_LBA_[A-Z0-9_]+)\s+(\d+)\s*$", text, re.MULTILINE)
    if not values:
        raise SystemExit(f"no LBA defines found in {args.header}")
    for name, value in values:
        print(f"{name}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    cdlink = subparsers.add_parser("write-cdlink", help="write an enhanced pcfx-cdlink manifest")
    cdlink.add_argument("--boot", type=Path, required=True)
    cdlink.add_argument("--asset", action="append", default=[])
    cdlink.add_argument("--output", type=Path, required=True)
    cdlink.add_argument("--lba-header", type=Path, required=True)
    cdlink.add_argument("--name", default="PC-FX Homebrew")
    cdlink.add_argument("--maker", default="homebrew")
    cdlink.add_argument("--makerid", default="HBR")
    cdlink.add_argument("--date", default="20260922")
    cdlink.add_argument("--country", type=int, default=1)
    cdlink.add_argument("--version", type=int, default=256)
    cdlink.set_defaults(function=write_cdlink)

    fixture = subparsers.add_parser("make-fixture", help="make a deterministic large-asset test file")
    fixture.add_argument("output", type=Path)
    fixture.add_argument("--bytes", type=int, default=256 * 1024)
    fixture.set_defaults(function=make_fixture)

    lbas = subparsers.add_parser("inspect-lbas", help="print generated LBA macros")
    lbas.add_argument("header", type=Path)
    lbas.set_defaults(function=inspect_lbas)

    args = parser.parse_args()
    args.function(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
