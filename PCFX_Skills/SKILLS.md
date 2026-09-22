# PC-FX skill bundle — index and router

Twenty-six knowledge modules for PC-FX homebrew. Each is a directory with a
`SKILL.md`; some ship runnable tools next to it.

**How to use this file: find your symptom or task in §1, open only the modules it
names, and follow them literally.** They record what was measured on real hardware and
override general intuition about the machine. Do not load all of them at once unless
you have the context budget — §2 lists what each one is for.

---

## 1. Router — go from symptom to module

### Starting or building

| Situation | Read |
|---|---|
| New project from zero | **pcfx-bringup** |
| New **3D** project from zero, or an asset and no code | **pcfx-3d-from-scratch**, then pcfx-bringup |
| Not sure what to do next / stuck / about to report a result | **pcfx-self-improve** |
| Won't boot / BIOS logo only / black screen / hang | **pcfx-bringup**, then pcfx-frame-timing §2 |
| Link errors, bad CD image | **pcfx-bringup** |
| Adding assets, loading at runtime, out of RAM | **pcfx-cd-assets** |
| Strict renderer: no newlib/libc, float, int64, software helpers, timer or IRQ handler | **pcfx-freestanding-runtime** |

### It draws the wrong thing

| Situation | Read |
|---|---|
| Bitmap / software-rendered output | **pcfx-king-framebuffer** |
| Software-3D renderer black/blank; transform or page-flip bugs | **pcfx-3d-pipeline §1 first** — it names both causes — then pcfx-king-framebuffer, pcfx-emulator-testing |
| "Every piece works in isolation but the renderer draws nothing" | **pcfx-3d-pipeline §1b** (the MUL high word), then §1a (the CG-base units) |
| Horizontal pixel pairs swapped | **pcfx-king-framebuffer** (two pixels per word) |
| Tiles, sprites, scrolling, sprite order | **pcfx-vdc-tiles-sprites** |
| Colours wrong, muddy, grey; baking art | **pcfx-yuv-palette** |
| Need to *prove* a colour is right, not just eyeball it; suspect a wrong colour-format assumption (RGB332/RGB555 instead of YUV) | **pcfx-color-verification** |
| Two subsystems corrupting each other's memory | **pcfx-kram-layout** |
| Tearing, flicker, one-field glitches | **pcfx-frame-timing** |
| Colour-noise bands, especially on real hardware only | **pcfx-frame-timing** §3 |
| Looks right in emulator, wrong on hardware | **pcfx-emulator-testing** §7 |

### It's too slow

| Situation | Read (in this order) |
|---|---|
| Any performance work at all | **pcfx-v810-profiling** first — always |
| Understanding the cost model | **pcfx-v810-performance**, **pcfx-v810-cpu-model** |
| Tuning placement / unroll / thresholds | **pcfx-optimize-loop** |
| A 3D renderer's design and budget | **pcfx-software-3d** |
| One large textured mesh must stay intact; 8bpp, outlines, target FPS | **pcfx-character-8bpp**, after profiling/performance |
| The answer is not derivable — placement, unroll, thresholds | **pcfx-self-improve** §4, **pcfx-optimize-loop** |
| Shared skeleton, compatible COLLADA clips, runtime animation/movement, compressed clip archive | **pcfx-character-animation**, plus pcfx-character-8bpp and pcfx-cd-assets |
| A per-pixel inner loop, span/column drawer, texture mapper | **pcfx-3d-rasterizer**, with **pcfx-v810-performance** |
| A `float` appears anywhere | **pcfx-fixed-point** |
| Hidden libc/libgcc calls, software divide helpers, timer/IRQ overhead | **pcfx-freestanding-runtime** |

### Other

| Situation | Read |
|---|---|
| Buttons, pad, mouse, scripted input | **pcfx-input** |
| Sound effects, music, wrong pitch, garbage audio | **pcfx-audio** |
| Need real working CD-DA/ADPCM/VDC/KING/microcode code, not only concepts | **pcfx-2d-code-examples** |
| Running/screenshotting/measuring the program | **pcfx-emulator-testing** |
| Need to see a screenshot, or need art from the user | **pcfx-vision-assets** |

### Cross-cutting rules that catch most bugs

1. **Profile before optimizing.** Every unprofiled guess made here was wrong.
   Multiplies are cheap on this machine; *compares* and *port reads* are expensive.
2. **A clean emulator run does not prove hardware correctness** — and for timing bugs
   it proves nothing at all. See pcfx-emulator-testing §7.
3. **No floats in a performance-critical renderer.** There is no FPU; a `float` links
   soft-float and can evict the hot loop from a 1 KB cache. For a strict no-runtime
   target, also audit the final map/ELF with **pcfx-freestanding-runtime**.
4. **Vertical blanking is raster 262 and 0..21**, not `>= 240`. Anything timing
   sensitive goes there and nowhere else.
5. **Define hardware constants once**, from the manual, and share them. Four private
   copies of a wrong predicate is a real bug that happened here.
6. **Report what you measured, including nothing.** "No measurable change" is a valid
   result; a 0.3% delta is not a speedup.

---

## 2. The modules

| Module | Covers | Ships |
|---|---|---|
| `pcfx-bringup` | toolchain, linker script, crt0, disc build, working template | `template/` |
| `pcfx-3d-pipeline` | verified 60 fps rotating-cube template, the two black-screen traps, page flipping, on-target verification | `template/` |
| `pcfx-3d-rasterizer` | span/column kernels in C and V810 asm, DRAM-page load clustering, edge stepping without divides, clipping | |
| `pcfx-3d-from-scratch` | output contract, renderer class, asset pipeline, frame chain, bring-up gates | |
| `pcfx-self-improve` | the agent loop: ground truth, profile routing, brute force, vision checks, honest reporting | |
| `pcfx-cd-assets` | LBA mechanism, CD→RAM/KRAM, DMA vs PIO, RAM budget | |
| `pcfx-kram-layout` | KRAM pages, per-engine routing, coexistence, corruption | |
| `pcfx-king-framebuffer` | BG0 256-colour bitmap, KRAM layout, double buffering | |
| `pcfx-vdc-tiles-sprites` | the two HuC6270s, BAT, SAT, scrolling, layering | |
| `pcfx-yuv-palette` | HuC6261 Y8U4V4, RGB conversion, palette layout | `rgb_to_yuv.py` |
| `pcfx-color-verification` | numeric proof of on-screen colour vs. intended palette word; names wrong-colour-format bugs (RGB332/RGB555/RGB444 vs. real YUV) | `check_palette_reference.py` |
| `pcfx-frame-timing` | raster double-read bug, vblank window, 60/N, timer IRQ | |
| `pcfx-input` | FX-Pad and mouse, button masks, edge detection, scripting | |
| `pcfx-audio` | KING ADPCM, PSG, CD-DA, KRAM contention | |
| `pcfx-2d-code-examples` | Copy-pasteable CD-DA/ADPCM, VDC 16-colour and 256-colour dual-VDC, KING scrolling, and microcode examples from working projects | |
| `pcfx-emulator-testing` | pcfx-headless, boot delay, input files, what it can't prove | |
| `pcfx-v810-performance` | instruction costs, icache, DRAM page, measured catalogue | |
| `pcfx-v810-cpu-model` | emulator cycle-model implementation, stalls, validation boundaries | |
| `pcfx-v810-profiling` | the profiler: CPI, icache, DRAM, flag stalls, hot PCs | |
| `pcfx-optimize-loop` | build knobs, automated search, noise floor, recording results | `search.py` |
| `pcfx-software-3d` | budgets, LOD, viewport, feasibility of a 3D design | |
| `pcfx-character-8bpp` | one large textured mesh kept intact, native 256x240 affine packing, UV/atlas fidelity, conditional finite-state output streams, compact scheduling, outlines | |
| `pcfx-character-animation` | any shared COLLADA base rig, influence-safe mesh, preserved root/body motion, manifest clips, PCA1 object-space animation, LZ4, CD DMA, viewer controls | |
| `pcfx-freestanding-runtime` | no newlib/libgcc/soft-float/int64/software-div/IRQ-handler runtime; source and ELF audits | |
| `pcfx-fixed-point` | 16.16 / 8.8, mul/div idioms, tables, conversion procedure | |
| `pcfx-vision-assets` | looking at screenshots, asking the user for art | `describe_image.py` |

`AGENTS.md` holds the project conventions and applies to all of them.

---

## 3. Using this bundle outside Claude Code

Nothing here depends on Claude. The modules are plain Markdown.

**With `pi`:**

```bash
# The wrapper points pi at the local server and, by default, ships only this
# router -- the agent then reads the one module it needs. On a local 27B that
# is the difference between a usable agent loop and a stalled one.
./PCFX_Skills/pi_pcfx.sh "your task"

# Preload every module instead (one-shot questions; ~60k tokens per turn):
PCFX_SKILL_MODE=full ./PCFX_Skills/pi_pcfx.sh "your task"
```

**With any OpenAI-compatible client:** concatenate what you need into the system
prompt. `eval/build_prompt.py` does this:

```bash
python3 PCFX_Skills/eval/build_prompt.py --mode all --out sys.md
python3 PCFX_Skills/eval/build_prompt.py --mode select \
        --skills pcfx-frame-timing,pcfx-emulator-testing --out sys.md
```

The full bundle is ~40k tokens — fine for a 128k-context model, but `--mode select`
via the router in §1 gives better answers, because the relevant module is not buried.

**Checking the bundle still teaches what it should:** `eval/` holds regression cases
built from real fixes in this workspace's git history, with a scorecard of how the
local model does with and without the bundle. See `eval/README.md`.
