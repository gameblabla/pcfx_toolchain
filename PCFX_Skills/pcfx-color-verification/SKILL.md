---
name: pcfx-color-verification
description: Numerically verify on-screen PC-FX colour against the palette words you wrote, instead of eyeballing a screenshot. Names the specific wrong-colour-format bug (RGB332/RGB555/RGB444 assumed instead of the real Y8U4V4) when it happens. Use whenever a colour claim needs proof - before committing palette work, after any change that touches Tetsu/VCE palette writes, or when a colour "looks off" and eyeballing hasn't settled it.
---

# Proving a colour is right, not just guessing it looks right

[pcfx-yuv-palette] tells you how to bake a correct Y8U4V4 palette. This skill is the
other half: **proving the pixel that actually landed on screen is the pixel you
intended**, with a number, not an impression.

This matters because the failure mode is specifically invisible to eyeballing:
[pcfx-vision-assets] §3 already documents that a vision model **cannot** catch a wrong
colour-format assumption ("YUV conversion errors are exactly the subtle kind it
misses"). A model that has never internalised "PC-FX palette = Y8U4V4" will readily
assume RGB332, RGB555, or RGB444 for a 16-bit palette word — all three are common,
plausible-sounding wrong guesses, and a screenshot produced from any of them still
looks like "a colour", not like an error. **A confidently wrong colour-format
assumption produces a confidently wrong screenshot that nothing but a numeric check
will catch.**

## The tool

`check_palette_reference.py` decodes a palette word the correct way (Y8U4V4, bit-exact
with `pcfx-yuv-palette/rgb_to_yuv.py`) and, if the actual pixel doesn't match within
tolerance, **also decodes it as RGB332, RGB555, RGB565, and RGB444** and reports which
wrong decode the actual pixel matches. This turns "colours look muddy" into "the
palette word is being read as RGB565 somewhere in the pipeline" — a bug you can
actually go fix.

```bash
# Check specific pixels against the palette words your code wrote there:
python3 PCFX_Skills/pcfx-color-verification/check_palette_reference.py shot.png \
    --sample 10,10=0x506F --sample 40,10=0x9730 --tolerance 12

# Or batch from a CSV (x,y,word per line):
python3 PCFX_Skills/pcfx-color-verification/check_palette_reference.py shot.png \
    --samples-file samples.csv

# Or a full exact pixel diff against a known-good reference screenshot
# (same technique as PCFX_Skills/eval/repo-cases/verify_reference.py):
python3 PCFX_Skills/pcfx-color-verification/check_palette_reference.py shot.png \
    --reference known_good.png
```

A failing sample looks like this, and names the bug instead of describing a vibe:

```
FAIL ( 10, 10) word=0x506F expected(YUV)=(207, 27, 14) actual=(82, 12, 123) err=166.5
     closest match: RGB565 -> (82, 12, 123)
     *** on-screen colour matches a RGB565 decode, not Y8U4V4. The palette word is
     very likely being interpreted with the wrong colour format somewhere in the
     pipeline (art bake, palette upload, or emulator/backend decode). See
     pcfx-yuv-palette.
```

## When to run it

1. **Before claiming a palette/colour change is done.** "I wrote `tetsu_set_palette`
   calls and the screenshot has colour in it" is not verification — a wrong-format
   decode also produces colour. Sample at least one pixel per distinct colour you
   changed.
2. **Any time a colour "looks off" and you're tempted to eyeball-tune it.** Tuning by
   eye against a wrong hypothesis (e.g. adjusting U/V assuming RGB) wastes cycles the
   numeric check would have saved immediately. Run the tool first.
3. **After touching anything between the palette table and the screen** — the KRAM
   burst writer, a palette-upload timing fix, the emulator's Tetsu/VCE decode, or an
   asset-bake step ([pcfx-king-framebuffer], [pcfx-frame-timing]). Any of these can
   silently reinterpret the word.
4. **When porting a colour routine from a different console's skill/notes.** Other
   8/16-bit machines the model has seen far more of (Mega Drive CRAM, SNES, Game Boy
   Advance) use RGB-family formats. Muscle memory from those is exactly what produces
   the RGB332/RGB555 guess here — see the table in `AGENTS.md` §0.

## Getting sample coordinates and words

Pick a handful of pixels whose expected colour you know exactly, because you wrote the
palette entry yourself:

- Solid single-colour regions (a background fill, a HUD panel) are easiest — pick any
  interior pixel, well away from edges/antialiasing.
- Use the exact word from your source, not a re-derived guess. If your code does
  `tetsu_set_palette(5, 0x506F)` and later draws with palette index 5 at some known
  pixel, sample that pixel with `--sample x,y=0x506F`.
- For a full scene, `--reference` against a screenshot taken from a commit already
  known to render correctly is faster than hand-picking samples — any pixel diff is
  worth explaining even if the cause turns out to be geometry, not colour.

## What this does not replace

- It does not replace [pcfx-yuv-palette]'s conversion or its `forbid_grey` /
  `Y = 1 for black` rules — bake the palette correctly first.
- It does not replace [pcfx-vision-assets] for gross checks (black screen, garbage
  blocks, wrong scene). Use vision for structure, this tool for colour correctness —
  they check different things and neither substitutes for the other.
- A `--reference` diff of 0 pixels only proves this run matches that prior run bit for
  bit; it does not prove the prior run was itself correct. Anchor at least one
  `--sample` check to a palette word you can justify by hand.

## Related

[pcfx-yuv-palette] for baking the palette correctly in the first place ·
[pcfx-vision-assets] for what a vision model can and cannot judge, and why colour
format bugs are in the "cannot" list · [pcfx-king-framebuffer] for where a pixel could
get reinterpreted between palette and screen · [pcfx-frame-timing] for when palette
writes are safe to issue.
