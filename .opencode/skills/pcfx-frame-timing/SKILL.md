---
name: pcfx-frame-timing
description: PC-FX frame pacing and vsync - the Tetsu raster counter double-read hardware bug and the correct wait-for-frame routine, where vertical blanking actually is (EVB=22/SVB=262), the 60/N fps quantization, and using a timer IRQ for a real millisecond clock. Use for tearing, frame pacing, hangs in a vsync spin (including a VDC status VD-bit wait that never returns), a game clock that runs slow, or measuring fps.
---

# Frame timing, vsync and the Tetsu raster

## 1. The raster counter has a hardware bug — read it TWICE

The Tetsu (HuC6261) raster counter lives at **I/O port `0x300`**, with the line number in
**bits 14:5** (i.e. `line << 5`, mask `0x3FE0`).

**The chip has a documented hardware bug: a single read can latch a transitional, bogus
value.** It must be read twice, and the two reads must agree before you trust the value.
Every project here that ignored this had frame-loop bugs.

## 2. The wait-frame routine — use this assembly, verbatim

**Write this in V810 assembly reading port `0x300` directly. Do not reimplement it in C.**
This is the canonical routine; it is verified working in this workspace's template, and in
`pcfx_tetsu_wait.S`.

Because it reads the port directly, the raster arrives **raw** as `line << 5` — hence the
`0x3FE0` mask and `0x20A0` (= 261 << 5) constants. Phase 1 waits until the raster **is**
the last line of the frame; phase 2 waits until it **is not**, returning exactly on the
wrap into the next frame.

```c
/* r10-r13 are caller-saved on this ABI, so they need no preservation. */
static inline void wait_frame(void)
{
    __asm__ volatile (
        "movea 0x20A0, r0, r12\n"   /* last raster of the frame */
        "movea 0x3FE0, r0, r13\n"   /* raster bit mask          */

        "1:\n"                      /* wait until this frame is finished */
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"     /* read twice: hardware bug */
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 1b\n"
        "cmp r10, r12\n"
        "bne 1b\n"

        "2:\n"                      /* then wait until the next one starts */
        "in.h 0x300[r0], r10\n"
        "in.h 0x300[r0], r11\n"
        "and r13, r10\n"
        "and r13, r11\n"
        "cmp r10, r11\n"
        "bne 2b\n"
        "cmp r10, r12\n"
        "be 2b\n"                   /* still the last raster: keep waiting */
        : : : "r10", "r11", "r12", "r13");
}
```

A standalone `.S` file with the same body and a `jmp [r31]` at the end works equally well
(see pcfx_tetsu_wait.S); the constants are for **262-line modes only**.

### ⚠ Why not C: the two raster encodings are different

| Access | What you get | Compare against |
|---|---|---|
| `in.h 0x300` (**asm**, above) | raw `line << 5`; mask `0x3FE0` | `0x20A0` |
| `tetsu_get_raster()` (**C**) | **already decoded** — it does `shr 5; andi 0x1FF` internally | `261` |

Mixing them is a real, verified hang: masking a decoded line number (0..511) with
`0x3FE0` can never equal `0x20A0`, so the wait spins **forever**. The program renders one
correct-looking frame and then freezes, which reads as "my drawing code doesn't work"
rather than as a hang. This exact bug appeared here in both hand-written and
LLM-generated code — which is why the assembly version is the one to use.

**Always verify your frame loop actually loops:** screenshot at two different `--frames`
values (e.g. 1400 and 1800) and confirm something moved.

Landing on the *leading edge* matters: a 256-entry palette upload, a KING page flip, or an
MPSW stop/start needs the whole blanking interval, not "somewhere past a threshold".

This project has this as hand-written asm in `pcfx_tetsu_wait.S`, which is worth
copying verbatim for a hot frame loop. The constants above are for **262-line mode only**.

### Status of this fix across the workspace

| Project | State |
|---|---|
| wolf-pcfx | asm two-phase wait (`pcfx_tetsu_wait.S`) — **the reference** |
| AirGT, 3DCharacterSpinning | `pcfx_tetsu_wait.S` — same routine |
| doom-pcfx | **has the double-read in C** (`pcfx_tetsu_raster_stable()`), but `video_wait_vsync()` polls a *threshold* predicate (`pcfx_in_vblank()`) instead of the two-phase wrap wait — **it does not have the asm routine** |

doom-pcfx is therefore not missing the hardware-bug workaround itself, but it lacks the
canonical wrap-edge wait: it waits for "raster is past a threshold" rather than "the frame
just wrapped". Porting `pcfx_tetsu_wait.S` into doom-pcfx is the
outstanding fix there, and is the thing to look at for any frame-edge-precision bug.

## 3. Where vertical blanking actually is

From the HuC6261 manual (`DEVICE_EN/C6261`, "Vertical timing"), 262-line mode:
**EVB = 22, SVB = 262**.

- Active picture: rasters **22 … 261** (240 lines)
- Vertical blanking: raster **262 and 0 … 21** (22 lines)

**A `raster >= 240` test for "in vblank" is wrong** — 240..261 are the *bottom of the
picture* (screen rows 218..236: the status bar / HUD strip). doom-pcfx carried that bug
in four separate private copies of the predicate before it was fixed and centralised.

### Copy this predicate verbatim — do not re-derive it from the numbers above

Put it in **one** header and delete every private copy. Re-deriving it from the prose is
where the off-by-one comes from: the blanking test is `>= 262`, **not** `>= 261` — raster
261 is the last *active* line.

```c
/* HuC6261 262-line mode: EVB=22, SVB=262.  DEVICE_EN/C6261, "Vertical timing".
 * Active picture = raster 22..261.  Vertical blanking = raster 262 and 0..21. */
#define PCFX_VBLANK_SVB 262u   /* start of vertical blank */
#define PCFX_VBLANK_EVB  22u   /* end of vertical blank   */

static inline int pcfx_raster_in_vblank(unsigned r)
{
    return (r >= PCFX_VBLANK_SVB) || (r < PCFX_VBLANK_EVB);
}

/* Always feed it the double-read stable raster (see §1), never a raw read. */
static inline int pcfx_in_vblank(void)
{
    return pcfx_raster_in_vblank(pcfx_tetsu_raster_stable());
}

/* Lines of blanking left — use this to decide if a burst FITS before EVB,
 * instead of starting one and hoping. Returns 0 when not in blanking. */
static inline unsigned pcfx_blank_lines_left(void)
{
    unsigned r = pcfx_tetsu_raster_stable();
    if (r >= PCFX_VBLANK_SVB) return (PCFX_VBLANK_SVB - r) + PCFX_VBLANK_EVB;
    if (r <  PCFX_VBLANK_EVB) return PCFX_VBLANK_EVB - r;
    return 0u;
}
```

**The blanking interval is 22 lines, so `pcfx_blank_lines_left()` never returns more
than 22.** Any gate of the form `if (lines_left >= N)` with `N > 22` is dead code that
silently disables the work forever — a real and easy mistake. Measure the cost of your
burst in lines and gate below 22, or just do the work right after `wait_frame()` where
you know all 22 are ahead of you. The measured 256-entry VCE palette upload comfortably fits.

### ⛔ ANTI-PATTERN: `spin_to(raster N)`

This shape appears in every port here before it was fixed, and it is always wrong:

```c
/* WRONG — do not write this, and delete it when you find it */
static void present_spin_to(unsigned raster) {
    unsigned spin = 0;
    while (pcfx_tetsu_raster_stable() < raster && spin++ < 200000u) { }
}
...
if (r < 208u || r > 258u) return;   /* "tear-safe window"  — it is active picture */
present_spin_to(240u);              /* "spin to vblank"    — 240 is active picture */
king_set_display_page(page);
```

Three independent things are broken:

- **It picks an active raster.** Any threshold in 22..261 is mid-picture by definition.
- **`<` never fires after the wrap.** Once the counter passes N the predicate is already
  false, so the "wait" returns instantly at a random raster; once it wraps to 0 it is
  false for the whole blanking interval — exactly when you wanted to act.
- **The bounded spin count silently gives up**, and the code proceeds anyway mid-frame.

**Replacement.** There is no "spin to a raster" primitive. To act in blanking you either

1. `wait_frame()` from §2 — returns on the wrap edge, i.e. at the *start* of blanking
   with the full 22 lines ahead of you. This is what a page flip / palette burst wants; or
2. poll `pcfx_in_vblank()` and act when it is true, if you must not block; or
3. use KING's raster IRQ compare (register `0x44`) for a mid-frame deadline.

```c
/* RIGHT */
static void pcfx_present_poll(void)
{
    if (!pcfx_in_vblank())
        return;                          /* not our window; try again next poll */

    if (g_pcfx_palette_pend && pcfx_blank_lines_left() >= PALETTE_BURST_LINES)
        pcfx_flush_palette();

    king_set_display_page(page);
    king_reassert_bg0();
    vdc_publish_weapon_sat();
}
```

Order the steps **shortest-deadline-first** and **re-read the raster between them** — a
long step can walk you out of blanking, and a raster sampled before it is stale.

### ⛔ ANTI-PATTERN: waiting on the VDC status VD bit

```c
/* WRONG — hangs forever unless something else keeps VDC CR bit 3 set */
static inline int vblank_active(void) {
    return (*(volatile uint16_t *)0x80000400u & 0x0020u) != 0;   /* VDC-A status, VD */
}
static void wait_vblank(void) { while (!vblank_active()) { } while (vblank_active()) { } }
```

`0x80000400` is VDC-A's status register (I/O port `0x400` through the
`0x80000000` memory-mapped I/O window). Its VD flag (bit 5) is raised only while that
VDC's **CR bit 3 (vblank interrupt enable, `0x08`)** is set — `vendor/pcfxemu`
`vdc_video.c`, `VDC_DoVBIRQTest()`: `if (CR & 0x08) status |= VDCS_VD`. There is no
HuC6270 manual in `DOCUMENTATION/`, so this is emulator-source evidence; the Tetsu
counter below is documented in C6261 and needs no VDC state at all. Reading the status
register also **clears** the flags, so a second reader (or an IRQ handler) steals the
edge.

Real incident (2026-09-22): a RAINBOW player ported from liberis to libpcfx replaced
`eris_low_sup_set_control(0,0,1,0)` — a read-modify-write that preserved CR's low
bits — with `vdc_setreg(0, VDC_REG_CR, VDC_CR_BB)`, which writes CR = `0x0080`
outright. VD never rose again, `wait_vblank()` never returned, and the screen stayed
black. The RAM dump showed the CD DMA state machine "stuck", which sent two agents
debugging SCSI: the state machine was fine, the loop that polls it was parked in
`wait_vblank()`.

Do **not** "fix" this by setting CR bit 3: that asserts a VDC interrupt every field
and now needs an interrupt mask/handler story. **Replace the wait:**

```c
static inline unsigned tetsu_raster_stable(void)       /* §1: read until two agree */
{
    unsigned a, b;
    do { a = tetsu_get_raster(); b = tetsu_get_raster(); } while (a != b);
    return a;
}
static inline int vblank_active(void)                  /* §3: 262 and 0..21 */
{
    unsigned r = tetsu_raster_stable();
    return r >= 262u || r < 22u;
}
static void wait_vblank(void)                          /* leading edge of blanking */
{
    while (vblank_active()) { }
    while (!vblank_active()) { }
}
```

`tetsu_get_raster()` returns the **decoded** line number, so compare with decoded
constants (262, 22), never with the raw `0x20A0`/`0x3FE0` of §2's assembly.

### Detecting "a new field began"

Same trap: `raster > SOME_THRESHOLD` is not a field boundary. Detect the **wrap** — the
raster going backwards — or latch off `pcfx_in_vblank()` going false:

```c
static unsigned s_last_raster;
static int new_field(void)
{
    unsigned r = pcfx_tetsu_raster_stable();
    int wrapped = (r < s_last_raster);
    s_last_raster = r;
    return wrapped;
}
```

This is how the RAINBOW per-field re-arm has to be gated; the threshold version re-armed
twice in one field and skipped others. See [pcfx-king-framebuffer].

## 4. fps is quantized to 60/N

Because the loop waits for a field, frame time can only be a multiple of ~16.7 ms:

| Fields | ms | fps |
|---|---|---|
| 1 | 16.7 | 60 |
| 2 | 33.3 | 30 |
| 3 | 50.0 | 20 |
| 4 | 66.7 | 15 |

**Cutting average work only helps when a frame class crosses a field boundary.** Shaving
2 ms off a 52 ms frame changes nothing; getting it under 50 ms turns 15 fps into 20.
Always look at the histogram of field counts, not just the mean. See
[pcfx-emulator-testing].

## 5. Use a timer IRQ for the game clock, not vblank counting

If you derive game time by counting vblank edges in the main loop, then **the moment a
frame takes longer than one field you start losing edges**, the clock runs slow, and the
game drags into slow motion. doom-pcfx hit exactly this.

Use the hardware interval timer (CPU clock / 15 = 1.4318 MHz) to fire an IRQ every ~1 ms
and increment a counter. An IRQ cannot be missed, so time stays real regardless of frame
rate. libpcfx: `timer_init`, `timer_set_period`, `timer_start`, `timer_ack_irq`
(`pcfx/timer.h`), with `irq_set_mask`/`irq_set_handler`/`irq_enable` from `pcfx/v810.h`.
`vendor/libpcfx/examples/030_hello_interrupt_1ms` is a working example.

**Keep the raster wait for the page flip** — a 1 ms timer cannot pinpoint blanking.
Use both: timer for *time*, raster for *presentation*.

## 6. Do these only in blanking

- palette writes (the measured 256-entry upload)
- KING mode / display-page changes
- the double-buffer page flip

Long KING or CD operations must not straddle a boundary you are relying on, and **never
carry a stale raster sample across one** — re-read it after.

If you need mid-frame work (e.g. re-arming a RAINBOW transfer), use KING's raster IRQ
compare (register `0x44`, `RASTER_COUNT`) rather than spinning.

## Sparse polling is not an FPS clock

Polling the raster counter only before or after long software-rendering stages does not
count every field. A renderer that returns once every ten fields may observe one wrap and
miss nine, making roughly 3 FPS appear as roughly 30 FPS. Do not compute FPS from such a
counter.

Use one of these instead:

1. emulator-profiler video-field count plus RAM `nframe` delta;
2. a real continuously maintained hardware timebase when handlers are allowed;
3. a build-stamped profiler average for a diagnostic HUD when timer/IRQ dependencies are
   explicitly forbidden.

Always display a decimal point for sub-10-FPS content (`FPS:3.1`), and document whether the
number is live or a profiled build value.

## Related

[pcfx-king-framebuffer] for the flip · [pcfx-yuv-palette] for palette timing ·
[pcfx-emulator-testing] for measuring fps.
