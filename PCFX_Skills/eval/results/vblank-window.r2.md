<reasoning>
Here's a thinking process:

1.  **Analyze the User Input:**
   - **Symptom:** Real-hardware screen noise/bands at bottom during palette changes, tearing of weapon/HUD against 3D view, one-field glitch after page flip. Perfect in emulator.
   - **Existing Code:**
     - `pcfx_in_vblank()` uses `raster >= 240`.
     - `present_spin_to(raster)` spins while `< raster`.
     - `pcfx_present_poll()` checks `r >= 240 && r <= 258` for palette, returns if `r < 208 || r > 258`, then spins to 240, flips page, reasserts BG0, publishes SATB.
     - Three more private copies of `raster >= 240`.
   - **Task:**
     1. Root cause with hardware numbers.
     2. Correct definition of vblank window & manual reference.
     3. Concrete patch plan (add/delete, handle private copies).
     4. Emulator trust statement.
     5. Provide real C code for the new predicate.

2.  **Consult Knowledge Modules:**
   - `[pcfx-frame-timing]` is highly relevant.
   - Section 3: "Where vertical blanking actually is"
     - HuC6261 manual (`DEVICE_EN/C6261`, "Vertical timing"), 262-line mode: **EVB = 22, SVB = 262**.
     - Active picture: rasters **22 … 261** (240 lines).
     - Vertical blanking: raster **262 and 0 … 21** (22 lines).
     - `raster >= 240` test is wrong — 240..261 are the *bottom of the picture* (status bar/HUD).
     - Copy predicate verbatim provided in skill.
     - Anti-pattern `spin_to(raster N)` explained: `<` never fires after wrap, bounded spin gives up mid-frame.
     - Replacement: use `wait_frame()` or poll `pcfx_in_vblank()`, act in blanking, order steps shortest-deadline-first, re-read raster between steps.
   - Section 1
</reasoning>

### 1. Root cause
The port treats rasters `240..261` as vertical blanking. On the HuC6261 in 262-line mode, those are the **bottom 22 lines of the active picture** (the status bar/HUD). Palette bursts, page flips, and SATB DMA writes landing there overwrite pixels mid-scan, causing the colour bands, tearing, and one-field glitches. The emulator applies register writes instantly, so it never shows the mid-picture corruption.

### 2. Correct vblank definition
- **SVB (Start of VBlank) = 262**
- **EVB (End of VBlank) = 22**
- Active picture: rasters `22 … 261` (240 lines)
- Vertical blanking: rasters `262` and `0 … 21` (22 lines)
- Source: `DEVICE_EN/C6261.pdf`, section *"Vertical timing"* (262-line mode).

### 3. Patch plan
**Add/Replace:**
1. Create a single header (e.g., `platform/pcfx_video.h`) with the canonical predicate and blanking helper:
```c
/* HuC6261 262-line mode: EVB=22, SVB=262.  DEVICE_EN/C6261, "Vertical timing". */
#define PCFX_VBLANK_SVB 262u
#define PCFX_VBLANK_EVB  22u

static inline int pcfx_raster_in_vblank(unsigned r)
{
    return (r >= PCFX_VBLANK_SVB) || (r < PCFX_VBLANK_EVB);
}

static inline int pcfx_in_vblank(void)
{
    return pcfx_raster_in_vblank(pcfx_tetsu_raster_stable());
}

/* Lines of blanking remaining — use to gate bursts. */
static inline unsigned pcfx_blank_lines_left(void)
{
    unsigned r = pcfx_tetsu_raster_stable();
    if (r >= PCFX_VBLANK_SVB) return (PCFX_VBLANK_SVB - r) + PCFX_VBLANK_EVB;
    if (r <  PCFX_VBLANK_EVB) return PCFX_VBLANK_EVB - r;
    return 0u;
}
```
2. Rewrite `pcfx_present_poll()` to drop the spin and act on the blanking window:
```c
static void pcfx_present_poll(void)
{
    unsigned r = pcfx_tetsu_raster_stable();

    if (!pcfx_in_vblank())
        return;

    /* Palette burst first (shortest deadline, must finish before EVB) */
    if (g_pcfx_palette_pend && pcfx_blank_lines_left() >= 24u)
        pcfx_flush_palette();

    r = pcfx_tetsu_raster_stable(); /* re-read after potential burst */
    if (!pcfx_in_vblank())
        return;

    king_set_display_page(page);
    king_reassert_bg0();
    vdc_publish_weapon_sat();
}
```
3. **Delete** the `present_spin_to()` function and the `r >= 240` threshold logic.
4. **Consolidate** the three private `raster >= 240` copies: replace each with `pcfx_in_vblank()` or `pcfx_raster_in_vblank(r)` and remove the local macros.

### 4. Emulator trust
No. The emulator applies KING/Tetsu register writes instantly and does not model mid-picture palette bursts or SATB DMA timing. A clean emulator run only proves you didn't regress boot/render logic; it cannot confirm the fix. The fix is justified by the C6261 manual and the measured hardware symptoms.