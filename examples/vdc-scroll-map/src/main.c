#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/vdc.h>
#include <pcfx/contrlr.h>

#include "map_meta.h"
#include "../../game-demo-common/wait_frame.h"

#define BAT_WIDTH 128u
#define BAT_HEIGHT 32u
#define BAT_WORDS (BAT_WIDTH * BAT_HEIGHT)
#define TILE_BASE 0x1000u
#define BLANK_TILE 0x100u /* tile IDs must match TILE_BASE at word address 0x1000 */

extern const unsigned short map_tile_patterns[];
extern const unsigned char map_cell_ids[];

static unsigned mod_map_x(int world_tile)
{
    int x = world_tile % (int)MAP_SOURCE_COLS;
    if (x < 0) x += MAP_SOURCE_COLS;
    return (unsigned)x;
}

static unsigned map_tile(unsigned world_x, unsigned row)
{
    unsigned source_x = world_x % MAP_SOURCE_COLS;
    if (row >= MAP_SOURCE_ROWS) return 0;
    return map_cell_ids[row * MAP_SOURCE_COLS + source_x];
}

static void write_world_column(int world_tile)
{
    unsigned ring_x = (unsigned)world_tile & (BAT_WIDTH - 1u);
    for (unsigned row = 0; row < BAT_HEIGHT; ++row) {
        unsigned id = row < MAP_SOURCE_ROWS ? map_tile(mod_map_x(world_tile), row) : 0;
        vdc_set_vram_write(VDC0, (u16)(row * BAT_WIDTH + ring_x));
        vdc_vram_write(VDC0, (u16)(BLANK_TILE + id));
    }
}

static void upload_tiles(void)
{
    vdc_set_vram_write(VDC0, TILE_BASE);
    for (unsigned i = 0; i < MAP_UNIQUE_TILES * 16u; ++i)
        vdc_vram_write(VDC0, map_tile_patterns[i]);
}

static void write_initial_bat(void)
{
    for (unsigned row = 0; row < BAT_HEIGHT; ++row) {
        vdc_set_vram_write(VDC0, (u16)(row * BAT_WIDTH));
        for (unsigned col = 0; col < BAT_WIDTH; ++col) {
            unsigned id = row < MAP_SOURCE_ROWS ? map_tile(col, row) : 0;
            vdc_vram_write(VDC0, (u16)(BLANK_TILE + id));
        }
    }
}

int main(void)
{
    int camera_x = 0;
    int auto_scroll = 1;
    u32 previous_tile = 0;

    vdc_init_5MHz(VDC0);
    vdc_init_5MHz(VDC1);
    king_init();
    king_set_kram_mode(1);
    tetsu_init();
    king_set_kram_pages(0, 0, 0, 0);
    king_set_bg_mode(KING_BGMODE_NONE, KING_BGMODE_NONE,
                     KING_BGMODE_NONE, KING_BGMODE_NONE);
    king_set_bg_prio(KING_BGPRIO_HIDE, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 0);
    tetsu_set_priorities(7, 6, 5, 4, 3, 2, 1);
    tetsu_set_vdc_palette(0, 0);
    tetsu_set_palette(0, 0x0188);
    for (unsigned i = 0; i < 16; ++i)
        tetsu_set_palette((u16)i, map_palette[i]);
    vdc_setreg(VDC0, VDC_REG_CR, VDC_CR_BB);
    vdc_setreg(VDC0, VDC_REG_MWR, VDC_MWR_SCREEN_128x32);
    vdc_set_scroll(VDC0, 0, 0);
    upload_tiles();
    write_initial_bat();
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_16, TETSU_COLORS_16,
                         1, 0, 0, 0, 0, 0, 0);
    contrlr_pad_init(0);

    for (;;) {
        u32 pad;
        unsigned now_tile;
        game_screen_wait_frame();
        pad = contrlr_pad_read(0);
        if (pad & (JOY_LEFT | JOY_RIGHT | JOY_UP | JOY_DOWN |
                   JOY_I | JOY_II | JOY_III | JOY_IV | JOY_V |
                   JOY_VI | JOY_SELECT)) auto_scroll = 0;
        if (pad & JOY_RUN) auto_scroll = 1;
        if (auto_scroll) ++camera_x;
        else {
            if (pad & JOY_LEFT)  camera_x -= 2;
            if (pad & JOY_RIGHT) camera_x += 2;
        }
        if (camera_x < 0) camera_x = 0;
        now_tile = (unsigned)camera_x >> 3;

        /* Scroll is set in blanking before the BAT ring receives new columns. */
        vdc_set_scroll(VDC0, (u16)(camera_x & 1023), 0);
        if (now_tile > previous_tile) {
            for (unsigned t = previous_tile + 1; t <= now_tile; ++t)
                write_world_column((int)(t + BAT_WIDTH - 1u));
        } else if (now_tile < previous_tile) {
            for (unsigned t = previous_tile; t > now_tile; --t)
                write_world_column((int)t - 1);
        }
        previous_tile = now_tile;
    }
}
