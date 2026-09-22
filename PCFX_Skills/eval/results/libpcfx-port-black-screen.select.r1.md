<reasoning>
The user has a PC-FX RAINBOW + MP2 video player that worked with liberis but is now a black screen after porting to libpcfx. Let me analyze the situation using the knowledge modules provided.

Key symptoms:
- Compiles and links cleanly
- Boots past BIOS
- Black screen forever, no sound
- Old liberis build of same stream plays fine
- RAM dump shows: CD DMA state machine in state 2 with delay counter 0, `g_scsi_dma_started` is 3, `g_video_frames_presented` is 0
- The CD DMA state machine stops being polled after a few calls

The user suspects the SCSI reset swap, but let me look at the actual code changes.

The critical change is in `setup_video()`:
- Old: `eris_low_sup_set_control(0, 0, 1, 0)` and `eris_low_sup_set_control(1, 0, 1, 0)`
- New: `vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)` and `vdc_setreg(1, VDC_REG_CR, VDC_CR_BB)`

From the knowledge modules, specifically `pcfx-liberis-port` §3 "The calls that are NOT renames" - "VDC control register (the black-screen port)":

> liberis `eris_low_sup_set_control()` selects VDC register 5, **reads the data port**, masks with `0xE73F`, ORs in increment/BG/sprite bits and writes it back. It looks like a read-modify-write of CR, but reading the VDC data port returns the **VRAM read latch**, not CR (`vendor/pcfxemu` `VDC_Read16`). So the bits it "preserved" were whatever the read latch held — including, by luck, CR bit 3 (vblank IRQ enable).
>
> libpcfx `vdc_setreg(chip, VDC_REG_CR, VDC_CR_BB)` writes CR = `0x0080` exactly, which **clears bit 3**. Any code that then waits on the VDC status VD flag (`0x80000400` bit 5) hangs forever, because VD is only raised while CR bit 3 is set.

And from `pcfx-frame-timing` §3, the
</reasoning>

## Root cause

The port renamed `eris_low_sup_set_control()` to `vdc_setreg()`, but they are **not equivalent**. This is the documented "black-screen port" bug from the liberis→libpcfx migration.

`eris_low_sup_set_control(chip, 0, 1, 0)` does a read-modify-write of VDC register 5 (CR). It reads the data port, masks with `0xE73F`, and ORs in the BG-show bit. By accident, the VRAM read latch it read back contained CR bit 3 (vblank IRQ enable, `0x08`), so the old code preserved it.

`vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)` writes CR = `0x0080` exactly. **Bit 3 is cleared.**

Your `wait_vblank()` polls `0x80000400` bit 5 (VDC-A status VD flag). Per `vendor/pcfxemu` `vdc_video.c` (`VDC_DoVBIRQTest()`), VD is only raised while VDC CR bit 3 is set. With CR = `0x0080`, VD never rises, so `wait_vblank()` hangs forever.

The CD DMA state machine isn't broken — it's parked in `scheduler_poll()` inside `pcfv_boot_stream_async()`, which never returns because `wait_vblank()` never returns. The RAM dump you read is consistent with this: the state machine made a few calls, then the loop stopped advancing.

## Fix

Replace the VDC status wait with the Tetsu raster counter wait. This is the documented replacement and does not depend on any VDC state.

```c
/* Replace vblank_active() and wait_vblank() entirely. */

static inline unsigned tetsu_raster_stable(void)
{
    unsigned a, b;
    do {
        a = tetsu_get_raster();
        b = tetsu_get_raster();
    } while (a != b);
    return a;
}

static inline int vblank_active(void)
{
    unsigned r = tetsu_raster_stable();
    return r >= 262u || r < 22u;
}

static void wait_vblank(void)
{
    while (vblank_active()) { }
    while (!vblank_active()) { }
}
```

`tetsu_get_raster()` returns the decoded line number, so compare against decoded constants (262, 22), not raw port values.

You can leave `vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)` as-is — it correctly sets BG-show. Just don't depend on the VDC status flag for timing.

## Verification

1. **Build and run both discs at the same frame count:**
   ```bash
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2000 --screenshot good.png old-liberis-build.cue
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2000 --screenshot fixed.png new-libpcfx-build.cue
   ```
   Use `--frames 2000` or more (BIOS boot animation takes ~1200 frames).

2. **Check the player's counters via the linker map** (not hand-computed addresses):
   ```bash
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2500 --dump ram build/ram.bin new-libpcfx-build.cue
   "$V810_GCC/bin/v810-nm" build/game.elf | grep -i 'frames_presented\|g_done\|underflow'
   ```
   `g_video_frames_presented` must be > 0. If it's still 0, the fix didn't take.

3. **Compare screenshots** — content should match the old liberis build (allow a few frames of drift if boot timing changed).

4. **Run past the first loop/restart** if the player has a loop mode — per-run state that the old code never reset shows up only there.

5. **Gate the fix:** show the counter check failing on the unfixed build (it will — `g_video_frames_presented` is 0) before trusting it passing on the fixed one. A gate that has never failed is decoration.

The emulator cannot prove timing, IRQ-in-KING-pair behaviour, or bus contention — those require real hardware. But a black screen caused by a hung vblank wait will be caught by the emulator and the counter check.