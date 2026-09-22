# PC-FX project — how to use the skill bundle

You are working on PC-FX homebrew (NEC PC-FX, 1994: V810 CPU at 21.477 MHz, KING +
HuC6261 + two HuC6270 video chips, 2 MB main RAM, no FPU, no hardware 3D).

A skill bundle is available at `PCFX_Skills/`. It records what was **measured on real
PC-FX hardware** in this workspace. **When it contradicts your general knowledge of
retro consoles or CPUs, the bundle is right and you are wrong.** Do not reason from
what is usually true of similar hardware.

## Evidence priority

For hardware-facing claims and decisions, including new bring-up, bringing up an
existing project, debugging, refactoring, and optimization, resolve conflicts in this
order:

1. Original Japanese Hudson Soft manuals in `DOCUMENTATION/ORIGINAL_JPN/` (the English
   translation is incomplete and is only a convenience).
2. Confirmed real-hardware tests documented in the skills.
3. `vendor/pcfxemu/` source, which is authoritative for emulator behavior only.
4. SDK/examples, local project evidence, emulator output, and general knowledge.

Do not turn an emulator result into a retail-hardware claim. If sources conflict, state
the conflict and keep the higher-priority source in control rather than inventing a
compromise.

## Before answering any PC-FX question

0. If you are starting a task, are stuck, or are about to report a result, read
   `PCFX_Skills/pcfx-self-improve/SKILL.md` — it is the working loop: establish ground
   truth with commands, change one thing, measure, and claim only what a command printed.
   For a 3D program that does not exist yet, read `pcfx-3d-from-scratch` before writing
   any code: it makes you fix the output contract (resolution, bit depth, mesh counts)
   first, so a later "optimization" cannot silently shrink the deliverable.
1. Read `PCFX_Skills/SKILLS.md` — it is a router from symptom to module.
2. Open the module(s) it names and follow them **literally**. Copy code blocks
   verbatim rather than re-deriving them from the surrounding prose; several are
   marked "copy this verbatim" precisely because re-derivation introduced
   off-by-one bugs.
3. If a module names a manual section or a file in this workspace, cite it. If you do
   not have a real citation, say the number is unverified. **Never invent a manual
   section number or a hardware constant** — that is the failure mode this bundle
   exists to prevent.

## Execution contract for coding-agent tasks

When the user asks to inspect, change, build, test, or commit a repository, act as an
engineer rather than a chat assistant. Start by using the available read/search/shell
tools to inspect the checkout. Do not stop after announcing an investigation or giving
a plan. Iterate: inspect -> make the smallest justified change -> run the relevant
build/test -> inspect `git diff` -> commit when the user asked for a commit. If a tool,
toolchain, or emulator is unavailable, record the exact blocker and still complete every
safe local step. Do not claim a build, screenshot, or hardware result you did not run.

## Non-negotiables

- **Profile before optimizing.** Use `pcfx-headless-prof`; see `pcfx-v810-profiling`.
  On this machine multiplies are cheap and compares and I/O port reads are expensive —
  the opposite of the usual intuition.
- When a complex 3D asset must remain intact, read `pcfx-character-8bpp`: preserve the
  vertex/face counts **from that project's own manifest** and the requested raster size;
  use affine presentation packing, keep `MIN_TRIANGLE_AREA2=0`, and preserve the UV/atlas
  contract. Never assert counts copied from another project.
  If a shared skeleton, additional clips, runtime movement or user zoom exists, also read
  `pcfx-character-animation`; preserve skin-influence seams, frame-zero root motion, and object-space clips.
  Exact native screen-pose streams are legal only for a proven closed finite visible-state
  set and are invalid for an extensible animation viewer.
- **No `float` or `double`.** There is no FPU. See `pcfx-fixed-point`.
- **Vertical blanking is raster 262 and 0..21**, never `>= 240`.
- **A clean emulator run does not prove hardware correctness**, and for timing bugs it
  proves nothing. Say so instead of inventing a verification procedure.
- **Report measurements honestly**, including "no measurable change". Do not present a
  sub-2% delta as a speedup — that is inside the emulator's noise floor.
- Prefer deleting a wrong pattern over adding a correct one next to it. When you fix a
  constant that exists in several private copies, centralize it.
