#!/usr/bin/env python3
"""Break: fx_mul stops reading the V810 MUL high word out of r30.

The asm declares `hi` as an output it never writes, so GCC hands it an
unrelated register and every product's top 16 bits are garbage. Symptom:
every vertex projects off-screen and the screen stays black, while the clear,
the triangle fill and the page flip all still demonstrably work.

Taught by: pcfx-3d-pipeline S1b, pcfx-3d-from-scratch S4.
"""
import sys, pathlib

GOOD = '''    int lo, hi;
    __asm__ ("mul %2, %0\\n\\t"
             "mov r30, %1"
             : "=r"(lo), "=&r"(hi)
             : "r"(b), "0"(a)
             : "r30");'''

BAD = '''    int lo, hi;
    __asm__ ("mul %2, %0"
             : "=r"(lo), "=r"(hi)
             : "r"(b), "0"(a)
             : "r30");'''

p = pathlib.Path(sys.argv[1]) / "src" / "cube3d.c"
s = p.read_text()
assert GOOD in s, "template does not contain the expected fx_mul asm"
p.write_text(s.replace(GOOD, BAD))
print(f"broke {p}")
