#ifndef PCFX_GAME_DEMO_WAIT_FRAME_H
#define PCFX_GAME_DEMO_WAIT_FRAME_H
#include <pcfx/types.h>

/* The raster port can return one bad sample at a transition: accept only a
 * pair of matching reads, then wait for line 261 to wrap to the next field. */
static void game_screen_wait_frame(void)
{
    __asm__ volatile (
        "movea 0x20A0, r0, r12\n"
        "movea 0x3FE0, r0, r13\n"
        "1:\n"
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 1b\n"
        "cmp r10, r12\n"
        "bne 1b\n"
        "2:\n"
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 2b\n"
        "cmp r10, r12\n"
        "be 2b\n"
        : : : "r10", "r11", "r12", "r13");
}

#endif
