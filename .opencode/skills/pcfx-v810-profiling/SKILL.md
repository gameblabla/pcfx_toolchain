---
name: pcfx-v810-profiling
description: Measure a PC-FX program with the pcfx-headless-prof V810 profiler - reading the CPI/opcode/icache/DRAM-page/flag-stall report, mapping hot PC buckets back to functions with v810_prof_symbols.py, and deciding what to optimize from the numbers instead of from intuition. Use BEFORE any optimization work, and whenever you need to know where the cycles actually go.
---

# Profiling the V810 with `pcfx-headless-prof`

**Never optimize a PC-FX program you have not profiled.** The cost model is
unintuitive: on this hardware multiplies are cheap and *compares* are expensive.
Every guess made in this workspace without a profile was wrong. This skill is how
you get the numbers.

## 1. Run it

`toolchain/bin/pcfx-headless-prof` is the bundled headless emulator build with
V810 profiling hooks enabled. The build switch and source branch vary by workspace;
do not assume an ordinary stock `Makefile.headless` contains those hooks. The
instrumented executable must prove itself by emitting the complete report below.

```bash
cd <project>
"$PCFXEMU_PROF" --bios-dir "$PCFX_BIOS_DIR" --frames 1800 game.cue 2>&1 \
  | sed -n '/V810 PROFILE/,/^####################/p' > prof-before.txt
```

- The report goes to **stderr** and is printed **at exit** — you must let the run
  finish, and you must redirect stderr.
- Everything is **divided by `video_frames`**, so the per-field numbers are directly
  comparable between runs of different length. Use the same `--frames` for A/B anyway.
- Remember the ~1200-frame BIOS boot delay: `--frames 1800` gives ~600 frames of
  actual program. To profile *gameplay* rather than a title screen, drive in with
  `--commands` (see [pcfx-emulator-testing]).
- It runs far faster than real time (1800 frames in ~6 s), so profiling is cheap —
  profile every change.

### Publish renderer FPS from a presented-frame counter

`% of a field` measures CPU utilization; it is **not renderer FPS**. For a renderer
that may need several video fields per completed image, expose a 32-bit global such as
`nframe` and increment it only when a newly rendered buffer is actually presented.
Then measure from one warmed savestate:

```text
before = u32(before.ram, address_of(nframe))
after  = u32(after.ram,  address_of(nframe))
presented = (after - before) & 0xffffffff
fps = presented * 60 / profiler_video_frames
```

Use the same warmed savestate for every run. Dump RAM before and after the capture;
do not use a polling HUD or emulator wall-clock speed. Require at least two captures
and reject publication when FPS, cycles/field, DRAM penalty/field, or i-cache
misses/field differ by more than the project noise gate (normally 3%).

For `3DCharacterSpinning`, the checked-in harness is:

```bash
cd source
make -f Makefile.pcfx profile \
  V810_GCC="$V810_GCC" \
  PCFX_PROFILER="$PCFXEMU_PROF" \
  PCFX_BIOS="$PCFX_BIOS_DIR"
```

It clean-builds, audits the ELF/map, warms once, runs twice from the same state,
computes FPS from `nframe`, and refuses a measured report unless the complete DRAM and
i-cache blocks parse. Missing inputs produce `null`/`unavailable`, never zero.


Current corrected reference result for that project (`LINEAR_BG=0 OUTLINE=1
MIN_TRIANGLE_AREA2=0 PREBAKED_POSES=1`, native 256x240, full
5,563-vertex/10,628-face source asset):

```text
presented FPS                  30.117  (1807 images / 3600 fields)
cycles/field                  357626
CPI                             2.705
DRAM penalty cycles/field       23996
  code-refill cycles/field        121
  data cycles/field             23875
i-cache misses/field              132
fixed i-cache miss cycles/field   264
```

Two captures from the same warmed savestate were identical. The active path is an exact
128-pose native output stream; all 61,440-byte indexed pose buffers match the committed
full-geometry baseline byte-for-byte. A prior 5.017 FPS capture was rejected after its
screenshot and fixed-pose face-count check exposed a truncated V810 `ADD imm5` stride
that omitted most geometry. Correctness gates precede performance publication.

### Verify that the executable is the instrumented profiler

Do not assume a stock `pcfx-headless` is a profiler merely because it accepts
`--frames`. The required binary must emit a `V810 PROFILE` block at exit and, when
requested, a profiler CSV. If the available source tree has no `V810_PROFILE` hooks or
no profiler build target, it cannot provide DRAM-page or i-cache counters. Do not
substitute generic host timing or invent equivalent counters.

## 2. A real report, and what each block means

This is an actual `wolf-pcfx` run, unedited. Read it top to bottom:

```
################  V810 PROFILE  (video_frames=1800)  ################
Instructions      : 236763554  (131535 / field)
Cycles attributed : 645381643  (358545 / field = 100.17% of a field)   dropped=0
CPI (mean)        : 2.726 cyc/instr
```

**`% of a field` is the headline number.** A field is ~357,955 cycles (21.477 MHz /
60.0). 100.17% means the CPU is saturated: the program is using every cycle it has,
so it is running at 30 fps (two fields) or worse. Under ~100% you have headroom.
`CPI 2.726` is high — a 1-cycle machine spending 2.7 cycles per instruction is
stalling somewhere, and the blocks below say where.

```
-- 1 KB icache --
hits=323394071  miss(subblock)=1123497  miss(tag)=1318535  total=325836103
miss-rate=0.749%   misses/field=1357   fixed miss cost=2713 cyc/field (+2 each, DRAM refill extra)
```

The icache is **1 KB, direct-mapped**, so two hot functions 1 KB apart in the address
space evict each other forever regardless of how much cache is "free".

- `miss(tag)` = a different address claimed the line — the *conflict* miss you can
  fix by moving code (see §4).
- `miss(subblock)` = right line, wrong half — usually just cold streaming.
- **0.749% looks tiny but is not the whole cost**: each miss is +2 cycles *plus* a
  DRAM refill, and refills show up again in the DRAM block. Judge by
  `cyc/field`, never by miss-rate.

```
-- conditional branches --
taken=47272388 (77.6%)  not-taken=13674849 (22.4%)  total/field=33860
branch cycles/field=86384 (taken 3, not 1)
```

**A taken branch costs 3 cycles, a fall-through 1.** Here branches alone are
86,384 cyc/field = **24% of the frame**. 77.6% taken is bad: it means the common
case is the branching one. Invert the conditions so the *hot* path falls through.

```
-- flag-use stalls (+2 when a Bcc/SETF/STSR follows a flag-writing op) --
flag-readers/field=33431  stalled=33299 (99.6%)  dodged=132
stall cost=66597 cyc/field (18.61% of a field) — hoisting a flag-neutral op
between compare and branch reclaims 2 cyc each
```

**This is usually the single biggest free win, and the compiler will not do it for
you.** The V810 stalls +2 cycles when a branch reads flags written by the immediately
preceding instruction. Here 99.6% of branches stall, costing **18.6% of every frame**.
The fix is to schedule *one flag-neutral instruction* between the compare and the
branch — a `MOV`, a load for the next iteration, an address computation. See §5.

```
-- slow ops --
MUL   count=17964 (10/field)  cycles=275332 (153/field, 0.04%)
MULU  count=48527 (27/field)  cycles=640545 (356/field, 0.10%)
DIV   count=2312 (1/field)  cycles=87878 (49/field, 0.01%)
DIVU  count=4042 (2/field)  cycles=146354 (81/field, 0.02%)
```

**Read this before you "optimize away a multiply".** All four slow ops together are
**0.17% of the frame**. A multiply is 13 cycles and a divide 38 — genuinely slow *per
op* — but they are so rare here that removing them all would gain nothing. Replacing a
multiply with a lookup table that adds a cache-missing load is a **net loss**. Divides
still deserve hoisting out of inner loops (one divide per span, not per pixel), but
"avoid multiplies" is not a PC-FX rule. Let the profile decide.

```
-- opcodes by cycles (top 24) --
op                count   %cnt         cycles   %cyc    CPI
BE             36321102  15.3%      171789684  26.6%   4.73
BNE            18172066   7.7%       91605566  14.2%   5.04
LD_H           25545167  10.8%       77808420  12.1%   3.05
IN_H            9402473   4.0%       58573498   9.1%   6.23
LD_W            8335519   3.5%       39445477   6.1%   4.73
CMP_I          33991055  14.4%       34335031   5.3%   1.01
```

Sort by `%cyc`, not `%cnt`. Here **`BE` + `BNE` = 40.8% of all cycles** at CPI ~4.8 —
a branch that should cost 3 is costing 4.8 because of the flag stall above. That one
finding directs the whole optimization effort.

`IN_H` at **CPI 6.23** is the other lesson: **I/O port reads are the most expensive
instruction you can execute.** Every `in.h` to a KING/VDC/Tetsu port is ~6 cycles.
Reading a port in a loop, or re-reading the raster you already have, is real money.
Cache port values in registers; batch KING writes.

`LD_H` at CPI 3.05 vs `CMP_I` at 1.01 shows the load-use stall: a load whose result is
used by the next instruction stalls. Separate the load from its consumer.

```
-- 2 KiB DRAM page penalties (+3 cyc each) --
penalty cyc/field=9263 (2.59% of a field)   code-refill=515  data=8748
code-refill page-changes: after-DATA=263018 (ping-pong, unfixable)  after-CODE=45974 (align-addressable)
```

Main RAM is paged in **2 KiB** units; crossing a page boundary costs +3 cycles.
`data=8748` dominates, meaning the *data* access pattern is scattered — walking two
arrays >2 KiB apart in one loop ping-pongs pages every iteration. Interleave the data
into one struct, or process in blocks that fit a page.
`after-DATA ... (ping-pong, unfixable)` is the profiler telling you the truth: a code
fetch following a data access will always change pages, and no amount of code
alignment fixes it. Only `after-CODE` is addressable by moving code.

```
-- hot code (top 16 of 32-byte buckets, by cycles) --
addr              count         cycles  icache-miss
0x00afe0       29971720       67504182        17815
0x009c20       14559271       43677713           69
0x02dd60       10632348       28637127        12346
...
(non-RAM PC e.g. BIOS: count=116067123 cycles=336466089)
```

32-byte buckets by cycles. `0x00afe0` is 10.5% of all attributed cycles **and** has
17,815 icache misses — a hot loop that is also thrashing. `0x009c20` is comparably hot
with **69** misses, so it is well-placed; leave it alone.

⚠ **Note the `non-RAM PC` line.** 336M cycles here are executing in **BIOS**, not your
code. If that number is large your program is spending its time in BIOS calls (usually
CD or pad access) and no amount of tuning your own loops will help — remove the calls.

## 3. Map hot buckets back to functions

Raw addresses are useless on their own. The profiler writes a CSV and there is a tool
to symbolize it (`tools/v810_prof_symbols.py`, present in the doom-pcfx and
descent-pcfx trees):

```bash
V810_PROF_CSV=prof.csv $PCFXEMU/pcfx-headless-prof --frames 1800 game.cue 2> prof.txt
python3 tools/v810_prof_symbols.py prof.csv game.elf | head -30
```

It maps each 32-byte bucket to the enclosing symbol via the ELF symbol table and
aggregates per function. If the tool is missing, do it by hand — the mechanism is just
the symbol table, and this is enough:

```bash
v810-none-elf-nm -n game.elf | awk '$2 ~ /[tT]/ {print $1, $3}' > syms.txt
# then for a hot address, the symbol is the last one at or below it
awk -v a=0x00afe0 'strtonum("0x"$1) <= strtonum(a) {s=$2} END {print s}' syms.txt
```

Always symbolize before acting. "Optimize `0x00afe0`" is not a plan; "the inner span
loop in `R_DrawColumn` is 10% of the frame and thrashing the icache" is.

## 4. Fixing icache conflicts

The cache is **1 KB direct-mapped**: line = `(address >> 4) & 0x3F` for 16-byte lines.
Two functions whose addresses are congruent mod 1 KB evict each other on every call.

The lever is the **linker script**: put the hot functions adjacent, in call order, in
one contiguous region under 1 KB total, using a dedicated section.

```c
/* mark the hot path */
#define HOT __attribute__((section(".text.hot"), noinline))
HOT void draw_span(...) { ... }
```

```ld
/* pcfx_hot.ld — keep the whole hot loop inside one cache footprint */
.text.hot : ALIGN(16) {
    KEEP(*(.text.hot.entry))
    KEEP(*(.text.hot))
    . = ALIGN(16);
} > RAM
```

doom-pcfx does exactly this (`platform/pcfx_hot.ld`) and made the layout tunable so it
could be searched — see [pcfx-optimize-loop], because which ordering wins is **not
predictable** and must be found by measurement.

Check your work: re-profile and compare the `icache-miss` column for that bucket. If
misses did not drop, the reordering did nothing — revert it.

## 5. The flag-stall fix, concretely

The pattern the profiler flags:

```asm
    cmp   r6, r7
    be    1f            /* +2 stall: reads flags written by the previous op */
```

Give the pipeline one flag-neutral instruction to chew on. Loads, `MOV`, `MOVEA`,
`MOVHI`, `SHL`/`SHR` by immediate and address arithmetic are all safe fillers **as long
as they do not write flags and do not feed the branch**:

```asm
    cmp   r6, r7
    ld.w  0[r8], r9     /* work for the next iteration — flag-neutral */
    be    1f            /* no stall: 2 cycles reclaimed */
```

In C you cannot place this directly, but you can create the opportunity: unroll by two
and interleave the iterations so there is always independent work between a comparison
and its branch. If a loop is hot enough to matter, write it in assembly — this is the
main reason hand-written `.S` files exist in these projects
(`platform/pcfx_span32.S`).

**Verify from the profile**: `stalled` should fall and `dodged` should rise. If
`dodged` did not move, your filler instruction wrote flags after all.

## 6. Reading a *pair* of reports

Always diff, never eyeball a single run:

```bash
diff <(grep -E "of a field|CPI \(mean\)|miss-rate|stall cost|penalty cyc" prof-before.txt) \
     <(grep -E "of a field|CPI \(mean\)|miss-rate|stall cost|penalty cyc" prof-after.txt)
```

The five numbers that decide whether a change was real:

| Number | Meaning | Want |
|---|---|---|
| `Cycles ... % of a field` | total CPU load | down |
| `CPI (mean)` | stalling | down |
| `misses/field` | icache thrash | down |
| `stall cost ... % of a field` | flag stalls | down |
| `penalty cyc/field` | DRAM page ping-pong | down |

**A change that lowers instruction count but raises CPI is usually a loss.** Trust
`% of a field`, and confirm against wall-clock fps from a normal headless run — the
field-count histogram is what the player sees, and it is quantized to 60/N (see
[pcfx-frame-timing]).

## 7. What the profiler cannot tell you

- It attributes cycles with the emulator's **approximate** cycle model. Differences
  under ~2% are noise; do not chase them.
- It does not model KING/CD bus contention against the CPU, so a change that moves
  work into a period when KING is busy can profile better and run worse.
- It says nothing about correctness. Always screenshot the result too — the fastest
  renderer here at one point was fast because it had stopped drawing. For indexed-mesh
  renderers, also freeze a pose and independently recompute the expected front-facing
  primitive count from dumped projected vertices; require it to equal submitted faces.

## Related

[pcfx-v810-performance] for the cost model and the catalogue of what worked ·
[pcfx-optimize-loop] for the automated search built on these numbers ·
[pcfx-emulator-testing] for running and screenshotting · [pcfx-software-3d] for
where 3D time goes.
