#!/usr/bin/env python3
"""Convert a little-endian V810 ELF into a HuEXE001 PC-FXGA executable.

The pcfxemu branch used by this toolkit recognizes the HuEXE001 container and
loads each segment from its big-endian segment table.  This converter keeps the
ELF PT_LOAD payloads, zeros BSS through each segment's memsz, and emits a compact
header.  The loader's documented/default entry address is 0x8000 when no public
__start/main export table is present, which is the normal address of the
libpcfx linker script.

This is intentionally a small format bridge, not a replacement for the official
PC-FXGA SDK.  It is useful for homebrew smoke tests and for bypassing the normal
PC-FX CD boot path.  A headless emulator run still needs a compatible BIOS image.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


ELF_MAGIC = b"\x7fELF"
PT_LOAD = 1
RAM_SIZE = 0x200000
HEADER_SIZE = 0x40
SEGMENT_SIZE = 0x30


@dataclass(frozen=True)
class Segment:
    offset: int
    vaddr: int
    filesz: int
    memsz: int
    flags: int
    align: int
    payload: bytes


def elf_load_segments(data: bytes) -> tuple[int, list[Segment]]:
    if len(data) < 52 or data[:4] != ELF_MAGIC:
        raise ValueError("input is not an ELF file")
    if data[4] != 1 or data[5] != 1:
        raise ValueError("only ELF32 little-endian input is supported")

    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    entry, phoff, phentsize, phnum = fields[3], fields[4], fields[8], fields[9]
    if phentsize < 32:
        raise ValueError(f"invalid ELF program-header size: {phentsize}")
    if phoff + phentsize * phnum > len(data):
        raise ValueError("ELF program-header table is outside the file")

    segments: list[Segment] = []
    for index in range(phnum):
        base = phoff + index * phentsize
        p_type, p_offset, p_vaddr, _p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(
            "<IIIIIIII", data, base
        )
        if p_type != PT_LOAD or p_memsz == 0:
            continue
        if p_filesz > p_memsz:
            raise ValueError(f"PT_LOAD {index} has filesz > memsz")
        if p_offset + p_filesz > len(data):
            raise ValueError(f"PT_LOAD {index} payload is outside the ELF")
        if p_vaddr >= RAM_SIZE or p_memsz > RAM_SIZE - p_vaddr:
            raise ValueError(f"PT_LOAD {index} does not fit in 2 MiB RAM")
        segments.append(
            Segment(
                offset=p_offset,
                vaddr=p_vaddr,
                filesz=p_filesz,
                memsz=p_memsz,
                flags=p_flags,
                align=p_align,
                payload=data[p_offset : p_offset + p_filesz],
            )
        )

    if not segments:
        raise ValueError("ELF contains no non-empty PT_LOAD segments")
    if len(segments) > 256:
        raise ValueError("HuEXE supports at most 256 segments")
    return entry, segments


def build_huexe(data: bytes) -> tuple[int, list[Segment], bytes]:
    entry, segments = elf_load_segments(data)
    output_offset = HEADER_SIZE + SEGMENT_SIZE * len(segments)
    records = bytearray(SEGMENT_SIZE * len(segments))
    payloads: list[tuple[int, bytes]] = []

    for index, segment in enumerate(segments):
        aligned_offset = (output_offset + 15) & ~15
        # The current pcfxemu loader copies `memsz` bytes from file_off and
        # zeros only when the file ends first. Store each segment's BSS tail
        # explicitly so a following segment can never be mistaken for data.
        segment_payload = segment.payload + bytes(segment.memsz - segment.filesz)
        output_offset = aligned_offset + segment.memsz
        payloads.append((aligned_offset, segment_payload))
        record = memoryview(records)[index * SEGMENT_SIZE : (index + 1) * SEGMENT_SIZE]
        label = f"SEG{index:02d}".encode("ascii")
        record[: len(label)] = label
        # HuEXE_LoadSegments reads these fields as big-endian values.
        struct.pack_into(">I", record, 0x10, aligned_offset)
        struct.pack_into(">I", record, 0x14, segment.memsz)
        struct.pack_into(">I", record, 0x18, segment.filesz)
        struct.pack_into(">I", record, 0x1C, segment.flags)
        struct.pack_into(">I", record, 0x20, segment.align)
        struct.pack_into(">I", record, 0x24, segment.vaddr)

    output = bytearray(output_offset)
    output[:8] = b"HuEXE001"
    struct.pack_into(">I", output, 0x0C, len(segments))
    output[HEADER_SIZE : HEADER_SIZE + len(records)] = records
    for offset, payload in payloads:
        output[offset : offset + len(payload)] = payload
    return entry, segments, bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_elf", type=Path)
    parser.add_argument("output_exe", type=Path)
    parser.add_argument("--inspect", action="store_true", help="print the converted segments")
    args = parser.parse_args()

    data = args.input_elf.read_bytes()
    entry, segments, output = build_huexe(data)
    args.output_exe.parent.mkdir(parents=True, exist_ok=True)
    args.output_exe.write_bytes(output)

    print(f"HuEXE001: {args.output_exe} ({len(output)} bytes, {len(segments)} segments)")
    print(f"ELF entry: 0x{entry:08x} (HuEXE fallback entry is 0x00008000 without exports)")
    if args.inspect:
        for index, segment in enumerate(segments):
            print(
                f"  {index}: vaddr=0x{segment.vaddr:08x} "
                f"file={segment.filesz:#x} mem={segment.memsz:#x} flags={segment.flags:#x}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
