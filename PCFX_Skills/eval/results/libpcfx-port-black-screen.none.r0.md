<reasoning>
Let me analyze this problem carefully.

The user has a PC-FX video player that worked with liberis but shows a black screen after migrating to libpcfx. Let me trace through the clues:

1. **Symptoms**: Black screen, no sound, boots past BIOS
2. **RAM dump analysis**: 
   - CD DMA state machine in state 2 with delay counter 0
   - `g_scsi_dma_started` is 3
   - `g_video_frames_presented` is 0
   - "CD DMA state machine stops being polled after a few calls"

3. **The video setup diff**:
   - liberis: `eris_low_sup_set_control(0, 0, 1, 0)` and same for chip 1
   - libpcfx: `vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)` and same for chip 1

4. **Key detail about liberis implementation**:
   - `eris_low_sup_set_control(chip, increment, bg_show, spr_show)` 
   - Selects VDC register 5
   - Reads data port with `in.h`
   - `andi 0xE73F` (clears bits)
   - ORs in `increment<<11 | bg_show<<7 | spr_show<<6`
   - Writes back with `out.h`

5. **libpcfx**: `VDC_CR_BB` is defined as `0x0080`

Let me decode the register 5 bits:
- Bit 11: increment
- Bit 7: bg_show
- Bit 6: spr_show

The mask `0xE73F` clears bits: let me compute `~0xE73F = 0x18C0`. In binary:
- 0xE73F = 1110 0111 0011 1111
- ~0xE73F = 0001 1000 1100 0000 = bits 11, 10, 7, 6

So the function clears bits 11, 10, 7, 6 and then sets:
- bit 11: increment
- bit 7: bg_show  
- bit 6: spr_show

With
</reasoning>

The root cause is in the video setup migration. The liberis call `eris_low_sup_set_control(0, 0, 1, 0)` sets **bit 7** of VDC register 5 (the "background show" bit), which enables the background layer to be displayed. The libpcfx replacement `vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)` writes `0x0080` to register 5, which sets **bit 7** — that part is correct.

However, the critical difference is that liberis's implementation does a **read-modify-write** of register 5: it reads the current value, clears only the specific bits it manages (11, 10, 7, 6), and sets only those. The libpcfx `vdc_setreg` does a **plain write**, which zeros out all other bits in register 5 that were set during VDC initialization — including bits that control display enable, mode, and other critical settings.

The fix is to use the same read-modify-write pattern as liberis:

```c
static void vdc_set_control(uint8_t chip, uint8_t increment, uint8_t bg_show, uint8_t spr_show) {
    vdc_setreg(chip, VDC_REG_CR, VDC_REG_CR);  /* select register 5 */
    uint16_t val = vdc_getreg(chip, VDC_REG_CR);
    val &= 0xE73F;  /* clear bits 11, 10, 7, 6 */
    val |= (increment << 11) | (bg_show << 7) | (spr_show << 6);
    vdc_setreg(chip, VDC_REG_CR, val);
}

static void setup_video(void) {
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    ...
    vdc_set_control(0, 0, 1, 0);
    vdc_set_control(1, 0, 1, 0);
}
```

If libpcfx doesn't expose `vdc_getreg`, you'll need to add it or use the raw port read directly.

**Verification before declaring fixed:**

1. **Check the register value**: After `setup_video()` returns, read back VDC register 5 on both chips and confirm bit 7 is set and the other bits match what they were before the call (compare against a dump taken right after `tetsu_init()`).

2. **Check the symptom chain**: The black screen with `g_video_frames_presented == 0` and the CD DMA state machine stalling is consistent with the display being disabled — if the VDC isn't showing the background, the player's frame presentation counter never increments, and depending on how the scheduler is gated, the CD DMA polling loop may effectively stop advancing. After the fix, `g_video_frames_presented` should increment each vblank.

3. **Audio check**: The "no sound" symptom is likely a downstream effect of the same stall (if audio scheduling is tied to video frames or the same scheduler that's not advancing). Verify audio resumes once video frames are presenting.

4. **Compare register dumps**: Dump all VDC registers after `setup_video()` in both the working liberis build and the fixed libpcfx build — they should match.