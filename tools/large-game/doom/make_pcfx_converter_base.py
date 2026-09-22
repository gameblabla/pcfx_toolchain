#!/usr/bin/env python3
"""Build the compact base image consumed by final_converter/index.html."""

import argparse
import json
import pathlib
import re
import struct


MAGIC = b"DPCFXB01"
FILE_RE = re.compile(
    r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY\s*$',
    re.IGNORECASE | re.MULTILINE,
)
GENERATED_MUSIC_RE = re.compile(r"^doom_pcfx_song\d+\.bin$", re.IGNORECASE)


def build_base(cue_path):
    cue_text = cue_path.read_text(encoding="utf-8")
    names = []
    for match in FILE_RE.finditer(cue_text):
        name = match.group(1) or match.group(2)
        if name not in names and not GENERATED_MUSIC_RE.match(pathlib.Path(name).name):
            names.append(name)

    if not names:
        raise SystemExit(f"{cue_path}: no binary FILE entries found")

    payloads = []
    files = []
    offset = 0
    for name in names:
        path = cue_path.parent / name
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise SystemExit(f"{cue_path}: referenced file is missing: {path}") from None
        files.append({"name": name, "offset": offset, "length": len(data)})
        payloads.append(data)
        offset += len(data)

    manifest = {
        "cueName": cue_path.name,
        "cueText": cue_text,
        "files": files,
    }
    header = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    return MAGIC + struct.pack("<I", len(header)) + header + b"".join(payloads)


def write_if_changed(path, data):
    if path.exists() and path.read_bytes() == data:
        print(f"{path}: already current ({len(data)} bytes)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    print(f"{path}: wrote {len(data)} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cue", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    write_if_changed(args.output, build_base(args.cue))


if __name__ == "__main__":
    main()
