# PC-FX CD image viewer

This project starts from `examples/rainbow-still/` and displays the supplied
`assets/source.png` through the HuC6271 RAINBOW decoder. The encoded image is
appended to the CD, then loaded from its generated LBA into KRAM during startup.
The program keeps the image still after the first complete decode.

The source is 3840×2160 (16:9). `tools/prepare_image.py` fits it inside the
PC-FX's 4:3 display frame with black letterboxing, preserving the full scene and
avoiding distortion. Use `FIT=crop` to fill the frame by trimming the left and
right edges, or `FIT=stretch` to fill it without bars.

```sh
make cd                                      # encode and build the bootable disc
make cd IMAGE=/path/to/other.png FIT=contain # substitute another image
PCFX_BIOS_DIR=/path/to/bios make run         # save build/image_cd_viewer.png
PCFX_BIOS_DIR=/path/to/bios make validate    # compare two static emulator captures
```

The stream is limited to 16 KiB because `eris_cd_read_kram` is hardware-confirmed
for one 16 KiB arm at KRAM word `0x08000`; larger arms or regions are unmeasured.
The LBA comes from `pcfx-cdlink-large`'s appended-asset header. Runtime setup,
page routing, per-field re-arm, raster sampling, and interrupt-atomic KING writes
follow `PCFX_Skills/pcfx-rainbow` and the validated still-image example.

`make validate` compares emulator output against the host-decoded preview of the
exact encoded stream, checking the image, static position, and strip decode.
It is emulator evidence only; it does not prove retail-hardware behavior.
