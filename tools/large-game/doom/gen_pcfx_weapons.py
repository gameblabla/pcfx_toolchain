#!/usr/bin/env python3
"""gen_pcfx_weapons.py -- convert DOOM first-person weapon (psprite) frames into
PC-FX HuC6270 VDC hardware sprites in 256-COLOR combined-VDC mode.

WHY: the DOOM 3D renderer draws the player's weapon straight into the KING KRAM
framebuffer (half horizontal res, and it has to be composited every frame and
clipped by hand).  The PC-FX can instead show the weapon as a hardware sprite
overlay: sharper (full 256px horizontal res), free to composite, and clipped
above the HUD by the VDC's own vertical display window.

256-COLOR SPRITES combine BOTH HuC6270 VDCs (this is the mednafen/king.c mixer
contract, verified in pcfxemu):
    combined_index = (VDC0.pixel4bpp << 4) | VDC1.pixel4bpp     (chip0=high, chip1=low)
    the pixel is TRANSPARENT iff VDC1's low nibble is 0
    the SPR-combine only triggers when VDC1's sprite carries palette-bank bit3
    (0x8) in its SAT flags -- the C side sets that; here we only guarantee that
    every OPAQUE colour lands in a palette slot whose LOW NIBBLE is non-zero
    (slot 0 stays the sole transparent slot).

PIPELINE
  doom1.wad psprite patch -> RGBA (transparent posts) -> PNG (for inspection)
    -> pre-scale to on-screen physical px (x *256/320, y *240/200, NEAREST)
    -> shared DOOM PLAYPAL indices (unsafe low-nibble-0 indices remapped to the
       nearest PLAYPAL entry whose low nibble is non-zero)
    -> 8bpp index bitmap -> 16x64 sprite cells (skip empty)
    -> per cell, split into VDC0 (high nibble) + VDC1 (low nibble) HuC6270
       pattern words (4 vertical blocks x 4 bitplanes x 16 rows = 256 words each)
    -> emit src/generated/pcfx_weapons.{h,c}

The C runtime uploads the active frame's cells to VDC VRAM on frame-change and
writes an identical SAT to both chips (see platform/pcfx_weapon.c).

Usage:  tools/gen_pcfx_weapons.py [--wad doom1.wad] [--out doom-pcfx/src/generated]
                                  [--png doom-pcfx/assets/weapons]
"""

import argparse
import os
import struct
import sys

from PIL import Image

# ------------------------------------------------------------------ config ----
# (lump prefix, "frame letters", SPR_ enum name).  Frame letters are the DOOM
# rotation-0 psprite frames (A=0, B=1, ...).  Data-driven: add weapons here.
WEAPONS = [
    ("PUNG", "ABCD",  "SPR_PUNG"),   # fist
    ("PISG", "ABCDE", "SPR_PISG"),   # pistol
    ("PISF", "AB",    "SPR_PISF"),   # pistol muzzle flash
    ("SHTG", "ABCD",  "SPR_SHTG"),   # shotgun
    ("SHTF", "AB",    "SPR_SHTF"),   # shotgun flash
    ("CHGG", "AB",    "SPR_CHGG"),   # chaingun
    ("CHGF", "AB",    "SPR_CHGF"),   # chaingun flash
]

CELL_W = 16
CELL_H = 64
CELL_WORDS = 256           # per VDC: 4 vblocks * 4 planes * 16 rows
SX_NUM, SX_DEN = 256, 320  # horizontal on-screen scale (pspritescale, physical px)
SY_NUM, SY_DEN = 240, 200  # vertical on-screen scale (pspriteyscale)


# -------------------------------------------------------------- wad access ----
def read_wad(path):
    data = open(path, "rb").read()
    magic, num, dirofs = struct.unpack("<4sII", data[:12])
    if magic not in (b"IWAD", b"PWAD"):
        raise SystemExit("not a WAD: %s" % path)
    lumps = {}
    order = []
    for i in range(num):
        off, sz, name = struct.unpack("<II8s", data[dirofs + i * 16:dirofs + i * 16 + 16])
        name = name.rstrip(b"\0").decode("latin1")
        lumps[name] = (off, sz)
        order.append(name)
    return data, lumps


def playpal(data, lumps):
    off, sz = lumps["PLAYPAL"]
    pal = []
    for i in range(256):
        r, g, b = data[off + i * 3], data[off + i * 3 + 1], data[off + i * 3 + 2]
        pal.append((r, g, b))
    return pal


def decode_patch(data, off):
    """Decode a DOOM patch_t -> (w, h, leftoffset, topoffset, idx[h][w]).
    idx cells are palette indices, or -1 for transparent."""
    w, h, lx, ty = struct.unpack("<HHhh", data[off:off + 8])
    colofs = struct.unpack("<%dI" % w, data[off + 8:off + 8 + 4 * w])
    idx = [[-1] * w for _ in range(h)]
    for x in range(w):
        p = off + colofs[x]
        while True:
            topdelta = data[p]
            if topdelta == 0xFF:
                break
            count = data[p + 1]
            p += 3  # skip topdelta, count, and the unused padding byte
            for r in range(count):
                yy = topdelta + r
                if 0 <= yy < h:
                    idx[yy][x] = data[p + r]
            p += count + 1  # pixels + trailing padding byte
    return w, h, lx, ty, idx


# ------------------------------------------------------------- conversion -----
def patch_to_rgba(w, h, idx, pal):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = im.load()
    for y in range(h):
        row = idx[y]
        for x in range(w):
            i = row[x]
            if i >= 0:
                r, g, b = pal[i]
                px[x, y] = (r, g, b, 255)
    return im


def prescale(im):
    w, h = im.size
    nw = max(1, round(w * SX_NUM / SX_DEN))
    nh = max(1, round(h * SY_NUM / SY_DEN))
    return im.resize((nw, nh), Image.NEAREST)


def prescale_indices(idx):
    """Nearest-neighbor scale while retaining the original PLAYPAL index.
    Mode I also preserves -1 as the transparent sentinel."""
    h, w = len(idx), len(idx[0])
    im = Image.new("I", (w, h))
    im.putdata([v for row in idx for v in row])
    nw = max(1, round(w * SX_NUM / SX_DEN))
    nh = max(1, round(h * SY_NUM / SY_DEN))
    scaled = im.resize((nw, nh), Image.NEAREST)
    out = [scaled.getpixel((x, y)) for y in range(nh) for x in range(nw)]
    return [out[y * nw:(y + 1) * nw] for y in range(nh)]


def safe_slots():
    """Sprite-palette slots usable for OPAQUE colours: 1..255 with low nibble
    != 0 (transparency in 256-colour combine mode is keyed on the low nibble)."""
    return [s for s in range(1, 256) if (s & 0x0F) != 0]


def build_palette(playpal, used_indices):
    """Map weapon pixels to shared DOOM PLAYPAL indices.

    The combined-VDC mixer keys transparency on the final index's low nibble,
    so opaque source indices 0x?0 cannot be used directly. Pick the nearest
    safe PLAYPAL entry instead; every safe source index remains unchanged and
    therefore follows damage/bonus/radiation palette swaps exactly.
    """
    slots = safe_slots()
    index_map = list(range(256))
    remapped = 0
    max_error = 0
    for source in sorted(used_indices):
        if source & 0x0F:
            continue
        c = playpal[source]
        best, bd = slots[0], 1 << 30
        for s in slots:
            cc = playpal[s]
            dr, dg, db = cc[0] - c[0], cc[1] - c[1], cc[2] - c[2]
            d = 2 * dr * dr + 4 * dg * dg + db * db
            if d < bd:
                best, bd = s, d
        index_map[source] = best
        remapped += 1
        if bd > max_error:
            max_error = bd
    return index_map, remapped, max_error


def index_bitmap(scaled_idx, index_map):
    """Pre-scaled source indices -> VDC indices (0 = transparent)."""
    h, w = len(scaled_idx), len(scaled_idx[0])
    bmp = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            source = scaled_idx[y][x]
            if source >= 0:
                bmp[y][x] = index_map[source]
    return bmp, w, h


def cell_patterns(bmp, w, h, cc, cr):
    """Build VDC0 (high nibble) and VDC1 (low nibble) pattern words for the
    16x64 cell at cell-column cc, cell-row cr.  Returns (pat0, pat1, nonempty).

    HuC6270 16x64 sprite = 4 vertical 16x16 blocks.  Each block = 4 bitplanes of
    16 rows; plane word bit (15-x) is screen column x.  Block b occupies words
    [b*64 .. b*64+63]: plane p rows 0..15 at b*64 + p*16 + row."""
    pat0 = [0] * CELL_WORDS
    pat1 = [0] * CELL_WORDS
    nonempty = False
    x0 = cc * CELL_W
    y0 = cr * CELL_H
    for b in range(4):                      # vertical block
        for row in range(16):
            yy = y0 + b * 16 + row
            if yy >= h:
                continue
            p0 = [0, 0, 0, 0]
            p1 = [0, 0, 0, 0]
            for x in range(16):
                xx = x0 + x
                if xx >= w:
                    continue
                v = bmp[yy][xx]
                if v == 0:
                    continue
                nonempty = True
                bit = 1 << (15 - x)
                hi = (v >> 4) & 0xF
                lo = v & 0xF
                for pl in range(4):
                    if hi & (1 << pl):
                        p0[pl] |= bit
                    if lo & (1 << pl):
                        p1[pl] |= bit
            base = b * 64 + row
            for pl in range(4):
                pat0[base + pl * 16] = p0[pl]
                pat1[base + pl * 16] = p1[pl]
    return pat0, pat1, nonempty


# ----------------------------------------------------------------- emit -------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="doom1.wad")
    ap.add_argument("--out", default="doom-pcfx/src/generated")
    ap.add_argument("--png", default="doom-pcfx/assets/weapons")
    args = ap.parse_args()

    data, lumps = read_wad(args.wad)
    pal = playpal(data, lumps)
    os.makedirs(args.png, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    # Pass 1: decode every frame, pre-scale, collect colours.
    frames = []           # list of dicts
    used_indices = set()
    for prefix, letters, spr in WEAPONS:
        for fi, ch in enumerate(letters):
            lump = "%s%s0" % (prefix, ch)
            if lump not in lumps:
                print("  skip (missing): %s" % lump)
                continue
            off, sz = lumps[lump]
            w, h, lx, ty, idx = decode_patch(data, off)
            rgba = patch_to_rgba(w, h, idx, pal)
            rgba.save(os.path.join(args.png, lump + ".png"))
            scaled = prescale(rgba)
            scaled_idx = prescale_indices(idx)
            for row in scaled_idx:
                used_indices.update(v for v in row if v >= 0)
            frames.append(dict(spr=spr, frame=fi, lump=lump, lx=lx, ty=ty,
                               scaled=scaled, scaled_idx=scaled_idx))

    index_map, remapped, max_error = build_palette(pal, used_indices)
    print("weapon palette: %d used PLAYPAL indices (%d unsafe indices remapped, "
          "max weighted error %d)" % (len(used_indices), remapped, max_error))

    # Pass 2: build cells + pattern data. The pattern words for the WHOLE weapon set are
    # ~160 KB and used to sit in RAM as two flat arrays (pcfx_weapon_pat0/pat1) — the
    # single biggest reclaimable block in the program image, and it only grows with the
    # registered WAD's extra weapons. Instead we LZ4-compress each FRAME's cells (both VDC
    # planes concatenated) into a per-frame block; the runtime decodes just the active
    # frame's block into a small scratch buffer when the weapon frame CHANGES (a few times
    # a second, in the deferred vblank upload — the same lz4_depack the renderer already
    # runs per-draw). A frame's cells are laid out contiguously (in-frame word offset =
    # cell-index * CELL_WORDS), so upload_frame reads the scratch directly.
    import lz4_block
    cells = []            # flat list of (col, row, in-frame word offset)
    frame_recs = []       # (spr, frame, lx, ty, ncols, nrows, cell_start, ncells, c0_off, c1_off)
    frame_raw = []        # per-frame (fp0, fp1) uncompressed words (for the self-check below)
    pat0c = bytearray()   # concatenated per-frame LZ4 blocks (plane 0), each [u16 clen][block]
    pat1c = bytearray()
    raw_words = 0
    def words_to_lz4(words):
        raw = bytearray()
        for w in words:
            raw += struct.pack('<H', w)
        blk = lz4_block.compress(bytes(raw))
        return struct.pack('<H', len(blk)) + blk    # 2-byte clen prefix (lz4_depack contract)
    for f in frames:
        bmp, w, h = index_bitmap(f["scaled_idx"], index_map)
        ncols = (w + CELL_W - 1) // CELL_W
        nrows = (h + CELL_H - 1) // CELL_H
        cell_start = len(cells)
        fp0 = []; fp1 = []
        for cr in range(nrows):
            for cc in range(ncols):
                p0, p1, ne = cell_patterns(bmp, w, h, cc, cr)
                if not ne:
                    continue
                cells.append((cc, cr, len(fp0)))     # in-frame word offset
                fp0.extend(p0); fp1.extend(p1)
        ncells = len(cells) - cell_start
        raw_words += len(fp0)
        frame_raw.append((fp0, fp1))
        c0_off = len(pat0c); pat0c += words_to_lz4(fp0)
        c1_off = len(pat1c); pat1c += words_to_lz4(fp1)
        frame_recs.append((f["spr"], f["frame"], f["lx"], f["ty"],
                           ncols, nrows, cell_start, ncells, c0_off, c1_off))
        print("  %-8s frame %d: %dx%d px, %d cells" % (f["lump"], f["frame"], w, h, ncells))

    total_cells = len(cells)
    max_ncells = max((r[7] for r in frame_recs), default=1)   # scratch is sized to this
    raw_kb = raw_words * 2 * 2 // 1024
    comp_kb = (len(pat0c) + len(pat1c)) // 1024
    print("total: %d frames, %d cells, %d pattern words/VDC -> LZ4 %d KB (was %d KB RAM, "
          "reclaim ~%d KB)" % (len(frame_recs), total_cells, raw_words, comp_kb, raw_kb,
                               raw_kb - comp_kb))

    # ------------------------------------------------------------- header ----
    hpath = os.path.join(args.out, "pcfx_weapons.h")
    with open(hpath, "w") as h:
        h.write("/* GENERATED by tools/gen_pcfx_weapons.py -- do not edit. */\n")
        h.write("#ifndef PCFX_WEAPONS_H\n#define PCFX_WEAPONS_H\n\n")
        h.write("#define PCFX_WEP_CELL_W    %d\n" % CELL_W)
        h.write("#define PCFX_WEP_CELL_H    %d\n" % CELL_H)
        h.write("#define PCFX_WEP_CELL_WORDS %d  /* per VDC */\n" % CELL_WORDS)
        h.write("#define PCFX_WEP_NUM_FRAMES %d\n" % len(frame_recs))
        h.write("#define PCFX_WEP_NUM_CELLS  %d\n" % total_cells)
        h.write("#define PCFX_WEP_MAX_CELLS  %d  /* largest frame; sizes the decode scratch */\n" % max_ncells)
        h.write("#define PCFX_WEP_SX_NUM %d\n#define PCFX_WEP_SX_DEN %d\n" % (SX_NUM, SX_DEN))
        h.write("#define PCFX_WEP_SY_NUM %d\n#define PCFX_WEP_SY_DEN %d\n\n" % (SY_NUM, SY_DEN))
        h.write("typedef struct { unsigned char col, row; unsigned short pat_ofs; } pcfx_wep_cell_t;\n")
        h.write("typedef struct {\n"
                "  short spr;            /* SPR_ enum */\n"
                "  short frame;          /* 0-based frame (A=0) */\n"
                "  short lx, ty;         /* patch left/top offset (doom px) */\n"
                "  unsigned char ncols, nrows;\n"
                "  unsigned short cell_start, ncells;\n"
                "  unsigned int c0_off, c1_off; /* byte offset of this frame's LZ4 block in pat0c/pat1c */\n"
                "} pcfx_wep_frame_t;\n\n")
        h.write("extern const pcfx_wep_cell_t  pcfx_weapon_cells[PCFX_WEP_NUM_CELLS];\n")
        h.write("/* Per-frame LZ4 pattern blocks (plane 0 = VDC0 high nibble, plane 1 = VDC1 low).\n"
                " * Each frame's block is [u16 clen][lz4 block] of ncells*PCFX_WEP_CELL_WORDS u16\n"
                " * words; lz4_depack it into a scratch of that many words. */\n")
        h.write("extern const unsigned char    pcfx_weapon_pat0c[]; /* VDC0 high nibble, LZ4 */\n")
        h.write("extern const unsigned char    pcfx_weapon_pat1c[]; /* VDC1 low nibble,  LZ4 */\n")
        h.write("extern const pcfx_wep_frame_t pcfx_weapon_frames[PCFX_WEP_NUM_FRAMES];\n\n")
        h.write("#endif\n")

    # -------------------------------------------------------------- body -----
    cpath = os.path.join(args.out, "pcfx_weapons.c")
    with open(cpath, "w") as c:
        c.write("/* GENERATED by tools/gen_pcfx_weapons.py -- do not edit. */\n")
        c.write('#include "info.h"\n#include "pcfx_weapons.h"\n\n')

        def emit_bytes(name, blob):
            c.write("const unsigned char %s[%d] = {\n" % (name, len(blob)))
            for i in range(0, len(blob), 16):
                c.write("  " + ", ".join("0x%02x" % b for b in blob[i:i + 16]) + ",\n")
            c.write("};\n\n")

        emit_bytes("pcfx_weapon_pat0c", pat0c)
        emit_bytes("pcfx_weapon_pat1c", pat1c)

        c.write("const pcfx_wep_cell_t pcfx_weapon_cells[PCFX_WEP_NUM_CELLS] = {\n")
        for (cc, cr, ofs) in cells:
            c.write("  { %d, %d, %d },\n" % (cc, cr, ofs))
        c.write("};\n\n")

        c.write("const pcfx_wep_frame_t pcfx_weapon_frames[PCFX_WEP_NUM_FRAMES] = {\n")
        for (spr, frame, lx, ty, ncols, nrows, cs, nc, c0, c1) in frame_recs:
            c.write("  { %s, %d, %d, %d, %d, %d, %d, %d, %d, %d },\n"
                    % (spr, frame, lx, ty, ncols, nrows, cs, nc, c0, c1))
        c.write("};\n")

    print("wrote %s and %s" % (hpath, cpath))

    # ------------------------------------------------------- self-check ------
    # Reconstruct each frame from the emitted pattern words using the EXACT
    # emulator combine contract, and save a recon PNG next to the source PNG.
    # If recon matches the pre-scaled source, the whole pipeline is correct:
    # patch decode -> palette -> bitplane pack -> VDC0/VDC1 nibble combine.
    recon_dir = os.path.join(args.png, "recon")
    os.makedirs(recon_dir, exist_ok=True)
    max_err = 0
    for fi, (rec, f) in enumerate(zip(frame_recs, frames)):
        spr, frame, lx, ty, ncols, nrows, cs, nc = rec[:8]
        fp0, fp1 = frame_raw[fi]           # this frame's uncompressed plane words
        w = ncols * CELL_W
        h = nrows * CELL_H
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = im.load()
        for ci in range(cs, cs + nc):
            cc, cr, ofs = cells[ci]        # ofs = in-frame word offset
            for b in range(4):
                for row in range(16):
                    yy = cr * CELL_H + b * 16 + row
                    base = ofs + b * 64 + row
                    w0 = [fp0[base + pl * 16] for pl in range(4)]
                    w1 = [fp1[base + pl * 16] for pl in range(4)]
                    for x in range(16):
                        bit = 1 << (15 - x)
                        hi = sum(((w0[pl] >> (15 - x)) & 1) << pl for pl in range(4))
                        lo = sum(((w1[pl] >> (15 - x)) & 1) << pl for pl in range(4))
                        if lo == 0:            # transparent (low nibble keyed)
                            continue
                        idx = (hi << 4) | lo
                        r, g, b2 = pal[idx]
                        px[cc * CELL_W + x, yy] = (r, g, b2, 255)
        im.save(os.path.join(recon_dir, f["lump"] + "_recon.png"))
        # Compare opaque-pixel count against the pre-scaled source (loose sanity).
        src = f["scaled"]
        sp = src.load()
        so = sum(1 for yy in range(src.size[1]) for xx in range(src.size[0])
                 if sp[xx, yy][3] >= 128)
        ro = sum(1 for yy in range(h) for xx in range(w) if px[xx, yy][3] >= 128)
        max_err = max(max_err, abs(so - ro))
    print("self-check: recon PNGs in %s (max opaque-pixel delta vs source: %d)"
          % (recon_dir, max_err))


if __name__ == "__main__":
    main()
