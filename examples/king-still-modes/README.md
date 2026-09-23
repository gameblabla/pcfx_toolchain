# KING BG0 still-image modes

Build the same 256×240 reference image in any of four KING formats. Each selected mode
is packed on the host, appended to the CD, loaded in sector-sized pieces, then written
to KRAM before BG0 appears.

| Mode | KING setting | Packed pixels | CG bank / microprogram slots | Rotation |
|---|---|---|---|---|
| `4bpp` | `KING_BGMODE_16_PAL` | 16 palette indices | A / 0–1, direct CG0–1 | Off |
| `8bpp` | `KING_BGMODE_256_PAL` | 256 palette indices | A / 0–7, rotation CG0 | On |
| `hicolor` | `KING_BGMODE_64K` | direct Y8U4V4 | B / 8–15, direct CG0–7 | Off |
| `16m` | `KING_BGMODE_16M` | YUV 4:2:2, shared U/V per horizontal pair | B / 8–15, direct CG0–7 | Off |

Choose one mode per build:

```sh
make MODE=4bpp run
make MODE=8bpp run
make MODE=hicolor run
make MODE=16m run
```

Screenshots are written to `build/<mode>/king_still_<mode>.png`. The source is
`../image-cd-viewer/assets/source.png`, fit to 256×240 on the host. Indexed modes reserve
index 0 and use the local Y8U4V4 converter. Hicolor uses the same tested Y8U4V4 palette
conversion per pixel. The original C6272_3 diagram shows each 16M pair as two Y values
followed by shared U and V. The packer uses the word and byte order implemented by
`pcfxemu`; retail hardware output has not been measured.

The 8bpp setup comes from `PCFX_Skills/pcfx-bringup/template/src/main.c` and
`PCFX_Skills/pcfx-2d-picture/SKILL.md`. Direct-colour fetch schedules match the
original KING diagrams and still require real-console confirmation.

All four modes render the CD-loaded image in the local headless emulator. The 4bpp,
64K, and 16M modes use normal direct-CG fetches with REG.12's rotation switch clear;
the 8bpp mode uses rotation fetches and identity coefficients. The original C6272
manual gives separate microprogram schedules for these paths and does not list 16M
as a rotation mode. Direct-colour output still needs confirmation on retail hardware.

The source of these schedules is the original Japanese `C6272_2.WRI` microprogram
bit-field and example diagrams, and `C6272_3.WRI` for the supported color and rotation
combinations. The Japanese figures are also preserved under
`DOCUMENTATION/ENGLISH_TRANSLATION/C6272_2/assets/` and `C6272_3/assets/`.
