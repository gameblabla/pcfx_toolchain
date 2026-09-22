#!/usr/bin/env python3
"""gen_pcfx_packs.py -- build the per-map contiguous asset pack blob (PSX-Doom style).

The scattered per-lump precache streamed a level's graphics from lumps spread across
the whole CD-WAD; pcfxemu charges a SEEK (33-283 ms) for every non-adjacent read, so
a level load spent ~20 s seeking (see memory/doom-pcfx-cd-seek-model.md). This tool
pre-assembles, for each map, ALL the compressed lumps that map precaches into ONE
GAP-FREE contiguous region on the CD (duplicated across maps -- CD space is cheap).
The runtime then streams the whole region into the arena in back-to-back sequential
reads (each abuts the last -> ~0 seek), collapsing the load to the transfer floor.

Inputs:
  * the baked CD-WAD blob (src/generated/pcfx_iwad.bin) -- the SAME compressed lump
    payloads the runtime reads, so a packed lump is byte-identical to the scattered one.
  * the per-map manifest (generated/mappack_manifest.txt) -- the authoritative reserve
    set + ORDER dumped by the engine's own R_PrecacheLevel (build -DGEN_MAPPACK_MANIFEST).
    Reserve order is preserved so the runtime packs the arena chunks identically and the
    same set is guaranteed to fit.

Output: pcfx_mappacks.bin, laid out (all sections sector-aligned):
  index (sector 0):  'MPK2'  u32 nmaps  u32 mirror_off  u32 blob_bytes  u32 index_sum
                     u32 reserved, then at byte 24:
                     nmaps x { char name[8]; u32 nlumps, hdr_off, pay_off, pay_bytes,
                               n_geo, gfx_bytes, hdr_sum }
  index copy (s. 1): byte-identical second index sector (see DUPLICATES below)
  per map header:    nlumps x { u32 lumpnum; u32 payload_off; u32 disclen; u32 lz4; u32 sum }
  per map payload:   concatenated on-disc (compressed) lump bytes, each 4-byte aligned
  mirror region:     byte copy of everything above, starting at mirror_off
All *_off are byte offsets from the blob start; hdr_off/pay_off are sector-aligned so the
runtime reads them by whole sectors (blob base LBA comes from the CD linker's lbas.h).

DUPLICATES + CHECKSUMS. An imperfect burn returns GOOD SCSI status with wrong data —
which is indistinguishable from a legitimately odd asset, and showed up in the field as
glitched enemy sprites. So every lump, every map header and the index carry a
pcfx_sum32 (tools/pcfx_sum32.py), and the whole blob is written TWICE. The runtime
verifies each read and, on a mismatch, re-reads the same offset from the copy — which
sits megabytes away on the disc, out of reach of a local defect — before giving up and
dropping the lump (src/w_wad.c). The index sector is ALSO duplicated at sector 1
because it is what tells the runtime where the mirror is.
"""
import sys, struct, argparse
import pcfx_sum32

SECTOR = 2048
INDEX_HDR = 24                    # magic, nmaps, mirror_off, blob_bytes, index_sum, reserved
ENT = 8 + 4 * 7                   # index entry: name8 + 7 u32 (see the layout comment above)
HDRENT = 20                       # per-lump header entry: lumpnum, poff, disclen, lz4, sum


def align(n, a):
    return (n + a - 1) & ~(a - 1)


def read_cd_wad(path):
    """Parse a bake_wad --cd-lz4 blob -> (by_name, by_index) where each entry is
    (index, name, filepos, usize, disc_bytes, lz4flag)."""
    d = open(path, 'rb').read()
    magic, numlumps, infotableofs = struct.unpack_from('<4sii', d, 0)
    if magic != b'IWAD':
        sys.exit(f'{path}: not an IWAD blob')
    disclen_ofs = 0
    if d[16:20] == b'LZ4C':
        disclen_ofs = struct.unpack_from('<I', d, 12)[0]
    by_index = []
    by_name = {}
    for i in range(numlumps):
        filepos, size = struct.unpack_from('<ii', d, infotableofs + i * 16)
        name = d[infotableofs + i * 16 + 8:infotableofs + i * 16 + 16].split(b'\x00', 1)[0].decode('latin1').upper()
        if disclen_ofs:
            dl = struct.unpack_from('<I', d, disclen_ofs + i * 4)[0]
            disclen, lz4 = dl & 0x7fffffff, dl >> 31
        else:
            disclen, lz4 = size, 0
        disc = d[filepos:filepos + disclen]
        ent = (i, name, filepos, size, disc, lz4)
        by_index.append(ent)
        by_name[name] = ent           # last wins (matches W_CheckNumForName backward search)
    return by_index, by_name


def read_manifest(path):
    """generated/mappack_manifest.txt -> [(mapname, [(lumpnum, name), ...]), ...]."""
    maps = []
    cur = None
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('MAP '):
            _, name, _n = line.split()[:3]
            cur = (name, [])
            maps.append(cur)
        else:
            num, nm = line.split()[:2]
            cur[1].append((int(num), nm.upper()))
    return maps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cd_wad')
    ap.add_argument('manifest')
    ap.add_argument('out')
    args = ap.parse_args()

    by_index, by_name = read_cd_wad(args.cd_wad)
    maps = read_manifest(args.manifest)
    if not maps:
        # Empty manifest (e.g. mid-regeneration, or a build that doesn't use packs):
        # emit a valid EMPTY pack blob so the build still links. The runtime's pack
        # lookup finds no map and falls back to the scattered path.
        blob = bytearray(2 * SECTOR)
        struct.pack_into('<4sIII', blob, 0, b'MPK2', 0, 2 * SECTOR, 2 * SECTOR)
        struct.pack_into('<I', blob, 16, pcfx_sum32.sum32(blob[:INDEX_HDR]))
        blob[SECTOR:2 * SECTOR] = blob[:SECTOR]        # index copy (sector 1)
        blob += bytes(blob)                            # mirror region
        open(args.out, 'wb').write(blob)
        print('  mappacks: 0 maps (empty manifest) — scattered load for every map')
        return

    # The 10 map GEOMETRY lumps (marker+1..marker+10: THINGS, LINEDEFS, SIDEDEFS,
    # VERTEXES, SEGS, SSECTORS, NODES, SECTORS, REJECT, BLOCKMAP — a fixed Doom order).
    # P_SetupLevel reads these via W_CacheLumpNum from the scattered IWAD region, out of
    # disc order and far from the graphics pack, which was the residual ~2431 ms level-load
    # seek (the map lumps + the IWAD<->mappack region jumps). We DUPLICATE them into the
    # FRONT of this map's payload (CD space is cheap) so the whole level — geometry then
    # graphics — is ONE gap-free contiguous region the runtime streams in a single ~0-seek
    # sweep. The runtime decodes the geometry lumps straight into lumpcache[] (so the
    # P_SetupLevel reads are RAM hits) and copies the graphics lumps into the arena.
    ML_COUNT = 10

    def geometry_lumps(mapname):
        """marker+1..marker+10 for a map marker; [] for a non-map entry (e.g. BOOT)."""
        mk = by_name.get(mapname.upper())
        if mk is None:
            return []
        mk_idx = mk[0]
        geo = []
        for k in range(1, ML_COUNT + 1):
            gi = mk_idx + k
            if gi >= len(by_index):
                print(f'  WARN {mapname}: geometry lump #{gi} out of range — no geo prefix')
                return []
            _, _, _, _, disc, lz4 = by_index[gi]
            geo.append((gi, disc, len(disc), lz4))
        return geo

    # Resolve each map's lump list against the CURRENT CD-WAD. The manifest lump NUMBER
    # is authoritative (it is the directory index the runtime uses); the NAME is a guard.
    # Serial-log capture can occasionally TRUNCATE a name (e.g. 'SHTFB0' -> 'S'), so a
    # manifest name that is a PREFIX of the directory name is accepted (truncation); a
    # name that diverges otherwise warns loudly (the WAD was likely rebaked -> regenerate).
    # Each pack's lumps = [geometry prefix (n_geo)] + [graphics from manifest].
    packs = []                        # (mapname, n_geo, [(lumpnum, disc_bytes, disclen, lz4)])
    warns = 0
    for mapname, ents in maps:
        geo = geometry_lumps(mapname)
        gfx = []
        for num, nm in ents:
            if num >= len(by_index):
                sys.exit(f'{mapname}: lump #{num} out of range (rebake manifest)')
            idx, dname, _fp, _sz, disc, lz4 = by_index[num]
            if dname != nm and not dname.startswith(nm):
                print(f'  WARN {mapname}: lump #{num} is {dname!r} not manifest {nm!r} '
                      f'(WAD changed? regenerate manifest)')
                warns += 1
            gfx.append((num, disc, len(disc), lz4))
        packs.append((mapname, len(geo), geo + gfx))
    if warns:
        print(f'  {warns} name mismatch(es) — used the authoritative lump numbers')

    # Layout. Index (sector 0) + its copy (sector 1), then for each map [header][payload],
    # all sector-aligned. Index entry: name8 + nlumps + hdr_off + pay_off + pay_bytes +
    # n_geo + gfx_bytes + hdr_sum. n_geo = leading geometry lumps (-> lumpcache);
    # gfx_bytes = the graphics tail of the payload (-> arena), which W_PrecacheReserve uses
    # to size the arena chunk (the geometry prefix is decoded into lumpcache, NOT the arena,
    # so it must be excluded).
    index_bytes = INDEX_HDR + len(packs) * ENT
    if index_bytes > SECTOR:
        sys.exit(f'index needs {index_bytes} bytes — the runtime reads ONE sector')
    cursor = 2 * SECTOR                       # sector 0 index, sector 1 its duplicate

    layout = []                       # (hdr_off, pay_off, pay_bytes, gfx_bytes, entries)
    for mapname, n_geo, lumps in packs:
        hdr_off = cursor
        hdr_bytes = len(lumps) * HDRENT
        cursor = align(hdr_off + hdr_bytes, SECTOR)
        pay_off = cursor
        entries = []
        poff = 0
        geo_end = 0                   # payload offset where the graphics tail begins
        for i, (num, disc, disclen, lz4) in enumerate(lumps):
            if i == n_geo:
                # SECTOR-align the start of the graphics tail. The graphics payload is a
                # byte-image of the runtime arena chunk (arena_off = disc_off - geo_end,
                # both 4-aligned cumulative in reserve order), so aligning its start to a
                # sector lets W_LoadMapPack read the WHOLE graphics payload directly into
                # the arena in ONE contiguous read (no w_stage windowing / per-lump copy).
                poff = align(poff, SECTOR)
                geo_end = poff
            entries.append((num, poff, disclen, lz4, pcfx_sum32.sum32(disc)))
            poff = align(poff + disclen, 4)     # 4-byte align each lump in the payload
        if n_geo == len(lumps):
            geo_end = poff                       # all-geometry (unused shape)
        pay_bytes = poff
        gfx_bytes = pay_bytes - geo_end
        cursor = align(pay_off + pay_bytes, SECTOR)
        layout.append((hdr_off, pay_off, pay_bytes, gfx_bytes, entries))

    total = cursor
    blob = bytearray(total)
    struct.pack_into('<4sIII', blob, 0, b'MPK2', len(packs), total, total)
    off = INDEX_HDR
    for (mapname, n_geo, lumps), (hdr_off, pay_off, pay_bytes, gfx_bytes, entries) in zip(packs, layout):
        nm = mapname.encode('latin1')[:8].ljust(8, b'\x00')
        # header (write it first: its checksum goes in the index entry below)
        for j, (num, poff, disclen, lz4, lsum) in enumerate(entries):
            struct.pack_into('<IIIII', blob, hdr_off + j * HDRENT, num, poff, disclen, lz4, lsum)
        hdr_sum = pcfx_sum32.sum32(blob[hdr_off:hdr_off + len(entries) * HDRENT])
        struct.pack_into('<8sIIIIIII', blob, off, nm, len(lumps), hdr_off, pay_off,
                         pay_bytes, n_geo, gfx_bytes, hdr_sum)
        off += ENT
        # payload
        for (num, disc, disclen, lz4), (_, poff, _, _, _) in zip(lumps, entries):
            blob[pay_off + poff:pay_off + poff + disclen] = disc

    # Index checksum over the index bytes with its own field held at 0 (the runtime does
    # the same in its resident copy), then the sector-1 index copy and the mirror region.
    struct.pack_into('<I', blob, 16, pcfx_sum32.sum32(blob[:index_bytes]))
    blob[SECTOR:SECTOR + index_bytes] = blob[:index_bytes]
    blob += bytes(blob)

    open(args.out, 'wb').write(blob)
    print(f'  mappacks: {len(packs)} maps, {total // SECTOR} sectors ({total / 1024:.0f} KB)'
          f' + duplicate copy ({2 * total / 1024:.0f} KB total)')
    for (mapname, n_geo, lumps), (hdr_off, pay_off, pay_bytes, gfx_bytes, _) in zip(packs, layout):
        print(f'    {mapname:8s} {len(lumps):4d} lumps ({n_geo} geo)  payload {pay_bytes / 1024:6.1f} KB '
              f'(gfx {gfx_bytes / 1024:6.1f} KB) @ sector {pay_off // SECTOR}')


if __name__ == '__main__':
    main()
