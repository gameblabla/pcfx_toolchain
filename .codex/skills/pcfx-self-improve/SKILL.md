---
name: pcfx-self-improve
description: The agent-level working loop for PC-FX - decide the next action from evidence, run the build/emulator/profiler yourself, brute-force a search when the answer is not derivable, check the picture with the vision model, ask the user for images or art when the repo lacks them, and record honest results. Use at the start of any multi-step PC-FX task, when stuck or looping, or when you are about to report a result.
---

# How to work on PC-FX without fooling yourself

Every other module in this bundle is knowledge. This one is **procedure**: what to do
next, how to know it worked, and what you are not allowed to claim. It is written for an
autonomous agent with shell access, and it assumes you will be wrong often — the loop is
designed so that being wrong is cheap and detectable.

The single rule underneath all of it: **you may only state what a command you ran
printed.** Not what the code implies, not what is usually true of similar hardware.

---

## 1. Start every task by establishing ground truth

Before trusting a code path or proposing a hardware-facing change, apply the repository
evidence hierarchy: original Japanese Hudson Soft manuals in
`DOCUMENTATION/ORIGINAL_JPN/`, then confirmed real-hardware tests recorded in the
skills, then `vendor/pcfxemu/` source, then SDK/local evidence and general knowledge.
This applies equally to a new project, bringing up a user's existing project,
debugging, refactoring, and optimization. `pcfxemu` tells you what the emulator does;
it does not prove retail hardware behavior. When sources disagree, record the conflict
and investigate the higher-priority source instead of averaging the claims.

Before proposing anything, spend three commands finding out where you actually are.

```bash
# 1. What is the project, and does it build at all?
ls; cat Makefile* 2>/dev/null | head -40; git -C . log --oneline | head -10

# 2. Does it build now? (never A/B against a stale object tree)
make clean && make cd 2>&1 | tail -20; echo "exit=$?"

# 3. What does it draw? (>=1800 frames — before that you get the BIOS logo)
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx \
    --frames 1800 --screenshot build/now.png game.cue
python3 "$PCFX_SKILLS/pcfx-vision-assets/describe_image.py" build/now.png \
    --prompt "Is the screen entirely black or a single flat colour? Answer yes or no, then describe the layout."
```

`make ... | tail` **hides a failed build** — the pipeline's exit status is `tail`'s. Check
`${PIPESTATUS[0]}` or run the build as its own command. Running the emulator on a stale
disc and then reasoning about the screenshot has wasted more time here than any other
mistake.

If the toolchain, emulator, or BIOS is missing: record the exact blocker, then still do
every safe local step (host tests, source audits, asset tooling). Do **not** invent a
result for a command you could not run.

---

## 2. The loop

```text
  observe ──► hypothesise ──► smallest change ──► measure ──► compare to gate
     ▲                                                            │
     └──────────────── record (win OR failure) ◄──────────────────┘
```

**One change at a time.** Two simultaneous edits produce a measurement you cannot
attribute, and on this machine the ±3% layout noise floor will happily assign the credit
to the wrong one.

Ordering, when the goal is speed — this order is not negotiable, because every stage
invalidates guesses made at the stage below it:

| Stage | Question | Module |
|---|---|---|
| 0 | Is it correct? | screenshots, host tests — never optimize a wrong program |
| 1 | Where do the cycles go? | [pcfx-v810-profiling] |
| 2 | Can I do less work? | [pcfx-software-3d], [pcfx-3d-from-scratch] §5 |
| 3 | Is memory behaviour wrong? | DRAM pages, then icache — [pcfx-v810-performance] |
| 4 | Which knob value wins? | [pcfx-optimize-loop] `search.py` |
| 5 | Can this loop be hand-scheduled? | [pcfx-3d-rasterizer] §4 — last resort |

Jumping to stage 5 on an unprofiled program is the characteristic failure of a model
that "knows assembly". Every unprofiled optimization attempted in this workspace was
either neutral or a regression.

---

## 3. Reading a profile: what each number sends you to

Run it (`pcfx-headless-prof`, stderr, at exit — [pcfx-v810-profiling] §1) and then read
the report as a *router*:

| Symptom in the report | What it means | Go to |
|---|---|---|
| High `% of a field` in one symbol | ordinary hot loop | reduce work there first |
| **CPI ≫ 2** | you are stalling, not executing | the two rows below |
| High **DRAM penalty cyc/field**, data | you cross 2 KiB pages constantly | cluster loads, interleave records |
| High **i-cache misses/field** | hot loop > 1 KB or two functions collide | split/shrink/realign functions |
| `IN_H`/`OUT_H` dominating | port traffic in a loop | latch the KRAM cursor once per span |
| High flag-stall % | compare feeding a branch immediately | reorder, or restructure the test |
| Fast, but the picture changed | you deleted work, not cost | screenshot diff, revert |

**The two PC-FX-specific stall mechanisms**, because they are what this hardware
punishes and generic CPU intuition misses entirely:

- **DRAM pages.** Main RAM has *one* globally open 2 KiB page; leaving it costs +3
  cycles. `colormap[texture[t]]` flips the open page **twice per pixel**. The fix is
  never "fewer instructions" — it is *clustering accesses to the same page*: read four
  source words, then four shadow words, rather than alternating. A change that adds
  instructions and removes page alternation usually wins.
- **The 1 KB direct-mapped icache.** Two hot functions whose addresses collide modulo
  1 KB evict each other every iteration, and the effect appears or vanishes when
  unrelated code is edited — that is the noise floor. Keep stages as separate compact
  routines, align hot sections to 1 KiB, and treat placement as a knob to be searched
  (§4), not reasoned about.

Map hot PC buckets back to functions with `v810_prof_symbols.py` rather than guessing
from the address.

---

## 4. When you cannot derive the answer, brute-force it

This is legitimate and expected on this machine. Placement, unroll factor and threshold
values are not predictable; the correct response is a **search over build knobs**.

```bash
# knobs must be Makefile `?=` variables or -D/--defsym values; the search never edits source
python3 "$PCFX_SKILLS/pcfx-optimize-loop/search.py" \
        --config search.json --strategy hill --budget 40
```

Rules that keep a brute-force search honest:

1. **Vary knobs, never source.** A search that edits code cannot be reverted or trusted.
2. **Every candidate gets a clean build.** Stale objects keep old flags.
3. **Score on one metric** you chose in advance (presented FPS, or cycles/field), and
   record the others alongside it.
4. **Re-measure the winner twice from the same warm savestate** before believing it.
5. **A win under ~3% is noise.** Report it as "no measurable change".
6. **Screenshot the winner.** A configuration that got faster by drawing less is a
   correctness regression wearing a speedup's clothes; this is the failure mode automated
   search creates most often.

If the search space is combinatorial and each build is slow, prefer hill-climbing from
the current default over a grid, and leave it running unattended — that is what the
ledger in `search.py` is for.

---

## 5. Look at the picture — but know what the vision model can judge

Numbers cannot tell you the render is correct, and source cannot either.

```bash
python3 "$PCFX_SKILLS/pcfx-vision-assets/describe_image.py" before.png after.png \
        --prompt "What differs between these two images?"
```

Ask for **gross facts and comparisons** (black/not black, layout, text, "what changed").
Do **not** ask for quality judgements ("do the colours look right?", "is there
banding?") — a small VL model asked to find defects will invent plausible ones, and has
done so here on a known-correct screen. Full reliability table: [pcfx-vision-assets] §3.
A vision answer never overrules a measurement.

**Ask the user for an image when the repository does not contain one**, instead of
inventing a placeholder:

- source art for a texture, title screen, sprite sheet or font;
- a reference for what the output is *supposed* to look like;
- a photo of a real PC-FX screen — the only evidence for the class of bugs the emulator
  cannot reproduce.

Ask concretely, with the constraints attached, so what comes back is usable:

> Please put the reference art at `assets/title.png`. Constraints: 256×240 or smaller;
> it will be reduced to 256 colours in the HuC6261's Y8U4V4 space, so flat colour areas
> survive far better than gradients or dithering.

Then verify what you were given (size, mode, colour count) before building with it, and
say so in your report if you had to resize or requantize it.

---

## 6. When you are stuck or looping

Stuck means: two consecutive changes did not move the number, or the same failure
reappeared. Do these in order rather than trying a third variation of the same idea.

1. **Re-read the module that owns the symptom** via the router in `SKILLS.md`, and copy
   its code blocks verbatim. Several are marked verbatim precisely because re-deriving
   them reintroduced off-by-one bugs.
2. **Grep history before re-running an experiment.** `git log`, `PERFORMANCE.md`,
   `verification/`, and the `NNNN-NN-NN-*.txt` session transcripts in each project
   record *why* things were done and which ideas were measured failures.
   ```bash
   grep -rniE "icache|dram page|unroll|tried|no measurable" --include=*.md --include=*.txt . | head -40
   ```
3. **Bisect the pipeline, do not stare at it.** Draw a static checkerboard, then one
   literal triangle, then the transformed mesh ([pcfx-3d-from-scratch] §6). Read KRAM
   back to separate "not drawn" from "not displayed".
4. **Suspect the artifacts.** A committed `.bin`/`.cue` is executable input, not a cache.
   If corrected source produces the old behaviour, rebuild the *disc*, not an object
   file, and check `git status` for stale generated outputs.
5. **Distrust hand-written assembly you just wrote.** Disassemble it. GNU `as` silently
   truncates out-of-range V810 immediates — `add 24,r20` assembles as `add -8,r20`,
   which in one real case walked a face loop backwards and produced a *faster*, visibly
   corrupted render. Signed 5-bit `ADD` range is **−16..15**; use `addi` above that.
6. **Reduce to a host test.** If the maths can run on x86 under `-DHOST_TEST`, get it
   right there against a geometric oracle before touching the target again. Remember
   what the host build stubs out — asm, I/O ports, the page flip — because "host test
   passes, screen is black" *localises* the bug rather than exonerating the code.
7. **Never disable a correct mechanism to make something appear.** Commenting out the
   backface cull, forcing a face visible, or drawing a debug rectangle in the frame loop
   changes the program you are debugging. Add the probe, read it, and **remove it in the
   same step**; a tree full of half-reverted probes is how a session stops converging.

**The failure shape to watch for in yourself:** you identify the right line, retype the
fix from memory instead of copying it, get an identical symptom back, and conclude the
diagnosis was wrong. It usually was not. Before abandoning a correct hypothesis, diff
your edit against the module's code block character by character — this exact loop, on a
missing `&` in an asm constraint, has burned an hour of agent time here.

---

## 7. Reporting — the part most likely to be wrong

Publish a number only when all of these hold:

```text
[ ] clean build from source, not a stale disc
[ ] two runs from the same warmed savestate, spread <= 3%
[ ] FPS derived from a presented-frame counter, not the HUD, not host wall clock
[ ] a screenshot proves the output is still correct
[ ] the asset/resolution contract is unchanged (or the change was requested)
[ ] failures and no-change results recorded alongside the win
```

**ANTI-PATTERN — the plausible number.** This appeared verbatim in a report here:

> FPS dropped from ~2.1 to ~2.7 — expected, since the previous "speedup" was actually
> drawing less geometry

The reasoning is sound, the direction is right, and **no profiler was run in that
session**. Both numbers were invented to decorate a correct diagnosis. Every figure you
publish must be traceable to a command whose output is in your own transcript; if you did
not run it, write "not measured" — that costs you nothing, because the fix stands on the
screenshot.

**ANTI-PATTERN — blaming code that never runs.** In the same session the agent "fixed"
two out-of-range immediates in a routine with **no callers**, and reported them as causes
of the corruption. They cannot be: the routine is not in the linked ELF. Before claiming
an instruction caused a symptom, prove it executes:

```bash
grep -rn "the_symbol" src/ --include=*.c --include=*.h    # is it called at all?
v810-nm build/*.elf | grep the_symbol                     # did it survive the link?
```

Finding dead code with the same defect is worth reporting — as a latent trap to clean up,
clearly separated from the bug you were asked to fix.

Say **"no measurable change"** when that is what happened; it is a valid, useful result
and it stops the next agent repeating the experiment. Report unavailable measurements as
`unavailable`, never as `0`. Never present a predicted improvement as a measured one,
and never claim hardware correctness from a clean emulator run — for timing bugs the
emulator proves nothing at all ([pcfx-emulator-testing] §7).

When a change works, commit the code and the newly learned fact **separately**: the code
to the project, the fact to the skill module that failed to prevent the bug. A bug that
this bundle should have prevented is a bug in this bundle.

---

## 8. Improving the bundle itself

`eval/` measures whether these modules actually teach what they claim, using real fixes
from this workspace's git history as gold answers.

```bash
# baseline: what the local model knows unaided
python3 PCFX_Skills/eval/build_prompt.py --mode none --out build/sys-none.md
python3 PCFX_Skills/eval/ask_qwen.py --system build/sys-none.md \
        --user PCFX_Skills/eval/cases/<case>/task.md \
        --out build/eval/<case>.none.md

# with the routed modules only — this is the arm that matters for a small context
python3 PCFX_Skills/eval/build_prompt.py --mode select \
        --skills pcfx-frame-timing,pcfx-emulator-testing \
        --out build/sys-sel.md
python3 PCFX_Skills/eval/ask_qwen.py --system build/sys-sel.md \
        --user PCFX_Skills/eval/cases/<case>/task.md \
        --out build/eval/<case>.select.md
```

The improvement loop: run a case → list the checkpoints the model missed → ask *why the
module failed to convey it* → change the module → re-run. Two failure patterns found so
far, both of which changed how every module is written:

- **Prose facts get re-derived, and the re-derivation is wrong.** State the fact *and*
  ship copy-paste code for anything with an edge case.
- **A fact does not displace a pattern.** Told the correct rule, the model still emitted
  the wrong shape it had been shown. Modules need explicit **ANTI-PATTERN** blocks that
  name the wrong code and give the replacement.

Add a case whenever you fix a bug that the bundle should have prevented: take the
pre-fix state, write the symptom as a human would report it (never name the fix), and
score against the commit.

## Related

[pcfx-v810-profiling] (the numbers) · [pcfx-optimize-loop] (`search.py`, the noise floor)
· [pcfx-v810-performance] (cost model, measured catalogue) · [pcfx-emulator-testing]
(running, savestates, what it cannot prove) · [pcfx-vision-assets] (seeing) ·
[pcfx-3d-from-scratch] (bring-up gates) · `SKILLS.md` (symptom router)
