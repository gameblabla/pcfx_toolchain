---
name: pcfx-king-framebuffer
description: Draw a bitmap on PC-FX using KING BG0 in 256-colour mode - the KRAM word/pixel layout, the I/O port access model, fast KRAM burst writes, double buffering and page flipping, BG sizes and affine scaling. Use for any bitmap/software-rendered output, when pixels land in the wrong place, when horizontal pixel pairs look swapped, or when the framebuffer blit is too slow.
---

# KING BG0 as a bitmap framebuffer

This is how nearly every project here draws. KING BG0 in `KING_BGMODE_256_PAL` is a
**linear 8bpp bitmap** in KRAM, composited by Tetsu like any other layer.

## 1. KRAM is I/O, not memory

**KRAM is not memory-mapped.** There is no pointer you can write. Every access goes
through two KING I/O ports:

| Port | Purpose |
|---|---|
| `0x600` | latch the KING register number |
| `0x604` | read/write that register's data |

Writing a pixel run is: latch register `0x0D` (`KRAM_AWR`) with a **word address plus an
auto-increment**, latch register `0x0E` (`KRAM_DATA`) once, then stream words to the data
port. The KING hardware advances the address automatically.

`king_set_kram_write()` and `king_kram_write()` are useful cold-path wrappers, but they
must not be in a per-word render loop: `king_kram_write()` reselects `KRAM_DATA` and pays
a `jal`/`jmp` pair for every word. For target code, use an inline helper pair like this:

```c
/* Match libpcfx's KWP encoding: A[17:0], signed increment field [27:18]. */
static inline __attribute__((always_inline)) void kram_set_write_inline(
    u32 addr, int incr)
{
    u32 command = addr | (((u32)incr & 0x000003ffu) << 18);
    __asm__ volatile (
        "out.h %[reg], 0x600[r0]\n"
        "out.w %[command], 0x604[r0]"
        : : [reg] "r" ((u16)0x000d), [command] "r" (command));
}

static inline __attribute__((always_inline)) void kram_begin_burst(void)
{
    __asm__ volatile (
        "out.h %[reg], 0x600[r0]"
        : : [reg] "r" ((u16)0x000e));
}

static inline __attribute__((always_inline)) void kram_write_latched(u16 word)
{
    __asm__ volatile ("out.h %[word], 0x604[r0]" : : [word] "r" (word));
}
```

The `out.w` above is only the one 32-bit KRAM address/increment control write; the hot
data stream is `out.h`. If a host test needs the libpcfx wrappers, hide that fallback
behind `#ifdef HOST_TEST`; target builds should emit the inline V810 path.

### Copy these helpers — the burst inner loop is mandatory

"Set the address once, then burst" means **one inline KRAM address setup followed by
MANY direct data-port writes**. A very common bug is setting the address per row but then
writing only *one* word, which leaves the rest of the row as uninitialised KRAM — the
screen comes out black with sparse coloured speckles. Use these:

```c
#define SCR_W          256u
#define WORDS_PER_ROW  (SCR_W / 2u)              /* 128: 2 pixels per word */
#define PAGE_WORDS     (WORDS_PER_ROW * 240u)    /* 30720 words per buffer */

/* Fill `count` consecutive KRAM words with `word`. */
static void kram_fill(u32 base, u16 word, u32 count)
{
    kram_set_write_inline(base, 1);     /* ONCE */
    kram_begin_burst();                 /* ONCE */
    while (count--)
        kram_write_latched(word);       /* MANY */
}

/* Solid rectangle. x and w must be even (a word is 2 pixels). */
static void draw_box(u32 base, unsigned x, unsigned y,
                     unsigned w, unsigned h, u8 colour)
{
    u16 pair = (u16)((colour << 8) | colour);
    unsigned row;

    for (row = 0; row < h; row++) {
        unsigned words = w / 2u;
        kram_set_write_inline(base + (y + row) * WORDS_PER_ROW + (x / 2u), 1);
        kram_begin_burst();
        while (words--)
            kram_write_latched(pair);
    }
}

/* A full-screen clear is then just: */
kram_fill(page_base, (colour << 8) | colour, PAGE_WORDS);

/* ...and a horizontal band (e.g. sky over ground): */
kram_fill(page_base,                          sky_pair,    120u * WORDS_PER_ROW);
kram_fill(page_base + 120u * WORDS_PER_ROW,   ground_pair, 120u * WORDS_PER_ROW);
```

Note the band fills need no per-row loop at all: rows are contiguous in KRAM, so one
`kram_fill` covers many rows in a single burst — which is also the fastest form.

### Two pitfalls that cost real hours here

- **Use `out.h`, never `out.w`.** The PC-FX has no 32-bit I/O write; `out.w` is split into
  two 16-bit writes *and* takes a **+3 cycle** consecutive-I/O penalty versus +1 for
  `out.h`. Packing two KRAM words into one `out.w` is measurably **slower**. This was
  tested and rejected in doom-pcfx.
- **`in.*` only works on the I/O bus.** An `in.*` against main RAM returns 0 — this caused
  a real depacker bug. Use `ld.*`/`st.*` for RAM.

## 2. The pixel layout

One KRAM word holds **two horizontally adjacent pixels**:

```
 bits 15..8 = LEFT pixel      bits 7..0 = RIGHT pixel
 word address = base + y * (width / 2) + x / 2
```

For a 256-wide buffer: `word = base + y * 128 + x / 2`, and one screen is
`256 * 240 / 2 = 30720` words.

**If every horizontal pixel pair in your art comes out swapped**, this is why: the V810 is
little-endian, so a halfword read of art stored "left pixel first" puts the left pixel in
the low byte, but KING reads the left pixel from the **high** byte. Fix it **once in the
asset build**, not in the per-frame copy (`emeraldpcfx/tools/build_gfx.py`'s
`swap_pixel_pairs`). emeraldpcfx shipped a one-pixel comb along every edge before this
was found.

Writing a solid pair is therefore `(colour << 8) | colour`.

## 3. Required setup

See [pcfx-bringup] §3 for the full mandatory sequence. The parts specific to the bitmap:

```c
king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                 KING_BGSIZE_256, KING_BGSIZE_256);   /* (h, w, subh, subw) */
king_set_bat_cg_addr(KING_BG0, 0, page_base >> 10);  /* 1024-word units */
king_set_bat_cg_addr(KING_BG0SUB, 0, page_base >> 10);
```

Sizes are enum steps, not pixels: `KING_BGSIZE_8/16/32/64/128/256/512/1024` (1024 is BG0
only). Modes: `4_PAL`, `16_PAL`, `256_PAL`, `64K`, `16M`, and `| KING_BGMODE_BAT` for
block-attribute-table (tiled) variants.

The [pcfx-bringup] template enables BG0 rotation, so it needs eight
`KING_CODE_ROTATE` slots and explicit affine coefficients at registers `0x38..0x3d`.
For a normal bitmap, clear REG.12's rotation switch and use direct-CG fetches instead:
two slots for 4bpp, four for 8bpp, or eight for 64K/16M, in the microprogram bank
selected by the CG base address. The original C6272 manual lists 16M only for the
non-rotation path. Do not mix normal direct-CG instructions with rotation enabled.

### Free 2:1 horizontal scaling

The affine `A` coefficient (register `0x38`, 8.8 fixed) is source-x step per display-x:

| A | Effect |
|---|---|
| `0x0100` | 1:1 — a 256-wide buffer fills the 256-wide screen |
| `0x0200` | 2:1 — a **512-wide** buffer is sampled down onto 256 pixels |

Inverting this is the classic performance trick: render a **128-wide** buffer and set
`A = 0x0080` to stretch it to 256, halving your pixel count for fat pixels.
descent-pcfx does exactly this (128×240 logical canvas on a 256×240 physical BG0).

## 4. Double buffering

Never draw into the page being displayed — you will get tearing and half-drawn frames.
Keep two buffers in KRAM and flip by repointing BG0's CG address **during blanking**:

```c
#define PAGE_WORDS (256 * 240 / 2)     /* 30720 */
#define PAGE0 0
#define PAGE1 PAGE_WORDS

/* ... render everything into the hidden page ... */
u32 back = front ^ 1u;
u32 base = back ? PAGE1 : PAGE0;
/* ... draw only into `base` ... */
wait_frame();                                  /* see [pcfx-frame-timing] */
king_set_bat_cg_addr(KING_BG0, 0, base >> 10); /* 1024-word units */
king_set_bat_cg_addr(KING_BG0SUB, 0, base >> 10);
front = back;
```

The flip is one register write, so it fits easily in vertical blanking. **Palette writes
and KING mode changes must also happen in blanking** — doing them during active display
produces visible glitches (a real fix in both wolf-pcfx and doom-pcfx).

Triple buffering (doom-pcfx, wolf-pcfx) lets the game logic start the next frame without
waiting for the flip; only add it once double buffering is correct.

## 5. Making the blit fast

The framebuffer blit is usually one of the top costs in a software renderer.

- **Burst, don't re-address.** One inline address setup per span/row, not per pixel.
- **Do not clear the whole page by default.** Initialize static background content once,
  then erase each page's previous moving-object bounds before drawing its new bounds.
- **Clear only what you must.** A full-screen clear is 30720 `out.h`s. If the renderer
  covers the screen anyway (a 3D world with a floor and ceiling), skip the clear entirely.
- **`out.h` beats `out.w`** (§1). Do not re-litigate this; it is measured.
- Consecutive `out.h` costs +1 each; interleaving a little ALU work between stores can
  avoid the pairing penalty, but only matters in genuinely hot loops.
- The KING profiler reports CPU KRAM writes per field — use it to check the blit is the
  size you think it is. See [pcfx-emulator-testing].

## 6. Other bit depths

For a still-picture path and full format/palette decision table, see [pcfx-2d-picture].
The KING format enum selects the pixel representation for each background plane:

| Mode | Pixels per 16-bit KRAM word | Storage at 256×240 | Color source |
|---|---:|---:|---|
| `KING_BGMODE_4_PAL` | 8 (2bpp) | 15,360 bytes | 4 Tetsu palette indices |
| `KING_BGMODE_16_PAL` | 4 (4bpp) | 30,720 bytes | 16 Tetsu palette indices |
| `KING_BGMODE_256_PAL` | 2 (8bpp) | 61,440 bytes | 256 Tetsu palette indices |
| `KING_BGMODE_64K` | 1 (16bpp) | 122,880 bytes | Direct Y8U4V4, no palette |
| `KING_BGMODE_16M` | 2 pixels / 2 words | 122,880 bytes | Direct YUV888 with U/V shared by a horizontal pixel pair |

For indexed formats, the leftmost pixel occupies the most-significant bits of the word.
Index 0 is transparent. In direct 64K/16M formats, Y=0 is transparent. Direct 64K/16M
are not RGB565/RGB888 storage; see [pcfx-2d-picture] for the YUV layout and the
unverified-on-retail-hardware boundary. Changing this enum alone does not provide a
matching KRAM asset or fetch microprogram.

`KING_BGMODE_16_PAL` halves KRAM write traffic per pixel vs 8bpp and is an
**unvalidated but promising** lever in doom-pcfx's notes (two 4bpp BGs ≈ same clear cost,
half the traffic). `KING_BGMODE_64K` is direct colour with no palette; measured in
3DCharacterSpinning at 8bpp **2.7–3.0 fps** vs high-colour **2.6–2.7 fps** — roughly half
the surface cost, as expected, since every surface-touching stage doubles.

**All backgrounds must fit in the same KRAM page** — see [pcfx-kram-layout].

## Related

[pcfx-bringup] · [pcfx-yuv-palette] for colours · [pcfx-frame-timing] for the flip ·
[pcfx-kram-layout] for where buffers live · [pcfx-v810-performance] for the pixel loop.
