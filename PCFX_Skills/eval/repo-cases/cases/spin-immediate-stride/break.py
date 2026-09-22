#!/usr/bin/env python3
"""Break: a face-record stride uses ADD with an immediate the V810 cannot hold.

V810 `ADD imm5,reg` takes a SIGNED FIVE-BIT immediate: -16..15. GNU `as` accepts
a larger constant and truncates it silently, with no warning. `add 28,r6`
assembles as a different, wrong stride, so the batch walks the face records at
the wrong pitch and most of the model never reaches the rasterizer.

The symptom is the nasty one: the program still runs, still draws something, and
runs FASTER. This exact bug produced a "5.017 FPS" result here that had to be
withdrawn.

Taught by: pcfx-character-8bpp S5, pcfx-self-improve S6.
"""
import sys, pathlib

GOOD = "    addi    28,r6,r6              /* aligned TankFaceToDraw stride */"
BAD  = "    add     28,r6                 /* aligned TankFaceToDraw stride */"

p = pathlib.Path(sys.argv[1]) / "src" / "tank_raster_v810.S"
s = p.read_text()
assert GOOD in s, "expected face-record stride not found"
p.write_text(s.replace(GOOD, BAD))
print(f"broke {p}")
