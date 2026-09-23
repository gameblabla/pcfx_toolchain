# CD-streamed ADPCM music

This builds a 40-second procedural 8 kHz mono tune, longer than the 32 KiB ring used
here, appends it to the CD, and plays it continuously through KING channel 0. The
player primes two 16 KiB halves, polls KING status, and refills whichever half has
finished. I mutes or unmutes playback while CD refills continue.

```sh
make cd
make run
```

The refill status bits and ring-register setup follow
`pcfx_rainbow_mp2_startup_sync_package/src/pcfx_pcfv_player.c`; encoding uses the local
Doom ADPCM encoder. The loader uses `eris_cd_read_kram` in 16 KiB chunks. Local
real-hardware measurements confirm that transfer shape at KRAM word `0x08000`; the
second-half and later ring destination addresses used for repeated streaming refills
have not been confirmed on retail hardware. An emulator run cannot settle that gap.
