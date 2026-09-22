<reasoning>
The user has a PC-FX game that freezes on the first frame after enabling sprites on VDC 1. Let me analyze this carefully using the knowledge modules provided.

Key symptoms:
1. First frame draws correctly
2. Then frozen - no animation, no input
3. Before the change (VDC_CR = 0x0008), it ran at 60 fps
4. After changing to VDC_CR_SB (0x0040), it freezes after first frame
5. User suspects sprite DMA stalling CPU

Let me look at the code:

```c
static void frame_wait(void)
{
    while (!(vdc_status(1) & 0x20)) { }     /* wait for vblank */
}
```

This is waiting on VDC status bit 0x20. Looking at the knowledge modules, specifically `pcfx-frame-timing`, there's a section about "waiting on the VDC status VD bit":

```c
/* WRONG — hangs forever unless something else keeps VDC CR bit 3 set */
static inline int vblank_active(void) {
    return (*(volatile uint16_t *)0x80000400u & 0x0020u) != 0;   /* VDC-A status, VD */
}
static void wait_vblank(void) { while (!vblank_active()) { } while (vblank_active()) { } }
```

The knowledge module says:
- `0x80000400` is VDC-A's status register (I/O port `0x400` through the `0x80000000` memory-mapped I/O window)
- Its VD flag (bit 5) is raised only while that VDC's **CR bit 3 (vblank interrupt enable, `0x08`)** is set
- Reading the status register also **clears** the flags

Now let's look at the CR values:
- Old value: `0x0008` - this has bit 3 set (vblank interrupt enable)
- New value: `VDC_CR_SB` = `0x0040` - this does NOT have bit 3 set

So the old code had CR = 0x0008, which means bit 3 was
</reasoning>

This is a known PC-FX pitfall documented in the `pcfx-frame-timing` module. The freeze is caused by your vblank wait routine, not by sprite DMA.

## What's wrong

Your `frame_wait()` polls VDC status bit 0x20 (the VD flag). That flag is only raised when the VDC's control register has **bit 3 set** (vblank interrupt enable, value 0x08).

- Old code: `vdc_setreg(1, VDC_REG_CR, 0x0008)` — bit 3 was set, so VD was raised every field and your wait worked.
- New code: `vdc_setreg(1, VDC_REG_CR, VDC_CR_SB)` = 0x0040 — bit 3 is **not** set, so VD is never raised. The first frame draws, then `frame_wait()` spins forever.

Additionally, reading the VDC status register **clears** its flags, so even if you fixed the CR, a second reader or IRQ handler could steal the edge.

## The fix

Replace the VDC status wait with the Tetsu raster counter method. This is the canonical approach used across all working projects in this workspace.

### Step 1: Replace `frame_wait()` with the Tetsu two-phase wait

```c
/* r10-r13 are caller-saved on this ABI, so they need no preservation. */
static inline void wait_frame(void)
{
    __asm__ volatile (
        "movea 0x20A0, r0, r12\n"   /* last raster of the frame */
        "movea 0x3FE0, r0, r13\n"   /* raster bit mask          */

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

### Step 2: Update your main loop

```c
int main(void)
{
    video_init();
    for (;;) {
        game_update();
        game_draw();
        wait_frame();   /* was: frame_wait() */
    }
}
```

### Step 3: Keep VDC_CR_SB for sprite display

Your sprite enable change is correct — keep it:

```c
vdc_setreg(1, VDC_REG_CR, VDC_CR_SB);   /* 0x0040: show sprites */
```

## How to confirm

1. **Build and run** with the emulator:
   ```bash
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 1800 --screenshot shot.png yourgame.cue
   ```
   Use `--frames 1800` or more — the BIOS boot animation takes ~1200 frames.

2. **Verify the loop actually loops** by screenshotting at two different frame counts:
   ```bash
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 1400 --screenshot shot1.png yourgame.cue
   "$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 1800 --screenshot shot2.png yourgame.cue
   ```
   If something moved between the two screenshots, your frame loop is working.

3. **Check input works** — the pad should now respond since the main loop is no longer stuck in `frame_wait()`.

## Why not just add bit 3 back to the CR?

You could write `vdc_setreg(1, VDC_REG_CR, VDC_CR_SB | 0x08)`, but that's not recommended because:

- It asserts a VDC interrupt every field, requiring an interrupt mask/handler story
- The Tetsu raster counter is documented in the HuC6261 manual and doesn't depend on VDC state
- It's the proven approach used by all working projects in this workspace (wolf-pcfx, AirGT, etc.)

## Important note about the raster counter

The Tetsu raster counter has a documented hardware bug: a single read can return a transitional bogus value. That's why the assembly routine reads it **twice** and checks that both reads agree before trusting the value. Don't simplify this to a single read.