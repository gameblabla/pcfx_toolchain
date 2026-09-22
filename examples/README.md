# Examples

- `hello/` — standard PC-FX CD bring-up using the verified KING BG0 bitmap template.
- `hello-huexe/` — the same program converted to `HuEXE001` for the PC-FXGA loader.
- `large-cd-assets/` — a boot image plus a generated 384 KiB external CD asset,
  linked with the streamed large-game `pcfx-cdlink` path.
- `../vendor/libpcfx/examples/` — the SDK's controller, VDC, sound, SCSI, KING,
  backup-memory, and interrupt examples. They are the hardware API ground truth.
- `../PCFX_Skills/pcfx-3d-pipeline/template/` — a verified software-3D cube template
  and host-side test harness.

The example Makefiles prefer `toolchain/v810-gcc` and `vendor/libpcfx`; export
`V810_GCC` (or legacy `V810GCC`) or `LIBPCFX` to point them elsewhere. Build products are disposable and
are ignored by Git.
