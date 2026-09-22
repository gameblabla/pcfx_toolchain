---
name: pcfx-audio
description: PC-FX sound - KING ADPCM sample playback (channels, KRAM banks, rates), the PSG/soundbox, and CD-DA music via the SCSI/CD path. Use when adding sound effects or music, when audio plays at the wrong pitch or as garbage, or when audio and graphics fight over KRAM.
---

# Audio

Two practical sound sources on the PC-FX:

- **KING ADPCM** — 2 channels of ADPCM streamed from KRAM. Use for sound effects.
- **CD-DA** — redbook audio tracks played by the CD drive. Use for music. Costs no CPU
  and no RAM, but you cannot play a track while streaming data from the same drive.

(There is also a PC-Engine-style PSG in the soundbox — `pcfx/sound.h`,
`vendor/libpcfx/examples/psg`. Cheap, but limited.)

## 1. ADPCM sound effects

Samples live in **KRAM**, on whichever page `king_set_kram_pages(..., adpcm)` selects.
Per channel, KING registers give a start, end and half-buffer address:

| Register | Meaning |
|---|---|
| `0x50` | `KS_MODE` |
| `0x51` / `0x52` | `KS_CR0` / `KS_CR1` — control |
| `0x53` | `KS_STAT` — status |
| `0x58` / `0x59` / `0x5a` | channel 0 START / END / HALF address |
| `0x5c` / `0x5d` / `0x5e` | channel 1 START / END / HALF address |

The play address auto-increments START → END; the HALF address raises an IRQ at the
midpoint so you can refill the other half for streaming playback.

Practical shape used by doom-pcfx: bake all effects into **one bank**, indexed by sound
id, upload it to KRAM once at load time, and for each trigger point a channel at that
sample's start/end. No per-effect allocation at runtime.

**Playback rate.** doom-pcfx hard-codes 8 kHz and flags it as unverified — a wrong rate
means every effect plays at the wrong pitch. If pitch sounds off, confirm the rate encoding
against `vendor/pcfxemu/mednafen/pcfx/king.c` rather than trusting a constant, and check with
`pcfx-headless --wav out.wav` against the source sample.

**KRAM budget.** The sample bank shares the page with your framebuffer and RAINBOW —
this is a real constraint, not a theoretical one (doom-pcfx had ~1389 words of margin).
Add a `_Static_assert` on the bank size. See [pcfx-kram-layout].

## 2. CD-DA music

libpcfx has a resilient CD-DA API (`src/cdda.c`). The hard-won details, from libpcfx's
own commit history — this took many iterations against real hardware:

- **Track numbers are sent as BCD, not binary** (`cdda: send track numbers as BCD`).
  This was fixed *after* an earlier commit sent them as binary; sending binary silently
  plays the wrong track or nothing.
- Start playback with the BIOS's **single `D8`** command, retrying `D9` alone
  (`cdda: start playback with the BIOS's single D8`).
- Match the known-good NEC audio command sequence exactly. Improvised sequences worked in
  the emulator and failed on hardware.
- **Act on the drive's returned status** rather than assuming a command took effect; a
  play command can be swallowed.

Use the library's API rather than issuing SCSI commands yourself.

## 3. Audio and the rest of the machine

- **Pause the interval timer across every CD operation.** libpcfx shipped
  `cd/cdda: pause the interval timer across EVERY CD operation (IRQ-vs-KING corruption)` —
  a timer IRQ landing inside a KING/CD sequence corrupts it.
- **Keep KING runs interrupt-atomic** — doom-pcfx made ADPCM and RAINBOW KING runs atomic
  to stop real-hardware garble. See [pcfx-kram-layout].
- **Disarm KING SCSI DMA (register `0x0B`) at every teardown**, or a later transfer
  inherits a live DMA arm.
- A resident audio/SCSI poll can be surprisingly expensive: doom-pcfx's profiler found
  `_eris_low_scsi_command` burning **~15% of all cycles** on a level with no CD activity.
  If you are hunting for frame time, check whether your audio layer is polling.
- ADPCM reads KRAM continuously while playing — it is a competing reader for KRAM
  bandwidth, and a wrong page bit makes it read your framebuffer as audio (loud garbage).

## 4. Verifying audio

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2400 \
    --wav out.wav --commands commands.txt game.cue
```

Compare length and pitch against the source sample. Audio is one of the areas where the
emulator is least authoritative — treat a clean emulator capture as necessary, not
sufficient. See [pcfx-emulator-testing] §7.

## Related

[pcfx-kram-layout] · [pcfx-cd-assets] · [pcfx-emulator-testing].
Reference: `vendor/libpcfx/docs/RETAIL_SCSI_TRACE.md`,
`vendor/doompcfx/` plus the bundled `PCFX_Skills/pcfx-audio/SKILL.md`.
