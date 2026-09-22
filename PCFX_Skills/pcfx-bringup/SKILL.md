---
name: pcfx-bringup
description: Create a new PC-FX homebrew project from zero, or fix boot/link/CD-image failures. Covers the toolchain, the linker script, crt0, the exact bincat + pcfx-cdlink disc build, and a verified-working 256x240 8bpp template that boots, draws and reads the pad. Use this FIRST for any new project, and whenever a program fails to boot, shows only the BIOS logo, hangs at a black screen, or the CD image is malformed.
---

# Bring-up: from empty directory to a booting PC-FX disc

**Never start from a blank file.** Copy the verified template in this skill, build it,
see it on screen, and only then change it. Bring-up has many independent ways to fail
silently (no affine coefficients, no microprogram, wrong palette, wrong disc layout) and
debugging all of them at once from a blank page does not work.

## 1. Copy the template

```bash
cp -r "$PCFX_SKILLS/pcfx-bringup/template" mygame
cd mygame
export V810_GCC="${V810_GCC:-${V810GCC:-$PCFX_TOOLKIT_ROOT/toolchain/v810-gcc}}"
export V810GCC="${V810GCC:-$V810_GCC}"  # compatibility alias
export PATH=$V810_GCC/bin:$PATH
make LIBPCFX="$LIBPCFX" cd          # -> game.cue + game.bin
make run                             # build + screenshot in the emulator
```

The template (`template/src/main.c`) is a **confirmed-working** 256×240 8bpp double-buffered
bitmap: it clears the screen, draws a moving box, reads the pad, and paces on the Tetsu
raster. It is the shortest correct path to pixels on this machine.

## 2. What the build actually does

```
main.c  --v810-gcc-->  main.o
        --v810-ld  -->  game.elf     (linker script + crt0 + libs)
        --objcopy  -->  game.bin     (raw image)
        --bincat   -->  out.bin + lbas.h
        --pcfx-cdlink--> game.cue + game.bin   (bootable disc)
```

| Piece | Value | Why |
|---|---|---|
| Compiler | `v810-gcc` (**GCC 4.9.4**) | old; no C11, no `-flto` worth using |
| CFLAGS | `-O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function` | `-msda=256` = gp-relative small globals; `-mno-prolog-function` avoids `__save_rXX` call trampolines |
| Linker script | `vendor/libpcfx/ldscripts/v810.x` | defines RAM layout, `__gp`, stack |
| Startup | `$(V810_GCC)/v810/lib/crt0.o` | **must be first object**; sets up gp/sp and calls `main` |
| Libraries | `-lpcfx -lc -lsim -lgcc` | in this order |
| Disc tools | `bincat`, `pcfx-cdlink` | bundled in `toolchain/bin/` (also available in `$(V810_GCC)/bin`) |

`bincat` concatenates your `.bin` (plus any extra asset files) into `out.bin` and writes
`lbas.h`, a header giving each file's **disc LBA** — that is how runtime code finds assets
on the disc. `pcfx-cdlink` reads `cdlink.txt` and wraps `out.bin` in a bootable disc.

`cdlink.txt` is a plain key/value file:

```
binary ./out.bin
name PCFX Template          # title shown by the BIOS
maker homebrew
makerid TFX
date 20260806
country 1
version 256
```

On success `pcfx-cdlink` prints `Code+data Size:` and `Stack+heap Free Space:`. That free
space is your remaining RAM out of 2 MB — watch it, code and heap share the same 2 MB.

## 3. The mandatory KING BG0 init sequence

A bitmap will show **nothing at all** unless every one of these is done. This is the
single most common bring-up failure. Order matters.

```c
king_init();
tetsu_init();
king_set_kram_pages(0, 0, 0, 0);              /* scsi, bg, rainbow, adpcm */
king_set_bg_mode(KING_BGMODE_256_PAL, 0, 0, 0);
king_set_bg_size(KING_BG0, KING_BGSIZE_256, KING_BGSIZE_256,
                 KING_BGSIZE_256, KING_BGSIZE_256);   /* (h, w, subh, subw) */
king_set_bat_cg_addr(KING_BG0, 0, PAGE_BASE >> 10); /* CG address is in 1024-word units */
king_set_bat_cg_addr(KING_BG0SUB, 0, PAGE_BASE >> 10);
king_set_scroll(KING_BG0, 0, 0);

/* 8 ROTATE microprogram slots then NOPs -- without this BG0 shows garbage. */
for (i = 0; i < 8;  i++) microprogram[i] = KING_CODE_ROTATE;
for (;     i < 16; i++) microprogram[i] = KING_CODE_NOP;
king_disable_microprogram();
king_write_microprogram(microprogram, 0, 16);
king_enable_microprogram();

king_set_bg_prio(KING_BGPRIO_0, KING_BGPRIO_HIDE,
                 KING_BGPRIO_HIDE, KING_BGPRIO_HIDE, 1);

/* Affine coefficients 0x38..0x3d, 8.8 fixed. libpcfx has NO helper for these;
 * write them raw. A=D=0x100 is 1:1. Omitting them = blank screen. */
king_reg16(0x38, 0x0100); king_reg16(0x39, 0x0000);
king_reg16(0x3a, 0x0000); king_reg16(0x3b, 0x0100);
king_reg16(0x3c, 0x0000); king_reg16(0x3d, 0x0000);

tetsu_set_king_palette(0, 0, 0, 0);
tetsu_set_video_mode(TETSU_LINES_262, 0, TETSU_DOTCLOCK_5MHz,
                     TETSU_COLORS_256, TETSU_COLORS_16,
                     0, 0, 1 /*bg0 on*/, 0, 0, 0, 0);
```

`king_reg16` is three lines of inline asm (in the template) because KING is I/O, not memory:

```c
static void king_reg16(u16 reg, u16 value) {
    __asm__ volatile ("out.h %[reg], 0x600[r0]\n"
                      "out.h %[value], 0x604[r0]\n"
                      : : [reg] "r" (reg), [value] "r" (value));
}
```

For KRAM drawing, copy the template's `kram_set_write_inline()`,
`kram_begin_burst()`, and `kram_write_latched()` helpers. They set KRAM_AWR once,
latch KRAM_DATA once, and stream `out.h` stores with KING auto-increment. Do not put
`king_set_kram_write()` or `king_kram_write()` in a hot per-word loop; retain those
libpcfx calls only for cold/simple paths or a `HOST_TEST` fallback. The template also
keeps the background static and erases the previous square on each hidden page, rather
than clearing all 30720 words every frame.

**On real hardware** also call `king_set_kram_mode()` for 4-Mbit mode before any other
KRAM access — doom-pcfx found addressing defects without it (`Program KRAM into 4-Mbit
mode; drop the phantom "A16 hole"`). The emulator is more forgiving than silicon here.

## 4. Boot failure decision tree

| Symptom | Cause |
|---|---|
| Screenshot shows the **PC-FX logo** | You screenshotted too early. BIOS boot is ~1200 frames — use `--frames 1800`. **Not a bug.** |
| Black screen forever | Missing affine coefficients, missing microprogram, or `bg0_disp=0` in `tetsu_set_video_mode`. |
| Garbage / noise on screen | Microprogram not written or not enabled; or BAT/CG address points at unwritten KRAM. |
| Right colours, wrong hues | Palette guessed by hand. Use `pcfx-yuv-palette`'s converter. |
| Boots then hangs | Often a big `static`/`.bss` array placed across the `__gp` window, corrupting libc. Put big buffers on the heap. |
| `pcfx-cdlink` errors / disc won't load | `cdlink.txt` `binary` path wrong, or `bincat` not re-run after rebuilding `.bin`. |
| Link error `undefined reference to main` | `crt0.o` missing or not first in the link line. |

## 5. Rules

- **Get a solid colour on screen before writing any game logic.** Verify with a screenshot.
- **One change, then a screenshot.** Bring-up bugs do not compose.
- Don't invent KING register numbers. The map is in `[pcfx-king-framebuffer]` and
  `vendor/doompcfx/platform/` and `vendor/libpcfx/docs/`; chip manuals are in
  `DOCUMENTATION/`.
- `vendor/libpcfx/examples/` is the ground truth for correct sequences — `030_king_bg0_512x256_8bpp`
  for a bitmap, `020_vdc_simple_background` / `021_vdc_simple_sprite` for tiles and sprites.

## Related

[pcfx-emulator-testing] to run it · [pcfx-king-framebuffer] to draw · [pcfx-yuv-palette]
for colour · [pcfx-frame-timing] for pacing · [pcfx-cd-assets] for loading data.
