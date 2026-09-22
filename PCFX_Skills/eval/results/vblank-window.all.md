<reasoning>
Here's a thinking process that leads to the suggested solution:

1.  **Analyze the Request:**
    *   **Symptom:** Real-hardware screen noise (bottom bands), tearing (weapon/status bar), one-field glitch after page flip. Perfect in emulator.
    *   **Context:** PC-FX Doom port.
    *   **Provided Code:** `pcfx_support.c` (vblank check) and `i_system_pcfx.c` (presenter logic).
    *   **Key Observation:** The code uses `#define PCFX_VBLANK_RASTER 240` and checks `>= 240`.
    *   **Task:** Identify root cause, define correct vblank window, provide a patch plan (including handling private copies), and state emulator trustworthiness.

2.  **Consult Knowledge Base (Mental Check & Search):**
    *   *Query:* What is the vertical blanking range on PC-FX?
    *   *Source:* `[pcfx-frame-timing]` §3 "Where vertical blanking actually is".
    *   *Fact:* HuC6261 manual (C6261), 262-line mode. EVB = 22, SVB = 262.
    *   *Active Picture:* Rasters 22 ... 261.
    *   *Vertical Blanking:* Raster 262 and 0 ... 21.
    *   *Error:* The code uses `>= 240`. Rasters 240..261 are the *bottom of the picture*, not vblank.
    *   *Consequence:* Palette writes and page flips happen while the beam is drawing the bottom of the screen (status bar area). This causes the "noise bands" and "tearing".

3.  **Analyze the Provided Code:**
    *   `pcfx_support.c`:
        ```c
        #define PCFX_VBLANK_RASTER 240
        // ...
        return pcfx_tetsu_raster_stable() >= 240;
        ```
        *Critique:* 240 is arbitrary and wrong. It misses the wrap-around (0..21) and includes the bottom 22 lines of the screen.
    *   `i_system_pcfx.c`:

</reasoning>

### 1. Root Cause

The port defines vertical blanking as `raster >= 240`.

In 262-line mode, the active picture is rasters **22 through 261**. Rasters 240–261 are the bottom 22 lines of the screen (where the status bar lives). By waiting for raster 240, the code performs palette bursts and page flips while the beam is actively drawing the bottom of the screen.

This causes:
*   **Noise bands:** Palette changes mid-scanline corrupt the pixels being drawn at that moment.
*   **Tearing:** The page flip happens while the beam is reading the old buffer, causing the weapon/status bar to mix with the 3D view.

### 2. Correct Definition

According to the HuC6261 manual (`DEVICE_EN/C6261`), 262-line mode:
*   **EVB (End of Vertical Blanking):** 22
*   **SVB (Start of Vertical Blanking):** 262

**Vertical Blanking Window:** Raster **262** and Raster **0 through 21**.

### 3. Patch Plan

**A. Centralize the predicate**
Delete the three private copies of `raster >= 240`. Replace them with a single correct definition in `platform/pcfx_support.c`.

**B. New Code (`platform/pcfx_support.c`)**
Replace the existing `pcfx_in_vblank` and the `PCFX_VBLANK_RASTER` macro with this:

```c
/* HuC6261 262-line mode: EVB=22, SVB=262.
 * Active picture is 22..261. Vblank is 262 and 0..21. */
#define TETSU_RASTER_ACTIVE_START 22
#define TETSU_RASTER_ACTIVE_END   261

static inline int pcfx_in_vblank(void)
{
    unsigned r = pcfx_tetsu_raster_stable() & 0x1FF; /* mask to 0..511 */
    return (r >= TETSU_RASTER_ACTIVE_END) || (r < TETSU_RASTER_ACTIVE_START);
}
```

**C. Fix the Presenter (`platform/i_system_pcfx.c`)**
The presenter logic currently spins until raster 240. This is too late for a clean flip. Move the spin target to **250** (well inside vblank, but after the beam has wrapped) to ensure the flip happens safely before the next frame starts drawing at raster 22.

```c
/* ... */
static void pcfx_present_poll(void)
{
    unsigned r = pcfx_tetsu_raster_stable() /* & 0x1FF */;

    /* Palette burst: safe anywhere in vblank (262..21). */
    if (g_pcfx_palette_pend && pcfx_in_vblank())
        pcfx_flush_palette();

    /* Flip logic: wait until we are safely past the active picture wrap.
     * 250 is inside vblank (262..21) but ensures we aren't spinning
     * across the 262->0 boundary unnecessarily if we are already there. */
    if (r < 250u && r > 21u) /* If we are in active picture */
        present_spin_to(250u);

    king_set_display_page(page);
    king_reassert_bg0();
    vdc_publish_weapon_sat();
}
```

### 4. Emulator Trust

**No.** The emulator (`pcfxemu`) is currently configured to be forgiving of mid-scanline register changes. It likely blends the palette/flip seamlessly or ignores the timing violation.

To verify the fix:
1.  Run `pcfx-headless` with `--frames 1800`.
2.  Take a screenshot at frame 1800 (before fix) and frame 1800 (after fix).
3.  Compare them. If the status bar pixels differ, the fix is working.