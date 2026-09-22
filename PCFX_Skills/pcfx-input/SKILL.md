---
name: pcfx-input
description: Reading the PC-FX FX-Pad and mouse - contrlr API, button bit masks, the two-step scan, edge detection, multitap and pad type, and scripting input in the headless emulator. Use when a button does the wrong thing, input is dropped, or you need to drive gameplay for a repro or benchmark.
---

# Input: the FX-Pad

## 1. Reading a pad

```c
#include <pcfx/contrlr.h>

contrlr_pad_init(0);              /* once, at startup; ports are 0 and 1 */

for (;;) {
    u32 pad = contrlr_pad_read(0);
    if (pad & JOY_LEFT) { ... }
}
```

`contrlr_pad_read()` does the whole scan (trigger, wait, read). The scan takes ~100 µs,
roughly 1.5 scanlines, and `contrlr_pad_read` **blocks** for it.

If you want that time back, do the scan in two halves and get on with other work between:

```c
contrlr_port_write_control(0, CONTRLR_CTRL_XFER |
                              CONTRLR_CTRL_RESETMULTI |
                              CONTRLR_CTRL_READDATA);
/* ... ~100us of useful work here ... */
while (contrlr_port_read_status(0) & CONTRLR_CTRL_XFER) { }
u32 pad = contrlr_port_read_data(0);
```

**Read the pad once per frame and cache it.** Every extra read costs another scan.

## 2. Button bits

| Bit | Constant | Physical button |
|---|---|---|
| `0x0001` | `JOY_I` | I |
| `0x0002` | `JOY_II` | II |
| `0x0004` | `JOY_III` | III |
| `0x0008` | `JOY_IV` | IV |
| `0x0010` | `JOY_V` | V |
| `0x0020` | `JOY_VI` | VI |
| `0x0040` | `JOY_SELECT` | SELECT |
| `0x0080` | `JOY_RUN` | RUN (= START) |
| `0x0100` | `JOY_UP` | ↑ |
| `0x0200` | `JOY_RIGHT` | → |
| `0x0400` | `JOY_DOWN` | ↓ |
| `0x0800` | `JOY_LEFT` | ← |
| `0x1000` / `0x4000` | `JOY_MODE1` / `JOY_MODE2` | the two mode switches |

Mouse: `MOUSE_LEFT` (`0x10000`), `MOUSE_RIGHT` (`0x20000`), with
`contrlr_mouse_x()` / `contrlr_mouse_y()` extracting 8-bit relative deltas.

Note the FX-Pad has **six face buttons** (I–VI) plus RUN and SELECT — do not assume an
A/B/START layout. In the supplied headless emulator mapping, `A B C X Y Z` correspond to
buttons `I II III IV V VI`. Verify the mapping in the emulator header before scripting a
new fork.

A renderer that takes many video fields per frame may miss a short scripted pulse because
pad polling occurs only when the main loop returns. Hold level-triggered test inputs for
longer than one worst-case render interval. For example, test Button V with `Y` held for
120 fields rather than a 10-field tap. This is an input-validation issue, not proof that
the hardware button failed.

## 3. Pad type and multitap

```c
contrlr_pad_type(0)       /* CONTRLR_TYPE_FXPAD / _MOUSE / _MULTITAP / _NONE */
contrlr_pad_connected(0)
```

Type lives in the top nibble of the pad word. Check it before interpreting the low bits —
a mouse and a pad have completely different meanings for the same bits. Set
`CONTRLR_CTRL_RESETMULTI` on the **first** controller of a multitap set.

## 4. Edge detection

Hardware gives you level, not edges. Menus need edges, or one press moves the cursor
every frame:

```c
static u32 prev;
u32 now     = contrlr_pad_read(0);
u32 pressed = now & ~prev;      /* rising edge this frame */
prev = now;
```

wolf-pcfx shipped `Wait for button release before exiting options menu` as a bug fix —
this is exactly that class of bug. Also beware the **first frame**: `prev` starts at 0, so
anything held at boot reads as a press. doom-pcfx suppresses input for the first few tics
for this reason.

## 5. Driving input in the emulator

```
# commands.txt — absolute frame numbers, past the ~1200-frame BIOS boot
1300 START
1320 NONE
1400 +RIGHT
1500 -RIGHT
```

```bash
"$PCFXEMU" --bios-dir "$PCFX_BIOS_DIR" --pcfx --frames 2400 \
    --commands commands.txt --screenshot shot.png game.cue
```

For **benchmarks, do not use scripted input at all** — use a compile-time scripted route
driven by the game tic, so the sequence is identical regardless of frame rate. doom-pcfx's
`-DDEV_BENCH_AUTOMOVE` does this. Input tied to *frames* changes behaviour when the frame
rate changes, which silently invalidates A/B comparisons. See [pcfx-emulator-testing].

## 6. Real-hardware note

doom-pcfx found mouse sensitivity differed on real hardware and needed a double-poll plus
tic-share smoothing (`mouse: fix real-hardware sensitivity with double-poll`). Input timing
is one of the areas where the emulator is not authoritative.

## Related

[pcfx-emulator-testing] · [pcfx-frame-timing]. Example: `vendor/libpcfx/examples/011_controller`.
