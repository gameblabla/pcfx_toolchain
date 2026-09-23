# VDC hardware-scrolled map

This uses `map_test/scene1_section_1_map.png`, a 514×24 grid of 8×8 cells, and its
16×8 metatile atlas as the source art. The packer deduplicates the preview into 96
HuC6270 tiles and assigns one 16-colour VDC palette group.

With no input the map scrolls right by one pixel per field and wraps at the source
width. Any pad input stops autoplay; left or right pans manually. RUN resumes autoplay. The map
uses a 128×32 VDC BAT as a ring: only the newly exposed column is rewritten. This is
VDC BXR scrolling; KING is disabled.

```sh
make cd
make run
```

The tile, BAT and scroll setup follows `vendor/libpcfx/examples/020_vdc_simple_background/`
and `PCFX_Skills/pcfx-vdc-tiles-sprites/SKILL.md`. The full source map and generated
tile data remain host-side / build-time assets.
