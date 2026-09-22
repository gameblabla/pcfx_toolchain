/*
 * cube3d.c - rotating flat-shaded cube on PC-FX, 100% software 3D.
 *
 * The complete pipeline, top to bottom, in fixed point, no floats:
 *   BAM trig -> rotation matrix -> transform 8 vertices -> perspective
 *   projection (one divide per vertex) -> backface cull -> painter's sort
 *   -> span rasterizer into KING BG0's KRAM bitmap.
 *
 * This is a VERIFIED template: it builds, boots, and runs at a measured
 * frame rate; see PCFX_Skills/pcfx-3d-pipeline/SKILL.md for the numbers
 * and for what to change to make it faster or prettier.
 *
 * Build:
 *   export PCFX_TOOLKIT_ROOT=..; export V810GCC=$PCFX_TOOLKIT_ROOT/prebuilt/v810-gcc
 *   export PATH=$V810GCC/bin:$PATH
 *   make cd && make run        # screenshot
 *   make prof                  # V810 cycle profile
 */

#include <pcfx/types.h>
#include <pcfx/king.h>
#include <pcfx/tetsu.h>
#include <pcfx/contrlr.h>
#include "sin_table.h"

/* --------------------------------------------------------------- screen --- */
#define SCR_W         128u                      /* logical render canvas */
#define SCR_H         120u
#define WORDS_PER_ROW 128u                      /* BG0 remains 256 wide */
#define PAGE_WORDS    (WORDS_PER_ROW * 240u)   /* 30720-word page stride */
#define PAGE0_BASE    0x00000u
#define PAGE1_BASE    PAGE_WORDS
#define CX            64
#define CY            60

/* ---------------------------------------------------------- fixed point --- */
typedef int32_t fx;                            /* Q16.16 */
#define FX_SHIFT 16
#define FX_ONE   (1 << FX_SHIFT)
#define FX_HALF  (1 << (FX_SHIFT - 1))

#define FX_FROM_INT(i)  ((fx)((i) << FX_SHIFT))
#define FX_TO_INT(f)    ((int)((f) >> FX_SHIFT))

/* 16.16 * 16.16 -> 16.16 using the hardware MUL (low in the reg, high in
 * r30). GCC 4.9.4 will NOT produce this from (int64)a*b -- it calls
 * __muldi3, which is far slower. Do not "simplify" this. */
static inline fx fx_mul(fx a, fx b)
{
#ifdef HOST_TEST
    return (int)(((int64_t)a * b) >> FX_SHIFT);
#else
    int lo, hi;
    __asm__ ("mul %2, %0\n\t"
             "mov r30, %1"
             : "=r"(lo), "=&r"(hi)
             : "r"(b), "0"(a)
             : "r30");
    return (int)(((unsigned)lo >> 16) | ((unsigned)hi << 16));
#endif
}

/* Set KRAM_AWR inline. This is the same encoding as libpcfx's
 * king_set_kram_write(), but avoids a call on every hot span/row. */
static inline __attribute__((always_inline)) void kram_set_write_inline(
    u32 addr, int incr)
{
#ifdef HOST_TEST
    king_set_kram_write(addr, incr);
#else
    /* A[17:0], signed increment field [27:18]. */
    u32 command = addr | (((u32)incr & 0x000003ffu) << 18);
    __asm__ volatile (
        "out.h %[reg], 0x600[r0]\n"
        "out.w %[command], 0x604[r0]"
        : : [reg] "r" ((u16)0x000d), [command] "r" (command));
#endif
}

/* KRAM_AWR leaves KRAM_DATA (register 0x0e) selected by the next latch.
 * Calling libpcfx's out-of-line king_kram_write() for every word would
 * redundantly latch 0x0e again and pay a jal/jmp pair. */
static inline __attribute__((always_inline)) void kram_write_latched(u16 word)
{
#ifdef HOST_TEST
    king_kram_write(word);
#else
    __asm__ volatile ("out.h %0, 0x604[r0]" : : "r" (word));
#endif
}

static inline __attribute__((always_inline)) void kram_begin_burst(void)
{
#ifndef HOST_TEST
    __asm__ volatile ("out.h %0, 0x600[r0]" : : "r" ((u16)0x000e));
#endif
}

/* Q16.16 / Q16.16 -> Q16.16. Goes through 64-bit; fine for per-vertex and
 * per-edge divides, NEVER inside a per-pixel loop (pcfx-fixed-point). */
static inline fx fx_div(fx a, fx b)
{
    return (fx)((((int64_t)a) << FX_SHIFT) / b);
}

/* Per-scanline edge step: (dx / dy) as Q16.16. dy=0 (flat edge) -> 0. */
static inline fx fx_step(int dx, int dy)
{
    return dy ? (fx)(((int64_t)dx << FX_SHIFT) / dy) : 0;
}

/* ------------------------------------------------------------- BAM trig --- */
#define BAM_ONE   1024                          /* binary angle: 1024 = turn */
#define BAM_MASK  (BAM_ONE - 1)
#define BAM_90    (BAM_ONE >> 2)

static inline int fx_sin(int a) { return g_sin[a & BAM_MASK]; }
static inline int fx_cos(int a) { return g_sin[(a + BAM_90) & BAM_MASK]; }

/* ------------------------------------------------------------ 3D types --- */
typedef struct { fx x, y, z; } vec3;

typedef struct { fx m[3][3]; } mat3;   /* v' = M * v, m[col][row] */

typedef struct {
    int sx, sy;                          /* projected screen coordinates */
    fx z;                                /* view-space depth (for sort)  */
} pt2;

/* ----------------------------------------------------------- matrix ops --- */
static void mat_rot_x(mat3 *m, int bam)
{
    fx s = (fx)fx_sin(bam) << 8, c = (fx)fx_cos(bam) << 8;
    m->m[0][0] = FX_ONE; m->m[0][1] = 0;      m->m[0][2] = 0;
    m->m[1][0] = 0;     m->m[1][1] = c;       m->m[1][2] = s;
    m->m[2][0] = 0;     m->m[2][1] = -s;      m->m[2][2] = c;
}

static void mat_rot_y(mat3 *m, int bam)
{
    fx s = (fx)fx_sin(bam) << 8, c = (fx)fx_cos(bam) << 8;
    m->m[0][0] = c;     m->m[0][1] = 0;       m->m[0][2] = -s;
    m->m[1][0] = 0;     m->m[1][1] = FX_ONE;  m->m[1][2] = 0;
    m->m[2][0] = s;     m->m[2][1] = 0;       m->m[2][2] = c;
}

static void mat_mul(const mat3 *a, const mat3 *b, mat3 *out)
{
    int c, r;
    for (c = 0; c < 3; c++)
        for (r = 0; r < 3; r++)
            out->m[c][r] = fx_mul(a->m[0][r], b->m[c][0])
                         + fx_mul(a->m[1][r], b->m[c][1])
                         + fx_mul(a->m[2][r], b->m[c][2]);
}

static vec3 v_transform(const mat3 *M, vec3 v)
{
    vec3 o;
    o.x = fx_mul(M->m[0][0], v.x) + fx_mul(M->m[1][0], v.y) + fx_mul(M->m[2][0], v.z);
    o.y = fx_mul(M->m[0][1], v.x) + fx_mul(M->m[1][1], v.y) + fx_mul(M->m[2][1], v.z);
    o.z = fx_mul(M->m[0][2], v.x) + fx_mul(M->m[1][2], v.y) + fx_mul(M->m[2][2], v.z);
    return o;
}

/* ------------------------------------------------------------ camera ---
 * Camera at the origin looking down +z.  FOCAL = 64 px at z = 1.0, so a
 * 2-unit-wide cube centred at z = 3.0 spans about half the screen.
 * One divide per vertex -- never inside a span loop.                    */
#define NEAR   FX_HALF                        /* 0.5: reject closer than this */
#define FOCAL  FX_FROM_INT(64)
#define CAMZ   FX_FROM_INT(3)                 /* cube centre distance        */

static int project(vec3 v, pt2 *o)
{
    if (v.z <= NEAR)
        return 0;
    o->sx = CX + (int)(fx_div(fx_mul(v.x, FOCAL), v.z) >> FX_SHIFT);
    o->sy = CY + (int)(fx_div(fx_mul(v.y, FOCAL), v.z) >> FX_SHIFT);
    o->z  = v.z;
    return 1;
}

/* --------------------------------------------------------------- model --- */
static const vec3 cube_v[8] = {
    { -FX_ONE, -FX_ONE, -FX_ONE }, {  FX_ONE, -FX_ONE, -FX_ONE },
    {  FX_ONE,  FX_ONE, -FX_ONE }, { -FX_ONE,  FX_ONE, -FX_ONE },
    { -FX_ONE, -FX_ONE,  FX_ONE }, {  FX_ONE, -FX_ONE,  FX_ONE },
    {  FX_ONE,  FX_ONE,  FX_ONE }, { -FX_ONE,  FX_ONE,  FX_ONE },
};

/* Six faces as quads; each becomes two triangles. The winding below is what
 * makes backface culling show the front three faces.                    */
static const int cube_faces[6][4] = {
    { 4, 7, 6, 5 },   /* +z (front)   */
    { 0, 1, 2, 3 },   /* -z (back)    */
    { 0, 3, 7, 4 },   /* -x (left)    */
    { 1, 5, 6, 2 },   /* +x (right)   */
    { 3, 2, 6, 7 },   /* +y (top)     */
    { 0, 4, 5, 1 },   /* -y (bottom)  */
};

/* ------------------------------------------------------------ raster --- */
/* Backface cull: signed area of the projected quad's first triangle.
 * With the winding above, outward faces give a positive area. */
static inline int face_visible(pt2 p0, pt2 p1, pt2 p2)
{
    return (p1.sx - p0.sx) * (p2.sy - p0.sy)
         - (p2.sx - p0.sx) * (p1.sy - p0.sy) > 0;
}

/* Fill one horizontal run into the KRAM bitmap. Words are 2 pixels:
 * x0 is rounded down to a word boundary, so a span may cover at most one
 * extra pixel -- invisible for an opaque closed mesh. */
static void span_fill(u32 base, int y, int x0, int x1, u16 color)
{
    int n;

    if (x0 < 0)            x0 = 0;
    if (x1 >= (int)SCR_W)  x1 = (int)SCR_W - 1;
    x0 &= ~1;
    x1 &= ~1;
    if (x1 - x0 < 2)
        return;
    n = (x1 - x0) >> 1;
    kram_set_write_inline(base + (u32)y * WORDS_PER_ROW + (u32)(x0 >> 1), 1);
    kram_begin_burst();
    while (n--)
        kram_write_latched((u16)(color | (color << 8)));
}

/* Flat triangle. a/b/c may be in any order; sorted internally.
 * One divide per edge (fx_step), then pure adds per scanline.        */
static void tri_fill(u32 base, pt2 a, pt2 b, pt2 c, u16 color)
{
    fx sl1, sl2, sr, xl, xr;
    int y0, y1, y2, y, on2;

    if (a.sy > b.sy) { pt2 t = a; a = b; b = t; }
    if (a.sy > c.sy) { pt2 t = a; a = c; c = t; }
    if (b.sy > c.sy) { pt2 t = b; b = c; c = t; }

    y0 = a.sy; y1 = b.sy; y2 = c.sy;
    if (y2 < 0 || y0 >= (int)SCR_H)
        return;
    if (y0 < 0) y0 = 0;
    if (y2 >= (int)SCR_H) y2 = (int)SCR_H - 1;

    sl1 = fx_step(b.sx - a.sx, b.sy - a.sy);   /* edge a->b  */
    sl2 = fx_step(c.sx - b.sx, c.sy - b.sy);   /* edge b->c  */
    sr  = fx_step(c.sx - a.sx, c.sy - a.sy);   /* edge a->c  */

    on2 = (y1 == a.sy);                        /* flat top: start on b->c */
    xl = FX_FROM_INT(on2 ? b.sx : a.sx);
    xr = FX_FROM_INT(a.sx);

    /* Walk the edges down to y0 for any rows above the screen. */
    for (y = a.sy; y < y0; y++) {
        if (y == y1 && y1 > a.sy) { xl = FX_FROM_INT(b.sx); on2 = 1; }
        xl += (y >= y1) ? sl2 : sl1;
        xr += sr;
    }

    for (y = y0; y <= y2; y++) {
        int xs = FX_TO_INT(xl), xe = FX_TO_INT(xr), t;
        if (xs > xe) { t = xs; xs = xe; xe = t; }
        span_fill(base, y, xs, xe, color);
        if (y == y1 && y1 > a.sy) { xl = FX_FROM_INT(b.sx); on2 = 1; }
        xl += (y >= y1) ? sl2 : sl1;
        xr += sr;
    }
}

/* ------------------------------------------------------------ KING --- */
/* Raw 16-bit KING register write (no libpcfx helper for 0x38..0x3d). */
static void king_reg16(u16 reg, u16 value)
{
#ifdef HOST_TEST
    (void)reg; (void)value;
#else
    __asm__ volatile (
        "out.h %[reg], 0x600[r0]\n"
        "out.h %[value], 0x604[r0]\n"
        : : [reg] "r" (reg), [value] "r" (value));
#endif
}

static void kram_fill(u32 base, u16 word, u32 count)
{
    kram_set_write_inline(base, 1);
    kram_begin_burst();
    while (count--)
        kram_write_latched(word);
}

typedef struct { int x0, y0, x1, y1; } dirty_rect;

/* Clear only the bounds occupied the last time this KRAM page was used.
 * The two pages keep independent rectangles because each is revisited two
 * rendered frames later.  Bounds are word-aligned and inclusive. */
static void clear_dirty(u32 base, const dirty_rect *r)
{
    int y;
    u32 words;

    if (r->x1 < r->x0 || r->y1 < r->y0)
        return;
    words = (u32)(r->x1 - r->x0 + 1) >> 1;
    for (y = r->y0; y <= r->y1; y++) {
        u32 n = words;
        kram_set_write_inline(base + (u32)y * WORDS_PER_ROW +
                              (u32)(r->x0 >> 1), 1);
        kram_begin_burst();
        while (n--)
            kram_write_latched(0x0000);
    }
}

/* ------------------------------------------------------ frame timing --- */
/* Canonical Tetsu wait, V810 asm, port 0x300 read twice (hardware bug).
 * Copy verbatim -- see PCFX_Skills/pcfx-frame-timing. */
static inline void wait_frame(void)
{
#ifndef HOST_TEST
    __asm__ volatile (
        "movea 0x20A0, r0, r12\n"
        "movea 0x3FE0, r0, r13\n"
        "1:\n"
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 1b\n"
        "cmp r10, r12\n"
        "bne 1b\n"
        "2:\n"
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 2b\n"
        "cmp r10, r12\n"
        "be 2b\n"
        : : : "r10", "r11", "r12", "r13");
#endif
}

/* ------------------------------------------------------------ main --- */
typedef struct { int idx; fx z; } face_rec;

static u16 face_color[6];
volatile u32 g_rendered_frames;

#ifndef HOST_TEST
int main(void)
{
    u16 microprogram[16];
    face_rec sort[6];
    u32 back = 1;
    dirty_rect dirty[2] = { { 0, 0, -1, -1 }, { 0, 0, -1, -1 } };
    unsigned i;
    int yaw = 0, pitch = 32;

    king_init();
    tetsu_init();

    king_set_kram_pages(0, 0, 0, 0);
    king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
    king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                     KING_BGSIZE_256, KING_BGSIZE_256);
    king_set_bat_cg_addr(KING_BG0, 0, PAGE0_BASE >> 10);
    king_set_bat_cg_addr(KING_BG0SUB, 0, PAGE0_BASE >> 10);
    king_set_scroll(KING_BG0, 0, 0);
    king_set_scroll(KING_BG0SUB, 0, 0);

    /* BG0 rotate microprogram.  A=D=0.5 stretches the 128x120 logical
     * canvas to the 256x240 display for free. */
    for (i = 0; i < 8; i++) microprogram[i] = KING_CODE_ROTATE;
    for (; i < 16; i++)     microprogram[i] = KING_CODE_NOP;
    king_disable_microprogram();
    king_write_microprogram(microprogram, 0, 16);
    king_enable_microprogram();
    king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                     KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 1);
    king_reg16(0x38, 0x0080);
    king_reg16(0x39, 0x0000);
    king_reg16(0x3a, 0x0000);
    king_reg16(0x3b, 0x0080);
    king_reg16(0x3c, 0x0000);
    king_reg16(0x3d, 0x0000);

    tetsu_set_king_palette(0, 0, 0, 0);
    tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                         TETSU_COLORS_256, TETSU_COLORS_16,
                         0, 0, 1, 0, 0, 0, 0);

    /* Greys 1..64 for flat shading; entry 0 = black. Y8U4V4, U=V=8. */
    for (i = 0; i < 256; i++)
        tetsu_set_palette((u16)i, 0x0088);
    for (i = 1; i <= 64; i++) {
        u16 y = (u16)(i * 4 > 255 ? 255 : i * 4);
        tetsu_set_palette((u16)i, (u16)((y << 8) | 0x88));
    }

    contrlr_pad_init(0);
    kram_fill(PAGE0_BASE, 0x0000, PAGE_WORDS);
    kram_fill(PAGE1_BASE, 0x0000, PAGE_WORDS);

    for (;;) {
        mat3 mr, my, rot;
        vec3 view[8];
        pt2  scr[8];
        u32  base = back ? PAGE1_BASE : PAGE0_BASE;
        int  nvis = 0, f, k;

        yaw   += 8;              /* ~2.8 deg/frame at 60 fps */
        pitch += 2;

        /* 1. Build the rotation and transform all vertices. */
        mat_rot_x(&mr, pitch);
        mat_rot_y(&my, yaw);
        mat_mul(&my, &mr, &rot);
        for (i = 0; i < 8; i++)
            view[i] = v_transform(&rot, cube_v[i]);

        /* 2. Push the cube down the z axis and project.
         *    All vertices stay in front of the camera here, so the guard
         *    in project() never fires -- it is still required in general. */
        for (i = 0; i < 8; i++) {
            vec3 v = view[i];
            v.z += CAMZ;
            if (!project(v, &scr[i]))
                goto next_frame;
        }

        /* 3. Cull, shade, and collect visible faces.
         *    Flat shade from the rotated face normal: v'_z = M[0][2] nx +
         *    M[1][2] ny + M[2][2] nz, so a face's brightness is a sign
         *    and one column of M -- no normal transforms, no normalize. */
        for (f = 0; f < 6; f++) {
            static const int norm_fx[6] = { 0, 0, -1, 1, 0, 0 };
            static const int norm_fy[6] = { 0, 0, 0, 0, 1, -1 };
            static const int norm_fz[6] = { 1, -1, 0, 0, 0, 0 };
            const int *q = cube_faces[f];
            pt2 p0 = scr[q[0]], p1 = scr[q[1]], p2 = scr[q[2]];
            fx nz;
            int sh;

            if (!face_visible(p0, p1, p2))
                continue;
            sort[nvis].idx = f;
            sort[nvis].z   = (scr[q[0]].z + scr[q[1]].z
                            + scr[q[2]].z + scr[q[3]].z) >> 2;
            nvis++;

            nz = fx_mul(rot.m[0][2], FX_FROM_INT(norm_fx[f]))
               + fx_mul(rot.m[1][2], FX_FROM_INT(norm_fy[f]))
               + fx_mul(rot.m[2][2], FX_FROM_INT(norm_fz[f]));
            sh = 8 + ((int)((nz + FX_ONE) >> (FX_SHIFT - 5)));  /* 8..72 */
            if (sh > 64) sh = 64;
            face_color[f] = (u16)sh;
        }

        /* 4. Painter's sort: far faces first (descending view z).
         *    nvis <= 6 -- an insertion sort is cheaper than anything else. */
        for (f = 1; f < nvis; f++) {
            face_rec t = sort[f];
            k = f;
            while (k > 0 && sort[k - 1].z < t.z) {
                sort[k] = sort[k - 1];
                k--;
            }
            sort[k] = t;
        }

        /* 5. Erase only this page's previous cube, then rasterize into it. */
        clear_dirty(base, &dirty[back]);
        {
            dirty_rect next = { (int)SCR_W, (int)SCR_H, -1, -1 };
            for (i = 0; i < 8; i++) {
                if (scr[i].sx < next.x0) next.x0 = scr[i].sx;
                if (scr[i].sx > next.x1) next.x1 = scr[i].sx;
                if (scr[i].sy < next.y0) next.y0 = scr[i].sy;
                if (scr[i].sy > next.y1) next.y1 = scr[i].sy;
            }
            if (next.x0 < 0) next.x0 = 0;
            if (next.y0 < 0) next.y0 = 0;
            if (next.x1 >= (int)SCR_W) next.x1 = (int)SCR_W - 1;
            if (next.y1 >= (int)SCR_H) next.y1 = (int)SCR_H - 1;
            next.x0 &= ~1;
            next.x1 |= 1;
            if (next.x1 >= (int)SCR_W) next.x1 = (int)SCR_W - 1;
            dirty[back] = next;
        }
        for (k = 0; k < nvis; k++) {
            const int *q = cube_faces[sort[k].idx];
            pt2 p0 = scr[q[0]], p1 = scr[q[1]],
                p2 = scr[q[2]], p3 = scr[q[3]];
            u16 col = face_color[sort[k].idx];
            tri_fill(base, p0, p1, p2, col);
            tri_fill(base, p0, p2, p3, col);
        }

        /* 6. Flip during blanking. */
        wait_frame();
        king_set_bat_cg_addr(KING_BG0, 0, base >> 10);
        king_set_bat_cg_addr(KING_BG0SUB, 0, base >> 10);
        g_rendered_frames++;
        back ^= 1u;

next_frame: ;
    }
}
#endif /* HOST_TEST */
