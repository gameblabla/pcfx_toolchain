# VDC 16-colour animated sprite

This small VDC game moves the supplied Yuri sprite on a black field. The RGBA strip is
24×374: the host packer quantizes its eleven 24×34 poses to fifteen opaque colors plus
transparent index 0, then lays each pose out as six 16×16 HuC6270 sprite cells.

Use the FX-Pad arrows to move. The pose advances every six fields. It uses VDC0's own
16-colour sprite path and leaves KING disabled.

```sh
make cd
make run
```

Patterns are converted by `tools/pack_sprite.py`; the VDC cell and SAT setup follows
`vendor/libpcfx/examples/021_vdc_simple_sprite/` and
`PCFX_Skills/pcfx-vdc-tiles-sprites/SKILL.md`. Build output and screenshots are under
`build/`.
