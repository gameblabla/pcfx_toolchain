---
name: pcfx-v810-cpu-model
description: The exact V810 machine model as pcfxemu implements it - instruction encoding, per-opcode cycle costs, the 1 KB direct-mapped icache (128x8-byte lines, 2 sub-blocks), the 2 KiB DRAM page penalty, the +2 flag-use stall, and the load/store/OUT pairing rules. With file:line references so you can verify any claim yourself and hand-compute a loop's cost before profiling. Use when you need to know WHY an instruction costs what it does, when deciding between two code shapes, when reading disassembly, or when a profiler number does not match your intuition.
---

# The V810 machine model (as pcfxemu implements it)

Everything the profiler prints comes from this source. If you understand the model
below you can **hand-compute** a loop's cycle cost, predict the profiler's numbers,
and — most importantly — **verify any claim about this CPU yourself** instead of
trusting memory or another model's guess.

## 1. Sources of truth, in order

| # | Source | What it gives you | Path |
|---|---|---|---|
| 1 | **pcfxemu CPU core** | the exact cycle model the profiler measures | `vendor/pcfxemu/mednafen/hw_cpu/v810/v810_cpu.c`, `v810_oploop.inc`, `v810_opt.h`, `v810_cpu.h` |
| 2 | **pcfxemu DRAM model** | the 2 KiB page penalty | `vendor/pcfxemu/shell/emu/core.c` (`RAMLPCHECK`, ~line 383) |
| 3 | **V810 user manual** | encoding, instruction semantics, cache control | `docs/v810-cpu-doc.pdf` (instruction set = chapter 5) |
| 4 | **the profiler itself** | what is actually happening in *your* program | [pcfx-v810-profiling] |

When the manual and the emulator disagree about cycles, the emulator wins **for
profiler purposes** — it is what the numbers measure. The manual wins for semantics.

## 2. Instruction encoding — enough to read disassembly

All V810 instructions are 16-bit (or a 16-bit opcode plus a 16-bit immediate
word). The opcode is **bits 15..9** of the first halfword (`tmpop >> 9` in
`v810_oploop.inc`). The exact opcode map is `v810_opt.h`:

```
MOV 0x00  ADD 0x01  SUB 0x02  CMP 0x03  SHL 0x04  SHR 0x05  JMP 0x06  SAR 0x07
MUL 0x08  DIV 0x09  MULU 0x0A DIVU 0x0B  OR 0x0C   AND 0x0D  XOR 0x0E  NOT 0x0F
MOV_I 0x10 ADD_I 0x11 SETF 0x12 CMP_I 0x13 SHL_I 0x14 SHR_I 0x15 EI 0x16 SAR_I 0x17
...        MOVEA 0x28 ADDI 0x29 JR 0x2A JAL 0x2B ORI 0x2C ANDI 0x2D XORI 0x2E MOVHI 0x2F
LD_B 0x30 LD_H 0x31 LD_W 0x33 ST_B 0x34 ST_H 0x35 ST_W 0x37 IN_B 0x38 IN_H 0x39
CAXI 0x3A IN_W 0x3B OUT_B 0x3C OUT_H 0x3D FPP 0x3E OUT_W 0x3F
branches: BV 0x40 BL 0x41 BE 0x42 BNH 0x43 BN 0x44 BR 0x45 BLT 0x46 BLE 0x47
           BNV 0x48 BNL 0x49 BNE 0x4A BH 0x4B BP 0x4C NOP 0x4D BGE 0x4E BGT 0x4F
```

The mode table (`addr_mode[]` in `v810_opt.h`) says how many halfwords and which
field layout each opcode has — modes I (reg-reg), II (reg-imm5), III (branch
displacement), V/VI (16-bit immediate in a second halfword), IV (24-bit
immediate). A disassembly tool (`v810-objdump`) prints all of this; use it when
the compiler generated something surprising.

## 3. The instruction fetch path and the 1 KB icache

Program counter advances in halfwords; instruction fetches go through
`V810_RDOP` → `V810_RDCACHE` (`v810_cpu.c:288`). The cache is **on by default in
every homebrew** — `crt0.S` runs `ldsr 2,chcw` (`vendor/libpcfx/src/crt0.S:133-138`,
disable-clear-enable). The model:

- **128 lines × 8 bytes = 1 KB**, direct-mapped: `CI = (addr >> 3) & 0x7F`.
- Each line holds **two 4-byte sub-blocks**: `SBI = (addr & 4) >> 2`.
- Tag is `addr >> 10` — i.e. lines are mapped by **1 KB address chunks**. Two
  functions whose addresses are congruent mod 1 KB map to the same line and evict
  each other on every call. This is the whole icache conflict story.
- **Hit**: 0 extra cycles.
- **Sub-block miss** (right line, wrong half): +2 cycles, then a DRAM refill.
- **Tag miss** (wrong line): +2 cycles, refill, and the other sub-block is
  invalidated (`Cache[CI].data_valid[SBI ^ 1] = FALSE`).
- The refill cost is whatever `MemRead*` charges — including a possible +3 DRAM
  page change (see §4). That is why a miss "costs more than 2".
- **Branch alignment**: with the cache on, branching to an **odd halfword**
  address costs +1 (`BRANCH_ALIGN_CHECK`, `v810_cpu.c:383`). Keep branch targets
  even-aligned.

Two hot functions 1 KB apart thrash **forever**, regardless of how much cache is
"free". The profiler's `miss(tag)` count is exactly this (`V810_PROF_MISS_TAG`).

## 4. Main RAM is paged in 2 KiB units

`core.c:117-120, 383-393`:

```c
static uint32 RAM_LPA;                 /* last page access */
static const int RAM_PageSize = 2048;
#define RAMLPCHECK { \
  if((A & RAM_PageNOTMask) != RAM_LPA) { \
   (*timestamp) += 3;                  /* +3 cycles on page change */ \
   RAM_LPA = A & RAM_PageNOTMask; } }
```

- **One globally open page**, 2 KiB. Every access to main RAM (address
  `0x00000000..0x001FFFFF`) whose page differs from the last costs **+3 cycles**.
- It applies to **data loads/stores AND instruction refills** (a refill is a
  `MemRead*` and goes through the same check).
- DRAM page state is **not reset** by other buses (KROM, BIOS, I/O): only main-RAM
  accesses touch it.
- Consequences, all measured in this workspace:
  - `colormap[tex[t]]` with flat and colormap in different 2 KiB pages flips the
    page **twice per pixel** (+6/pixel).
  - Walking two arrays >2 KiB apart in one loop ping-pongs every iteration.
  - A hot function straddling a 2 KiB boundary refills across pages on every
    miss — that is the profiler's `code-refill ... after-CODE (align-addressable)`.
  - The `after-DATA ... (ping-pong, unfixable)` line means code fetch after a data
    access: no code alignment can fix a data access pattern that leaves the page
    open at the wrong address.

## 5. Per-opcode cycle costs — the complete table

From `v810_oploop.inc`. The `ADDCLOCK(n)` at each op is the **base**; the
pairing/penalty rules in §6 add to it.

| Instruction | Base cycles | Notes |
|---|---|---|
| MOV, ADD, SUB, CMP, OR, AND, XOR, NOT, shifts, MOV_I/ADD_I/CMP_I/SHL_I/SHR_I/SAR_I | **1** | |
| SETF, LDSR, STSR | **1** | +2 flag stall if STSR reads PSW (reads flags) |
| MOVEA, ADDI, ORI, ANDI, XORI, MOVHI | **1** | |
| NOP, HALT | **1** | |
| LD_B, LD_H | **1** | +1 if previous op was a load, +2 otherwise (§6) |
| LD_W | **1** | +3 after a load, +4 otherwise (on the PC-FX's non-32-bit bus path) |
| ST_B, ST_H | **1** | +1 if previous op was a store |
| ST_W | **1** | +1 (32-bit bus) or +3 (16-bit path) after a store |
| IN_B, IN_H, IN_W | **3** | I/O reads; IN_W 5 if no 32-bit I/O handler |
| OUT_B, OUT_H | **1** | +1 if previous op was an OUT |
| OUT_W | **1** | +1/+3 after an OUT |
| Bcc (conditional) | **taken 3, not-taken 1** | +2 flag stall if it reads flags just after a flag-writer (§7) |
| BR (unconditional) | **3** | does **not** read flags → no flag stall |
| JR, JAL, JMP | **3** | JAL writes r31 = PC+4 |
| RETI | **10** | |
| TRAP | **15** | |
| CAXI | **26** | compare-and-swap; rare |
| MUL, MULU | **13** | result: r30 = high word, reg = low word; resets the pairing chain |
| DIVU | **36** | r30 = remainder |
| DIV | **38** | r30 = remainder; ÷0 and MIN/-1 handled specially |
| FPP (FPU ops) | **1** + subop | do not use — soft-float is cheaper than any FPU path on this part |

The conditional-branch `COND_BRANCH` macro (`v810_oploop.inc:442`) is the exact
shape: `V810_FLAG_STALL()` is called **before** the taken/not-taken clock add.

## 6. The pairing model — one shared `lastop` chain

A single global `lastop` (`v810_cpu.c:73`) tracks the *kind* of the previous
memory-ish instruction. The rules, exactly as coded:

- **Load after load: +1. Load after anything else: +2.** This is why clustering
  loads in groups of four (four `ld.b` back to back) is cheaper *per load* — the
  second through fourth loads pay +1 instead of +2. (Ends at `lastop = LASTOP_LD`.)
- **Store after store: +1. Store after anything else: +0.**
- **OUT after OUT: +1. OUT after anything else: +0.** So consecutive `out.h` to
  KING's KRAM data port pair-penalize each other; interleaving a single ALU op
  (e.g. the loop counter `add`) between them makes the next OUT cost 1 not 2.
- **MUL/DIV/FPP set `lastop = -1`**, breaking the chain: a load right after a
  multiply pays no load-issue penalty (base 1 only).
- LD/ST/IN/OUT use `END_OP_SKIPLO` so the generic `lastop = opcode` fallback does
  not overwrite their marker.

Note what this model does **not** include: there is **no register-to-register
data dependency stall**. `mov r3,r2` after `ld.w 0[r4],r3` costs exactly the
`ld.w` + `mov` costs; the V810 (per this model) only stalls on flag use and on
the address-generation/issue pairing above. Do not invent load-use stalls the
profiler does not show — check the numbers first.

## 7. The flag-use stall — +2 cycles, and the table that decides it

`v810_cpu.c:260-286` + `v810_oploop.inc:49-55`:

- A flag-**reading** instruction is: any conditional branch, `SETF`, and
  `STSR` from PSW. `BR` is unconditional and does **not** read flags.
- A flag-**writing** instruction is any op whose bit in the hard-coded
  `op_writes_flags[256]` table is set. The table in `v810_cpu.c:268` is the
  authority: e.g. ADD/SUB/CMP/shifts/MUL/DIV/OR/AND/XOR write flags; MOV, MOVEA,
  MOVHI, LD, ST, IN, OUT, JAL, JR, NOP do not.
- If a flag-reader immediately follows a flag-writer: **+2 cycles**.
- One flag-neutral instruction between them removes the stall — a `MOV`, a load
  for the next iteration, an address computation, an `out.h` in a KING burst.
- The compiler does **not** schedule for this. A real profile measured 99.6% of
  branches stalling, costing 18.6% of a frame ([pcfx-v810-profiling] §5).

## 8. Hand-computing a loop — worked example

Take the span-kernel pattern from [pcfx-v810-performance] and the active renderer source:

```c
while (count--) {
    unsigned texel = ((pos >> 5) & 0x07e0) | (pos >> 27);
    out_h(0x604, cmap[src[texel]]);
    pos += step;
}
```

The v810-gcc 4.9.4 code shape is roughly (16-bit opcodes, no icache/DRAM
misses, no flag stall yet):

```asm
        srl     5, r2, r3      ; 1
        andi    0x07e0, r3, r3 ; 1
        srl     27, r2, r4     ; 1
        or      r3, r4, r4     ; 1
        ld.b    0[r5], r4      ; 3   (after `or` = +2)   r5 = src
        ld.h    0[r6], r4      ; 3   (after ld.b = +1, but r4 depends on it — no stall modeled)
        ...
```

Run the actual loop under `pcfx-headless-prof` and the per-opcode CPI column
will show `LD_B`/`LD_H` around 3.0 and `OUT_H` around 2 when the compiler emits
back-to-back OUTs — matching §5/§6, not matching the "load-use stall" folklore.
**The procedure to resolve any doubt:**

1. Write the loop in C, build, disassemble with `v810-objdump -d game.elf`.
2. Sum the base costs from §5 for each instruction.
3. Add §6 pairings for every LD-after-X and OUT-after-OUT you see.
4. Add §7 stalls where a Bcc/SETF follows a flag-writer.
5. Compare with the profiler's per-opcode `%cyc` and the loop's CPI. If the
   profiler shows more, the difference is DRAM page changes (§4) and icache
   misses (§3) — the profile report tells you which.

## 9. What the model is and is not

The emulator's cycle model is **scanline/dot accurate for what it models**, but
it does not model:

- **KING/VDC/CD bus contention** against the CPU. Moving work to a period when
  KING's DMA is active can profile identically and run worse on hardware.
- **Sub-cycle races** between CPU writes and video engine state.
- Anything about **hardware 3D** — there is none in a retail PC-FX.

And it *does* model things other emulators omit, verified against real hardware:
the flag-use stall (+2, measured dshadoff/FPGA 2025 — see the comment at
`v810_cpu.c:260`), the DRAM 2 KiB page (+3, from the RAM timing), and the
consecutive-OUT/load clustering rules. These are exactly the numbers the
profiler reports, so a prediction from this skill should match a profiler run
within noise; if it does not, **the skill or your reading is wrong — check the
source files listed in §1 before changing your code.**

## 10. Verifying a claim you are unsure about

Someone (a model, a forum, a blog) told you "X costs N cycles". Do not argue.
Do this:

```bash
grep -n "BEGIN_OP(X)" vendor/pcfxemu/mednafen/hw_cpu/v810/v810_oploop.inc
# read the ADDCLOCK() right below it; then check the pairing (§6) and
# flag-stall (§7) code around it; then check the icache/DRAM model (§3, §4).
```

Every number in this skill maps to a line of source. If the line says something
different from this skill, the source wins — file a fix for the skill.

## Related

[pcfx-v810-profiling] for reading the profiler's output against this model ·
[pcfx-v810-performance] for the cost model and the measured catalogue ·
[pcfx-fixed-point] for arithmetic costs · [pcfx-v810-performance] for hot loops
this model explains · [pcfx-optimize-loop] for the search loop built on these
numbers.
