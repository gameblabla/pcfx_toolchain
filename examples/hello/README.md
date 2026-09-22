# Hello / bring-up

This is the copied `pcfx-bringup` template with paths made relative to this
repository. It clears and double-buffers a KING BG0 256x240 bitmap, writes a YUV
palette, reads the pad, and waits on the Tetsu raster.

```sh
../../scripts/build-host-tools.sh
make cd
```

The resulting `game.cue` needs an external BIOS to run under `pcfx-headless`:

```sh
PCFX_BIOS_DIR=/path/to/bios ../../scripts/run-headless.sh \
  --pcfx --frames 1800 --screenshot game.png game.cue
```

Read `PCFX_Skills/pcfx-bringup/SKILL.md` before modifying the initialization sequence.
