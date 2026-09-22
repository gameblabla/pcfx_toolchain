---
name: pcfx-optimize-loop
description: The measure-change-measure discipline for PC-FX optimization, and how to run an automated search (hill-climb/grid/random) over build knobs scored by the V810 profiler using the bundled search.py. Use when making a program faster without guessing, when hot-code cache layout needs tuning, or to leave an optimization search running unattended.
---

# The optimization loop

Optimization on this hardware is a **search**, not a derivation. Cache placement,
unroll factors and instruction scheduling interact in ways nobody predicts correctly —
including this bundle. The winning strategy is to make the interesting choices into
**build knobs**, then let a script measure every combination.

**The rule that makes this safe: the search varies knobs, never source.** A search that
edits code cannot be trusted or reverted; a search that only sets `--defsym` and `-D`
values can be left running unattended, and its result reproduced by one command.

## 1. The loop, in order

1. **Profile first** ([pcfx-v810-profiling]). Do not start until you can name a
   number and a function.
2. **Form one hypothesis** that would move that number.
3. **Make it a knob** (§2) if the right value is not obvious. It usually isn't.
4. **Measure baseline and candidate identically** — same `--frames`, same commands
   file, same disc.
5. **Keep it only if it beats the noise floor** (§4).
6. **Screenshot the result.** A faster renderer that stopped drawing is not faster.
7. **Record the outcome — including failures.** The catalogue of what *didn't* work
   is worth more than the wins: it stops the next agent re-running the same search.

## 2. Turning a decision into a knob

Anything the linker or preprocessor can decide should be settable from the
environment, with the measured default baked in. Pattern taken from `doom-pcfx`:

**Makefile** — `?=` so the environment wins:

```make
# Cache indices within the 1 KiB-aligned renderer section. Deliberate build knobs:
# re-benchmark candidate placements without editing C or the linker script.
PCFX_HOT_SPAN_LIT_OFFSET   ?= 0xa40
PCFX_HOT_COLUMN_LIT_OFFSET ?= 0xb04

PCFX_HOT_LAYOUT_LDFLAGS := \
  --defsym=__pcfx_span_lit_offset=$(PCFX_HOT_SPAN_LIT_OFFSET) \
  --defsym=__pcfx_column_lit_offset=$(PCFX_HOT_COLUMN_LIT_OFFSET)
```

**Linker script** — `PROVIDE` so a direct `ld` call still works; `--defsym` overrides:

```ld
PROVIDE(__pcfx_span_lit_offset   = 0xa40);
PROVIDE(__pcfx_column_lit_offset = 0xb04);

.text.renderhot : ALIGN(1024) {
    __pcfx_renderhot_start = .;
    . = __pcfx_renderhot_start + __pcfx_span_lit_offset;
    KEEP(*(.text.hot.span_lit))
    . = __pcfx_renderhot_start + __pcfx_column_lit_offset;
    KEEP(*(.text.hot.column_lit))
} > RAM
```

Now `PCFX_HOT_SPAN_LIT_OFFSET=0x880 make` relinks with a different cache placement and
**no source change**. That is a searchable knob. Numeric `-D` values (unroll factors,
tile sizes, LOD thresholds) work the same way.

Good knobs on PC-FX, in rough order of payoff:

| Knob | Why it is unpredictable |
|---|---|
| hot-function offsets in the 1 KB icache | direct-mapped conflicts; cannot be reasoned out |
| loop unroll factor | trades icache footprint against branch count |
| span / column batch size | interacts with the 2 KiB DRAM page |
| LOD / subdivision thresholds | fps is quantized 60/N, so only some values matter |
| inline vs. not, for mid-size functions | changes cache footprint more than call cost |

## 3. Running the search

`search.py` (next to this file) builds, runs the profiler, parses `% of a field`, and
hill-climbs. Write a config naming your build and run commands:

```json
{
  "build": "make -j8 cd",
  "run":   "./prebuilt/bin/pcfx-headless-prof --frames 1800 --commands demo.txt game.cue",
  "workdir": ".",
  "knobs": {
    "PCFX_HOT_SPAN_LIT_OFFSET":   {"type":"hex","min":0,"max":4096,"step":64,"default":2624},
    "PCFX_HOT_COLUMN_LIT_OFFSET": {"type":"hex","min":0,"max":4096,"step":64,"default":2820},
    "PCFX_SPAN_UNROLL":           {"type":"int","choices":[1,2,4,8],"default":4}
  }
}
```

```bash
python3 PCFX_Skills/pcfx-optimize-loop/search.py \
    --config search.json --strategy hill --budget 60
```

- **`hill`** (default) — vary one knob at a time, keep improvements, repeat until
  stable. Use this; it finds most of the win in a fraction of the runs.
- **`grid`** — shuffled exhaustive, capped at `--budget`. Use for ≤2 knobs.
- **`random`** — sampling; use to check hill-climbing did not park in a bad local
  optimum.

It writes `search-ledger.json` with every trial, so an interrupted search is not lost
and every claim is auditable. **Always start from the current defaults** — the baseline
is trial 0 and every result is relative to it.

A cycle is ~6 s of emulation plus build time, so a 60-trial search is minutes, not
hours. There is no excuse for guessing.

### ⚠ Local optima are real, and are a finding

`doom-pcfx` recorded *"pcfx_column_lit64 is a local optimum in both directions"* —
moving that function either way made things worse. That is a **result**, not a failure:
write it down, or the next agent burns the same 60 builds. Confirm with one
`--strategy random` pass before declaring it.

## 4. The noise floor — the discipline that prevents fake wins

The emulator's cycle model is approximate. **Differences under ~2% are noise.**
`search.py` accepts a hill-climb step at 0.02 percentage points, but the bar for
*reporting a win to a human* is much higher:

- Re-run winner and baseline **again**, in that order, and confirm the gap holds.
- Confirm on the metric that matters: **field count**, not cycle percent. fps is
  quantized to 60/N ([pcfx-frame-timing]), so a 4% cycle win that does not cross a
  field boundary changes **nothing the player sees**. Say so plainly.
- Check the other four profiler numbers did not get worse ([pcfx-v810-profiling] §6).
  Lower cycles with higher CPI usually means you moved work rather than removed it.

**Report "no measurable change" when that is what happened.** A search that finds
nothing is a valid and useful outcome. Never present a 0.3% delta as a speedup.

## 5. When to stop searching and think

Automated search tunes *placement*; it cannot find *algorithmic* wins. Go back to the
profile when:

- the top opcode is `IN_H` — you are I/O bound; batch or cache the port reads
- `non-RAM PC` cycles are large — you are in BIOS; remove the calls
- the top cost is flag stalls — needs hand asm scheduling
  ([pcfx-v810-profiling] §5), not a knob
- the renderer is drawing pixels nobody sees — LOD and viewport work beats every
  micro-optimization ([pcfx-software-3d] §3)

No amount of hill-climbing fixes drawing too many pixels.

## 6. Recording the outcome

After every search, append to the catalogue in [pcfx-v810-performance] — **both**
sections:

```markdown
### Worked
- Hot-layout search over span/column offsets: 104.2% -> 98.6% of a field
  (30 -> 60 fps on the flat-heavy demo). Winner: span=0x880 column=0xb04.
  Reproduce: PCFX_HOT_SPAN_LIT_OFFSET=0x880 make

### Failed — do not retry without new information
- Unroll factor above 4: every value regressed; the loop stops fitting the icache.
- Replacing the span multiply with a LUT: +1.2% (the missing loads cost more than
  the 13-cycle multiply saved). Slow ops are only 0.17% of the frame here.
```

This is how the bundle self-improves: every search makes the next one cheaper.

## Related

[pcfx-v810-profiling] for the numbers · [pcfx-v810-performance] for the cost model and
catalogue · [pcfx-frame-timing] for 60/N quantization · [pcfx-emulator-testing] for
A/B discipline and screenshots.
