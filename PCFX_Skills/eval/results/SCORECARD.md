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
