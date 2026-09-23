#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/contrlr.h>
#include <eris/cd.h>

#include "lbas.h"
#include "still_meta.h"
#include "../../game-demo-common/wait_frame.h"

#define SCRATCH_KRAM_WORD 0x08000u
#define SCRATCH_WORDS     8192u
#define CD_CHUNK_BYTES    16384u
#if STILL_MODE_HICOLOR || STILL_MODE_16M
/* Place this example's direct-colour images in KRAM bank B, and program their
 * fetches in the matching microprogram slots 8..15. */
#define IMAGE_BASE        0x20000u
#else
#define IMAGE_BASE        0u
#endif

static u8 cd_bounce[CD_CHUNK_BYTES] __attribute__((aligned(4)));

static void king_reg16(u16 reg, u16 value)
{
    __asm__ volatile ("out.h %0,0x600[r0]\n out.h %1,0x604[r0]"
                      : : "r" (reg), "r" (value));
}

static void kram_write_words(u32 dst, const u8 *src, u32 words)
{
    king_set_kram_write(dst, 1);
    while (words--) {
        u16 word = (u16)(src[0] | ((u16)src[1] << 8));
        king_kram_write(word);
        src += 2;
    }
}

static int load_still_from_cd(void)
{
    u32 offset = 0;
#if STILL_MODE_4BPP
    if (!BINARY_LBA_STILL_BIN) return 0;
#elif STILL_MODE_8BPP
    if (!BINARY_LBA_STILL_BIN) return 0;
#elif STILL_MODE_HICOLOR
    if (!BINARY_LBA_STILL_BIN) return 0;
#else
    if (!BINARY_LBA_STILL_BIN) return 0;
#endif
    /* Bounce the CD data through page-0 KRAM before copying each chunk into
     * the image area. The background is still disabled during the load. */
    king_set_kram_pages(0, 0, 0, 0);
    eris_cd_reset();
    while (offset < STILL_BYTES) {
        u32 chunk = STILL_BYTES - offset;
        u32 lba;
        if (chunk > CD_CHUNK_BYTES) chunk = CD_CHUNK_BYTES;
#if STILL_MODE_4BPP
        lba = BINARY_LBA_STILL_BIN;
#elif STILL_MODE_8BPP
        lba = BINARY_LBA_STILL_BIN;
#elif STILL_MODE_HICOLOR
        lba = BINARY_LBA_STILL_BIN;
#else
        lba = BINARY_LBA_STILL_BIN;
#endif
        if (!eris_cd_read_dma(lba + (offset >> 11), cd_bounce, chunk,
                              SCRATCH_KRAM_WORD, SCRATCH_WORDS))
            return 0;
        kram_write_words(IMAGE_BASE + (offset >> 1), cd_bounce, chunk >> 1);
        offset += chunk;
    }
    return 1;
}

static void setup_bg0(void)
{
    u16 microprogram[16];
    for (unsigned i = 0; i < 16; ++i) microprogram[i] = KING_CODE_NOP;
#if STILL_MODE_4BPP
    king_set_bg_mode(KING_BGMODE_16_PAL, 0, 0, 0);
    microprogram[0] = KING_CODE_BG0_CG_0;
    microprogram[1] = KING_CODE_BG0_CG_1;
#elif STILL_MODE_8BPP
    king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
    for (unsigned i = 0; i < 8; ++i) microprogram[i] = KING_CODE_ROTATE;
#elif STILL_MODE_HICOLOR
    king_set_bg_mode(KING_BGMODE_64K, 0, 0, 0);
    for (unsigned i = 0; i < 8; ++i)
        microprogram[8 + i] = (u16)(KING_CODE_BG0_CG_0 + i);
#else
    king_set_bg_mode(KING_BGMODE_16M, 0, 0, 0);
    for (unsigned i = 0; i < 8; ++i)
        microprogram[8 + i] = (u16)(KING_CODE_BG0_CG_0 + i);
#endif
    king_disable_microprogram();
    king_write_microprogram(microprogram, 0, 16);
    king_enable_microprogram();
    king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                     KING_BGSIZE_256, KING_BGSIZE_256);
    king_set_bat_cg_addr(KING_BG0, 0, IMAGE_BASE >> 10);
    king_set_bat_cg_addr(KING_BG0SUB, 0, IMAGE_BASE >> 10);
    king_set_scroll(KING_BG0, 0, 0);
    king_set_scroll(KING_BG0SUB, 0, 0);
    /* REG.12 bit 12 selects BG0 rotation. Only the 8bpp schedule above uses
     * rotation microinstructions; the other modes use ordinary direct CG. */
    king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE,
                     STILL_MODE_8BPP ? 1 : 0);
    /* Identity coefficients for 8bpp rotation. */
    king_reg16(0x38, 0x0100); king_reg16(0x39, 0);
    king_reg16(0x3A, 0);      king_reg16(0x3B, 0x0100);
    king_reg16(0x3C, 0);      king_reg16(0x3D, 0);
}

int main(void)
{
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    king_set_kram_pages(1, 0, 0, 0);
    tetsu_set_priorities(7, 6, 5, 4, 3, 2, 1);
    tetsu_set_king_palette(0, 0, 0, 0);
#if STILL_MODE_4BPP || STILL_MODE_8BPP
    for (unsigned i = 0; i < sizeof(still_palette) / sizeof(still_palette[0]); ++i)
        tetsu_set_palette((u16)i, still_palette[i]);
#endif
    if (!load_still_from_cd()) {
        for (;;) { }
    }
    king_set_kram_pages(0, 0, 0, 0);
    setup_bg0();
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_256, TETSU_COLORS_16,
                         0, 0, 1, 0, 0, 0, 0);
    contrlr_pad_init(0);
    for (;;) {
        /* A still remains on screen; controller reads keep this useful as a
         * minimal bootable game disc without changing the loaded image. */
        (void)contrlr_pad_read(0);
        game_screen_wait_frame();
    }
}
