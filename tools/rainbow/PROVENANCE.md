# Provenance of `tools/rainbow`

Host-only PC-FX RAINBOW (HuC6271) authoring tools. Everything here runs on the
build machine; nothing runs on the V810.

## What each file is

| File | Role |
|---|---|
| `rainbow_codec.py` | MPCONV-compatible HuC6271 still-image encoder (base tables, integer FDCT, null runs, rescale controls, stuffed sizes, word alignment, inner dummy + guard). |
| `rainbow_decode.py` | Strict entropy validator + approximate host preview. Follows `pcfxemu`'s decoder for Huffman/zigzag/null/rescale semantics; the floating IDCT and chroma upsampling are approximations. |
| `rainbow.py` | CLI: `image`, `video`, `inspect`, `repair-legacy`. Imports the two modules above plus `pcfv`. |
| `pcfv.py` | `PCFV0001` sector container (video frames + interleaved MP2) shared by authoring, repair, and inspection. |

`rainbow_codec.py` was derived from Doom PC-FX's `gen_pcfx_rainbow_bg.py`
(`tools/large-game/doom/`, mirrored at `vendor/doompcfx/tools/`), which in turn
was reverse-engineered from `MPCONV2.EXE` (base tables at data offsets
`0x0902`/`0x0942`, integer FDCT, `0x10..0x1F` scale controls, null runs) and
checked against the HuC6272 manual (`DOCUMENTATION/ORIGINAL_JPN/C6272_2.WRI`,
§3.4.2: three `0000H` guard words per 16-raster block; scrolling/split
playback) and `MPCONV2.HLP` (scale 0 finest … 15 coarsest, word alignment +
separate dummy region).

`rainbow_decode.py` transcribes `vendor/pcfxemu/mednafen/pcfx/rainbow_fast.c`
(Huffman LUTs, zigzag, null-run fill, qtable rescale, EOB handling) with a
stricter physical-framing check than the emulator needs: it rejects truncated
entropy, unstuffed `FF`, bad sizes, and missing dummy/guard words. It is a
gate for catching bad encodes on the host, not a third emulator backend.

## What these tools do NOT prove

- The host preview is **not pixel-exact**: neither emulator backend nor retail
  silicon is modelled exactly (integer IDCT rounding, chroma interpolation).
- A passing `inspect` does **not** prove the 16-raster transfer deadline is met
  under the real workload, or that timing is hardware-correct. Confirm motion,
  scrolling, and sound on `pcfx-headless` captures and, for release claims, on
  real hardware (see `pcfx-emulator-testing` §7).
- `repair-legacy` preserves entropy bits; it cannot repair coefficients that
  were quantized with the wrong tables or arithmetic. Re-encode from source
  when quality is the problem.
