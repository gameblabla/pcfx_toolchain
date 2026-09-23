# Examples

- `vdc-animated-16color/` — move and animate the supplied 24×34 Yuri sprite strip as
  16-colour VDC hardware sprites on black.
- `vdc-animated-256color/` — minimal Doom-style paired-VDC 256-colour sprite animation.
- `vdc-scroll-map/` — VDC BXR ring scrolling of the `map_test/` side-scrolling map;
  autoplay pauses for manual movement and RUN resumes it.
- `king-still-modes/` — CD-loaded KING BG0 stills in 4bpp, 8bpp, 64K Y8U4V4 hicolor,
  or 16M YUV422 (`make MODE=... run`; all four render in the headless emulator).
- `image-cd-viewer/` — the supplied 3840×2160 image, fitted with letterboxing,
  encoded as a RAINBOW still, and loaded from an appended CD asset.
- `adpcm-sample-game/` — CD-loaded one-shot KING ADPCM coin pickup.
- `adpcm-stream-game/` — CD-streamed KING ADPCM tune with alternating half-buffer refills.
- `psg-game/` — controller-driven SoundBox PSG melody, waveform and noise demo.
- `bios-save-game/` — star-catching mini-game with BIOS `/SRAM` score save/load.
- `game-demo-common/` — shared 8bpp HUD and frame-wait helpers for the small game demos.
- `hello/` — standard PC-FX CD bring-up using the verified KING BG0 bitmap template.
- `hello-huexe/` — the same program converted to `HuEXE001` for the PC-FXGA loader.
- `large-cd-assets/` — a boot image plus a generated 384 KiB external CD asset,
  linked with the streamed large-game `pcfx-cdlink` path.
- `rainbow-still/` — a RAINBOW (HuC6271) still image from any 256x240 PNG, DMA'd
  from CD into KRAM, re-armed per field, with endless horizontal pan; `make validate`
  gates it in the emulator. For RAINBOW video see `../vendor/pcfx_rainbow_mp2_adpcm/`.
- `../vendor/libpcfx/examples/` — the SDK's controller, VDC, sound, SCSI, KING,
  backup-memory, and interrupt examples. They are the hardware API ground truth.
- `../PCFX_Skills/pcfx-3d-pipeline/template/` — a verified software-3D cube template
  and host-side test harness.

The example Makefiles prefer `toolchain/v810-gcc` and `vendor/libpcfx`; export
`V810_GCC` (or legacy `V810GCC`) or `LIBPCFX` to point them elsewhere. Build products are disposable and
are ignored by Git.
