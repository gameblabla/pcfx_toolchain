#include <stdio.h>
#include <stdint.h>
#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/contrlr.h>
#include "src/sin_table.h"

#define HOST_TEST

/* Stub the libpcfx hardware layer. */
void king_init(void){}
void tetsu_init(void){}
void king_set_kram_pages(u8 a,u8 b,u8 c,u8 d){}
void king_set_bg_mode(king_bgmode a,king_bgmode b,king_bgmode c,king_bgmode d){}
void king_set_bg_prio(king_bgprio a,king_bgprio b,king_bgprio c,king_bgprio d,int e){}
void king_set_bg_size(king_bg a,king_bgsize b,king_bgsize c,king_bgsize d,king_bgsize e){}
void king_set_bat_cg_addr(king_bg a,u32 b,u32 c){}
void king_set_scroll(king_bg a,s16 b,s16 c){}
void king_write_microprogram(u16* d,u8 a,u8 b){}
void king_disable_microprogram(void){}
void king_enable_microprogram(void){}
void tetsu_set_king_palette(u16 a,u16 b,u16 c,u16 d){}
void tetsu_set_video_mode(tetsu_lines a,int b,tetsu_dotclock c,tetsu_colordepth d,tetsu_colordepth e,int f,int g,int h,int i,int j,int k,int l){}
void tetsu_set_palette(u16 a,u16 b){}
void contrlr_pad_init(int a){}
void king_set_kram_write(u32 a,int b){}
void king_kram_write(u16 w){}

/* Include the real engine (main is compiled out by HOST_TEST). */
#include "src/cube3d.c"

int main(void)
{
    int yaw = 0, pitch = 32, i, f;
    int bad = 0;
    for (int frame = 0; frame < 6; frame++, yaw += 8, pitch += 2) {
        mat3 mr, my, rot;
        vec3 view[8];
        pt2 scr[8];
        mat_rot_x(&mr, pitch);
        mat_rot_y(&my, yaw);
        mat_mul(&my, &mr, &rot);
        for (i = 0; i < 8; i++) view[i] = v_transform(&rot, cube_v[i]);
        for (i = 0; i < 8; i++) {
            vec3 v = view[i];
            v.z += CAMZ;
            if (!project(v, &scr[i])) {
                printf("frame %d: vert %d behind near plane!\n", frame, i);
                bad = 1;
                continue;
            }
        }
        printf("frame %d: ", frame);
        for (i = 0; i < 8; i++)
            printf("v%d(%d,%d) ", i, scr[i].sx, scr[i].sy);
        printf("\n");
        /* Winding-independent geometric truth: a face is visible iff the
         * transformed OUTWARD axis of the face points toward the camera,
         * checked at the face centre (translated view coords).  This must
         * agree exactly with the screen-space winding test, or the face
         * table has a wound-inward quad. */
        static const vec3 axis[6] = {
            { 0, 0, FX_ONE },  { 0, 0, -FX_ONE }, { -FX_ONE, 0, 0 },
            { FX_ONE, 0, 0 },  { 0, FX_ONE, 0 },  { 0, -FX_ONE, 0 },
        };
        int nvis = 0;
        for (f = 0; f < 6; f++) {
            const int *q = cube_faces[f];
            pt2 p0 = scr[q[0]], p1 = scr[q[1]], p2 = scr[q[2]];
            int screen_vis = face_visible(p0, p1, p2);
            vec3 n = v_transform(&rot, axis[f]);
            vec3 c = { 0, 0, 0 };
            for (i = 0; i < 4; i++) {
                c.x += view[q[i]].x; c.y += view[q[i]].y; c.z += view[q[i]].z;
            }
            c.x >>= 2; c.y >>= 2; c.z >>= 2;
            c.z += CAMZ;
            int geom_vis = ((long)n.x * c.x + (long)n.y * c.y + (long)n.z * c.z) < 0;
            if (screen_vis != geom_vis) {
                printf("  face %d: screen=%d geometry=%d MISMATCH!\n", f, screen_vis, geom_vis);
                bad = 1;
            }
            if (geom_vis) nvis++;
        }
        printf("  visible faces: %d (all 6 agree with geometry)\n", nvis);
        if (nvis > 3) bad = 1;
    }
    printf(bad ? "FAIL\n" : "PASS (every face agrees with geometry, all verts projected)\n");
    return bad;
}
