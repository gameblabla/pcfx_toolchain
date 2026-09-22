<reasoning>
The user has a PC-FX RAINBOW video player that was working with liberis but is now black after moving to libpcfx. Let me analyze the clues:

1. **State machine stuck**: CD DMA state machine is in state 2 with delay counter 0, `g_scsi_dma_started` is 3, `g_video_frames_presented` is 0. This means the CD DMA state machine stops being polled after a few calls.

2. **The vblank detection code**:
```c
static inline int vblank_active(void) {
    volatile uint16_t * const sr = (volatile uint16_t *)0x80000400u;
    return ((*sr & 0x0020u) != 0);
}
```

This is reading memory at `0x80000400` to detect vblank. But according to the AGENTS.md:
- "VRAM is memory-mapped at `0x8000` / `0x80000000`" is FALSE
- "KRAM is not memory-mapped. It is reachable only through KING I/O ports `0x600` (index) and `0x604` (data)."

So `0x80000400` is NOT a valid memory-mapped address for any status register. This is likely reading garbage or zero from main RAM (or whatever happens to be at that address), which would make `vblank_active()` always return 0 (or some constant value).

If `vblank_active()` always returns 0:
- `wait_vblank()` would spin forever in the first `while (!vblank_active())` loop
- This would block `pcfv_boot_stream_async()` from ever calling `scheduler_poll()` again after the first iteration
- The CD DMA state machine would stop advancing

Wait, but the user says "the CD DMA state machine is sitting in state 2 with a delay counter of 0" - this suggests it advanced a few times and then stopped. If `wait_vblank()` blocked forever on the first call, it would be in state 0 or 1.

Actually, let me reconsider. If `vblank_active()` returns a constant value (say 0), then:
- First call to `wait_vblank()`: spins forever
</reasoning>

## Root cause

`vblank_active()` reads `0x80000400` as if it were a memory-mapped status register. On the PC-FX, KRAM is not memory-mapped — it is reachable only through the KING I/O ports `0x600` (index) and `0x604` (data). There is no status register at `0x80000400`. The read returns whatever happens to be at that address in main RAM, so `vblank_active()` returns a constant value.

If it returns 0 (the likely case), `wait_vblank()` spins forever in its first loop:

```c
while (!vblank_active()) { }   // spins forever if vblank_active() is always 0
```

This blocks `pcfv_boot_stream_async()` from calling `scheduler_poll()` again after the first iteration. The CD DMA state machine advances a few times (state 0 → 1 → 2) and then stops being polled, which matches your RAM dump exactly: state 2, delay 0, `g_scsi_dma_started` = 3, `g_video_frames_presented` = 0.

The old liberis build worked because it used `eris_*` calls that handled vblank correctly; the bug was introduced when you replaced them with your own `wait_vblank()` helper.

## Fix

Replace the fake memory-mapped vblank detection with the canonical Tetsu raster double-read wait. This is the verified working routine from the workspace template:

```c
/* Replace the broken vblank_active() and wait_vblank() entirely */

static inline void wait_vblank(void)
{
    __asm__ volatile (
        "movea 0x20A0, r0, r12\n"   /* last raster of the frame (261 << 5) */
        "movea 0x3FE0, r0, r13\n"   /* raster bit mask                   */

        "1:\n"                      /* wait until this frame is finished */
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"     /* read twice: hardware bug */
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 1b\n"
        "cmp r10, r12\n"
        "bne 1b\n"

        "2:\n"                      /* then wait until the next one starts */
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 2b\n"
        "cmp r10, r12\n"
        "be 2b\n"                   /* still the last raster: keep waiting */
        : : : "r10", "r11", "r12", "r13");
}
```

Delete `vblank_active()` — it has no correct implementation as a memory read.

## Verification

1. **Build and run in the emulator with enough frames:**
   ```bash
   make clean && make LIBPCFX="$LIBPCFX" cd
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2500 --screenshot shot.png yourgame.cue
   ```
   Use `--frames 2500` or more — the BIOS boot animation takes ~1200 frames.

2. **Check that the frame loop actually loops:** Take screenshots at two different frame counts (e.g., 1400 and 1800) and confirm something moved. If the image is identical, the loop is still blocked.

3. **Dump RAM again after 2500 frames** and verify:
   - `g_video_frames_presented` > 0 (video is actually being presented)
   - The CD DMA state machine is cycling, not stuck in state 2
   - `g_scsi_dma_started` is being reset appropriately between transfers

4. **Confirm the picture:** The screenshot should show video content, not a black screen. If it's still black but the state machine is cycling, the problem has moved downstream (e.g., RAINBOW layer not enabled on Tetsu, or the stream isn't being decoded).

The VDC control register change you made (`vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)`) is correct — `VDC_CR_BB` (0x0080) sets the background show bit, matching what the liberis call did. That part is fine.