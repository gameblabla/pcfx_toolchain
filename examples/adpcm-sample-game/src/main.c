#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/sound.h>
#include <pcfx/tetsu.h>
#include <pcfx/contrlr.h>
#include <eris/cd.h>

#include "screen.h"
#include "lbas.h"
#include "sfx_meta.h"

#define SAMPLE_BASE 0x08000u
#define SAMPLE_RATE ADPCM_RATE_8000
#define SAMPLE_VOLUME 48u

static void king_reg16(u16 reg, u16 value)
{
    __asm__ volatile ("out.h %0,0x600[r0]\n out.h %1,0x604[r0]"
                      : : "r" (reg), "r" (value));
}

static void king_reg32(u16 reg, u32 value)
{
    __asm__ volatile ("out.h %0,0x600[r0]\n out.w %1,0x604[r0]"
                      : : "r" (reg), "r" (value));
}

static void reset_voice(void)
{
    adpcm_set_volume(0, 0, 0);
    king_reg16(0x50, 0);
    adpcm_set_control(SAMPLE_RATE, 1, 1, 1, 1);
    game_screen_wait_frame();
    game_screen_wait_frame();
    adpcm_set_control(SAMPLE_RATE, 1, 1, 0, 0);
}

static void play_coin(void)
{
    reset_voice();
    king_reg16(0x51, 0x0002); /* Doom's sequential one-shot configuration */
    king_reg16(0x58, (u16)(SAMPLE_BASE >> 8));
    king_reg32(0x59, SAMPLE_BASE + SFX_WORDS - 1u);
    adpcm_set_volume(0, SAMPLE_VOLUME, SAMPLE_VOLUME);
    king_reg16(0x50, 0x0009); /* channel 0 enable + 8 kHz rate field */
}

static void draw_scene_text(u32 base, unsigned score)
{
    char score_text[24] = "COINS: 000000";
    unsigned i;
    for (i = 0; i < 6; ++i) {
        score_text[12 - i] = (char)('0' + score % 10u);
        score /= 10u;
    }
    game_screen_rect(base, 24, 52, 144, 18, 1);
    game_screen_text(base, 24, 52, score_text, 4);
}

int main(void)
{
    unsigned score = 0;
    unsigned front = 0;
    int sample_ready;
    u32 prev_pad = 0;

    game_screen_init();
    game_screen_text(GAME_PAGE0, 24, 20, "COIN PICKUP SOUND TEST", 2);
    game_screen_text(GAME_PAGE1, 24, 20, "COIN PICKUP SOUND TEST", 2);
    game_screen_text(GAME_PAGE0, 24, 216, "PRESS I TO COLLECT A COIN", 2);
    game_screen_text(GAME_PAGE1, 24, 216, "PRESS I TO COLLECT A COIN", 2);
    for (unsigned page = 0; page < 2; ++page) {
        u32 base = page ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_rect(base, 108, 100, 40, 40, 4);
        game_screen_rect(base, 118, 108, 20, 24, 2);
    }

    king_set_kram_pages(1, 0, 0, 1);
    eris_cd_reset();
    sample_ready = BINARY_LBA_COIN_ADP &&
        eris_cd_read_kram(BINARY_LBA_COIN_ADP,
                          0x80000000u | SAMPLE_BASE, SFX_BYTES_PADDED);
    if (!sample_ready) {
        game_screen_text(GAME_PAGE0, 24, 184, "CD SAMPLE LOAD FAILED", 6);
        game_screen_text(GAME_PAGE1, 24, 184, "CD SAMPLE LOAD FAILED", 6);
    }
    reset_voice();
    contrlr_pad_init(0);
    draw_scene_text(GAME_PAGE0, score);
    draw_scene_text(GAME_PAGE1, score);

    for (;;) {
        u32 pad, pressed;
        unsigned back = front ^ 1u;
        u32 base = back ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        pressed = pad & ~prev_pad;
        prev_pad = pad;
        if ((pressed & JOY_I) && sample_ready) {
            ++score;
            play_coin();
        }
        draw_scene_text(base, score);
        game_screen_flip(base);
        front = back;
    }
}
