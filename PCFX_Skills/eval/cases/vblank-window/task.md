# Task: real-hardware screen noise and torn HUD in a PC-FX Doom port

## Symptom (reported from a real PC-FX console, NOT visible in the emulator)

- Thin bands of colour noise flicker across the bottom of the screen, over the
  status bar, whenever the palette changes (picking up an item, taking damage).
- The weapon sprite and the status bar tear against the 3D view.
- The KING background layer occasionally shows a one-field glitch after a page flip.
- Everything looks perfect under pcfxemu.

## Relevant existing code

`platform/pcfx_support.c`:

```c
/* Vblank is detected from the HuC6261 (tetsu) raster counter, NOT the VDC's VD
 * status bit ... The tetsu raster is independent of VDC state.  Active display
 * is lines 0..239 in the 262-line mode; vblank is raster >= 240. */
#define PCFX_VBLANK_RASTER 240
static inline int pcfx_in_vblank(void)
{
    /* Stable double-read: a single raw tetsu_get_raster() can latch a
     * bogus transitional value (Tetsu HW bug), which would flip this predicate
     * at the wrong scanline and mistime the page flip / sprite uploads. */
    return pcfx_tetsu_raster_stable() >= PCFX_VBLANK_RASTER;
}
```

`platform/i_system_pcfx.c` (the presenter, run once per frame):

```c
/* Act only inside [208..258]: early enough that the flip and the SAT
 * publish still land in this vblank, late enough to be tear-safe. */
static void present_spin_to(unsigned raster)
{
    unsigned spin = 0;
    while (pcfx_tetsu_raster_stable() < raster && spin++ < 200000u) { }
}

static void pcfx_present_poll(void)
{
    unsigned r = pcfx_tetsu_raster_stable();

    if (g_pcfx_palette_pend && r >= 240u && r <= 258u)
        pcfx_flush_palette();            /* 256-entry VCE palette burst */

    if (r < 208u || r > 258u)
        return;

    present_spin_to(240u);
    king_set_display_page(page);         /* the page flip */
    king_reassert_bg0();                 /* KING page/CG/affine registers */
    vdc_publish_weapon_sat();            /* VDC SATB DMA + weapon tiles */
}
```

There are three more private copies of the `raster >= 240` test elsewhere in the port.

## What to produce

1. **Root cause.** State precisely what is wrong, with the hardware numbers.
2. **The correct definition** of the vertical blanking window for this video mode,
   and which manual section it comes from.
3. **A concrete patch plan**: what to add, what to delete, and how the four private
   copies of the predicate should be handled.
4. Say explicitly whether the emulator can be trusted to confirm this fix.

Be specific and terse. Give real C code for the new predicate.
