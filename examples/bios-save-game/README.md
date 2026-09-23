# BIOS-backed save game

Move the ship with the arrows to catch falling stars. I saves the score to
`/SRAM/STAR.SAV` through libpcfx's BIOS filesystem; II loads it. The save record has a
magic value and checksum. The demo does not format backup memory, so the BIOS device
must already be available and formatted by its normal setup flow.

```sh
make cd
make run
```

This follows `vendor/doompcfx/platform/pcfx_save.c` and
`vendor/libpcfx/include/pcfx/filesys.h`, including a persistent 8 KiB BIOS dispatcher
heap and a fresh `filesys_init()` before each operation.
