#!/usr/bin/env python3
"""Fit square-pixel source art to the PC-FX's 4:3 display frame."""

import argparse
from pathlib import Path

from PIL import Image, ImageOps


FRAME = (320, 240)  # square-pixel 4:3 frame; raster is resampled to 256x240
RASTER = (256, 240)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fit", choices=("contain", "crop", "stretch"), default="contain")
    args = parser.parse_args()

    with Image.open(args.source) as image:
        image = image.convert("RGB")
        if args.fit == "contain":
            fitted = ImageOps.contain(image, FRAME, method=Image.Resampling.LANCZOS)
            frame = Image.new("RGB", FRAME, (0, 0, 0))
            frame.paste(fitted, ((FRAME[0] - fitted.width) // 2,
                                 (FRAME[1] - fitted.height) // 2))
        elif args.fit == "crop":
            frame = ImageOps.fit(image, FRAME, method=Image.Resampling.LANCZOS)
        else:
            frame = image.resize(FRAME, Image.Resampling.LANCZOS)

    raster = frame.resize(RASTER, Image.Resampling.LANCZOS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raster.save(args.output)
    print(f"{args.source} -> {args.output}: {raster.width}x{raster.height} ({args.fit})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
