# Task: RAINBOW FMV has glitched tiles along the right edge

Our PC-FX FMV player streams RAINBOW (HuC6271) frames from CD into KRAM and re-arms
the decoder every field. Most of the picture is fine, but blocks along the right side
of the screen are corrupted: coloured garbage in the last 16-pixel column, worse in
busy scenes. A colleague said it looked fine in their copy of the emulator, so they
think it is a hardware quirk we have to live with. Compression also seems poor: a
completely black frame is not much smaller than a normal one.

This is how our C encoder writes each 16-line strip of a 256x240 frame:

```c
static void bw_emit_byte(BitWriter *bw, uint8_t b) {
    vec_push(bw->out, b);
    bw->logical_bytes++;
    if (b == 0xff) vec_push(bw->out, 0x00); /* decoder consumes stuffed byte without counting it */
}

for (int strip = 0; strip < 15; ++strip) {
    uint8_t block_type = (strip == 0) ? 0xff : 0xf8;
    vec_push(&out, 0xff);
    vec_push(&out, block_type);
    size_t size_pos = out.len;
    vec_push(&out, 0x00);
    vec_push(&out, 0x00);
    if (block_type == 0xff) {             /* JPEG-style tables scaled by --quality */
        vec_write(&out, q_y, 64);
        vec_write(&out, q_uv, 64);
    }
    Vec payload = {0};
    BitWriter bw = { &payload, 0, 0, 0 };
    for (int col = 0; col < 16; ++col) {
        /* 4 Y blocks, 1 U, 1 V: float FDCT, quantize, Huffman */
        ...
    }
    bw_flush(&bw);                         /* pads the last byte with 1 bits */
    size_t size = 2 + bw.logical_bytes + ((block_type == 0xff) ? 128 : 0);
    out.p[size_pos + 0] = (uint8_t)(size >> 8);
    out.p[size_pos + 1] = (uint8_t)(size & 0xff);
    vec_write(&out, payload.p, payload.len);
}
```

Explain what is wrong, why it shows up on the right edge in particular, why the
emulator might not show it, how to fix the encoder (and what to do with streams that
were already encoded), and how to verify the fix.
