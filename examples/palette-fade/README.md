# Palette fade example

This small 256×240 KING BG0 program draws an indexed image **once** into KRAM,
then cycles a 32-step fade at one step per 60 Hz field. Each step updates only
16 precomputed HuC6261 Y8U4V4 palette entries during vertical blanking. It
never changes the image pixels in the transition loop. The palette table is
generated from RGB at build time by `tools/make_palette.py` using the toolkit's
`rgb_to_yuv.py` converter.

```sh
make -C examples/palette-fade cd
./scripts/run-headless.sh --bios-dir "$PCFX_BIOS_DIR" --pcfx \
  --frames 1800 --screenshot /tmp/palette-fade.png \
  examples/palette-fade/game.cue
```

`palette_steps_presented` counts completed palette updates and can be read
from a RAM dump and the fresh ELF. Over N emulator fields after boot, its
delta should equal N for 60 updates per second. The visible animation may
appear faster or slower to a viewer depending on the 32-step envelope, but
its presentation cadence is fixed at one update per field.

```sh
python3 PCFX_Skills/pcfx-palette-transitions/measure_presented.py \
  --headless toolchain/bin/pcfx-headless --bios-dir "$PCFX_BIOS_DIR" \
  --cue examples/palette-fade/game.cue --elf examples/palette-fade/game.elf \
  --nm toolchain/v810-gcc/bin/v810-nm --symbol palette_steps_presented \
  --start 1800 --window 60 --minimum 60
```

On 2026-09-24, the bundled headless emulator produced 888 updates at field
1800 and 948 at field 1860, using the fresh ELF/map symbol address `0x8bd8`:
**60 updates in 60 fields**. That establishes the emulator cadence; the PC-FX
video signal itself is 60 fields per second, so “60 fps+” means meeting every
field rather than displaying more than 60 distinct pictures per second.

The black frame and bitmap are initialized before BG0 is made visible. The
example keeps palette writes on the leading blanking edge because the HuC6261
manual says writes during active display cause visible noise; emulator output
alone cannot validate that hardware timing.
