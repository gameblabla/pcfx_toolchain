# Repo-level regression cases

`../cases/` asks the model a question and scores the *answer*. These cases give it a
**broken repository** and score the *result of its work*: does the program build, and does
the screen show the right thing afterwards?

The target is `pcfx-3d-pipeline/template/` — the verified rotating-cube project. It is
small, builds in seconds, boots in the headless emulator, and ships a host-side geometric
oracle, so a full break-fix-verify cycle is cheap enough to run repeatedly.

## Running

```bash
./run_case.sh mul-high-word skills    # pi + the PCFX_Skills bundle
./run_case.sh mul-high-word none      # pi with no bundle — the control arm
./run_case.sh mul-high-word manual    # just produce the broken tree, no agent
```

Each run copies the template to `build/eval/cases/<case>-<arm>/` by default (override
with `PCFX_CASE_WORKDIR`), applies the break,
**asserts the broken tree fails the verifier** (a case that passes while broken proves
nothing), runs the agent in that directory, and prints a verdict plus `verdict.json`.

Start any OpenAI-compatible local server first; set `PCFX_LLM_ENDPOINT` when it is not
listening at the default `http://127.0.0.1:8080`.

### Operational notes, learned the hard way on this box

- **Use router mode.** `pi_pcfx.sh` defaults to `PCFX_SKILL_MODE=router`: only
  `ROUTER_PROMPT.md` + `SKILLS.md` go into the system prompt (~3k tokens) and the agent
  opens individual modules with its `read` tool. `PCFX_SKILL_MODE=full` preloads every
  module (~60k tokens); on this hardware that made a *single* `ls` turn take over seven
  minutes and never complete, because every tool round trip reprocesses the prompt.
  Full mode is for a one-shot question, not for an agentic loop.
- **Never put a chat-control token in an appended system prompt.** `ROUTER_PROMPT.md`
  used to begin with a `<|think_off|>` line; it is text to the shell and a control token
  to the template.
- **The server serves one slot (`-np 1`).** Killing a client does not stop the generation
  it started: it runs to completion while every later request sits in
  `llamacpp:requests_deferred` and looks like a hang. Watch
  `curl -s localhost:8080/metrics | grep -E 'requests_deferred|tokens_predicted_total'`
  before concluding the agent, the bundle or the harness is broken —
  `requests_processing` alone can read `1` spuriously after an aborted request, while a
  rising `tokens_predicted_total` means it is working and a rising `requests_deferred`
  means you are queued.

## The verifier

`verify.py` is deliberately mechanical, so a model cannot talk its way past it:

| Check | Requirement |
|---|---|
| build | `make cd` exits 0 — checked as an exit status, never as the last line of a pipe |
| screen | a screenshot at 1800 frames (past the ~1200-frame BIOS boot) has 3,000–40,000 non-black pixels |
| `--flip` | the same holds at 1801 frames, which a broken page flip fails |
| `--hosttest` | `make hosttest` prints `PASS (` |

Per-case flags live in `cases/<id>/flags`, one per line.

## The cases

| Case | Break | Symptom shown to the agent | Module that should fix it |
|---|---|---|---|
| `mul-high-word` | `fx_mul` stops reading the MUL high word from `r30` | black screen although every piece works in isolation | pcfx-3d-pipeline §1b, pcfx-3d-from-scratch §4 |
| `face-winding` | three faces of the cube table wound backwards | sides of the cube missing, changing with rotation | pcfx-3d-pipeline §4, pcfx-3d-from-scratch §6 gate 1 |

Both symptoms are **misleading on their face** — that is the point. A black screen invites
rewriting the rasterizer; missing faces invite blaming the depth sort. The bundle's value
is redirecting a plausible-but-wrong diagnosis, so a case whose cause is guessable from
the symptom measures nothing.

## Adding a case

1. Pick a bug the bundle claims to prevent, ideally one that really happened here.
2. `cases/<id>/break.py <workdir>` — edit the template's source, and **assert** the text
   you expect to find, so the case fails loudly when the template changes.
3. `cases/<id>/task.md` — the symptom as a human would report it, plus what they already
   ruled out. **Never name the fix**, and never name the module.
4. `cases/<id>/flags` — `flip` and/or `hosttest` if the screen check alone is not decisive.
5. Run `manual` first and confirm the setup assertion fires.
6. Run the `none` arm. If the unaided model passes, the case is too easy to be evidence.

## Reading a result

A `FAIL` is data about the **bundle**, not just the model. Read `agent.log` and ask which
module should have prevented the wrong turn, and why it did not: usually either the fact
was there as prose and got re-derived incorrectly, or the correct fact failed to displace
the wrong pattern the agent was already looking at. Both fixes are described in
[pcfx-self-improve] §8. Fix the module, re-run, and record the round.
