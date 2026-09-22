# Qwen 3.6 27B vs. Claude — PCFX_Skills eval scorecard

Model: `Qwen3.6-27B-uncensored-heretic-v2` IQ4_XS @ `0.0.0.0:8080`, temp 0.3.
Gold answers = the actual commits in `doom-pcfx` / `descent-pcfx` / `wolf-pcfx`.

Grading: each case has N checkpoints taken from the real commit. Score = hit/N.

---

## Case `vblank-window` — doom-pcfx `32cf6d4`

"video: fix vblank window to real C6261 EVB=22/SVB=262, reorder presenter"

| # | Checkpoint | no skills | skills r1 | skills r2 |
|---|---|---|---|---|
| 1 | Identifies `raster >= 240` as the defect | ~ | ✅ | ✅ |
| 2 | States EVB=22 / SVB=262 | ❌ | ✅ | ✅ |
| 3 | Vblank = raster 262 and 0..21 | ❌ | ✅ | ✅ |
| 4 | 240..261 are active picture / bottom rows | ❌ | ✅ | ✅ |
| 5 | Correct predicate boundary (`>=262`, not `>=261`) | ❌ | ❌ off-by-one | ✅ |
| 6 | Centralize into ONE shared definition | ✅ | ✅ | ✅ |
| 7 | Deletes the "spin to raster N" threshold pattern | ❌ | ❌ kept it, spins to 250 | ✅ |
| 8 | Uses the wrap-edge wait to enter vblank | ❌ | ❌ | ✅ |
| 9 | Says the emulator cannot confirm this | ✅ | ~ vague + invented method | ✅ |
| | **score** | **2.5/9** | **5.5/9** | **9/9** |

### Round-1 failure analysis → skill changes made

1. **Off-by-one in the predicate (cp5).** The skill stated the numbers in prose
   ("Active picture: rasters 22 … 261") and the model re-derived code from them,
   writing `r >= 261` — including an active line in "vblank".
   → *Fix: ship the predicate as copy-paste C, not as prose to be re-derived.*

2. **Kept the anti-pattern (cp7, cp8).** Having correctly said 240–261 is active
   picture, it then wrote `present_spin_to(250u)` — spinning to a raster it had
   just called active display. It preserved the *shape* of the buggy code it was
   shown. Stating a fact does not displace a pattern already on the page.
   → *Fix: add an explicit ANTI-PATTERN block naming `spin_to(threshold)` and
   giving the replacement call. Skills need **replacement recipes**, not facts.*

3. **Invented a verification method (cp9).** Proposed diffing two screenshots at
   the same frame number to detect a timing fix — meaningless.
   → *Fix: add a "what the emulator does not model" table to
   pcfx-emulator-testing, and cross-link it from every timing claim.*

### Control observation

Without skills the model was **confidently wrong and fabricated citations**:
invented "vblank = 240..259", invented "PC-FX Hardware Manual §4.1.2" and
"§5.3.1". Both do not exist. This is the failure mode the bundle must suppress —
so every hardware constant in the bundle carries its real manual reference, and
the preamble tells the model the bundle overrides its priors.


---

## Case `character-8bpp-10fps` — 3DCharacterSpinning `de68a6b..3f91bdb`

"preserve the complete character asset while restructuring and reducing 8bpp output work"

This case has been added but was **not run in this environment** because the local Qwen
server was unavailable. Run `none`, `all`, and the selected set
`pcfx-character-8bpp,pcfx-v810-profiling,pcfx-v810-performance,pcfx-software-3d,pcfx-king-framebuffer`.

| # | Checkpoint | no skills | selected skills |
|---|---|---|---|
| 1 | Rejects mesh decimation and preserves 5,563 vertices / 10,628 faces | pending | pending |
| 2 | Does not revive the general 4bpp/16bpp renderer experiments | pending | pending |
| 3 | Replaces two 28-byte face arrays with compact packed keys + one final expansion | pending | pending |
| 4 | Emits projected byte offsets offline and validates the uint16 range | pending | pending |
| 5 | Keeps a native 256×240 raster and correctly treats 512×256 as affine KRAM packing | pending | pending |
| 6 | Provides a DRAM-aware V810 affine delta uploader with one duplicated halfword per logical pixel | pending | pending |
| 7 | Generates outline as a postprocess rather than a second geometry pass | pending | pending |
| 8 | Explains 2 KiB DRAM-page and 1 KB direct-mapped icache consequences | pending | pending |
| 9 | Gates a separate 2bpp outline surface on measured outline/KRAM cost | pending | pending |
| 10 | Provides clean A/B profiling and refuses to claim 10 FPS without measurement | pending | pending |


---

## Case `freestanding-character-runtime` — 3DCharacterSpinning strict runtime audit

This case has been added but was **not run in this environment** because the local Qwen
server and V810 toolchain were unavailable. Use selected skills
`pcfx-freestanding-runtime,pcfx-character-8bpp,pcfx-v810-profiling,pcfx-fixed-point`.

| # | Checkpoint | no skills | selected skills |
|---|---|---|---|
| 1 | Distinguishes a strict freestanding renderer from the normal SDK/newlib template | pending | pending |
| 2 | Removes libc/libsim/libgcc and `-mprolog-function`, with link failure as a feature | pending | pending |
| 3 | Removes float/double/int64/long-long and libc calls, not only their headers | pending | pending |
| 4 | Uses explicit V810 `DIV`/`DIVU` and declares `r30` clobbered | pending | pending |
| 5 | Generates the reciprocal table offline and explains 4 KiB/2 KiB page alignment | pending | pending |
| 6 | Removes timer IRQ and handler registration; labels any polled HUD coarse | pending | pending |
| 7 | Separates source audit from final map/ELF archive and symbol audit | pending | pending |
| 8 | Reports current FPS/DRAM/i-cache as unavailable rather than estimated or zero | pending | pending |


---

## Case `character-emulator-profile` — authoritative FPS/DRAM/i-cache capture

This case checks whether a weaker agent distinguishes a real instrumented emulator
measurement from a plausible estimate or ordinary headless run. Use selected skills
`pcfx-v810-profiling,pcfx-emulator-testing,pcfx-character-8bpp,pcfx-freestanding-runtime`.

| # | Checkpoint | no skills | selected skills |
|---|---|---|---|
| 1 | Clean-builds and audits the fresh ELF/map before measurement | pending | pending |
| 2 | Rejects an ordinary headless binary without a complete `V810 PROFILE` block | pending | pending |
| 3 | Warms once and proves nonzero presented-frame progress | pending | pending |
| 4 | Computes FPS from 32-bit `nframe` RAM delta over profiler video fields | pending | pending |
| 5 | Parses DRAM total/code-refill/data penalties and page-change split | pending | pending |
| 6 | Parses i-cache tag/subblock misses, misses/field, and fixed miss cost | pending | pending |
| 7 | Runs twice from the same warmed savestate and applies a 3% gate | pending | pending |
| 8 | Reports missing inputs/counters as unavailable or null, never zero or estimated | pending | pending |


---

## Case `libpcfx-port-black-screen` — RAINBOW+MP2 player port, 2026-09-22

Real incident: a liberis → libpcfx port linked cleanly and was a black screen. Gold
fix: `wait_vblank()` polled the VDC status VD bit, which only rises while VDC CR bit 3
is set; the port's `vdc_setreg(…, VDC_CR_BB)` cleared it. Replace with the Tetsu raster
wait. Model: `Qwen3.8-27B … IQ3_S` @ :8080, temp 0.3.
r0 = skills before this round (router picked `pcfx-bringup,pcfx-frame-timing,pcfx-rainbow`);
r1 = after (`pcfx-regression-triage,pcfx-liberis-port,pcfx-frame-timing,pcfx-rainbow`).

| # | Checkpoint | no skills | skills r0 | skills r1 |
|---|---|---|---|---|
| 1 | Hang is in `wait_vblank()`, not the CD DMA state machine / SCSI reset | ❌ | ✅ | ✅ |
| 2 | VD needs VDC CR bit 3; the port's CR write cleared it (links both diffs) | ~ blamed RMW, invented bits | ❌ called the CR change "fine" | ✅ |
| 3 | No invented hardware facts | ❌ invented `vdc_getreg()`, "display enable" bits | ❌ "0x80000400 is main RAM, no status register there" | ✅ cites pcfxemu source |
| 4 | Replacement: Tetsu raster, double read, correct window/edge | ❌ | ✅ | ✅ |
| 5 | Does not "fix" it by re-enabling the VDC IRQ bit | ❌ | ✅ | ✅ |
| 6 | Verifies with runtime counters (frames presented) via map + screenshots | ~ | ✅ | ✅ |
| 7 | Compares against the known-good liberis build; gate shown failing first | ~ | ❌ | ✅ |
| | **score** | **1/7** | **4/7** | **7/7** |

r0 failure → change: AGENTS.md said "KRAM is not memory-mapped", and the model
over-generalized it to "`0x80000400` is RAM". AGENTS.md now says
`0x80000000–0x807FFFFF` is the I/O-port alias. The VD trap had no anti-pattern at all;
`pcfx-frame-timing` now has one with the replacement code, and `pcfx-liberis-port`
lists the non-equivalent CR call.

## Case `rainbow-right-edge` — legacy RAINBOW encoder framing

Gold fix: strip size must count stuffed `FF 00` bytes, plus word alignment, a 2-byte
inner dummy inside the size and three `0000H` guard words outside; the emulator hid it
because the installed binary predated pcfxemu's stuffed-byte accounting fix.
Routed skills both rounds: `pcfx-rainbow,pcfx-emulator-testing`.

| # | Checkpoint | no skills | skills r0 | skills r1 |
|---|---|---|---|---|
| 1 | Size must count stored (stuffed) bytes | ❌ blamed byte padding | ✅ | ✅ |
| 2 | Right edge = byte budget runs out before the last columns | ❌ | ~ blamed alignment | ✅ |
| 3 | Word alignment + inner dummy in size + 6-byte guard outside | ❌ | ✅ (fix code order unclear) | ✅ correct code |
| 4 | Emulator: stale binary / old stuffed-byte accounting; rebuild | ❌ "well-known discrepancy" | ❌ generic "lenient" | ✅ |
| 5 | Old streams: `repair-legacy` (lossless) or re-encode | ❌ "must re-encode" | ✅ | ✅ |
| 6 | Compression: base tables + rescale controls + null runs | ❌ DC prediction | ✅ | ✅ |
| 7 | Verification: strict inspect + emulator gate + hardware | ~ | ~ no emulator gate | ✅ full ladder |
| 8 | No invented tools/limits | ❌ invented decoders/SDK video | ✅ | ✅ |
| | **score** | **0.5/8** | **6/8** | **8/8** |

Both r1 prompts describe incidents the updated skills document, so they measure
whether the skills convey the facts, not generalization. `vdc-status-frame-wait`
(below) is the transfer test: same trap, different chip/API/story.

## Case `vdc-status-frame-wait` — transfer test (VDC-B, `vdc_status()`, sprites)

Same trap in a different story: CR changed from `0x0008` to `VDC_CR_SB`, frame wait
polls `vdc_status(1) & 0x20`. Routed skills: `pcfx-frame-timing,pcfx-regression-triage,pcfx-vdc-tiles-sprites`.

| # | Checkpoint | no skills | skills r1 |
|---|---|---|---|
| 1 | Hang is in `frame_wait()`, not sprite DMA/VDC lock-up | ❌ "VDC locks up without a SAT" | ✅ |
| 2 | VD needs CR bit 3; new CR value cleared it | ❌ | ✅ |
| 3 | No invented API/registers | ❌ `vdc_clear_vram()`, SAT "register 0x0E" | ✅ |
| 4 | Tetsu raster wait (double read, wrap edge) | ❌ | ✅ canonical asm |
| 5 | Does not re-add CR bit 3 as the fix (IRQ implications) | ❌ | ✅ explains why |
| 6 | Verifies the loop advances (two frame counts / counters), not with the broken wait | ❌ verifies with the same VD wait | ✅ |
| | **score** | **0/6** | **6/6** |

Takeaway: the lesson transferred to a chip, API and symptom the skill does not
describe verbatim. The unaided model's characteristic failure is unchanged since
the first case: a plausible mechanism plus invented API names.

Transcripts: `results/libpcfx-port-black-screen.*`, `results/rainbow-right-edge.*`,
`results/vdc-status-frame-wait.*`.
