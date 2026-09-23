#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/sound.h>
#include <pcfx/contrlr.h>
#include <eris/cd.h>

#include "screen.h"
#include "lbas.h"
#include "theme_meta.h"

#define STREAM_BASE       0x08000u
#define HALF_BYTES        16384u
#define HALF_WORDS        (HALF_BYTES / 2u)
#define RING_WORDS        (HALF_WORDS * 2u)
#define SECTORS_PER_HALF  (HALF_BYTES / 2048u)
#define RATE_FIELD        2u /* 8 kHz, same field as ADPCM_RATE_8000 */

static u32 next_sector;
static unsigned front;

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

static u16 king_read16(u16 reg)
{
    u16 value;
    __asm__ volatile ("out.h %1,0x600[r0]\n in.h 0x604[r0],%0"
                      : "=r" (value) : "r" (reg));
    return value;
}

static void clear_half(unsigned half)
{
    king_set_kram_write(0x80000000u | (STREAM_BASE + half * HALF_WORDS), 1);
    for (unsigned i = 0; i < HALF_WORDS; ++i) king_kram_write(0);
}

static int fill_half(unsigned half)
{
    u32 dst = STREAM_BASE + half * HALF_WORDS;
    if (next_sector + SECTORS_PER_HALF <= THEME_SECTORS) {
        int ok = eris_cd_read_kram(BINARY_LBA_THEME_ADP + next_sector,
                                   0x80000000u | dst, HALF_BYTES);
        if (!ok) return 0;
        next_sector += SECTORS_PER_HALF;
        return 1;
    }
    clear_half(half); /* pad the tail with ADPCM zero until playback is stopped */
    next_sector = THEME_SECTORS;
    return 1;
}

static void start_stream(void)
{
    king_set_kram_pages(1, 0, 0, 1);
    adpcm_set_volume(0, 0, 0);
    king_reg16(0x50, 0);
    adpcm_set_control(ADPCM_RATE_8000, 1, 1, 1, 1);
    game_screen_wait_frame();
    game_screen_wait_frame();
    king_reg16(0x51, 0x0001); /* PCFV ring-buffer mode */
    king_reg16(0x52, 0x0000);
    king_reg16(0x58, (u16)(STREAM_BASE >> 8));
    king_reg32(0x59, STREAM_BASE + RING_WORDS - 1u);
    king_reg16(0x5A, (u16)((STREAM_BASE + HALF_WORDS) >> 6));
    adpcm_set_control(ADPCM_RATE_8000, 1, 1, 0, 0);
    (void)king_read16(0x53);
    adpcm_set_volume(0, 48, 48);
    king_reg16(0x50, (u16)(1u | (RATE_FIELD << 2)));
}

int main(void)
{
    u32 prev_pad = 0;
    int playing = 1;
    game_screen_init();
    game_screen_text(GAME_PAGE0, 24, 20, "CD STREAMED ADPCM MUSIC", 2);
    game_screen_text(GAME_PAGE1, 24, 20, "CD STREAMED ADPCM MUSIC", 2);
    game_screen_text(GAME_PAGE0, 24, 216, "I: MUTE/UNMUTE  40 SEC TRACK", 2);
    game_screen_text(GAME_PAGE1, 24, 216, "I: MUTE/UNMUTE  40 SEC TRACK", 2);

    king_set_kram_pages(1, 0, 0, 1);
    eris_cd_reset();
    if (!BINARY_LBA_THEME_ADP || !fill_half(0) || !fill_half(1)) {
        game_screen_text(GAME_PAGE0, 24, 184, "CD MUSIC LOAD FAILED", 6);
        game_screen_text(GAME_PAGE1, 24, 184, "CD MUSIC LOAD FAILED", 6);
        for (;;) game_screen_wait_frame();
    }
    start_stream();
    contrlr_pad_init(0);

    for (;;) {
        u32 pad, pressed;
        u16 status;
        unsigned back;
        u32 base;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        pressed = pad & ~prev_pad;
        prev_pad = pad;
        if (pressed & JOY_I) {
            playing = !playing;
            adpcm_set_volume(0, playing ? 48 : 0, playing ? 48 : 0);
        }
        status = king_read16(0x53);
        if ((status & 0x0002u) && !fill_half(0)) clear_half(0);
        if ((status & 0x0001u) && !fill_half(1)) clear_half(1);

        back = front ^ 1u;
        base = back ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_rect(base, 24, 64, 208, 88, 1);
        game_screen_text(base, 24, 64, playing ? "STREAMING FROM THE CD" : "MUSIC MUTED - BUFFER REFILLS", 5);
        game_screen_text(base, 24, 88, "RING HALF 0  <->  RING HALF 1", 2);
        game_screen_rect(base, 24, 124, 208, 12, 3);
        game_screen_rect(base, 24, 124, 16 + ((next_sector * 184u) / THEME_SECTORS), 12, 4);
        game_screen_flip(base);
        front = back;
    }
}
