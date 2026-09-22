# Task: game freezes on the first frame after enabling sprites

My PC-FX game draws its playfield with KING BG0 and uses the second HuC6270 (VDC 1)
for sprites. Until today VDC 1 displayed nothing; its control register was set up
from an old sample. I added sprites:

```c
static void video_init(void)
{
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    vdc_init_5MHz(0);
    vdc_init_5MHz(1);
    ...
-   vdc_setreg(1, VDC_REG_CR, 0x0008);      /* from the old sample */
+   vdc_setreg(1, VDC_REG_CR, VDC_CR_SB);   /* 0x0040: show sprites */
}

static void frame_wait(void)
{
    while (!(vdc_status(1) & 0x20)) { }     /* wait for vblank */
}

int main(void)
{
    video_init();
    for (;;) {
        game_update();
        game_draw();
        frame_wait();
    }
}
```

Now the first frame draws correctly and then the game is frozen: no animation, pad
input ignored. Before the change it ran at 60 fps. I think the sprite DMA might be
stalling the CPU. What is wrong, what should the code be, and how do I confirm it?
