# Paired-VDC 256-colour animated sprite

This is the minimal C-side example for a Doom-style combined sprite. VDC0 supplies the
high colour nibble; VDC1 supplies the low nibble. Both chips receive matching SAT
geometry and timing, and VDC1 uses sprite palette-bank bit 3 to select the mixer. The
host packer reserves every low-nibble-zero index for transparency and quantizes the
strip to 240 opaque colors.

Arrows move the 24×34 actor. Its eleven poses advance every six fields against black.
Both VDCs are occupied by the one 256-colour sprite, as on the Doom PC-FX path.

```sh
make cd
make run
```

The mixer contract and upload layout follow `vendor/doompcfx/platform/pcfx_weapon.c`
and `vendor/doompcfx/tools/gen_pcfx_weapons.py`. The build emits VDC0/VDC1 pattern
planes separately under `build/`.
