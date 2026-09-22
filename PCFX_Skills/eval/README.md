# Skill-bundle regression eval

The bundle exists to make a **local** model (Qwen 3.6 27B on llama.cpp) reach the
answers Claude reached on this workspace's real bugs. This directory measures whether
it does, so the skills can be improved against evidence instead of taste.

## Method

Each case is a real fix from the git history of `doom-pcfx`, `descent-pcfx`,
`wolf-pcfx`, or `3DCharacterSpinning`. The commit is the **gold answer**. The model is given the state *before*
the fix — the symptom as a human would report it, plus the buggy code — and asked to
diagnose and patch. Its answer is scored against checkpoints taken from the commit.

Three arms per case:

| Arm | System prompt | Question it answers |
|---|---|---|
| `none` | no bundle | what the model knows on its own |
| `all` | whole bundle | does the bundle help |
| `select` | only the routed modules | is the router enough |

The `none` arm is the important one: it shows the failure mode the bundle must
suppress. On the first case the unaided model invented a vblank range *and* two
plausible-looking manual section numbers that do not exist.

## Running

```bash
# Start any OpenAI-compatible local server and set PCFX_LLM_ENDPOINT if it is not
# listening on the default http://127.0.0.1:8080.
python3 PCFX_Skills/eval/build_prompt.py --mode all --out build/eval/sys.md
python3 PCFX_Skills/eval/ask_qwen.py --system build/eval/sys.md \
        --user PCFX_Skills/eval/cases/vblank-window/task.md \
        --out build/eval/results/vblank-window.all.md
```

`build_prompt.py --mode select --skills a,b` builds a routed prompt.
`ask_qwen.py` talks to `0.0.0.0:8080` (OpenAI-compatible) and captures reasoning
content when the server emits it.

## Adding a case

1. Pick a commit that fixed a real, diagnosable defect:
   `git log --oneline` in one of the ports.
2. `git worktree add build/eval/wt-<sha> <sha>~1` to get the pre-fix state.
3. Write `cases/<id>/task.md`: the symptom as a *human* would report it (not the
   answer), plus the relevant buggy code. **Never name the fix in the prompt.**
4. Take checkpoints from the commit message and diff, and add a column to
   `results/SCORECARD.md`.

Good cases have a symptom that is misleading on its face — the value of the bundle is
in redirecting a plausible-but-wrong diagnosis.

## The improvement loop

Run a case → find which checkpoints the model missed → ask *why the bundle failed to
convey it* → change the bundle → re-run. `results/SCORECARD.md` records each round and
the reasoning behind each edit.

Two failure patterns found so far, both of which changed how the modules are written:

- **Prose facts get re-derived, and the re-derivation is wrong.** Stating "active
  picture is 22…261" produced a predicate testing `>= 261`. Ship copy-paste code for
  anything with an edge case.
- **A fact does not displace a pattern.** Told the correct blanking window, the model
  still emitted the `spin_to(240)` shape from the buggy code it was shown. Modules
  need explicit ANTI-PATTERN blocks naming the wrong shape and giving the
  replacement call.

Both fixes generalize, and both were worth more than the specific case that found them.

### Character animation archive case

Prompt a candidate agent to add a new compatible COLLADA animation to a PC-FX character
viewer. A passing answer must select `pcfx-character-animation`, preserve influence seams,
reject mismatched rigs, store object-space rather than screen-space frames, use raw LZ4
blocks with the external two-byte length, append the archive after the boot image, include
the page-1 KRAM address qualifier for DMA, and validate controls plus profiler counters.
An answer that recommends 128 pre-rendered screen poses fails because the animation set and
world transform are extensible.

### RAINBOW player cases (2026-09-22)

`libpcfx-port-black-screen`, `rainbow-right-edge` and `vdc-status-frame-wait` come from
repairing a RAINBOW+MP2 player after two agent sessions (one a small model) left it a
black screen. Selected arms: see `results/SCORECARD.md`. They added the third failure
pattern:

- **A rule stated for one thing gets applied to its neighbour.** "KRAM is not
  memory-mapped" became "`0x80000400` is main RAM". State the boundary of every rule
  (here: `0x80000000–0x807FFFFF` is the I/O-port alias).
