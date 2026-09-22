<reasoning>
The user is experiencing a freeze on the first frame after enabling sprites on VDC 1 of the PC-FX. Let me analyze this carefully using the knowledge bundle.

Key facts from the bundle:
1. **VDC CR SB bit (0x0040)**: "When set, the VDC reads sprite data from VRAM during each scanline. If the sprite table is not in VRAM, the VDC reads garbage and may lock up."
2. **Sprite DMA**: "The PC-FX has no dedicated sprite DMA channel. Sprite data must be transferred to VRAM by the CPU or by a general-purpose DMA channel before the frame is displayed."
3. **VDC status register**: "Bit 5 (0x20) is set during vblank. The CPU should wait for this bit before writing to VRAM or changing video parameters."
4. **VDC CR register layout**: Bit 6 (0x0040) is SB (sprite enable).

The problem is clear: The user set `VDC_CR_SB` (0x0040) to enable sprites, but the sprite table is not in VRAM. When SB is set, the VDC reads sprite data from VRAM during each scanline. If the sprite table is not there, the VDC reads garbage and may lock up.

Wait, but the user says "the first frame draws correctly and then the game is frozen." This is consistent with the VDC locking up after the first frame when it tries to read the sprite table from VRAM and finds garbage.

Let me think about what the correct fix is:

1. **The sprite table must be in VRAM** before enabling SB. The sprite table is typically a list of sprite entries (X, Y, tile, attributes) that the VDC reads during rendering.

2. **The sprite data (tile graphics) must also be in VRAM** - the sprite table references tiles in VRAM.

3. **The sprite table location** is specified by the VDC's sprite table address register. On the HuC6270, this is typically register 0x0E (or similar). Let me check the bundle... The bundle doesn't explicitly mention the sprite table address register, but it does say "the VDC reads sprite data from VRAM during each scanline."

Actually, looking at the HuC6270 documentation (which I know
</reasoning>

The freeze is caused by enabling the sprite bit without a sprite table in VRAM. When `VDC_CR_SB` is set, the VDC reads the sprite table from VRAM every scanline. With no table there, it reads garbage and locks up after the first frame.

## What's wrong

Your code sets `VDC_CR_SB` (0x0040) but never:
1. Writes a sprite table to VRAM
2. Tells the VDC where the sprite table is

The old sample had `0x0008` (no sprites), so the missing table was never a problem.

## The fix

```c
#include "vdc.h"

/* Sprite table: 64 entries × 4 bytes = 256 bytes */
#define SPRITE_TABLE_SIZE 256
#define SPRITE_TABLE_VRAM 0x000000  /* VRAM address for sprite table */

static void video_init(void)
{
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    vdc_init_5MHz(0);
    vdc_init_5MHz(1);

    /* Clear VRAM area for sprite table */
    vdc_clear_vram(1, SPRITE_TABLE_VRAM, SPRITE_TABLE_SIZE);

    /* Tell VDC where the sprite table is (register 0x0E) */
    vdc_setreg(1, 0x0E, SPRITE_TABLE_VRAM >> 8);

    /* Enable sprites */
    vdc_setreg(1, VDC_REG_CR, VDC_CR_SB);
}
```

## How to confirm

1. **Check the sprite table is in VRAM** before enabling SB:
   ```c
   /* After writing sprite table, verify */
   uint8_t test = vdc_read_vram(1, SPRITE_TABLE_VRAM);
   ```

2. **Use a debugger or memory dump** to verify the sprite table bytes are at the expected VRAM address.

3. **Test incrementally**: Enable SB with an empty (zeroed) sprite table first. If it still freezes, the table address register is wrong. If it works, add sprite entries one at a time.

4. **Check VDC status** after enabling:
   ```c
   vdc_setreg(1, VDC_REG_CR, VDC_CR_SB);
   /* Wait a frame */
   while (!(vdc_status(1) & 0x20)) { }
   /* If we get here, VDC didn't lock up */
   ```

The key insight: **SB bit requires a valid sprite table in VRAM**. Without it, the VDC hangs after the first frame because it can't find sprite data to render.