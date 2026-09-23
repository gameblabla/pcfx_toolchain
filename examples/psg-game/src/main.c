#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/sound.h>
#include <pcfx/contrlr.h>

#include "screen.h"

static const u16 notes[8] = { 428, 381, 339, 320, 285, 254, 226, 214 };
static const u8 wave[32] = {
    0, 12, 6, 18, 12, 24, 18, 30, 31, 31, 31, 31, 31, 31, 31, 31,
    30, 18, 24, 12, 18, 6, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0
};

static void draw_keys(u32 base, unsigned active)
{
    game_screen_rect(base, 40, 96, 176, 52, 1);
    for (unsigned i = 0; i < 8; ++i)
        game_screen_rect(base, 48 + i * 20, 104, 16, 36,
                         i == active ? 4 : 3);
}

int main(void)
{
    unsigned note = 0, tick = 0, speed = 24;
    unsigned front = 0;
    int playing = 1, noise = 0;
    u32 prev_pad = 0;

    game_screen_init();
    for (unsigned page = 0; page < 2; ++page) {
        u32 base = page ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_text(base, 24, 20, "PSG ARCADE MUSIC BOX", 2);
        game_screen_text(base, 24, 52, "LEFT/RIGHT: SELECT NOTE", 2);
        game_screen_text(base, 24, 72, "I: PLAY/STOP   II: NOISE", 2);
        game_screen_text(base, 24, 200, "PSG VOICES: WAVE DDA NOISE", 2);
    }
    psg_set_main_volume(12, 12);
    for (unsigned ch = 0; ch < 6; ++ch) {
        psg_set_channel((u8)ch);
        psg_set_balance(15, 15);
        psg_set_volume(0, 0, 0);
        if (ch < 5)
            for (unsigned i = 0; i < 32; ++i) psg_waveform_data(wave[i]);
    }
    psg_set_channel(0);
    psg_set_freq(notes[note]);
    psg_set_volume(24, 1, 0);
    contrlr_pad_init(0);

    for (;;) {
        u32 pad, pressed;
        unsigned back = front ^ 1u;
        u32 base = back ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        pressed = pad & ~prev_pad;
        prev_pad = pad;
        if ((pressed & JOY_LEFT) && note) --note;
        if ((pressed & JOY_RIGHT) && note < 7) ++note;
        if (pressed & JOY_I) {
            playing = !playing;
            psg_set_channel(0);
            psg_set_volume(playing ? 24 : 0, playing, 0);
        }
        if (pressed & JOY_II) {
            noise = !noise;
            psg_set_channel(5);
            psg_set_noise(12, noise);
            psg_set_volume(noise ? 16 : 0, noise, 0);
        }
        if (pad & JOY_UP && speed > 8) speed -= 1;
        if (pad & JOY_DOWN && speed < 60) speed += 1;
        if (playing && ++tick >= speed) {
            tick = 0;
            note = (note + 1) & 7u;
            psg_set_channel(0);
            psg_set_freq(notes[note]);
        }
        draw_keys(base, note);
        game_screen_flip(base);
        front = back;
    }
}
