# Repo-case rounds

One entry per run. A `FAIL` is data about the bundle: what did the agent read, where did
it turn wrong, and which module should have prevented it?

---

## Round 1 — `mul-high-word`, arm `skills`, 2026-08-08

**Result:** FAIL (`rc=124`, the 3000 s budget expired; 147 tool calls, no working fix).

**What it got right.** Router mode worked exactly as designed: the first two actions were
`read pcfx-self-improve/SKILL.md` and `read SKILLS.md`, then it listed the tree, read the
source and the Makefile, ran `make hosttest`, built, and disassembled — the ground-truth
procedure from [pcfx-self-improve] §1. It also identified the true cause on its **first
edit**, adding the missing `mov r30, %1`.

**Where it went wrong, and why the bundle was at fault.**

1. **It never opened the module with the answer.** From the symptom it read
   `pcfx-software-3d` and `pcfx-king-framebuffer` and never `pcfx-3d-pipeline`, whose §1b
   *is this bug*. The `SKILLS.md` row for "software-3D renderer black/blank" did not name
   `pcfx-3d-pipeline` at all — a routing hole, not a model failure.
   → Fixed: that row now sends you to `pcfx-3d-pipeline §1` first, plus a new row for
   "every piece works in isolation but the renderer draws nothing".

2. **It retyped the asm instead of copying it**, producing
   `"=r"(hi)` with no early-clobber and an empty clobber list. That fails *identically*
   to the original bug, so it read the unchanged black screen as "diagnosis was wrong"
   and spent ~100 disassembly calls on the rasterizer, the flip and the KRAM path.
   → Fixed: `pcfx-3d-pipeline` §1b now shows this exact near-miss as an ANTI-PATTERN and
   says why both `&` and the `r30` clobber are load-bearing; `pcfx-self-improve` §6 now
   names the "right line, retyped from memory, identical symptom, abandon the correct
   hypothesis" loop and says to diff your edit against the module's block first.

3. **A passing host oracle read as "the maths is fine, look elsewhere"** — but
   `-DHOST_TEST` swaps `fx_mul` for an `int64` path, so the oracle cannot see this bug at
   all. Its passing was in fact strong evidence the fault lay in something the host build
   stubs out.
   → Fixed: stated in `pcfx-3d-from-scratch` §6 (gate 1) and `pcfx-self-improve` §6.

4. **It started disabling working mechanisms** — commented out `face_visible`, made
   `base` volatile, left debug rectangles in the frame loop — and never fully reverted
   them. → Fixed: `pcfx-self-improve` §6 now forbids leaving probes in the tree.

**Harness lessons (already applied):** `pi -p` prints nothing until it exits, so use the
session JSONL under the `pi` provider's configured session directory to see the
trajectory; that is
where all of the above came from.

---

## Round 2 — `mul-high-word`, arm `skills`, same day, after the four fixes above

**Result: PASS in 104 seconds** (`drawn_even: 15680`, byte-identical to the reference
good tree), against a 3000 s timeout and 147 fruitless tool calls in round 1.

The agent named `pcfx-3d-pipeline` §1b explicitly, applied the block verbatim — early
clobber and `r30` clobber intact — and verified with a build, a screenshot and the host
oracle before reporting. Two of the three fixes are visible directly in its output: it
cited the module it previously never opened, and it copied rather than retyped.

The lesson generalises past this case: **the bundle's failure mode is routing, not
content.** The correct fact had been in `pcfx-3d-pipeline` all along; it lost an hour of
agent time purely because no symptom row pointed there.

---

## Round 3 — `mul-high-word`, arm `none` (control), same day

**Result: the tree passes, but the agent never stopped.** It ran 113 tool calls and was
still iterating when the 3000 s budget expired; the outer timeout killed the script
before the verdict ran. Verified afterwards by hand: `drawn_even: 15680`, **PASS**.

So the honest comparison is *not* "unaided fails, bundle succeeds":

| Arm | Reached a working fix | Converged and stopped | Wall clock |
|---|---|---|---|
| `skills` (round 2) | yes | **yes**, with build + screenshot + oracle stated | **104 s** |
| `none` (round 3) | yes | no — still working at the cutoff | >3000 s |

Unaided, it eventually wrote `"=&r"(lo), "=r"(hi)` — the early clobber on the wrong
operand. That happens to work here (nothing aliases `lo`), so the case scores it a pass;
it is luck, not knowledge, and the same edit on a different register allocation is the
round-1 bug again.

The claim this case supports is therefore about **convergence and confidence**: the
bundle turned a 50-minute unterminated search into a 104-second diagnosis the agent could
justify. Do not report it as the control failing.

**Harness fix applied:** the agent phase now gets its own `PCFX_AGENT_TIMEOUT` (default
1800 s) and the verdict always runs afterwards, so "found the fix but kept going" can
never again be recorded as "failed".

---

## Round 4 — `face-winding`, arm `skills`, same day

**Result: PASS in 625 s** (`drawn_even: 15680`, `hosttest_pass: true`).

It did **not** restore the original table. It reversed the *other* three faces and
flipped the sign in `face_visible()` — a globally consistent inversion of the same
convention — and the geometric oracle accepts it, because the oracle tests agreement
with geometry rather than equality with a golden table.

That is the case working as designed, and it is the argument for scoring by oracle
instead of by diff: a different but correct convention passes, while the plausible
half-fix (reversing three faces and leaving the sign alone) cannot. The agent's own
report reasons in exactly those terms — that the two errors had been masking each other
— which is the reasoning [pcfx-3d-pipeline] §4.3 asks for.

**Case status after four rounds**

| Case | `skills` | `none` |
|---|---|---|
| `mul-high-word` | PASS, 104 s | passes, but did not converge in 3000 s |
| `face-winding` | PASS, 625 s | not yet run |
| `spin-immediate-stride` | PASS, 473 s | not yet run |

---

## Round 5 — `spin-immediate-stride` (real project), arm `skills`

**Result: PASS in 473 s, `diff_pixels: 0`** — the rebuilt disc reproduces the reference
screenshot exactly.

It cited `pcfx-character-8bpp` §5 by name, identified the truncated `ADD imm5`, converted
it to the three-operand `ADDI`, rebuilt through the project's own wrapper (not a bare
`make`), and checked the screenshot rather than the frame rate. On a real 300 KB project
with hand-written V810 assembly, that is the module working as intended.

**Two reporting defects in an otherwise correct fix**, both now ANTI-PATTERNs in
[pcfx-self-improve] §7:

1. **It published numbers it never measured.** "FPS dropped from ~2.1 to ~2.7 — expected,
   since the previous speedup was actually drawing less geometry." Correct reasoning,
   correct direction, and no profiler was run in the session. The rule is now explicit:
   every figure must be traceable to a command in your own transcript.

2. **It attributed the corruption to code that never executes.** It found two further
   out-of-range immediates — `add 28,r22` and `add 24,r20` at `tank_raster_v810.S:848`
   and `:853` — and reported them as additional causes. They are real defects and worth
   fixing, but they sit in `_scene_append_faces_v810`, which has **no callers and is not
   in the linked ELF**; the pixel-exact match against a reference built *with* them
   proves they cannot have affected the picture. The module now requires proving a symbol
   executes (`grep` for callers, `v810-nm` the ELF) before blaming it, and separating
   "latent trap found nearby" from "the bug you were asked to fix".

**Standing finding for the project:** `3DCharacterSpinning`'s `_scene_append_faces_v810`
carries two immediates that GNU `as` truncates silently. Dead today; a live bug the moment
anything calls it.
