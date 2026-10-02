# VDC world has horizontal bands

A PC-FX port displays a 32x12 map of 16x16 metatiles on a VDC 64x32 BAT.
Each metatile uses four consecutive 8x8 pattern cells. The pattern upload
matches every source word (7,808/7,808), and all 16 active palette entries
match the native RGB-to-YUV conversion, but gameplay has horizontal bands and
misplaced scenery. The RAM BAT shadow is filled with this code:

```c
for (row = 0; row < 12; ++row)
  for (col = 0; col < 32; ++col)
    for (y = 0; y < 2; ++y)
      for (x = 0; x < 2; ++x)
        shadow[(row * 2 + y) * 64 + col * 2 + x] =
            base_tile + y * 2 + x;
```

The current flush is:

```c
for (col = 0; col < 32; ++col) {
  if (!dirty[col]) continue;
  for (row = 0; row < 24; ++row) {
    unsigned left = row * 64 + col * 2;
    vdc_set_vram_write(0, left);
    vdc_vram_write(0, shadow[left]);
    vdc_vram_write(0, shadow[left + 1]);
    vdc_set_vram_write(0, row * 64 + col * 2 + 32);
    vdc_vram_write(0, shadow[left + 64]);
    vdc_vram_write(0, shadow[left + 65]);
  }
  dirty[col] = 0;
}
```

Identify the defect, give a corrected flush loop, and describe a concrete
emulator-state check that would have failed on this code. Do not edit files.
