#ifndef PCFX_GAME_DEMO_SCREEN_H
#define PCFX_GAME_DEMO_SCREEN_H

#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/romfont.h>
#include "wait_frame.h"

#define GAME_SCREEN_W 256u
#define GAME_SCREEN_H 240u
#define GAME_ROW_WORDS 128u
#define GAME_PAGE_WORDS (GAME_ROW_WORDS * GAME_SCREEN_H)
#define GAME_PAGE0 0u
#define GAME_PAGE1 GAME_PAGE_WORDS
#define GAME_FONT_CHARS 128u

static u8 game_font_cache[GAME_FONT_CHARS][16];
static int game_font_cached;

static void game_screen_cache_font(void)
{
    unsigned ch, row;
    if (game_font_cached) return;
    for (ch = 0; ch < GAME_FONT_CHARS; ++ch) {
        const u8 *glyph = romfont_get(ch, ROMFONT_ANK_8x16);
        for (row = 0; row < 16; ++row) game_font_cache[ch][row] = glyph[row];
    }
    game_font_cached = 1;
}

static inline void game_kram_begin(u32 addr)
{
    u32 command = addr | (1u << 18);
    __asm__ volatile (
        "out.h %[reg], 0x600[r0]\n"
        "out.w %[command], 0x604[r0]\n"
        "out.h %[datareg], 0x600[r0]\n"
        : : [reg] "r" ((u16)0x000d), [command] "r" (command),
            [datareg] "r" ((u16)0x000e));
}

static inline void game_kram_put(u16 word)
{
    __asm__ volatile ("out.h %[word], 0x604[r0]" : : [word] "r" (word));
}

static void game_screen_fill(u32 base, u8 index)
{
    u32 words = GAME_PAGE_WORDS;
    u16 pair = (u16)((index << 8) | index);
    game_kram_begin(base);
    while (words--) game_kram_put(pair);
}

static void game_screen_rect(u32 base, unsigned x, unsigned y,
                             unsigned w, unsigned h, u8 index)
{
    unsigned row;
    u16 pair = (u16)((index << 8) | index);
    if ((x | w) & 1u) return;
    for (row = 0; row < h; ++row) {
        unsigned count = w >> 1;
        game_kram_begin(base + (y + row) * GAME_ROW_WORDS + (x >> 1));
        while (count--) game_kram_put(pair);
    }
}

static void game_screen_text(u32 base, unsigned x, unsigned y,
                             const char *str, u8 ink)
{
    while (*str) {
        u8 ch = (u8)*str++;
        const u8 *glyph;
        unsigned row;
        if (ch >= GAME_FONT_CHARS) {
            x += 8;
            continue;
        }
        glyph = game_font_cache[ch];
        for (row = 0; row < 16; ++row) {
            unsigned pair;
            game_kram_begin(base + (y + row) * GAME_ROW_WORDS + (x >> 1));
            for (pair = 0; pair < 4; ++pair) {
                unsigned bit = 7u - pair * 2u;
                u8 a = (glyph[row] & (1u << bit)) ? ink : 1;
                u8 b = (glyph[row] & (1u << (bit - 1u))) ? ink : 1;
                game_kram_put((u16)((a << 8) | b));
            }
        }
        x += 8;
    }
}

static void game_screen_palette(void)
{
    unsigned i;
    for (i = 0; i < 256; ++i) tetsu_set_palette((u16)i, 0x0188);
    tetsu_set_palette(1, 0x0188); /* black gameplay field */
    tetsu_set_palette(2, 0xFF88); /* white text */
    tetsu_set_palette(3, 0x1DF6); /* blue */
    tetsu_set_palette(4, 0xE31A); /* yellow */
    tetsu_set_palette(5, 0x9730); /* green */
    tetsu_set_palette(6, 0x506F); /* red */
    tetsu_set_palette(7, 0xB2A0); /* cyan */
}

static void game_screen_init(void)
{
    u16 microprogram[16];
    unsigned i;
    game_screen_cache_font();
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    king_set_kram_pages(0, 0, 0, 0);
    king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
    king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                     KING_BGSIZE_256, KING_BGSIZE_256);
    king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 1);
    king_set_bat_cg_addr(KING_BG0, 0, 0);
    king_set_bat_cg_addr(KING_BG0SUB, 0, 0);
    king_set_scroll(KING_BG0, 0, 0);
    king_set_scroll(KING_BG0SUB, 0, 0);
    for (i = 0; i < 8; ++i) microprogram[i] = KING_CODE_ROTATE;
    for (; i < 16; ++i) microprogram[i] = KING_CODE_NOP;
    king_disable_microprogram();
    king_write_microprogram(microprogram, 0, 16);
    king_enable_microprogram();
    __asm__ volatile (
        "out.h %0, 0x600[r0]\n out.h %1, 0x604[r0]\n"
        "out.h %2, 0x600[r0]\n out.h %3, 0x604[r0]\n"
        "out.h %4, 0x600[r0]\n out.h %5, 0x604[r0]\n"
        "out.h %6, 0x600[r0]\n out.h %7, 0x604[r0]\n"
        "out.h %8, 0x600[r0]\n out.h %9, 0x604[r0]\n"
        "out.h %10, 0x600[r0]\n out.h %11, 0x604[r0]"
        : : "r" ((u16)0x38), "r" ((u16)0x0100),
            "r" ((u16)0x39), "r" ((u16)0),
            "r" ((u16)0x3A), "r" ((u16)0),
            "r" ((u16)0x3B), "r" ((u16)0x0100),
            "r" ((u16)0x3C), "r" ((u16)0),
            "r" ((u16)0x3D), "r" ((u16)0));
    tetsu_set_priorities(7, 6, 5, 4, 3, 2, 1);
    tetsu_set_king_palette(0, 0, 0, 0);
    game_screen_palette();
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_256, TETSU_COLORS_16,
                         0, 0, 1, 0, 0, 0, 0);
    game_screen_fill(GAME_PAGE0, 1);
    game_screen_fill(GAME_PAGE1, 1);
    king_set_bat_cg_addr(KING_BG0, 0, GAME_PAGE0 >> 10);
    king_set_bat_cg_addr(KING_BG0SUB, 0, GAME_PAGE0 >> 10);
}

static void game_screen_flip(u32 base)
{
    king_set_bat_cg_addr(KING_BG0, 0, base >> 10);
    king_set_bat_cg_addr(KING_BG0SUB, 0, base >> 10);
}

#endif
