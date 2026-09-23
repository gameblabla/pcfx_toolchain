# ADPCM coin pickup

A tiny game-style one-shot sample demo. The host creates a 0.42-second 8 kHz coin tone
with the local Doom PC-FX ADPCM encoder and appends it to the CD. At startup the sample
is loaded into page-1 KRAM. Press I to increment the coin counter and trigger channel 0.

```sh
make cd
make run
```

The KING ADPCM registers and one-shot configuration follow
`vendor/doompcfx/platform/i_sound_pcfx.c`; the sample encoding reuses
`vendor/doompcfx/tools/gen_pcfx_sfx.py`. The screen is a small KING BG0 8bpp game HUD.
