#include <pcfx/types.h>
#include <pcfx/filesys.h>
#include <pcfx/contrlr.h>

#include "screen.h"

#define SAVE_MAGIC 0x46584353u /* "SCXF" */

typedef struct {
    u32 magic;
    u32 score;
    u32 checksum;
} SaveData;

static unsigned char fs_heap[8192];
static unsigned score;
static const char *message = "NEW RUN  I:SAVE  II:LOAD";

static u32 checksum(const SaveData *save)
{
    return save->magic ^ save->score ^ 0xA51ECAFEu;
}

static int load_save(void)
{
    SaveData save;
    u32 got = 0;
    int rc = filesys_init(fs_heap, sizeof fs_heap);
    if (rc < 0) return rc;
    rc = filesys_load_file("/SRAM/STAR.SAV", &save, sizeof save, &got);
    if (rc < 0) return rc;
    if (got != sizeof save || save.magic != SAVE_MAGIC || save.checksum != checksum(&save))
        return -1;
    score = save.score;
    return 0;
}

static int save_game(void)
{
    SaveData save;
    int rc = filesys_init(fs_heap, sizeof fs_heap);
    if (rc < 0) return rc;
    save.magic = SAVE_MAGIC;
    save.score = score;
    save.checksum = checksum(&save);
    return filesys_save_file("/SRAM/STAR.SAV", &save, sizeof save);
}

static void draw_score(u32 base)
{
    char text[20] = "SCORE 000000";
    unsigned value = score;
    for (unsigned i = 0; i < 6; ++i) {
        text[11 - i] = (char)('0' + value % 10u);
        value /= 10u;
    }
    game_screen_rect(base, 24, 52, 136, 18, 1);
    game_screen_text(base, 24, 52, text, 4);
}

static void draw_message(u32 base)
{
    game_screen_rect(base, 24, 76, 208, 18, 1);
    game_screen_text(base, 24, 76, message, 2);
}

static void restore_game_screen(void)
{
    game_screen_init();
    for (unsigned page = 0; page < 2; ++page) {
        u32 base = page ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_text(base, 24, 20, "STAR CATCHER SAVE DEMO", 2);
        game_screen_text(base, 24, 216, "ARROWS MOVE  I SAVE  II LOAD", 2);
        draw_score(base);
        draw_message(base);
    }
}

int main(void)
{
    int player_x = 112;
    int star_x = 72, star_y = 106;
    int old_player_x[2] = { -1, -1 };
    int old_star_x[2] = { -1, -1 };
    int old_star_y[2] = { -1, -1 };
    unsigned front = 0;
    u32 prev_pad = 0;

    game_screen_cache_font();
    if (load_save() == 0) message = "SAVE LOADED";
    restore_game_screen();
    contrlr_pad_init(0);

    for (;;) {
        u32 pad, pressed;
        unsigned back = front ^ 1u;
        u32 base = back ? GAME_PAGE1 : GAME_PAGE0;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        pressed = pad & ~prev_pad;
        prev_pad = pad;
        if (pad & JOY_LEFT) player_x -= 2;
        if (pad & JOY_RIGHT) player_x += 2;
        if (player_x < 32) player_x = 32;
        if (player_x > 208) player_x = 208;

        if (pressed & JOY_I) {
            message = save_game() >= 0 ? "SAVED TO BIOS SRAM" : "BIOS SAVE FAILED";
            restore_game_screen();
            contrlr_pad_init(0);
        }
        if (pressed & JOY_II) {
            message = load_save() == 0 ? "SAVE LOADED" : "NO VALID SAVE";
            restore_game_screen();
            contrlr_pad_init(0);
        }

        ++star_y;
        if (star_y > 196) {
            star_y = 18;
            star_x = 36 + (int)((score * 53u + 29u) % 176u);
        }
        if (star_y + 12 >= 178 && star_y <= 192 &&
            star_x + 12 >= player_x && star_x <= player_x + 32) {
            ++score;
            star_y = 18;
            star_x = 36 + (int)((score * 53u + 29u) % 176u);
        }

        if (old_player_x[back] >= 0)
            game_screen_rect(base, (unsigned)old_player_x[back], 188, 40, 16, 1);
        if (old_star_x[back] >= 0)
            game_screen_rect(base, (unsigned)old_star_x[back],
                             (unsigned)old_star_y[back], 12, 12, 1);
        game_screen_rect(base, (unsigned)star_x, (unsigned)star_y, 12, 12, 4);
        game_screen_rect(base, (unsigned)player_x, 188, 40, 16, 3);
        old_player_x[back] = player_x;
        old_star_x[back] = star_x;
        old_star_y[back] = star_y;
        draw_score(base);
        draw_message(base);
        game_screen_flip(base);
        front = back;
    }
}
