#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/vdc.h>
#include <pcfx/contrlr.h>

#include "sprite16_meta.h"
#include "../../game-demo-common/wait_frame.h"

#define PATTERN_BASE 0x2000u
#define SAT_BASE     0xFF00u
#define SPRITE_X_BIAS 0x20u
#define SPRITE_Y_BIAS 0x40u

extern const unsigned short sprite16_patterns[];

static void upload_patterns(void)
{
    for (unsigned cell = 0; cell < SPRITE16_FRAME_COUNT * SPRITE16_CELL_COUNT; ++cell) {
        vdc_set_vram_write(VDC0, (u16)(PATTERN_BASE + cell * 64u));
        for (unsigned word = 0; word < 64; ++word)
            vdc_vram_write(VDC0, sprite16_patterns[cell * 64u + word]);
    }
}

static void write_sat(int x, int y, unsigned frame)
{
    vdc_set_vram_write(VDC0, SAT_BASE);
    for (unsigned entry = 0; entry < 64; ++entry) {
        if (entry < SPRITE16_CELL_COUNT) {
            unsigned cx = entry & 1u;
            unsigned cy = entry / 2u;
            u16 address = (u16)(PATTERN_BASE +
                (frame * SPRITE16_CELL_COUNT + entry) * 64u);
            vdc_vram_write(VDC0, (u16)(y + cy * 16u + SPRITE_Y_BIAS));
            vdc_vram_write(VDC0, (u16)(x + cx * 16u + SPRITE_X_BIAS));
            vdc_vram_write(VDC0, VDC_SPR_PATTERN(address));
            vdc_vram_write(VDC0, 0);
        } else {
            vdc_vram_write(VDC0, 0x03FF);
            vdc_vram_write(VDC0, 0x03FF);
            vdc_vram_write(VDC0, 0);
            vdc_vram_write(VDC0, 0);
        }
    }
    vdc_set_satb_address(VDC0, SAT_BASE);
}

static void setup_black_backdrop(void)
{
    u16 microprogram[16];
    for (unsigned i = 0; i < 16; ++i) microprogram[i] = KING_CODE_NOP;
    microprogram[0] = KING_CODE_BG0_CG_0;
    king_set_bg_mode(KING_BGMODE_4_PAL, 0, 0, 0);
    king_disable_microprogram();
    king_write_microprogram(microprogram, 0, 16);
    king_enable_microprogram();
    king_set_bg_prio(KING_BGPRIO_3, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 0);
    king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                     KING_BGSIZE_256, KING_BGSIZE_256);
    king_set_bat_cg_addr(KING_BG0, 0, 0);
    king_set_scroll(KING_BG0, 0, 0);
    king_set_kram_write(0, 1);
    for (unsigned i = 0; i < 0x1E00u; ++i) king_kram_write(0);
}

int main(void)
{
    int x = 112, y = 96;
    unsigned tick = 0, frame = 0;

    vdc_init_5MHz(VDC0);
    vdc_init_5MHz(VDC1);
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    king_set_kram_pages(0, 0, 0, 0);
    setup_black_backdrop();
    tetsu_set_priorities(0, 0, 1, 0, 0, 0, 0);
    tetsu_set_vdc_palette(0, 0);
    tetsu_set_king_palette(0, 0, 0, 0);
    tetsu_set_palette(0, 0x0188); /* black backdrop / transparent pixel */
    for (unsigned i = 0; i < 16; ++i)
        tetsu_set_palette((u16)i, sprite16_palette[i]);

    vdc_setreg(VDC0, VDC_REG_CR, VDC_CR_SB);
    vdc_setreg(VDC0, VDC_REG_MWR, VDC_MWR_SCREEN_32x32);
    vdc_setreg(VDC0, VDC_REG_DCR, VDC_DCR_SATB_AUTO);
    vdc_set_scroll(VDC0, 0, 0);
    vdc_set_satb_address(VDC0, SAT_BASE);
    upload_patterns();
    write_sat(x, y, 0);
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_16, TETSU_COLORS_16,
                         0, 1, 1, 0, 0, 0, 0);
    contrlr_pad_init(0);

    for (;;) {
        u32 pad;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        if (pad & JOY_LEFT)  x -= 2;
        if (pad & JOY_RIGHT) x += 2;
        if (pad & JOY_UP)    y -= 2;
        if (pad & JOY_DOWN)  y += 2;
        if (x < 0) x = 0;
        if (x > 232) x = 232;
        if (y < 0) y = 0;
        if (y > 206) y = 206;
        if (++tick >= 6) {
            tick = 0;
            frame = (frame + 1) % SPRITE16_FRAME_COUNT;
        }
        write_sat(x, y, frame);
    }
}
