# Hello HuEXE / PC-FXGA path

This uses the same verified BG0 program as `examples/hello`, then converts its
V810 ELF load segments to the `HuEXE001` container accepted by the imported
`pcfxemu` branch:

```sh
make huexe
```

Run with a compatible external BIOS:

```sh
PCFX_BIOS_DIR=/path/to/pcfxga-bios make run
```

The HuEXE path avoids the normal PC-FX CD boot header and is useful for uploader or
PC-FXGA-style workflows. It does not embed or replace the BIOS.
