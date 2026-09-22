<reasoning>
The user is asking about a RAINBOW FMV player with glitched tiles along the right edge of the screen. They've provided their C encoder code and want me to explain:
1. What is wrong
2. Why it shows up on the right edge in particular
3. Why the emulator might not show it
4. How to fix the encoder
5. What to do with streams that were already encoded
6. How to verify the fix

Let me analyze the encoder code against the knowledge in the pcfx-rainbow skill.

Looking at the encoder code:

```c
static void bw_emit_byte(BitWriter *bw, uint8_t b) {
    vec_push(bw->out, b);
    bw->logical_bytes++;
    if (b == 0xff) vec_push(bw->out, 0x00); /* decoder consumes stuffed byte without counting it */
}
```

The comment says "decoder consumes stuffed byte without counting it" — this is the key bug. The encoder is tracking `logical_bytes` but NOT counting the stuffed `0x00` bytes in the size field.

From the pcfx-rainbow skill:
- `size` counts bytes **after** the 4-byte header: 128 table bytes on strip 0, entropy **as stored** (every entropy `FF` is stuffed as `FF 00` and **both bytes count**), zero alignment to a 16-bit boundary, and the 2-byte inner dummy.
- The **6-byte guard** (three `0000H` words) is outside the size.
- Every strip starts on a **word boundary** (even size).

So the bugs are:
1. **Size calculation is wrong**: `size = 2 + bw.logical_bytes + ((block_type == 0xff) ? 128 : 0)` — this uses `logical_bytes` which doesn't count the stuffed `0x00` bytes. The size should count the **stored** bytes (including stuffing), not the logical bytes.
2. **No word alignment**: The size should be aligned to a 16-bit boundary (even).
3. **No 2-byte inner dummy**: The spec says there should be a 2-byte inner dummy after the entropy data.
4. **No 6-byte guard**: After each strip, there should be a 
</reasoning>

This is a known RAINBOW encoder bug that has shipped in this workspace before. Your colleague's emulator is almost certainly stale. Here's the full diagnosis.

## What is wrong

Your encoder has **four framing bugs**, all in the size calculation and strip termination:

### 1. Size counts logical bytes, not stored bytes (the main bug)

```c
size_t size = 2 + bw.logical_bytes + ((block_type == 0xff) ? 128 : 0);
```

`bw.logical_bytes` does **not** include the stuffed `0x00` bytes. The RAINBOW decoder reads exactly `size` bytes from KRAM for each strip. When your stream contains `FF` entropy bytes (very common in high-frequency DCT coefficients — i.e., busy scenes), the stored stream is longer than `logical_bytes`, but you told the decoder a shorter size. The decoder runs out of its byte budget **before** it has decoded all 16 macroblock columns.

The last columns are on the right side of the screen, so they're the first to starve. That's why the corruption is on the right edge and worse in busy scenes.

### 2. No word alignment

The spec requires every strip's size to be even (word-aligned). Your size can be odd.

### 3. Missing 2-byte inner dummy

After the entropy data, there must be a 2-byte inner dummy (`00 00`). You don't write it.

### 4. Missing 6-byte guard

After each strip, there must be a 6-byte guard (three `0000H` words). KING may prefetch KRAM data past the strip boundary; the guard makes that harmless because the HuC6271 ignores `0000H`. You don't write it.

## Why the right edge specifically

A 256×240 frame is 16 macroblock columns wide. The decoder processes them left to right within each strip. When the byte budget runs short, the **last columns** (rightmost) never get their data. In quiet scenes there are fewer `FF` bytes so the shortfall is small; in busy scenes the shortfall grows and more columns are affected.

## Why the emulator might not show it

This workspace has a documented erratum: an older `pcfx-headless` binary charged a stuffed `FF 00` pair as **one byte** instead of two — exactly lenient enough to hide this bug. Your colleague's emulator is almost certainly that stale build. Check:

```bash
ls -l --time-style=+%F\ %T toolchain/bin/pcfx-headless
git -C vendor/pcfxemu log -1 --format='%ci %h %s'
```

If the binary is older than the last `vendor/pcfxemu` commit, rebuild it:

```bash
./scripts/build-headless.sh
```

Then re-test. The fixed emulator will show the right-edge corruption.

## How to fix the encoder

Replace the size calculation and strip termination with the correct framing:

```c
for (int strip = 0; strip < 15; ++strip) {
    uint8_t block_type = (strip == 0) ? 0xff : 0xf8;
    vec_push(&out, 0xff);
    vec_push(&out, block_type);
    size_t size_pos = out.len;
    vec_push(&out, 0x00);
    vec_push(&out, 0x00);

    size_t table_bytes = (block_type == 0xff) ? 128 : 0;
    if (block_type == 0xff) {
        vec_write(&out, q_y, 64);
        vec_write(&out, q_uv, 64);
    }

    Vec payload = {0};
    BitWriter bw = { &payload, 0, 0, 0 };
    for (int col = 0; col < 16; ++col) {
        /* 4 Y blocks, 1 U, 1 V: FDCT, quantize, Huffman */
        ...
    }
    bw_flush(&bw);

    /* Size = tables + stored entropy (including stuffing) + alignment + 2-byte dummy */
    size_t stored_entropy = payload.len;  /* actual bytes written, stuffing included */
    size_t align = (stored_entropy & 1) ? 1 : 0;
    size_t size = table_bytes + stored_entropy + align + 2;

    out.p[size_pos + 0] = (uint8_t)(size >> 8);
    out.p[size_pos + 1] = (uint8_t)(size & 0xff);

    vec_write(&out, payload.p, payload.len);
    if (align) vec_push(&out, 0x00);   /* word-align */
    vec_push(&out, 0x00);              /* 2-byte inner dummy */
    vec_push(&out, 0x00);
    vec_push(&out, 0x00);              /* 6-byte guard (three 0000H words) */
    vec_push(&out, 0x00);
    vec_push(&out, 0x00);
}
```

Key changes:
- `size` uses `payload.len` (stored bytes, stuffing included), not `bw.logical_bytes`
- Size includes alignment padding and the 2-byte inner dummy
- 6-byte guard written after each strip
- Every strip starts on a word boundary

## What to do with already-encoded streams

You have two options:

**Option A: Re-encode** (preferred for new work)
```bash
python3 tools/rainbow/rainbow.py video clip.mkv clip.pcfv --fps 15 --audio mp2
```

**Option B: Repair in place** (preserves entropy bits, no re-encode needed)
```bash
python3 tools/rainbow/rainbow.py repair-legacy old.pcfv fixed.pcfv
```

This rewrites the framing (size fields, alignment, dummies, guards) while keeping the original entropy data. It's fast and lossless.

## How to verify the fix

Follow the verification ladder in order:

1. **Encoder tests pass:**
   ```bash
   python3 tools/rainbow/test_rainbow.py
   ```

2. **Stream passes strict inspection:**
   ```bash
   python3 tools/rainbow/rainbow.py inspect clip.pcfv --frame 0 --preview build/f0.png
   ```
   This checks framing and fully decodes all 16 columns of every strip. If the right-edge columns decode correctly here, the stream is good.

3. **Fresh emulator:**
   ```bash
   ./scripts/build-headless.sh
   ```

4. **Template validation:**
   ```bash
   PCFX_BIOS_DIR=... make validate VIDEO_IN=movie.mkv
   ```

5. **Real hardware** — the emulator cannot prove bus timing, IRQ-in-KING-pair races, or sub-cycle re-arm edges. A clean emulator run is necessary but not sufficient.

## The compression issue

Your black-frame compression problem is separate but related. You're using JPEG-style quality-scaled tables directly. The correct approach (used by MPCONV and `tools/rainbow`) is:

- Use the **MPCONV base tables** unchanged
- Use **DC-Y rescale controls** (`0x10..0x1F` symbols) to scale quality per macroblock
- Use **DC-Y `0x0F` null-run escape** for black/neutral macroblocks (fills with the programmed null colour, no coefficient data)

With null runs, a black frame becomes tiny. Without them, every black macroblock still emits its full coefficient stream. The `tools/rainbow` encoder handles all of this automatically — use it instead of hand-rolling.