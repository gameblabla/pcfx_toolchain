#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/vdc.h>
#include <pcfx/contrlr.h>

#include "sprite256_meta.h"
#include "../../game-demo-common/wait_frame.h"

#define PATTERN_BASE 0x2000u
#define PATTERN_STRIDE 128u /* Doom paired-VDC 16x16 cell placement */
#define SAT_BASE 0xFF00u
#define X_BIAS 0x20u
#define Y_BIAS 0x40u

extern const unsigned short sprite256_vdc0_patterns[];
extern const unsigned short sprite256_vdc1_patterns[];

static void upload_patterns(void)
{
    for (int chip = 0; chip < 2; ++chip) {
        const u16 *patterns = chip ? sprite256_vdc1_patterns : sprite256_vdc0_patterns;
        for (unsigned cell = 0; cell < SPRITE256_FRAME_COUNT * SPRITE256_CELL_COUNT; ++cell) {
            u16 address = (u16)(PATTERN_BASE + cell * PATTERN_STRIDE);
            vdc_set_vram_write(chip, address);
            for (unsigned word = 0; word < 64; ++word)
                vdc_vram_write(chip, patterns[cell * 64u + word]);
        }
    }
}

static void configure_chip(int chip)
{
    vdc_init_5MHz(chip);
    /* Same pair timing and enable contract used by Doom PC-FX's weapon sprites. */
    vdc_setreg(chip, VDC_REG_CR, VDC_CR_SB);
    vdc_setreg(chip, VDC_REG_MWR, VDC_MWR_SCREEN_32x32);
    vdc_setreg(chip, VDC_REG_HSR, 0x0202);
    vdc_setreg(chip, VDC_REG_HDR, 0x041F);
    vdc_setreg(chip, VDC_REG_VPR, 0x1102);
    vdc_setreg(chip, VDC_REG_VDR, 239);
    vdc_setreg(chip, VDC_REG_VCR, 0x0002);
    vdc_setreg(chip, VDC_REG_DCR, VDC_DCR_SATB_AUTO);
    vdc_set_scroll(chip, 0, 0);
    vdc_set_satb_address(chip, SAT_BASE);
}

static void write_sat(int chip, int x, int y, unsigned frame)
{
    vdc_set_vram_write(chip, SAT_BASE);
    for (unsigned entry = 0; entry < 64; ++entry) {
        if (entry < SPRITE256_CELL_COUNT) {
            unsigned cx = entry & 1u;
            unsigned cy = entry / 2u;
            u16 address = (u16)(PATTERN_BASE +
                (frame * SPRITE256_CELL_COUNT + entry) * PATTERN_STRIDE);
            vdc_vram_write(chip, (u16)(y + (int)cy * 16 + Y_BIAS));
            vdc_vram_write(chip, (u16)(x + (int)cx * 16 + X_BIAS));
            vdc_vram_write(chip, VDC_SPR_PATTERN(address));
            vdc_vram_write(chip, chip ? 8 : 0);
        } else {
            vdc_vram_write(chip, 0x03FF);
            vdc_vram_write(chip, 0x03FF);
            vdc_vram_write(chip, 0);
            vdc_vram_write(chip, 0);
        }
    }
    vdc_set_satb_address(chip, SAT_BASE);
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

    configure_chip(VDC0);
    configure_chip(VDC1);
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    king_set_kram_pages(0, 0, 0, 0);
    setup_black_backdrop();
    tetsu_set_priorities(0, 0, 1, 0, 0, 0, 0);
    tetsu_set_vdc_palette(0, 0); /* both VDC sprite palette offsets = 0 */
    tetsu_set_palette(0, 0x0188);
    for (unsigned i = 0; i < 256; ++i)
        tetsu_set_palette((u16)i, sprite256_palette[i]);
    upload_patterns();

    for (int chip = 0; chip < 2; ++chip) {
        write_sat(chip, x, y, 0);
    }
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_256, TETSU_COLORS_256,
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
            frame = (frame + 1) % SPRITE256_FRAME_COUNT;
        }
        for (int chip = 0; chip < 2; ++chip)
            write_sat(chip, x, y, frame);
    }
}
