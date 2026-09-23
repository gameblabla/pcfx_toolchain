# PSG arcade music box

A small controller-driven SoundBox demo with an eight-note arcade melody and eight
visible piano bars. Left/right select notes, up/down change tempo, I toggles the melody,
and II toggles the noise voice. It initializes waveforms on the PSG channels and uses
the final channel for noise.

```sh
make cd
make run
```

The waveform and PSG setup follow `vendor/libpcfx/examples/psg/psg.c`; the sample uses
the shared `examples/game-demo-common/screen.h` KING 8bpp HUD.
