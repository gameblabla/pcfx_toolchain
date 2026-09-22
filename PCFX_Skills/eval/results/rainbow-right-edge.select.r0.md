<reasoning>
The user is describing a classic PC-FX RAINBOW encoder bug. Let me analyze the code they provided against the knowledge in the pcfx-rainbow skill.

Looking at the encoder code, I can identify several issues:

1. **Size field counts unstuffed bytes**: The code does `size = 2 + bw.logical_bytes + ((block_type == 0xff) ? 128 : 0)` where `bw.logical_bytes` is incremented for every byte written, but the stuffing byte (the `0x00` after each `0xff`) is NOT counted in `logical_bytes`. However, the size field in the RAINBOW stream format must count the **stuffed** bytes (as stored), not the logical bytes. The skill says: "size counts bytes after the 4-byte header: 128 table bytes on strip 0, entropy as stored (every entropy FF is stuffed as FF 00 and both bytes count), zero alignment to a 16-bit boundary, and the 2-byte inner dummy."

   So the size should be: `size = tables + stuffed_entropy + alignment + 2` where stuffed_entropy is the actual byte count including stuffing.

2. **No word alignment**: The size must be even (word-aligned). The code doesn't ensure this.

3. **No inner dummy bytes**: The code doesn't add the 2-byte inner dummy after the entropy data.

4. **No guard bytes**: The code doesn't add the 6-byte guard (three 0x0000 words) after each block.

5. **JPEG-style quality-scaled tables**: The code transmits JPEG-style tables scaled by quality, but RAINBOW uses MPCONV base tables with rescale control symbols (0x10..0x1F) instead.

6. **No null runs**: Black frames should use DC-Y symbol 0x0F (null-run escape) to fill macroblocks with the null colour, making black frames nearly free. The code doesn't do this.

7. **Float FDCT**: The code uses float FDCT, but RAINBOW's IDCT has 4x gain and expects MPCONV integer FDCT with specific asymmetry.

Let me focus on the main issue causing the right-edge glitch:

The size field undercounts because it doesn't include stuffing bytes. This means the decoder reads fewer bytes than actually
</reasoning>

This is a known class of RAINBOW encoder bugs. Your colleague's emulator copy is likely not strict about block framing, or is a different build. The right-edge corruption is deterministic, not a hardware quirk.

## What's wrong

Your encoder has multiple framing errors that compound:

**1. Size field counts unstuffed bytes (the primary bug)**

```c
size_t size = 2 + bw.logical_bytes + ((block_type == 0xff) ? 128 : 0);
```

`bw.logical_bytes` counts only the original bytes, not the stuffing. Every `0xFF` in the entropy stream becomes `0xFF 0x00` on the wire, but your size field only accounts for the `0xFF`. The decoder reads `size` bytes starting after the header, so it stops **short** of the actual block end. The next block's header (`0xFF 0xF8`) gets consumed as entropy data, desynchronizing the decoder from that point on.

The size field must count **stuffed bytes as stored**:

```c
// Correct: count actual bytes written including stuffing
size_t size = payload.len + ((block_type == 0xff) ? 128 : 0);
```

**2. No word alignment**

Every strip must start on a word boundary (even size). Your size can be odd, putting the next block's first KRAM fetch on the wrong half-word. This is why the corruption appears on the **right edge**: the last macroblock column of each strip is the last to be decoded, so it's the first to hit the misaligned boundary.

**3. Missing inner dummy and guard bytes**

The stream format requires after each block's entropy:
- 2-byte inner dummy (part of `size`)
- 6-byte guard (three `0x0000` words, outside `size`)

Your encoder writes neither. Without the guard, prefetched KRAM data from the next block leaks into the current decode window.

**4. JPEG-style quality-scaled tables**

RAINBOW transmits MPCONV **base** tables unchanged and uses DC-Y symbols `0x10..0x1F` as rescale controls. Your encoder scales the tables by quality, which the decoder doesn't expect.

**5. No null-run encoding for black**

DC-Y symbol `0x0F` is the null-run escape: it fills macroblocks with the programmed null colour (black). A black frame should be nearly free. Your encoder processes every macroblock normally, which is why black frames aren't small.

**6. Float FDCT**

RAINBOW's IDCT has 4× gain and expects MPCONV integer FDCT with `0x15F2` first-pass asymmetry. Float FDCT produces washed/clipped output.

## Why the emulator might not show it

The emulator's RAINBOW decoder may be lenient about block boundaries, or may not model KRAM prefetch behavior. The pcfx-rainbow skill notes that the emulator's cycle model and some KING/CD behaviors are approximations. A strict framing check (`tools/rainbow/rainbow.py inspect`) will catch these issues even if the emulator renders "mostly fine."

## How to fix the encoder

Use the reference encoder in `tools/rainbow/rainbow.py`, which implements all of this correctly:

```bash
# For still images
python3 tools/rainbow/rainbow.py image input.png output.bin \
    --header build/output.h --preview build/preview.png --report build/report.json

# For video
python3 tools/rainbow/rainbow.py video input.mkv output.pcfv \
    --fps 15 --audio mp2 --max-frame-sectors 4 --jobs 8 --report build/report.json
```

If you must fix your C encoder, the minimal changes are:

```c
// 1. Count stuffed bytes in size
size_t size = payload.len + ((block_type == 0xff) ? 128 : 0);

// 2. Ensure word alignment
if (size & 1) {
    vec_push(&out, 0x00);
    size++;
}

// 3. Add inner dummy (2 bytes) and guard (6 bytes)
vec_push(&out, 0x00);
vec_push(&out, 0x00);
size += 2;  // inner dummy is part of size
vec_push(&out, 0x00); vec_push(&out, 0x00);
vec_push(&out, 0x00); vec_push(&out, 0x00);
vec_push(&out, 0x00); vec_push(&out, 0x00);

// 4. Use MPCONV base tables, not quality-scaled
// 5. Emit 0x0F null-run for black macroblocks
// 6. Use integer FDCT with MPCONV asymmetry
```

## What to do with already-encoded streams

Use the repair tool, which rewrites framing without re-encoding the entropy:

```bash
python3 tools/rainbow/rainbow.py repair-legacy old.pcfv fixed.pcfv
```

This preserves the entropy bits while fixing sizes, alignment, dummy, and guard bytes.

## How to verify

1. **Strict framing check** (catches all framing errors):
```bash
python3 tools/rainbow/rainbow.py inspect output.pcfv --frame 0 --preview build/f0.png
```

2. **Check per-strip sizes** in the report JSON — the largest strip is the one most likely to miss the raster deadline.

3. **Verify black frames are small** — a black frame should be dramatically smaller than a normal frame due to null-run encoding.

4. **Test on real hardware** — the emulator cannot confirm all RAINBOW timing issues. Use `pcfx-headless` for regression testing but burn to real hardware for release claims.

The right-edge glitch is the classic symptom of the unstuffed-byte size bug. Fix the size calculation first, then add alignment, dummy, and guard bytes, and the corruption should disappear.