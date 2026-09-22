# Task: RAINBOW video player is a black screen after moving to libpcfx

I had a working PC-FX RAINBOW + MP2 video player built against liberis. I moved it to
libpcfx (swapped `eris_*` calls for the libpcfx equivalents). It compiles and links
cleanly and the disc boots past the BIOS, but the screen stays black forever and there
is no sound. The old liberis build of the same stream plays fine.

I dumped RAM after 2500 frames and read the player's globals through the linker map:
the CD DMA state machine is sitting in state 2 with a delay counter of 0, and
`g_scsi_dma_started` is 3, `g_video_frames_presented` is 0. It looks like the CD DMA
state machine stops being polled after a few calls. Maybe the SCSI reset I swapped in
is different?

What changed in video setup (diff, liberis on `-`, libpcfx on `+`):

```c
 static void setup_video(void) {
-    eris_king_init();
-    eris_tetsu_init();
+    king_init();
+    king_set_kram_mode(1); /* 4-Mbit KRAM mode before access */
+    tetsu_init();
     ...
-    eris_low_sup_set_control(0, 0, 1, 0);
-    eris_low_sup_set_control(1, 0, 1, 0);
+    vdc_setreg(0, VDC_REG_CR, VDC_CR_BB);
+    vdc_setreg(1, VDC_REG_CR, VDC_CR_BB);
 }
```

For reference, liberis implements `eris_low_sup_set_control(chip, increment, bg_show,
spr_show)` as: select VDC register 5, `in.h` the data port, `andi 0xE73F`, OR in
`increment<<11 | bg_show<<7 | spr_show<<6`, `out.h` it back. libpcfx `vdc.h` defines
`VDC_CR_BB 0x0080`.

Unchanged helper code the boot path uses:

```c
static inline int vblank_active(void) {
    volatile uint16_t * const sr = (volatile uint16_t *)0x80000400u;
    return ((*sr & 0x0020u) != 0);
}

static void wait_vblank(void) {
    while (!vblank_active()) { }
    while (vblank_active()) { }
}

static void pcfv_boot_stream_async(void) {
    scheduler_start_if_idle();
    while (!g_header_ready) {
        scheduler_poll();                 /* advances the CD DMA state machine */
        pcfv_mp2_decode_budget(PCFV_MP2_FIELD_BUDGET);
        wait_vblank();
        if (g_cd_dma.state == CD_DMA_ERROR) fail_black_loop();
    }
    ...
}
```

Find the root cause, give the fix as code, and say how you would verify it before
telling me it is fixed. Do not guess register meanings you cannot support.
