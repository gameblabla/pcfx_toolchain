/* Static KING 8bpp picture, 60 palette updates per second, zero pixel writes
 * after startup. See PCFX_Skills/pcfx-palette-transitions/SKILL.md. */
#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include "../../game-demo-common/wait_frame.h"
#include "fade_palette.h"

#define WIDTH 256u
#define HEIGHT 240u
#define PAGE0_WORD_ADDR 0u

volatile u32 palette_steps_presented;

static void king_reg16(u16 reg, u16 value)
{
    __asm__ volatile ("out.h %[reg], 0x600[r0]\n"
                      "out.h %[value], 0x604[r0]\n"
                      : : [reg] "r" (reg), [value] "r" (value));
}

static void draw_once(void)
{
    unsigned y, x;
    king_set_kram_write(PAGE0_WORD_ADDR, 1);
    /* Keep KRAM_DATA latched for the entire bitmap upload. */
    __asm__ volatile ("out.h %[reg], 0x600[r0]" : : [reg] "r" ((u16)0x000e));
    for (y = 0; y < HEIGHT; ++y) {
        for (x = 0; x < WIDTH; x += 2) {
            u16 left = (u16)(1u + ((x / 16u + y / 16u) % 15u));
            u16 right = (u16)(1u + (((x + 1u) / 16u + y / 16u) % 15u));
            u16 pair = (u16)((left << 8) | right);
            __asm__ volatile ("out.h %[word], 0x604[r0]" : : [word] "r" (pair));
        }
    }
}

int main(void)
{
    u16 microprogram[16];
    unsigned i, step = 0, direction = 1;

    king_init();
    tetsu_init();
    king_set_kram_mode(1);
    king_set_kram_pages(0, 0, 0, 0);
    king_set_bg_mode(KING_BGMODE_256_PAL, KING_BGMODE_NONE,
                     KING_BGMODE_NONE, KING_BGMODE_NONE);
    king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                     KING_BGSIZE_256, KING_BGSIZE_256);
    king_set_bat_cg_addr(KING_BG0, 0, PAGE0_WORD_ADDR >> 10);
    king_set_bat_cg_addr(KING_BG0SUB, 0, PAGE0_WORD_ADDR >> 10);
    king_set_scroll(KING_BG0, 0, 0);
    king_set_scroll(KING_BG0SUB, 0, 0);
    for (i = 0; i < 8; ++i) microprogram[i] = KING_CODE_ROTATE;
    for (; i < 16; ++i) microprogram[i] = KING_CODE_NOP;
    king_disable_microprogram();
    king_write_microprogram(microprogram, 0, 16);
    king_enable_microprogram();
    king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 1);
    king_reg16(0x38, 0x0100); king_reg16(0x39, 0);
    king_reg16(0x3a, 0); king_reg16(0x3b, 0x0100);
    king_reg16(0x3c, 0); king_reg16(0x3d, 0);

    /* Prepare the bitmap and black palette before making BG0 visible. */
    draw_once();
    tetsu_set_king_palette(0, 0, 0, 0);
    for (i = 0; i < 16; ++i) tetsu_set_palette((u16)i, fade_palette[0][i]);
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_256, TETSU_COLORS_16,
                         0, 0, 1, 0, 0, 0, 0);

    for (;;) {
        /* Wait first; all 16 palette writes fit at the leading blank edge.
         * No KRAM pixel writes or color conversion happen in this loop. */
        game_screen_wait_frame();
        for (i = 0; i < 16; ++i)
            tetsu_set_palette((u16)i, fade_palette[step][i]);
        ++palette_steps_presented;
        if (direction) {
            if (++step == 31u) direction = 0;
        } else if (step-- == 0u) {
            step = 1u;
            direction = 1;
        }
    }
    return 0;
}
