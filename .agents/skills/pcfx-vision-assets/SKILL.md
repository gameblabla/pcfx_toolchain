---
name: pcfx-vision-assets
description: Using a local vision model to look at PC-FX screenshots and source artwork - the describe_image.py helper, which endpoint serves vision, what the model can and cannot reliably judge, when to ask the user for an image instead, and turning reference art into PC-FX assets. Use to check what a program actually drew, to triage a rendering bug from a screenshot, or when a task needs artwork the repo does not contain.
---

# Looking at images

A PC-FX agent is nearly blind without this: the emulator's only honest output is a
screenshot, and "did it draw the right thing?" cannot be answered from source.

## 1. Which endpoint can see

Vision is served by whichever llama.cpp endpoint has a **matching** projector:

- **`:8080`** — the main model with `--mmproj` attached. Works only if the projector's
  `clip.vision.projection_dim` equals the text model's `embedding_length`, and its
  `general.name` is the same model. `qwen.sh` checks this at startup and refuses a bad
  pair rather than accepting images and silently ignoring them.
- **`:8081`** — the CPU vision sidecar (a small self-consistent VL model), used
  automatically when the main projector is missing or mismatched.

```bash
python3 gguf_meta.py models/<mmproj>.gguf | grep projection_dim   # must match
python3 gguf_meta.py models/<text>.gguf   | grep embedding_length
```

⚠ **A mismatched projector is the cause of "vision does nothing".** The server starts,
accepts images, and produces text that ignores them — which reads as the model being
bad at vision rather than as a configuration error. Always verify the pair before
concluding anything about image quality.

## 2. The helper

```bash
python3 PCFX_Skills/pcfx-vision-assets/describe_image.py shot.png
python3 .../describe_image.py shot.png --prompt "Is the screen entirely black? Answer yes or no."
python3 .../describe_image.py before.png after.png --prompt "What differs between these two?"
```

It auto-detects the vision-capable endpoint (`:8080`, then `:8081`), prints which one
it used to stderr, and fails with instructions if neither can see.

The normal workflow:

```bash
$PCFXEMU/pcfx-headless --frames 1800 --screenshot shot.png game.cue
python3 .../describe_image.py shot.png --prompt "..."
```

Remember the ~1200-frame BIOS boot delay — a screenshot before that is the BIOS logo,
not your program ([pcfx-emulator-testing]).

## 3. What it can and cannot judge — read this before trusting an answer

The local vision models are small. They are **reliable on gross facts and unreliable on
quality judgements**, and they will confabulate defects if you invite them to.

**Ask these — the answers are trustworthy:**

| Question | Why it works |
|---|---|
| "Is the screen entirely black / a single flat colour?" | gross, unambiguous |
| "Is there any readable text? Transcribe it." | OCR-ish, usually right |
| "Roughly what fraction is filled vs. background?" | coarse spatial |
| "Are there large blocks of obviously garbage pixels?" | high-contrast structure |
| "Is this a title screen, a menu, or gameplay?" | scene classification |
| "Describe the layout: what is top, middle, bottom?" | coarse spatial |

**Do not ask these — the answers are confabulated:**

- "Are the colours correct?" — it cannot know your intended palette.
- "Is there tearing / banding / aliasing?" — asked to find defects, it will invent
  plausible ones. In testing it reported "inconsistent colours" and "lack of
  anti-aliasing" on a *correct* title screen.
- "Is this the right hue?" — YUV conversion errors are exactly the subtle kind it
  misses ([pcfx-yuv-palette]).
- Anything about *timing* — a screenshot cannot show when in the frame a write landed
  ([pcfx-emulator-testing]).

**Phrase for a yes/no or a count, not for an opinion.** "Is the screen black? Answer
only yes or no." beats "does this look right?" every time. A leading question produces
a leading answer.

**Never let a vision answer overrule a measurement.** If the profiler says the frame
costs 104% of a field, the model saying "looks smooth" is worthless.

## 4. Where it genuinely helps

- **Regression triage.** Screenshot before and after a change and ask what differs.
  Catches "the optimization worked because it stopped drawing" — the failure mode that
  fps measurement alone will happily call a win.
- **Boot triage.** "Black screen", "BIOS logo only", "garbage blocks" are exactly the
  gross classes it gets right, and they map to distinct causes in [pcfx-bringup].
- **Confirming a load.** After a CD→KRAM asset load, does the expected image appear at
  all? Structure, not fidelity.
- **Reading back on-screen debug text** you rendered, when you have no other console.

## 5. When to ask the user for an image

**Ask instead of guessing** whenever the task needs artwork or a visual target that
the repository does not contain:

- source art for a title screen, sprite sheet, texture or font
- a reference of what the output is *supposed* to look like
- a photo of the screen from **real hardware** — the only evidence for the whole class
  of bugs the emulator cannot show ([pcfx-emulator-testing])

Ask concretely and state the constraints, so what comes back is usable:

> To build the title screen I need the source artwork. Please put a PNG in
> `assets/title.png`. Constraints: 256×240 or smaller, and it will be reduced to
> 256 colours in the HuC6261's Y8U4V4 space — flat areas of colour survive that far
> better than gradients or dithering.

Then verify what you were given before building with it:

```bash
python3 -c "from PIL import Image; im=Image.open('assets/title.png'); \
print(im.size, im.mode, len(im.getcolors(1<<24) or []), 'distinct colours')"
python3 .../describe_image.py assets/title.png --prompt "Describe this image and its main colour regions."
```

Do not silently downscale or re-quantize art the user supplied without saying so — the
colour loss is the thing they will notice, and it belongs in your report.

## 6. Turning reference art into an asset

The pipeline is host-side Python; nothing here runs on the target:

1. Resize/crop to the target rectangle (Pillow), nearest-neighbour for pixel art.
2. Quantize to ≤256 colours, then convert the palette to Y8U4V4 with
   `PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py` ([pcfx-yuv-palette]).
3. Emit the pixel data in KING word order — **two horizontal pixels per word**, and
   getting the halves backwards is the classic swapped-pixel-pairs bug
   ([pcfx-king-framebuffer]).
4. Put it on the disc and load it ([pcfx-cd-assets]).
5. **Screenshot the result and compare it to the source with the vision model** —
   ask "what differs between these two images?", which is a comparison question and
   therefore one of the reliable ones.

## Related

[pcfx-emulator-testing] for capturing screenshots and what they do not prove ·
[pcfx-yuv-palette] for the colour conversion · [pcfx-king-framebuffer] for pixel
packing · [pcfx-cd-assets] for getting the asset onto the disc.
