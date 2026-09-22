#!/usr/bin/env python3
"""bake_wad.py — GBADoom-style build-time WAD preprocessor, PC-FX (V810) edition.

GBADoom's GbaWadUtil pre-converts an IWAD so the rendering-critical map lumps
already match the engine's *runtime* structs — the engine then casts a memory
pointer straight to the struct (zero copy, zero alloc, zero swap per level).

This is the PC-FX fork of the portable core's baker. The V810 is LITTLE-ENDIAN
(like the GBA that GBADoom originally targeted), so we emit LITTLE-ENDIAN
records by default. An earlier big-endian SH-1 target emitted big-endian
records; pass --endian big to reproduce that.

Per map we repack four lumps into their runtime layouts (native endian):
  VERTEXES -> vertex_t   (8B)   mapvertex short -> fixed_t (<<16)
  SIDEDEFS -> mapsidedef (12B)  texture NAMES -> texture indices (TEXTURE1/2 order)
  LINEDEFS -> line_t     (56B)  inlined fixed vertices + dx/dy/bbox/slopetype
  SEGS     -> seg_t      (32B)  inlined fixed vertices + resolved side/line/sector nums
Every other lump (SECTORS/SUBSECTORS/NODES/THINGS/REJECT/graphics/directory) stays
verbatim little-endian; the engine's SHORT()/LONG() (no-ops on LE) read them raw.
BLOCKMAP is all int16: kept verbatim (LE) for the V810, byte-swapped only for --endian big.

Output: <out>.c emits a C array; <out>.bin emits the raw baked WAD blob (loadable
from CD into RAM). The blob itself is a self-contained IWAD starting with 'IWAD'.

Usage: bake_wad.py <in.wad> <out.c|out.bin> [--name doom_iwad] [--endian little|big]
       [--drop-audio] [--drop-demos] [--keep-maps E1M1] [--cull-graphics]
       [--pcfx-textures] [--replace-maps jaguartc.wad] [--png-dir DIR] [--texture-png NAME=FILE]
       [--flat-png NAME=FILE] [--merge WAD:LUMP1,...] [--also-bin PATH]
"""
import sys, struct, argparse, os, math
import lz4_block   # per-lump LZ4 compression for the CD IWAD (--cd-lz4)
import pcfx_sum32  # per-lump CD integrity checksums (see the DUP1 block below)

FRACBITS = 16
NO_INDEX = 0xFFFF
NO_TEXTURE = 0
ML_TWOSIDED = 0x0004

ML_THINGS, ML_LINEDEFS, ML_SIDEDEFS, ML_VERTEXES = 1, 2, 3, 4
ML_SEGS, ML_SSECTORS, ML_NODES, ML_SECTORS = 5, 6, 7, 8
ML_REJECT, ML_BLOCKMAP = 9, 10

ST_HORIZONTAL, ST_VERTICAL, ST_POSITIVE, ST_NEGATIVE = 0, 1, 2, 3
BOXTOP, BOXBOTTOM, BOXLEFT, BOXRIGHT = 0, 1, 2, 3

# Endian prefix for the repacked runtime structs. Set in main() from --endian.
E = '<'   # '<' little (V810/GBA), '>' big (SH-1)

PCFX_TEX_W = 32
PCFX_TEX_H = 64
PCFX_TEX_BYTES = PCFX_TEX_W * PCFX_TEX_H


def pcfx_wall_lump_name(index):
    return f'PWT{index:05d}'


def pcfx_flat_lump_name(index):
    return f'PFT{index:05d}'


def to_int32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


def read_dir(data):
    magic, numlumps, infotableofs = struct.unpack_from('<4sii', data, 0)
    lumps = []
    off = infotableofs
    for _ in range(numlumps):
        filepos, size = struct.unpack_from('<ii', data, off)
        name = data[off + 8:off + 16].split(b'\x00', 1)[0].decode('latin1')
        lumps.append((filepos, size, name))
        off += 16
    return magic, lumps


def is_map_marker(name):
    if len(name) == 4 and name[0] == 'E' and name[2] == 'M' and name[1].isdigit() and name[3].isdigit():
        return True
    if len(name) == 5 and name.startswith('MAP') and name[3:].isdigit():
        return True
    return False


MAP_SUBLUMPS = {'THINGS', 'LINEDEFS', 'SIDEDEFS', 'VERTEXES', 'SEGS', 'SSECTORS',
                'NODES', 'SECTORS', 'REJECT', 'BLOCKMAP'}
MAP_LUMP_ORDER = ('THINGS', 'LINEDEFS', 'SIDEDEFS', 'VERTEXES', 'SEGS', 'SSECTORS',
                  'NODES', 'SECTORS', 'REJECT', 'BLOCKMAP')

# Jaguar TC's maps use a few flats from the registered PC IWAD.  The shareware
# doom1.wad cannot supply those graphics, so preserve a playable map by using a
# close available flat rather than leaving a name that makes R_FlatNumForName abort
# during level setup.  Registered IWADs retain their original names untouched.
JAGUAR_SHAREWARE_FLAT_REMAP = {
    'CRATOP2': 'FLAT5_5',
    'MFLR8_4': 'FLOOR4_8',
    'FLAT5_2': 'FLAT5_5',
    'GATE3':   'FLAT5_5',
    'GATE4':   'FLAT5_5',
    'GRASS':   'FLAT5_5',
}

# The Jaguar TC maps also name a large set of *wall textures* that only exist in
# the registered PC IWAD (ASH01, STWAR*, MARBLE*, the SKIN*/SP_* flesh walls, the
# TECH*/BRICK* sets, and a handful of GARG/GSTON/HOT/WOOD switches).  With a
# shareware doom1.wad those names resolve to NO_TEXTURE (index 0), so the solid
# wall renderer simply skips the wall — the level loads but is untextured.  Map
# each missing name to the closest fully-opaque shareware texture (one that owns a
# dense PC-FX page); switch textures keep their SW1/SW2 pairing so activation still
# animates.  Registered IWADs already have these names, so they never remap.
JAGUAR_SHAREWARE_TEX_REMAP = {
    'ASH01':    'GRAY5',
    'CEMENT01': 'GRAY5',
    'COMTAL02': 'COMPTALL',
    'STWAR01':  'STARTAN2',
    'STWAR02':  'STARTAN3',
    'METAL':    'METAL1',
    'SUPPORT3': 'SUPPORT2',
    'TECH01':   'TEKWALL1',
    'TECH02':   'TEKWALL4',
    'TECH04':   'TEKWALL5',
    'BRICK01':  'BROWN1',
    'BRICK02':  'BROWN96',
    'BRICK03':  'BROWNHUG',
    'BIGDOOR6': 'BIGDOOR4',
    'CRATE1':   'BROWN1',
    'CRATELIT': 'BROWN1',
    'CRATINY':  'BROWN1',
    'MARBLE01': 'STONE2',
    'MARBLE02': 'STONE2',
    'MARBLE03': 'STONE3',
    'MARBLE04': 'STONE3',
    'DFACE01':  'STONE2',
    'GSTSATYR': 'GRAY7',
    'SKIN01':   'REDWALL1',
    'SKIN02':   'REDWALL1',
    'SKIN03':   'REDWALL1',
    'SKINEDGE': 'REDWALL1',
    'SKULLS01': 'REDWALL1',
    'SP_DUDE4': 'REDWALL1',
    'SP_HOT1':  'REDWALL1',
    'SW1GARG':  'SW1STON1',
    'SW2GARG':  'SW2STON1',
    'SW1GSTON': 'SW1STONE',
    'SW2GSTON': 'SW2STONE',
    'SW1HOT':   'SW1BRN1',
    'SW2HOT':   'SW2BRN1',
    'SW1WOOD':  'SW1BROWN',
    'SW2WOOD':  'SW2BROWN',
}


def is_audio(name):
    return (name.startswith('DS') or name.startswith('DP') or name.startswith('D_')
            or name in ('GENMIDI', 'DMXGUS'))


def filter_lumps(lumps, drop_audio, drop_demos, keep_maps):
    out = []
    in_dropped_map = False
    for (fp, sz, nm) in lumps:
        if is_map_marker(nm):
            in_dropped_map = keep_maps is not None and nm not in keep_maps
            if in_dropped_map:
                continue
            out.append((fp, sz, nm)); continue
        if in_dropped_map and nm in MAP_SUBLUMPS:
            continue
        in_dropped_map = False
        if drop_audio and is_audio(nm):
            continue
        if drop_demos and nm.startswith('DEMO'):
            continue
        out.append((fp, sz, nm))
    return out


def lump_index(lumps, name):
    for i, (_, _, nm) in enumerate(lumps):
        if nm == name:
            return i
    return -1


def map_lump_indices(lumps, marker_idx, wad_path):
    """Return the ten standard map-lump indices following a map marker."""
    indices = []
    for offset, expected in enumerate(MAP_LUMP_ORDER, 1):
        idx = marker_idx + offset
        if idx >= len(lumps) or lumps[idx][2].upper() != expected:
            got = '<end>' if idx >= len(lumps) else lumps[idx][2]
            raise ValueError(f'{wad_path}: map {lumps[marker_idx][2]} lump {offset} '
                             f'is {got!r}, expected {expected!r}')
        indices.append(idx)
    return indices


def read_map_overrides(path, base_lumps):
    """Read matching map groups from an IWAD/PWAD overlay.

    Maps present only in the overlay are deliberately ignored. That keeps a
    shareware base IWAD shareware-only, and preserves PC maps the Jaguar set
    does not provide in a registered base IWAD.
    """
    with open(path, 'rb') as f:
        data = f.read()
    magic, lumps = read_dir(data)
    if magic not in (b'IWAD', b'PWAD'):
        raise ValueError(f'{path}: not a WAD (magic={magic!r})')

    overlay_maps = {name.upper(): i for i, (_, _, name) in enumerate(lumps)
                    if is_map_marker(name)}
    overrides = {}
    for base_idx, (_, _, name) in enumerate(base_lumps):
        if not is_map_marker(name):
            continue
        overlay_idx = overlay_maps.get(name.upper())
        if overlay_idx is not None:
            map_lump_indices(base_lumps, base_idx, 'base IWAD')
            map_lump_indices(lumps, overlay_idx, path)
            overrides[base_idx] = (data, lumps, overlay_idx)

    print(f'  map overlay: {len(overrides)} matching map(s) from {path}')
    return overrides


def build_texture_map(data, lumps):
    tex = {}
    order = []
    patches = {}
    pnames = read_pnames(data, lumps)
    idx = 0
    for name in ('TEXTURE1', 'TEXTURE2'):
        li = lump_index(lumps, name)
        if li < 0:
            continue
        base, size, _ = lumps[li]
        numtex = struct.unpack_from('<i', data, base)[0]
        for t in range(numtex):
            offset = struct.unpack_from('<i', data, base + 4 + 4 * t)[0]
            o = base + offset
            tname = data[o:o + 8].split(b'\x00', 1)[0].decode('latin1').upper()
            if tname not in tex:
                tex[tname] = idx
            order.append(tname)
            npatch = struct.unpack_from('<h', data, o + 20)[0]
            ps = patches.setdefault(tname, set())
            for p in range(npatch):
                pi = struct.unpack_from('<h', data, o + 22 + p * 10 + 4)[0]
                if 0 <= pi < len(pnames):
                    ps.add(pnames[pi])
            idx += 1
    return tex, order, patches


def read_pnames(data, lumps):
    li = lump_index(lumps, 'PNAMES')
    if li < 0:
        return []
    base, _, _ = lumps[li]
    n = struct.unpack_from('<i', data, base)[0]
    return [data[base + 4 + 8 * i:base + 4 + 8 * i + 8].split(b'\x00', 1)[0].decode('latin1').upper()
            for i in range(n)]


# --- Jaguar TC texture-namespace merge ---------------------------------------
# The Jaguar TC maps are authored against jaguartc.wad's OWN texture set. Many of
# its wall textures share a name with a shareware texture but use different
# dimensions (e.g. SW1BROWN 64x128 vs 128x128, STEP6 32x128 vs 32x16), and 35
# more exist only in jaguartc. Rendering those maps against the shareware texture
# table therefore mis-scales every switch and drops the jaguar-only walls. When
# the overlay is COMPLETE (every base map is a Jaguar map — the shareware case),
# the whole game is Jaguar, so we replace the base texture namespace (TEXTURE1/2,
# PNAMES, wall patches, flats) with jaguartc's, giving each map its native
# graphics at native dimensions. A handful of jaguar textures cite patches that
# jaguartc itself does not ship (registered-IWAD-only art); those are rebuilt
# from a solid filler patch so they stay opaque at the correct size instead of
# turning into a see-through hole. Registered/partial overlays keep the base
# namespace and fall back to the per-name shareware aliasing above.

def read_texture_defs(data, lumps, which):
    li = lump_index(lumps, which)
    if li < 0:
        return None
    base, _, _ = lumps[li]
    pnames = read_pnames(data, lumps)
    num = struct.unpack_from('<i', data, base)[0]
    defs = []
    for t in range(num):
        o = base + struct.unpack_from('<i', data, base + 4 + 4 * t)[0]
        name = data[o:o + 8].split(b'\x00', 1)[0].decode('latin1').upper()
        w, h = struct.unpack_from('<hh', data, o + 12)
        npatch = struct.unpack_from('<h', data, o + 20)[0]
        pats = []
        for p in range(npatch):
            xo, yo, pi = struct.unpack_from('<hhh', data, o + 22 + p * 10)
            pname = pnames[pi] if 0 <= pi < len(pnames) else ''
            pats.append((xo, yo, pname))
        defs.append({'name': name, 'w': w, 'h': h, 'patches': pats})
    return defs


def serialize_pnames(names):
    out = bytearray(struct.pack('<i', len(names)))
    for n in names:
        out += n.encode('latin1')[:8].ljust(8, b'\x00')
    return bytes(out)


def serialize_textures(defs, pindex):
    bodies = []
    for d in defs:
        b = bytearray()
        b += d['name'].encode('latin1')[:8].ljust(8, b'\x00')
        b += struct.pack('<i', 0)                 # masked (unused by the engine)
        b += struct.pack('<hh', d['w'], d['h'])
        b += struct.pack('<i', 0)                 # columndirectory (unused)
        b += struct.pack('<h', len(d['patches']))
        for (xo, yo, pname) in d['patches']:
            b += struct.pack('<hhhhh', xo, yo, pindex[pname], 0, 0)
        bodies.append(bytes(b))
    out = bytearray(struct.pack('<i', len(defs)))
    off = 4 + 4 * len(defs)
    for body in bodies:
        out += struct.pack('<i', off)
        off += len(body)
    for body in bodies:
        out += body
    return bytes(out)


def make_filler_patch(w, h, color):
    """A solid-colour Doom patch (single full-height post per column)."""
    post = bytes([0, h, 0]) + bytes([color]) * h + bytes([0, 0xFF])
    colofs_bytes = 4 * w
    first = 8 + colofs_bytes
    header = struct.pack('<HHhh', w, h, 0, 0)
    colofs = b''.join(struct.pack('<I', first) for _ in range(w))  # every column shares one post
    return header + colofs + post


def lumps_between(lumps, start, end):
    out, inside = [], False
    for fp, sz, nm in lumps:
        if nm == start:
            inside = True
            continue
        if nm == end:
            break
        if inside and not (nm.endswith('_START') or nm.endswith('_END')):
            out.append((nm, fp, sz))
    return out


def assemble_iwad(entries):
    out = bytearray(b'IWAD' + struct.pack('<ii', 0, 0))
    directory = bytearray()
    for name, payload in entries:
        while len(out) % 4:
            out += b'\x00'
        pos = len(out)
        out += payload
        directory += struct.pack('<ii', pos, len(payload))
        directory += name.encode('latin1')[:8].ljust(8, b'\x00')
    while len(out) % 4:
        out += b'\x00'
    ofs = len(out)
    out += directory
    struct.pack_into('<ii', out, 4, len(entries), ofs)
    return bytes(out)


FILLER_PATCH_NAME = 'PWTFILL'
FILLER_COLOR = 96   # a mid-grey in the stock Doom PLAYPAL (never index 0)

# A few jaguartc textures cite patches that exist only in the registered PC IWAD
# (WALL47_1, WALL42_3, the SW2_x switch faces, the crate/skin/marble-face art):
# jaguartc ships neither the patch nor a self-contained definition, and shareware
# doom1.wad lacks both the patch and the texture, so the composite cannot be built
# from anything on hand.  Rather than drop such a texture to a flat grey filler --
# which is exactly what left E1M3's METAL/SUPPORT3 stairs an untextured light grey
# -- alias it to the closest AVAILABLE texture (one whose every patch ships), so it
# renders real art at its own dimensions.  Switch faces keep their SW1/SW2 pairing
# so activation still animates.  Anything not listed here still falls back to the
# opaque filler.
JAGUAR_FILLER_TEXTURE_SUB = {
    'METAL':    'METAL1',      # plain metal wall (E1M3 stair risers)
    'SUPPORT3': 'SUPPORT2',    # girder support (E1M3 stairs)
    'SW1GARG':  'SW1SATYR', 'SW2GARG':  'SW2SATYR',   # gargoyle-stone switch
    'SW1GSTON': 'SW1STON1', 'SW2GSTON': 'SW2STON1',   # gargoyle stone
    'SW1HOT':   'SW1METAL', 'SW2HOT':   'SW2METAL',   # hot/metal switch
    'CRATE1':   'BROWN1', 'CRATELIT': 'BROWN1', 'CRATINY': 'BROWN1',  # crates
    'DFACE01':  'MARBLE01',    # demon-face marble (tiled to 128 wide)
    'SKINEDGE': 'SKIN01',      # flesh wall
    'SKY2':     'SKY1', 'SKY3': 'SKY1', 'SKY4': 'SKY1',  # sky as a wall texture
}


def tile_patches(sub, w, h):
    """Patch list that tiles `sub` (a texture def) to fully cover a w x h area.

    The substitute is opaque within its own w x h, so laying copies on a grid that
    spans the target guarantees no transparent (index-0) holes even when the target
    is larger -- e.g. a 64-wide marble filling a 128-wide demon-face texture.
    """
    sw, sh = max(1, sub['w']), max(1, sub['h'])
    out = []
    for oy in range(0, h, sh):
        for ox in range(0, w, sw):
            for (pxo, pyo, pn) in sub['patches']:
                out.append((ox + pxo, oy + pyo, pn))
    return out


def merge_jaguar_texture_world(base_data, base_lumps, jag_path):
    """Return (data, lumps) with jaguartc's texture namespace swapped in."""
    with open(jag_path, 'rb') as f:
        jd = f.read()
    _, jlumps = read_dir(jd)
    jt1 = read_texture_defs(jd, jlumps, 'TEXTURE1') or []
    jt2 = read_texture_defs(jd, jlumps, 'TEXTURE2') or []

    jag_patches = lumps_between(jlumps, 'PP_START', 'PP_END')
    jag_flats = lumps_between(jlumps, 'FF_START', 'F_END')
    jag_patch_payload = {nm: jd[fp:fp + sz] for nm, fp, sz in jag_patches}

    base_names = {nm for _, _, nm in base_lumps}
    base_flat_names = {nm for nm, _, _ in lumps_between(base_lumps, 'F_START', 'F_END')}
    available = base_names | set(jag_patch_payload)

    # Rewrite any texture whose patch art is not shippable: prefer aliasing to the
    # closest available texture (real art at the right size, see the table above),
    # and only when no substitute exists fall back to a solid opaque filler so it
    # stays a wall of the right size (no hall-of-mirrors, no bad switch).
    byname = {d['name']: d for d in jt1 + jt2}

    def tex_ok(d):
        return all(p[2] and p[2] in available for p in d['patches'])

    rebuilt = subbed = 0
    for d in jt1 + jt2:
        if tex_ok(d):
            continue
        sub = byname.get(JAGUAR_FILLER_TEXTURE_SUB.get(d['name'], ''))
        if sub is not None and sub is not d and tex_ok(sub):
            d['patches'] = tile_patches(sub, d['w'], d['h'])
            subbed += 1
        else:
            d['patches'] = [(0, 0, FILLER_PATCH_NAME)]
            rebuilt += 1

    used_pnames = []
    seen = set()
    for d in jt1 + jt2:
        for (_, _, pn) in d['patches']:
            if pn not in seen:
                seen.add(pn)
                used_pnames.append(pn)
    pindex = {pn: i for i, pn in enumerate(used_pnames)}

    tex1_bytes = serialize_textures(jt1, pindex)
    tex2_bytes = serialize_textures(jt2, pindex)
    pnames_bytes = serialize_pnames(used_pnames)
    filler_bytes = make_filler_patch(256, 128, FILLER_COLOR)

    # Build the new lump list from the base entries: replace the texture tables and
    # PNAMES, insert jaguar wall patches (P namespace) and flats (F namespace).
    jag_new_patches = [(nm, jag_patch_payload[nm]) for nm in jag_patch_payload
                       if nm not in base_names]
    jag_override = {nm: jag_patch_payload[nm] for nm in jag_patch_payload
                    if nm in base_names}
    jag_new_flats = [(nm, jd[fp:fp + sz]) for nm, fp, sz in jag_flats
                     if nm not in base_flat_names]

    entries = []
    for fp, sz, nm in base_lumps:
        if nm == 'TEXTURE1':
            entries.append(('TEXTURE1', tex1_bytes))
            entries.append(('TEXTURE2', tex2_bytes))
            continue
        if nm == 'PNAMES':
            entries.append(('PNAMES', pnames_bytes))
            continue
        if nm == 'P_END':
            for pn, pl in jag_new_patches:
                entries.append((pn, pl))
            entries.append((FILLER_PATCH_NAME, filler_bytes))
            entries.append((nm, base_data[fp:fp + sz]))
            continue
        if nm == 'F_END':
            for fn, fl in jag_new_flats:
                entries.append((fn, fl))
            entries.append((nm, base_data[fp:fp + sz]))
            continue
        payload = jag_override.get(nm, base_data[fp:fp + sz])
        entries.append((nm, payload))

    print(f'  jaguar textures: {len(jt1)}+{len(jt2)} defs '
          f'({subbed} aliased to available art, {rebuilt} filler-rebuilt), '
          f'+{len(jag_new_patches)} patches, +{len(jag_new_flats)} flats merged')
    data = assemble_iwad(entries)
    _, lumps = read_dir(data)
    return data, lumps


FLAT_ANIMS = [
    ('NUKAGE1', 'NUKAGE3'), ('FWATER1', 'FWATER4'), ('SWATER1', 'SWATER4'),
    ('LAVA1', 'LAVA4'), ('BLOOD1', 'BLOOD3'),
    ('SLIME01', 'SLIME04'), ('SLIME05', 'SLIME08'), ('SLIME09', 'SLIME12'),
]
TEX_ANIMS = [
    ('BLODGR1', 'BLODGR4'), ('SLADRIP1', 'SLADRIP3'),
    ('BLODRIP1', 'BLODRIP4'), ('FIREWALA', 'FIREWALL'),
    ('GSTFONT1', 'GSTFONT3'), ('FIRELAV3', 'FIRELAVA'),
    ('FIREMAG1', 'FIREMAG3'), ('FIREBLU1', 'FIREBLU2'),
    ('ROCKRED1', 'ROCKRED3'), ('BFALL1', 'BFALL4'),
    ('SFALL1', 'SFALL4'), ('WFALL1', 'WFALL4'), ('DBRAIN1', 'DBRAIN4'),
]
KEEP_TEXTURES = {'SKY1', 'SKY2', 'SKY3', 'SKY4'}
KEEP_FLATS = {'F_SKY1', 'FLOOR4_8', 'SFLR6_1', 'MFLR8_4', 'MFLR8_3'}
SWITCH_PAIRS = [('SW1' + s, 'SW2' + s) for s in (
    'BRCOM', 'BRN1', 'BRN2', 'BRNGN', 'BROWN', 'COMM', 'COMP', 'DIRT', 'EXIT',
    'GRAY', 'GRAY1', 'METAL', 'PIPE', 'SLAD', 'STARG', 'STON1', 'STON2', 'STONE',
    'STRTN', 'BLUE', 'CMT', 'GARG', 'GSTON', 'HOT', 'LION', 'SATYR', 'SKIN',
    'VINE', 'WOOD', 'PANEL', 'ROCK', 'MET2', 'WDMET', 'BRIK', 'MOD1', 'ZIM', 'STON6',
    'TEK', 'MARB', 'SKULL')]


def _range_between(names_in_order, start, end):
    try:
        i, j = names_in_order.index(start), names_in_order.index(end)
    except ValueError:
        return []
    return names_in_order[i:j + 1] if i <= j else []


def expand_solid_wall_refs(names, texorder):
    """Add runtime texture states reachable from solid map references.

    The renderer's dense-wall tier deliberately has no page-presence fallback.
    A map may initially name one frame of an animation or one side of a switch,
    then replace it at runtime.  Restrict expansion to textures present in this
    WAD: episode-specific switch pairs which are absent cannot be selected by
    P_InitSwitchList either.
    """
    used = set(names)
    available = set(texorder)

    for start, end in TEX_ANIMS:
        family = _range_between(texorder, start, end)
        if family and used.intersection(family):
            used.update(family)

    for first, second in SWITCH_PAIRS:
        if first in available and second in available and (first in used or second in used):
            used.add(first)
            used.add(second)

    return used


def collect_map_refs(data, lumps):
    used_tex, used_flat = set(), set()
    def nm8(off):
        return data[off:off + 8].split(b'\x00', 1)[0].decode('latin1').upper()
    for i, (fp, sz, name) in enumerate(lumps):
        if not is_map_marker(name):
            continue
        sfp, ssz, _ = lumps[i + ML_SIDEDEFS]
        for k in range(ssz // 30):
            for toff in (4, 12, 20):
                t = nm8(sfp + k * 30 + toff)
                if t and t != '-':
                    used_tex.add(t)
        cfp, csz, _ = lumps[i + ML_SECTORS]
        for k in range(csz // 26):
            for foff in (4, 12):
                used_flat.add(nm8(cfp + k * 26 + foff))
    return used_tex, used_flat


def _solid_wall_refs_one(data, lumps, marker_idx, used):
    """Accumulate opaque-tier wall textures from one map's raw lumps into `used`.

    Top and bottom textures are opaque tiers on either kind of line. A middle
    texture is opaque only on a one-sided line; two-sided middles retain Doom's
    post mask and are handled by the separate masked renderer.
    """
    side_fp, side_size, _ = lumps[marker_idx + ML_SIDEDEFS]
    line_fp, line_size, _ = lumps[marker_idx + ML_LINEDEFS]
    num_sides = side_size // 30

    def side_name(side, field_offset):
        off = side_fp + side * 30 + field_offset
        return data[off:off + 8].split(b'\x00', 1)[0].decode('latin1').upper()

    for line in range(line_size // 14):
        flags, side0, side1 = struct.unpack_from('<HxxxxHH', data,
                                                 line_fp + line * 14 + 4)
        two_sided = bool(flags & ML_TWOSIDED) and side1 != NO_INDEX
        for side in (side0, side1):
            if side == NO_INDEX or side >= num_sides:
                continue
            fields = (4, 12) if two_sided else (4, 12, 20)
            for field in fields:
                texture = side_name(side, field)
                if texture and texture != '-':
                    used.add(texture)


def collect_solid_wall_refs(data, lumps, map_overrides=None):
    """Textures that can enter the opaque wall-tier renderer.

    For overlaid maps the FINAL geometry is the overlay's, so read that map's
    sidedefs from the overlay WAD rather than the (soon-discarded) base map.
    """
    map_overrides = map_overrides or {}
    used = set()
    for i, (fp, size, name) in enumerate(lumps):
        if not is_map_marker(name):
            continue
        overlay = map_overrides.get(i)
        if overlay is not None:
            ov_data, ov_lumps, ov_idx = overlay
            _solid_wall_refs_one(ov_data, ov_lumps, ov_idx, used)
        else:
            _solid_wall_refs_one(data, lumps, i, used)
    return used


def _section_names(lumps, start, end):
    out, inside = [], False
    for _, _, nm in lumps:
        if nm == start:
            inside = True; continue
        if nm == end:
            break
        if inside and not (nm.endswith('_START') or nm.endswith('_END')):
            out.append(nm)
    return out


def compute_keep_sets(data, lumps, texorder, texpatches):
    used_tex, used_flat = collect_map_refs(data, lumps)
    used_tex |= KEEP_TEXTURES
    used_flat |= KEEP_FLATS
    for start, end in TEX_ANIMS:
        fam = _range_between(texorder, start, end)
        if used_tex & set(fam):
            used_tex |= set(fam)
    for a, b in SWITCH_PAIRS:
        if a in used_tex or b in used_tex:
            used_tex |= {a, b}
    keep_patches = set()
    for t in used_tex:
        keep_patches |= texpatches.get(t, set())
    flat_order = _section_names(lumps, 'F_START', 'F_END')
    for start, end in FLAT_ANIMS:
        fam = _range_between(flat_order, start, end)
        if used_flat & set(fam):
            used_flat |= set(fam)
    keep_flats = set(used_flat)
    return keep_patches, keep_flats


def cull_unreferenced(data, lumps, texorder, texpatches):
    keep_patches, keep_flats = compute_keep_sets(data, lumps, texorder, texpatches)
    patch_lumps = set(_section_names(lumps, 'P_START', 'P_END'))
    flat_lumps = set(_section_names(lumps, 'F_START', 'F_END'))
    out, dropped_p, dropped_f, kb = [], 0, 0, 0
    for fp, sz, nm in lumps:
        if nm in patch_lumps and nm not in keep_patches:
            dropped_p += 1; kb += sz; continue
        if nm in flat_lumps and nm not in keep_flats:
            dropped_f += 1; kb += sz; continue
        out.append((fp, sz, nm))
    kept_p = sorted(n for n in patch_lumps if n in keep_patches)
    kept_f = sorted(n for n in flat_lumps if n in keep_flats)
    missing = [n for n in keep_flats if n in flat_lumps and n not in set(n2 for _, _, n2 in out)]
    if missing:
        sys.exit(f'cull bug: referenced flats dropped: {missing}')
    print(f'  cull: dropped {dropped_p} patches + {dropped_f} flats = {kb/1024:.0f} KB '
          f'(kept {len(kept_p)}/{len(patch_lumps)} patches, {len(kept_f)}/{len(flat_lumps)} flats)')
    return out


def tex_index(name_bytes, texmap):
    name = name_bytes.split(b'\x00', 1)[0].decode('latin1').upper()
    if name == '-' or name == '':
        return NO_TEXTURE
    return texmap.get(name, NO_TEXTURE)


# --- index-0 remap -----------------------------------------------------------
# On the PC-FX, palette index 0 is hijacked to mean TRANSPARENT (the HuC6271
# RAINBOW sky, and the black backdrop, show through it). Doom art, however, uses
# index 0 as an ordinary opaque colour (pure black in the stock PLAYPAL), so any
# index-0 texel in a sprite/texture/flat/HUD graphic would punch a see-through
# hole in that pixel at runtime — the sky/backdrop bleeding through solid art.
#
# The fix belongs in the converter, not the engine: rewrite every index-0 texel
# in the graphic lumps to the closest non-zero palette entry (in the stock PLAYPAL
# that is index 247 == (0,0,0), a bit-for-bit black twin), so the pixel looks
# identical but is opaque. Column (patch) transparency is unaffected: it is encoded
# by the post structure (gaps between posts), which we never touch — only the
# opaque pixel bytes inside posts are remapped.
#
# The COLORMAP has the same problem from the other direction: it is an index->index
# table (light levels + the invulnerability map) and its darker levels fold most
# colours down to index 0 (up to 144/256 at the darkest level) because index 0 is
# black in RGB. On the PC-FX that makes distant/dark geometry TRANSPARENT — the sky
# and backdrop punch through solid walls and floors, and during a damage/pickup
# palette fade the dark areas show the untinted sky instead of the tint. So the
# colormap is remapped the same way: every output index 0 -> the opaque black twin,
# so darkness renders as solid black (as intended) rather than a see-through hole.

DATA_LUMPS_NO_REMAP = {'PLAYPAL', 'PNAMES', 'TEXTURE1', 'TEXTURE2',
                       'ENDOOM', 'GENMIDI', 'DMXGUS'}
# Raw 8bpp images that are NOT in Doom's column/post format (so remap byte-wise).
RAW_IMAGE_LUMPS = {'STBARFX'}
# Index->index tables whose OUTPUT bytes must avoid index 0 (== transparent).
INDEX_TABLE_LUMPS = {'COLORMAP'}

# Doom's COLORMAP is 34 index->index maps of 256 bytes: 32 diminishing-light
# levels (0 = full bright .. 31 = darkest), then the invulnerability map and a
# spare. Only the light levels are rebuilt below; the rest are left byte-for-byte.
COLORMAP_LIGHT_LEVELS = 32


def _hue_deg(c):
    """Hue angle 0..360 of an (r,g,b) triple; 0 for a neutral grey."""
    r, g, b = c[0] / 255.0, c[1] / 255.0, c[2] / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d <= 0:
        return 0.0
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return h * 60.0


def _hue_dist(a, b):
    d = abs(a - b)
    return min(d, 360.0 - d)


def rebuild_colormap_hue(pal0, cm, luma_tol=10, sat_lo=0.20, sat_hi=0.50,
                         grey_out_sat=24, hue_limit=32.0, min_src_sat=18,
                         min_out_luma=26):
    """General fix for the 'grey speckle on coloured walls' colormap degradation.

    Doom's COLORMAP was built by darkening each palette colour and snapping to the
    NEAREST palette index in RGB. For a coloured ramp (browns, reds) the nearest
    match to a darkened shade is often a neutral GREY (the palette has a dense grey
    ramp but few dark saturated colours), so a diminished brown wall collapses,
    texel by texel, to a salt-and-pepper mix of brown and grey. On the PC-FX's
    coarse 4-bit chroma that grey speckle is glaring (see the distant techbase
    walls). It is baked into the stock lump so it must be corrected once here,
    generally, not per-texture at runtime.

    The rule is deliberately surgical -- it only UN-GREYS, it never recolours a
    shade vanilla already kept coloured (doing so drifts good tans toward green):

      * act only when vanilla's output for this (level, index) is DESATURATED
        (saturation < grey_out_sat) -- i.e. exactly the speckle;
      * act only when the SOURCE colour is meaningfully saturated -- a chroma gate
        on the source's saturation fraction (0 below sat_lo, full at/above sat_hi)
        leaves pale near-white highlights on the vanilla grey pick, so nothing pale
        is pushed into a false saturated colour (no orange/pink pop);
      * act only when vanilla's grey output is bright enough to still read as a lit
        surface (luma >= min_out_luma). In deep shadow the palette folds every warm
        colour to near-black anyway; re-colouring those to a dark brown just sprinkles
        brown speckle onto surfaces that should read as uniform shadow (e.g. the far
        techbase floor), so those are left as vanilla's dark grey;
      * the replacement keeps vanilla's brightness (search is limited to candidates
        within +/-luma_tol of the vanilla output's luma) and must share the source's
        hue to within hue_limit degrees, so a brown re-picks a darker BROWN and can
        never flip to green.

    Near-grey sources (saturation < min_src_sat) are skipped outright. Returns the
    rebuilt bytes (index 0 may still appear as an output and is remapped to the
    opaque twin afterwards)."""
    if len(cm) < COLORMAP_LIGHT_LEVELS * 256:
        return cm                                  # not a colormap we recognise

    def rgb(i):
        return (pal0[i * 3], pal0[i * 3 + 1], pal0[i * 3 + 2])

    def lu(c):
        return (c[0] + c[1] + c[2]) / 3.0

    def sat(c):
        return max(c) - min(c)

    # Precompute each candidate index's (luma, chroma vector, saturation, hue).
    cand = []
    for j in range(256):
        c = rgb(j)
        l = lu(c)
        cand.append((l, c[0] - l, c[1] - l, c[2] - l, sat(c), _hue_deg(c)))

    out = bytearray(cm)
    changed = 0
    for lvl in range(COLORMAP_LIGHT_LEVELS):
        base = lvl * 256
        for idx in range(256):
            src = rgb(idx)
            if sat(src) < min_src_sat:
                continue                           # near-grey source -> keep vanilla
            m = out[base + idx]
            mc = rgb(m)
            if sat(mc) >= grey_out_sat:
                continue                           # vanilla kept it coloured -> leave it
            ml = lu(mc)                            # keep vanilla's brightness
            if ml < min_out_luma:
                continue                           # deep shadow: leave it dark, don't
                                                   # sprinkle brown onto near-black surfaces
            srcl = lu(src)
            mx = max(src)
            sf = (sat(src) / mx) if mx else 0.0     # source saturation fraction
            k = (sf - sat_lo) / (sat_hi - sat_lo)   # chroma gate: 0 (pale) .. 1 (saturated)
            k = 0.0 if k < 0.0 else (1.0 if k > 1.0 else k)
            if k <= 0.0:
                continue                           # pale source -> keep the grey pick
            src_hue = _hue_deg(src)
            tcr, tcg, tcb = (src[0] - srcl) * k, (src[1] - srcl) * k, (src[2] - srcl) * k
            best, bj = 1e18, m
            for j in range(256):
                jl, jcr, jcg, jcb, jsat, jhue = cand[j]
                if abs(jl - ml) > luma_tol:
                    continue
                if jsat >= 8 and _hue_dist(jhue, src_hue) > hue_limit:
                    continue                       # forbid a hue flip (e.g. brown->green)
                e = 0.15 * (jl - ml) ** 2 + ((jcr - tcr) ** 2 +
                                             (jcg - tcg) ** 2 + (jcb - tcb) ** 2)
                if e < best:
                    best, bj = e, j
            if bj != m:
                out[base + idx] = bj
                changed += 1
    print(f'  colormap: hue-restored {changed} grey speckle entries '
          f'(coloured shades diminish through their hue, not to grey)')
    return bytes(out)


def read_playpal0(data, lumps):
    li = lump_index(lumps, 'PLAYPAL')
    if li < 0:
        return None
    fp, _, _ = lumps[li]
    return data[fp:fp + 768]


def pick_safe_index(pal0):
    r0, g0, b0 = pal0[0], pal0[1], pal0[2]
    best_i, best_d = 1, 1 << 30
    for i in range(1, 256):
        r, g, b = pal0[i * 3], pal0[i * 3 + 1], pal0[i * 3 + 2]
        d = (r - r0) ** 2 + (g - g0) ** 2 + (b - b0) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def remap_raw(payload, safe):
    n = payload.count(0)
    if not n:
        return payload, 0
    # translate table: 0 -> safe, every other index unchanged
    table = bytes([safe] + list(range(1, 256)))
    return payload.translate(table), n


def pick_grey_for(pal0, idx):
    """Nearest true-grey (R==G==B) palette entry to colour `idx`, matched on luma —
    used to neutralise a dark-brown accent in a grey wall texture."""
    r, g, b = pal0[idx * 3], pal0[idx * 3 + 1], pal0[idx * 3 + 2]
    best_i, best_d = idx, 1 << 30
    for i in range(1, 256):
        rr, gg, bb = pal0[i * 3], pal0[i * 3 + 1], pal0[i * 3 + 2]
        if rr == gg == bb:                        # only the neutral-grey ramp
            d = (rr - r) ** 2 + (gg - g) ** 2 + (bb - b) ** 2
            if d < best_d:
                best_d, best_i = d, i
    return best_i


# Textures the PC-FX shows as an over-saturated brown that should instead read as
# grey (they are brown in the IWAD but on the 4-bit-chroma display their dark shades
# render orange and pop against surrounding grey; see the "brown step beam"). Each
# is recoloured to its grey-by-luma equivalent at bake time. Extend as needed.
GREY_TEXTURES = {'STEP6'}


def build_to_grey(pal0, safe):
    """256-entry table mapping each palette index to the neutral-grey entry of the
    same luma (0 -> safe). Recolours a coloured texture to greyscale, brightness
    preserved."""
    greys = [i for i in range(1, 256)
             if pal0[i * 3] == pal0[i * 3 + 1] == pal0[i * 3 + 2]]
    tbl = bytearray(256)
    tbl[0] = safe
    for i in range(1, 256):
        y = (77 * pal0[i * 3] + 150 * pal0[i * 3 + 1] + 29 * pal0[i * 3 + 2]) >> 8
        tbl[i] = min(greys, key=lambda g: abs(pal0[g * 3] - y))
    return bytes(tbl)


def greyable_patches(grey_textures, texpatches, used_tex):
    """Patches of `grey_textures` that no OTHER used texture needs (safe to recolour
    in place). Patches shared with a kept non-grey texture are skipped (they would
    need a private copy) and reported."""
    patch_users = {}
    for tex, ps in texpatches.items():
        for p in ps:
            patch_users.setdefault(p, set()).add(tex)
    safe, shared = set(), set()
    for tex in grey_textures:
        for p in texpatches.get(tex, ()):
            others = (patch_users.get(p, set()) - grey_textures) & used_tex
            (shared if others else safe).add(p)
    return safe, shared


def remap_patch(payload, table):
    """Remap patch texels through `table` (256-entry index->index). Returns
    (bytes, count), or (None, 0) if the lump is not a valid patch."""
    if len(payload) < 8:
        return None, 0
    w, h, _lo, _to = struct.unpack_from('<hhhh', payload, 0)
    if not (1 <= w <= 4096 and 1 <= h <= 4096):
        return None, 0
    if len(payload) < 8 + 4 * w:
        return None, 0
    colofs = struct.unpack_from('<%di' % w, payload, 8)
    buf = bytearray(payload)
    n = len(payload)
    cnt = 0
    for c in range(w):
        o = colofs[c]
        if o < 0 or o >= n:
            return None, 0
        while True:
            if o >= n:
                return None, 0
            topdelta = buf[o]
            if topdelta == 0xff:
                break
            if o + 1 >= n:
                return None, 0
            length = buf[o + 1]
            start = o + 3                 # skip topdelta, length, leading pad
            end = start + length
            if end + 1 > n:               # need the trailing pad byte too
                return None, 0
            for k in range(start, end):
                t = table[buf[k]]
                if t != buf[k]:
                    buf[k] = t
                    cnt += 1
            o = end + 1                   # skip trailing pad
    return bytes(buf), cnt


# --- PC-FX 32x64 8bpp texture pages -----------------------------------------

def decode_patch_image(payload):
    """Decode a Doom patch into row-major indices plus an independent opacity mask.

    The mask matters because palette index 0 is a real opaque Doom colour before
    --fix-index0. It must not be confused with a gap between posts when deciding
    whether a wall can use the dense (unmasked) PC-FX path.
    """
    if len(payload) < 8:
        raise ValueError('short patch header')
    w, h, _left, _top = struct.unpack_from('<hhhh', payload, 0)
    if not (1 <= w <= 4096 and 1 <= h <= 4096) or len(payload) < 8 + 4 * w:
        raise ValueError('invalid patch dimensions')
    offsets = struct.unpack_from('<%dI' % w, payload, 8)
    pixels = bytearray(w * h)
    opaque = bytearray(w * h)
    for x, start in enumerate(offsets):
        o = start
        previous_top = -1
        while True:
            if o >= len(payload):
                raise ValueError('column outside patch')
            top = payload[o]
            if top == 0xff:
                break
            if o + 3 > len(payload):
                raise ValueError('short post header')
            length = payload[o + 1]
            # Boom tall-patch convention: a non-increasing delta continues from
            # the previous post instead of restarting at the top of the image.
            if top <= previous_top:
                top += previous_top
            previous_top = top
            src = o + 3
            if src + length + 1 > len(payload):
                raise ValueError('short post data')
            for k in range(length):
                y = top + k
                if 0 <= y < h:
                    pixels[y * w + x] = payload[src + k]
                    opaque[y * w + x] = 1
            o = src + length + 1
    return w, h, pixels, opaque


def _nearest_palette_index(rgb, pal, cache):
    found = cache.get(rgb)
    if found is not None:
        return found
    r, g, b = rgb
    found = min(range(256), key=lambda i: (pal[i * 3] - r) ** 2 +
                (pal[i * 3 + 1] - g) ** 2 + (pal[i * 3 + 2] - b) ** 2)
    cache[rgb] = found
    return found


def load_png_indices(path, pal):
    """Load a PNG as PLAYPAL indices and retain alpha as an opacity mask."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit(f'{path}: Pillow is required for PNG texture overrides')
    im = Image.open(path)
    w, h = im.size
    def image_data(image):
        getter = getattr(image, 'get_flattened_data', image.getdata)
        return list(getter())
    direct = None
    if im.mode == 'P':
        pp = im.getpalette() or []
        if len(pp) >= 768 and all(pp[i] == pal[i] for i in range(768)):
            direct = image_data(im)
    rgba = image_data(im.convert('RGBA'))
    cache = {}
    pixels = bytearray(w * h)
    opaque = bytearray(w * h)
    for i, (r, g, b, a) in enumerate(rgba):
        if a < 128:
            continue
        opaque[i] = 1
        pixels[i] = direct[i] if direct is not None else _nearest_palette_index((r, g, b), pal, cache)
    return w, h, pixels, opaque


def resample_nearest(pixels, width, height, out_w=PCFX_TEX_W, out_h=PCFX_TEX_H):
    """Nearest-neighbour stretch. This preserves crisp indexed Doom artwork."""
    out = bytearray(out_w * out_h)
    for y in range(out_h):
        sy = min(height - 1, y * height // out_h)
        for x in range(out_w):
            sx = min(width - 1, x * width // out_w)
            out[y * out_w + x] = pixels[sy * width + sx]
    return bytes(out)


def parse_png_specs(specs):
    out = {}
    for spec in specs:
        name, sep, path = spec.partition('=')
        if not sep or not name or not path:
            sys.exit(f'bad PNG override {spec!r}; expected NAME=FILE.png')
        out[name.upper()[:8]] = path
    return out


def _png_override(name, explicit, png_dir):
    path = explicit.get(name.upper())
    if path:
        return path
    if png_dir:
        candidate = os.path.join(png_dir, name + '.png')
        if os.path.isfile(candidate):
            return candidate
    return None


def build_pcfx_texture_pages(entries, png_dir=None, texture_png=None, flat_png=None):
    """Build optional dense PC-FX pages while retaining every original WAD lump.

    Wall pages are 32 columns x 64 rows, column-major. Flat pages are row-major,
    matching the span drawer. Both are exactly 2048 bytes. Every fully opaque
    wall receives a page, including short STEP textures: the PC-FX solid-wall
    renderer treats page availability as a build-time invariant. Masked walls
    retain their original posts for the separate masked-middle renderer.
    """
    texture_png = texture_png or {}
    flat_png = flat_png or {}
    by_name = {}
    for name, payload in entries:
        by_name[name.upper()] = payload
    pal = by_name.get('PLAYPAL', b'')[:768]
    if len(pal) != 768:
        sys.exit('--pcfx-textures: PLAYPAL is missing or malformed')
    pnames_raw = by_name.get('PNAMES')
    if not pnames_raw or len(pnames_raw) < 4:
        sys.exit('--pcfx-textures: PNAMES is missing or malformed')
    npnames = struct.unpack_from('<I', pnames_raw, 0)[0]
    pnames = [pnames_raw[4 + i * 8:12 + i * 8].split(b'\0', 1)[0].decode('latin1').upper()
              for i in range(npnames)]

    pages = []
    wall_total = wall_built = wall_masked = wall_bad = 0
    tex_index = 0
    for lump_name in ('TEXTURE1', 'TEXTURE2'):
        table = by_name.get(lump_name)
        if not table:
            continue
        count = struct.unpack_from('<I', table, 0)[0]
        for n in range(count):
            off = struct.unpack_from('<I', table, 4 + n * 4)[0]
            if off + 22 > len(table):
                wall_bad += 1; tex_index += 1; continue
            name = table[off:off + 8].split(b'\0', 1)[0].decode('latin1').upper()
            width, height = struct.unpack_from('<hh', table, off + 12)
            patch_count = struct.unpack_from('<h', table, off + 20)[0]
            png = _png_override(name, texture_png, png_dir)
            wall_total += 1
            try:
                if png:
                    sw, sh, canvas, coverage = load_png_indices(png, pal)
                else:
                    sw, sh = width, height
                    if sw <= 0 or sh <= 0 or sw * sh > 16 * 1024 * 1024:
                        raise ValueError('invalid composite dimensions')
                    canvas = bytearray(sw * sh)
                    coverage = bytearray(sw * sh)
                    for p in range(patch_count):
                        po = off + 22 + p * 10
                        if po + 10 > len(table):
                            raise ValueError('short texture patch record')
                        ox, oy, patch_idx = struct.unpack_from('<hhh', table, po)
                        if patch_idx < 0 or patch_idx >= len(pnames):
                            raise ValueError('PNAMES index outside table')
                        payload = by_name.get(pnames[patch_idx])
                        if payload is None:
                            raise ValueError('missing patch ' + pnames[patch_idx])
                        pw, ph, pix, mask = decode_patch_image(payload)
                        for py in range(ph):
                            dy = oy + py
                            if dy < 0 or dy >= sh:
                                continue
                            for px in range(pw):
                                dx = ox + px
                                si = py * pw + px
                                if 0 <= dx < sw and mask[si]:
                                    di = dy * sw + dx
                                    canvas[di] = pix[si]
                                    coverage[di] = 1
                if not all(coverage):
                    wall_masked += 1
                    tex_index += 1
                    continue
                row_major = resample_nearest(canvas, sw, sh)
                column_major = bytearray(PCFX_TEX_BYTES)
                for x in range(PCFX_TEX_W):
                    for y in range(PCFX_TEX_H):
                        column_major[x * PCFX_TEX_H + y] = row_major[y * PCFX_TEX_W + x]
                pages.append((pcfx_wall_lump_name(tex_index), bytes(column_major)))
                wall_built += 1
            except (ValueError, struct.error) as exc:
                print(f'  pcfx texture: {name} fallback ({exc})')
                wall_bad += 1
            tex_index += 1

    flat_total = flat_built = flat_bad = 0
    inside = False
    flat_index = 0
    for name, payload in entries:
        up = name.upper()
        if up in ('F_START', 'FF_START'):
            inside = True
            continue
        if up in ('F_END', 'FF_END'):
            inside = False
            continue
        if not inside:
            continue
        # R_InitFlats numbers every lump between F_START and F_END, including
        # nested namespace markers such as Doom's F1_START/F1_END. Preserve
        # those holes in PFT numbering or every optimized flat after the marker
        # is paired with the wrong runtime flat (most visibly, ceilings).
        if up.endswith('_START') or up.endswith('_END'):
            flat_index += 1
            continue
        png = _png_override(up, flat_png, png_dir)
        try:
            if png:
                fw, fh, fpix, _mask = load_png_indices(png, pal)
            else:
                side = math.isqrt(len(payload))
                if side * side != len(payload):
                    raise ValueError(f'non-square raw flat ({len(payload)} bytes)')
                fw = fh = side
                fpix = payload
            if fw > PCFX_TEX_W or fh > PCFX_TEX_H or png:
                flat_total += 1
                pages.append((pcfx_flat_lump_name(flat_index),
                              resample_nearest(fpix, fw, fh)))
                flat_built += 1
        except (ValueError, struct.error) as exc:
            flat_bad += 1
            print(f'  pcfx flat: {up} fallback ({exc})')
        flat_index += 1

    assert all(len(payload) == PCFX_TEX_BYTES for _name, payload in pages)
    print(f'  pcfx 32x64x8: walls {wall_built}/{wall_total} pages '
          f'({wall_masked} masked fallback, {wall_bad} invalid), '
          f'flats {flat_built}/{flat_total} pages ({flat_bad} invalid)')
    return pages


def fix_index0_entries(entries, safe, flat_names, wall_names, grey_patches, pal0):
    """Rewrite index-0 texels to `safe` across every graphic entry, neutralise the
    two darkest-brown palette entries (idx 1, 2) to grey in WALL PATCHES, and fully
    recolour the GREY_TEXTURES' patches (grey_patches) to greyscale.

    Those entries can't be shown as muted dark brown on the PC-FX (the 4-bit chroma
    forces grey or an over-saturated orange). In grey tech wall textures the idx-1/2
    dark accent rendered orange and popped against the grey; greying it makes it
    blend. A few whole textures (GREY_TEXTURES, e.g. the brown STEP6 step beam) read
    as an orange strip against grey and are recoloured to grey-by-luma. Flats (brown
    floors) and SPRITES/fonts keep idx 1/2 so their brown shading stays brown, and
    the colormap still darkens brown surfaces toward idx 1/2, so distant browns stay
    brown. Map data and palettes are left byte-for-byte identical."""
    g1, g2 = pick_grey_for(pal0, 1), pick_grey_for(pal0, 2)
    wall_tbl = bytes([safe, g1, g2] + list(range(3, 256)))   # neutralise idx 1/2
    keep_tbl = bytes([safe] + list(range(1, 256)))           # only fix index 0
    grey_tbl = build_to_grey(pal0, safe)                     # full greyscale recolour
    total_px = greyed = 0
    remapped = 0
    for i, (name, payload) in enumerate(entries):
        up = name.upper()
        if (not payload or up in DATA_LUMPS_NO_REMAP or is_map_marker(name)
                or up in MAP_SUBLUMPS or up.endswith('_START') or up.endswith('_END')
                or is_audio(name)):
            continue
        if up in flat_names or up in RAW_IMAGE_LUMPS or up in INDEX_TABLE_LUMPS:
            new = payload.translate(keep_tbl)
            n = sum(1 for a, b in zip(payload, new) if a != b)
        else:
            tbl = grey_tbl if up in grey_patches else (wall_tbl if up in wall_names else keep_tbl)
            new, n = remap_patch(payload, tbl)
            if new is None:               # not a patch -> don't touch it
                continue
            if up in grey_patches:
                greyed += 1
        if n:
            entries[i] = (name, new)
            total_px += n
            remapped += 1
    print(f'  index0: remapped {total_px} texels across {remapped} graphic lumps '
          f'(safe={safe}, wall idx1/2 -> grey {g1}/{g2}, {greyed} patches greyscaled)')


def repack_map(data, lumps, marker_idx, texmap, flat_names=None):
    def sub(off):
        fp, sz, _ = lumps[marker_idx + off]
        return data[fp:fp + sz]

    vraw = sub(ML_VERTEXES)
    lraw = sub(ML_LINEDEFS)
    sraw = sub(ML_SIDEDEFS)
    graw = sub(ML_SEGS)
    braw = sub(ML_BLOCKMAP)
    secraw = bytearray(sub(ML_SECTORS))
    _, sec_sz, _ = lumps[marker_idx + ML_SECTORS]
    numsectors = sec_sz // 26

    # The Jaguar TC PWAD expects a registered IWAD's flat namespace.  A normal
    # map never enters this path; only an overlaid map receives the shareware-safe
    # aliases, and only when its requested flat is actually absent from the base.
    flat_remaps = []
    if flat_names is not None:
        fallback = 'FLAT5_5' if 'FLAT5_5' in flat_names else next(iter(flat_names))
        for i in range(numsectors):
            for off in (4, 12):
                p = i * 26 + off
                name = bytes(secraw[p:p + 8]).split(b'\x00', 1)[0].decode('latin1').upper()
                if name and name not in flat_names:
                    mapped = JAGUAR_SHAREWARE_FLAT_REMAP.get(name, fallback)
                    if mapped not in flat_names:
                        mapped = fallback
                    secraw[p:p + 8] = mapped.encode('latin1').ljust(8, b'\x00')
                    flat_remaps.append((name, mapped))
        if flat_remaps:
            changes = ', '.join(f'{src}->{dst}' for src, dst in sorted(set(flat_remaps)))
            print(f'  map {lumps[marker_idx][2]}: shareware flat fallback(s): {changes}')

    # BLOCKMAP is all int16. V810/LE: keep verbatim. Big-endian host: swap.
    nshort = len(braw) // 2
    if E == '<':
        out_blockmap = braw[:nshort * 2]
    else:
        out_blockmap = struct.pack('>%dH' % nshort, *struct.unpack('<%dH' % nshort, braw[:nshort * 2]))

    nverts = len(vraw) // 4
    fverts = []
    for i in range(nverts):
        x, y = struct.unpack_from('<hh', vraw, i * 4)
        fverts.append((x << FRACBITS, y << FRACBITS))

    # The Jaguar TC PWAD expects a registered IWAD's wall-texture namespace.  As
    # with the flats above, only an overlaid map takes this path, and only a name
    # actually absent from the base is aliased to a shareware-safe opaque texture;
    # a name the base provides is left untouched (registered IWADs never remap).
    tex_remaps = []
    tex_available = texmap if flat_names is not None else None
    tex_fallback = 'GRAY5' if (tex_available and 'GRAY5' in tex_available) else None

    def side_tex(name_bytes):
        if tex_available is None:
            return name_bytes
        name = name_bytes.split(b'\x00', 1)[0].decode('latin1').upper()
        if not name or name == '-' or name in tex_available:
            return name_bytes
        mapped = JAGUAR_SHAREWARE_TEX_REMAP.get(name, tex_fallback)
        if mapped not in tex_available:
            mapped = tex_fallback or name
        tex_remaps.append((name, mapped))
        return mapped.encode('latin1').ljust(8, b'\x00')

    nsides = len(sraw) // 30
    side_sector = []
    out_sidedefs = bytearray()
    for i in range(nsides):
        b = i * 30
        toff, roff = struct.unpack_from('<hh', sraw, b)
        top = side_tex(sraw[b + 4:b + 12])
        bot = side_tex(sraw[b + 12:b + 20])
        mid = side_tex(sraw[b + 20:b + 28])
        sector = struct.unpack_from('<h', sraw, b + 28)[0]
        if sector < 0 or sector >= numsectors:
            sector = 0
        side_sector.append(sector)
        out_sidedefs += struct.pack(E + 'hhhhhh', toff, roff,
                                    tex_index(top, texmap),
                                    tex_index(bot, texmap),
                                    tex_index(mid, texmap),
                                    sector)
    if tex_remaps:
        changes = ', '.join(f'{src}->{dst}' for src, dst in sorted(set(tex_remaps)))
        print(f'  map {lumps[marker_idx][2]}: shareware texture fallback(s): {changes}')

    nlines = len(lraw) // 14
    lines = []
    out_linedefs = bytearray()
    for i in range(nlines):
        v1, v2, flags, special, tag, s0, s1 = struct.unpack_from('<HHHhhHH', lraw, i * 14)
        lines.append((v1, v2, flags, special, tag, s0, s1))
        v1x, v1y = fverts[v1]
        v2x, v2y = fverts[v2]
        dx = to_int32(v2x - v1x)
        dy = to_int32(v2y - v1y)
        if dx == 0:
            slope = ST_VERTICAL
        elif dy == 0:
            slope = ST_HORIZONTAL
        else:
            slope = ST_POSITIVE if ((dx < 0) == (dy < 0)) else ST_NEGATIVE
        bbox = [0, 0, 0, 0]
        bbox[BOXTOP] = max(v1y, v2y)
        bbox[BOXBOTTOM] = min(v1y, v2y)
        bbox[BOXLEFT] = min(v1x, v2x)
        bbox[BOXRIGHT] = max(v1x, v2x)
        out_linedefs += struct.pack(E + 'iiiiIiiHHiiiiHhhh',
                                    v1x, v1y, v2x, v2y, i, dx, dy, s0, s1,
                                    bbox[0], bbox[1], bbox[2], bbox[3],
                                    flags, special, tag, slope)

    out_vertexes = bytearray()
    for (fx, fy) in fverts:
        out_vertexes += struct.pack(E + 'ii', fx, fy)

    nsegs = len(graw) // 12
    out_segs = bytearray()
    for i in range(nsegs):
        rv1, rv2, angle, ldnum, side, offset = struct.unpack_from('<HHhHhh', graw, i * 12)
        v1x, v1y = fverts[rv1]
        v2x, v2y = fverts[rv2]
        ld = lines[ldnum]
        s0, s1 = ld[5], ld[6]
        sidenum = s0 if side == 0 else s1
        frontsec = side_sector[sidenum] if sidenum != NO_INDEX else NO_INDEX
        other = s1 if side == 0 else s0
        if (ld[2] & ML_TWOSIDED) and other != NO_INDEX:
            backsec = side_sector[other]
        else:
            backsec = NO_INDEX
        out_segs += struct.pack(E + 'iiiiiIHHHH',
                                v1x, v1y, v2x, v2y,
                                to_int32(offset << FRACBITS),
                                (angle & 0xFFFF) << FRACBITS,
                                sidenum, ldnum, frontsec, backsec)

    assert len(out_vertexes) == nverts * 8
    assert len(out_segs) == nsegs * 32
    assert len(out_linedefs) == nlines * 56
    assert len(out_sidedefs) == nsides * 12

    return {
        marker_idx + ML_VERTEXES: bytes(out_vertexes),
        marker_idx + ML_SIDEDEFS: bytes(out_sidedefs),
        marker_idx + ML_LINEDEFS: bytes(out_linedefs),
        marker_idx + ML_SEGS:     bytes(out_segs),
        marker_idx + ML_BLOCKMAP: bytes(out_blockmap),
        marker_idx + ML_SECTORS:  bytes(secraw),
    }


def build(data, lumps, texmap, extra=(), replace_by_name=None, map_overrides=None,
          fix_index0=False, texpatches=None, sector_align=0, compress_lumps=False,
          pcfx_textures=False, png_dir=None, texture_png=None, flat_png=None):
    replace_by_name = replace_by_name or {}
    map_overrides = map_overrides or {}
    flat_names = set(n.upper() for n in _section_names(lumps, 'F_START', 'F_END'))
    replace = {}
    nmaps = 0
    for i, (_, _, name) in enumerate(lumps):
        if is_map_marker(name):
            overlay = map_overrides.get(i)
            if overlay is None:
                replace.update(repack_map(data, lumps, i, texmap))
            else:
                overlay_data, overlay_lumps, overlay_idx = overlay
                packed = repack_map(overlay_data, overlay_lumps, overlay_idx, texmap,
                                    flat_names)
                for base_idx, overlay_lump_idx in zip(
                        map_lump_indices(lumps, i, 'base IWAD'),
                        map_lump_indices(overlay_lumps, overlay_idx, 'map overlay')):
                    fp, size, _ = overlay_lumps[overlay_lump_idx]
                    replace[base_idx] = packed.get(
                        overlay_lump_idx, overlay_data[fp:fp + size])
            nmaps += 1
    # Per-index map repack takes precedence; --replace swaps a whole lump's data
    # in-place (e.g. drop in doom1.wad's real TITLEPIC over the stripped one).
    entries = [(name, replace_by_name.get(name, replace.get(i, data[filepos:filepos + size])))
               for i, (filepos, size, name) in enumerate(lumps)]
    entries += list(extra)

    # PC-FX: no graphic may use index 0 (== transparent). Remap it away here so the
    # engine never has to (see fix_index0_entries). Applies to source, merged and
    # replaced lumps alike, since they are all in `entries` by now.
    if fix_index0:
        pal0 = read_playpal0(data, lumps)
        if pal0 is None:
            sys.exit('--fix-index0: no PLAYPAL lump to derive a safe index from')
        safe = pick_safe_index(pal0)
        # General colormap repair: make coloured surfaces diminish through their own
        # hue instead of speckling grey (must run before the index-0 remap below).
        for i, (name, payload) in enumerate(entries):
            if name.upper() == 'COLORMAP' and payload:
                entries[i] = (name, rebuild_colormap_hue(pal0, payload))
        flat_names = set(n.upper() for n in _section_names(lumps, 'F_START', 'F_END'))
        wall_names = set(n.upper() for n in _section_names(lumps, 'P_START', 'P_END'))
        grey_patches = set()
        if texpatches:
            used_tex, _ = collect_map_refs(data, lumps)
            grey_patches, shared = greyable_patches(GREY_TEXTURES, texpatches, used_tex)
            if shared:
                print(f'  warn: grey-texture patches shared with kept textures, skipped: '
                      f'{sorted(shared)}')
        fix_index0_entries(entries, safe, flat_names, wall_names, grey_patches, pal0)

    if pcfx_textures:
        pcfx_pages = build_pcfx_texture_pages(entries, png_dir, texture_png,
                                               flat_png)
        page_names = {name for name, _payload in pcfx_pages}
        # build() receives the compact name->index map, while animation frames
        # are defined by their original TEXTURE1/2 table order.
        _unused_texmap, texorder, _unused_patches = build_texture_map(data, lumps)
        missing = []
        solid_refs = expand_solid_wall_refs(
            collect_solid_wall_refs(data, lumps, map_overrides), texorder)
        for name in sorted(solid_refs):
            index = texmap.get(name)
            if index is None or pcfx_wall_lump_name(index) not in page_names:
                missing.append(name)
        if missing:
            sys.exit('--pcfx-textures: opaque wall texture lacks dense page: ' +
                     ', '.join(missing))
        entries += pcfx_pages

    # Lump data alignment. Normally 4 bytes (V810 struct loads). For the CD IWAD
    # (sector_align=2048) each lump STARTS on a 2048-byte CD sector so the runtime
    # can read it with one eris_cd_read_dma(base_lba + filepos/2048, ...) — no
    # sub-sector windowing. The directory is sector-aligned too so it loads in one
    # read at boot. Costs up to ~1 sector of padding per lump (fine on a CD).
    align = sector_align if sector_align else 4
    def pad(buf, boundary=align):
        while len(buf) % boundary:
            buf += b'\x00'

    # Standard 12-byte IWAD header (id, numlumps, infotableofs). When compressing,
    # extend it with our own [disclen_ofs u32][magic 'LZ4C'] at offsets 12/16 —
    # both live inside sector 0, ahead of the first (sector-aligned) lump, so the
    # blob still starts with a plain IWAD directory that non-LZ4 readers ignore.
    # A CD blob carries a second extension at 20.. ('DUP1'): per-lump checksums and
    # a duplicate of the whole blob, so the runtime can detect and repair a bad burn
    # (see the DUP1 block at the end of this function).
    out = bytearray(b'IWAD' + struct.pack('<ii', 0, 0))
    if compress_lumps:
        out += struct.pack('<I', 0) + b'LZ4C'          # [12:16] disclen_ofs, [16:20] magic

    directory = bytearray()
    disc_lens = []                                     # per-lump: on-disc len | (comp<<31)
    lump_sums = []                                     # per-lump: pcfx_sum32 of the ON-DISC bytes
    n_comp = tot_u = tot_d = 0
    for name, payload in entries:
        usize = len(payload)
        disc  = payload                                # on-disc bytes (raw by default)
        comp  = 0
        # LZ4 each lump whose data fits one 64 KB block AND actually shrinks. The
        # runtime (w_wad.c W_CacheLumpNum) reads `disc` bytes and lz4_depack's them
        # back to `usize`; the directory keeps the UNCOMPRESSED size so W_LumpLength
        # and every consumer is unchanged. Bigger-than-64KB or incompressible lumps
        # stay raw (comp=0) — read + memcpy as before.
        if compress_lumps and 0 < usize <= 0x10000:
            block = lz4_block.compress(payload)        # raw LZ4 block (no frame)
            cand  = struct.pack('<H', len(block)) + block
            if len(cand) < usize:
                disc, comp = cand, 1
        # PC-FX texture pages retain 2 KiB alignment even in a source-array WAD;
        # with --cd-wad every lump already receives this alignment.
        page_lump = name.startswith('PWT') or name.startswith('PFT')
        pad(out, 2048 if page_lump else align)
        newpos = len(out)
        out += disc
        directory += struct.pack('<ii', newpos, usize) # size = UNCOMPRESSED
        directory += name.encode('latin1')[:8].ljust(8, b'\x00')
        disc_lens.append((len(disc) & 0x7fffffff) | (comp << 31))
        lump_sums.append(pcfx_sum32.sum32(disc))       # verified per lump at read time
        n_comp += comp; tot_u += usize; tot_d += len(disc)

    pad(out)
    infotableofs = len(out)
    out += directory

    disclen_ofs = 0
    if compress_lumps:
        pad(out)
        disclen_ofs = len(out)
        for dl in disc_lens:
            out += struct.pack('<I', dl)

    if sector_align:                 # pad the whole blob to a sector boundary
        while len(out) % sector_align:
            out += b'\x00'
    struct.pack_into('<ii', out, 4, len(entries), infotableofs)
    if compress_lumps:
        struct.pack_into('<I', out, 12, disclen_ofs)   # magic bytes already at [16:20]
        print(f'  cd-lz4: {n_comp}/{len(entries)} lumps compressed, '
              f'lump bytes {tot_u} -> {tot_d} ({100.0 * tot_d / max(tot_u, 1):.1f}%)')

    # ---- DUP1: integrity checks + a duplicate of the whole blob ---------------
    # Only for the CD blob (a source-array WAD is in the program image, not on disc).
    # An imperfect burn returns GOOD SCSI status with wrong data, which the engine
    # cannot tell from a legitimately odd asset — the field report was glitched enemy
    # sprites. So: a checksum per lump (plus one for each metadata table), and then a
    # byte-for-byte SECOND COPY of everything above appended at mirror_ofs. On a failed
    # check the runtime re-reads the same offset from the copy, megabytes away on the
    # disc, where a local defect cannot reach (src/w_wad.c). Header layout (sector 0):
    #   [20] sum_ofs  [24] mirror_ofs  [28] 'DUP1'
    #   [32] dir_sum  [36] disclen_sum [40] sumtab_sum  [44] hdr_sum (over [0,44))
    if sector_align:
        sums = bytearray()
        for s in lump_sums:
            sums += struct.pack('<I', s)
        pad(out)
        sum_ofs = len(out)
        out += sums
        while len(out) % sector_align:
            out += b'\x00'
        disclen_bytes = out[disclen_ofs:disclen_ofs + 4 * len(disc_lens)] if disclen_ofs else b''
        struct.pack_into('<I', out, 20, sum_ofs)
        struct.pack_into('<I', out, 24, len(out))      # mirror starts right here
        out[28:32] = b'DUP1'
        struct.pack_into('<I', out, 32, pcfx_sum32.sum32(directory))
        struct.pack_into('<I', out, 36, pcfx_sum32.sum32(disclen_bytes))
        struct.pack_into('<I', out, 40, pcfx_sum32.sum32(sums))
        struct.pack_into('<I', out, 44, pcfx_sum32.sum32(out[0:44]))
        out += bytes(out)                              # the duplicate copy
        print(f'  dup: {len(entries)} lump checksums, blob duplicated '
              f'({len(out) // 2 // 1024} KB -> {len(out) // 1024} KB)')
    return bytes(out), nmaps


def emit_c(out_path, name, blob):
    # Array only: source/doom_iwad.c wraps this include and defines
    # doom_iwad_len = sizeof(doom_iwad), so DON'T emit a _len here (dup symbol).
    with open(out_path, 'w') as f:
        f.write('#pragma GCC optimize ("-O0")\n')
        # Page lump offsets are multiples of 2048, so aligning the enclosing array
        # makes every generated 32x64x8 texture page 2 KiB-aligned in source builds.
        f.write(f'const unsigned char {name}[] __attribute__((aligned(2048))) = {{\n')
        for i in range(0, len(blob), 16):
            f.write(','.join(str(b) for b in blob[i:i + 16]) + ',\n')
        f.write('};\n')


def main():
    global E
    ap = argparse.ArgumentParser()
    ap.add_argument('wad')
    ap.add_argument('out')
    ap.add_argument('--name', default='doom_iwad')
    ap.add_argument('--endian', choices=('little', 'big'), default='little',
                    help='endianness of repacked runtime structs (V810=little)')
    ap.add_argument('--drop-audio', action='store_true',
                    help='drop sfx/music lumps (converted separately to ADPCM)')
    ap.add_argument('--drop-demos', action='store_true',
                    help='drop DEMO* lumps (attract demo must be disabled in d_main.c)')
    ap.add_argument('--keep-maps', default=None,
                    help='comma list of maps to keep (e.g. E1M1); others are dropped')
    ap.add_argument('--cull-graphics', action='store_true',
                    help='drop wall patches + flats not referenced by the kept maps')
    ap.add_argument('--fix-index0', action='store_true',
                    help='remap index-0 texels in graphics to an opaque twin (PC-FX: '
                         'index 0 == transparent, so art must never use it)')
    ap.add_argument('--pcfx-textures', action='store_true',
                    help='append dense 32x64 8bpp PC-FX wall/flat pages; originals '
                         'remain in the WAD as runtime fallbacks')
    ap.add_argument('--png-dir', default=None,
                    help='optional directory of NAME.png wall/flat replacements')
    ap.add_argument('--texture-png', action='append', default=[], metavar='NAME=FILE',
                    help='override one wall texture before PC-FX conversion (repeatable)')
    ap.add_argument('--flat-png', action='append', default=[], metavar='NAME=FILE',
                    help='override one floor/ceiling flat before PC-FX conversion (repeatable)')
    ap.add_argument('--merge', action='append', default=[], metavar='WAD:LUMP1,LUMP2,...',
                    help='append named graphic lumps from a second WAD verbatim (repeatable)')
    ap.add_argument('--replace', action='append', default=[], metavar='WAD:LUMP1,LUMP2,...',
                    help='replace named lumps in-place with versions from another WAD '
                         '(repeatable; later --replace wins on a name collision)')
    ap.add_argument('--replace-maps', metavar='WAD',
                    help='replace map groups that also exist in this IWAD; maps absent '
                         'from WAD remain PC-IWAD maps')
    ap.add_argument('--also-bin', default=None,
                    help='additionally write the raw baked blob to this .bin path')
    ap.add_argument('--cd-wad', action='store_true',
                    help='pack each lump on a 2048-byte CD sector boundary (for the '
                         'CD-streamed IWAD: W_CacheLumpNum reads by filepos/2048)')
    ap.add_argument('--cd-lz4', action='store_true',
                    help='LZ4-compress each lump inside the CD IWAD (per-lump, like '
                         'Jaguar DOOM LZSS); w_wad.c lz4_depacks on cache. Implies --cd-wad.')
    a = ap.parse_args()
    E = '<' if a.endian == 'little' else '>'

    with open(a.wad, 'rb') as f:
        data = f.read()
    magic, lumps = read_dir(data)
    if magic != b'IWAD':
        sys.exit(f'{a.wad}: not an IWAD (magic={magic!r})')

    keep_maps = set(a.keep_maps.split(',')) if a.keep_maps else None
    lumps = filter_lumps(lumps, a.drop_audio, a.drop_demos, keep_maps)

    extra = []
    for mspec in a.merge:
        mpath, _, mnames = mspec.partition(':')
        with open(mpath, 'rb') as f:
            mdata = f.read()
        mmagic, mlumps = read_dir(mdata)
        if mmagic not in (b'IWAD', b'PWAD'):
            sys.exit(f'{mpath}: not a WAD (magic={mmagic!r})')
        mdir = {name: (fp, sz) for fp, sz, name in mlumps}
        for name in mnames.split(','):
            if name not in mdir:
                sys.exit(f'{mpath}: missing merge lump {name!r}')
            fp, sz = mdir[name]
            extra.append((name, mdata[fp:fp + sz]))

    replace_by_name = {}
    for rspec in a.replace:
        rpath, _, rnames = rspec.partition(':')
        with open(rpath, 'rb') as f:
            rdata = f.read()
        rmagic, rlumps = read_dir(rdata)
        rdir = {name: (fp, sz) for fp, sz, name in rlumps}
        for name in rnames.split(','):
            if name not in rdir:
                sys.exit(f'{rpath}: missing replace lump {name!r}')
            fp, sz = rdir[name]
            replace_by_name[name] = rdata[fp:fp + sz]

    try:
        map_overrides = (read_map_overrides(a.replace_maps, lumps)
                         if a.replace_maps else {})
    except ValueError as e:
        sys.exit(str(e))

    # When every base map is overlaid by a Jaguar map (the shareware case), the
    # whole game is Jaguar, so adopt jaguartc.wad's own texture namespace to get
    # native art at native dimensions. Rebuilding the WAD renumbers lumps, so the
    # map-override indices must be recomputed against the merged directory.
    if a.replace_maps and map_overrides:
        num_base_maps = sum(1 for _, _, nm in lumps if is_map_marker(nm))
        if len(map_overrides) == num_base_maps:
            data, lumps = merge_jaguar_texture_world(data, lumps, a.replace_maps)
            map_overrides = read_map_overrides(a.replace_maps, lumps)
        else:
            print(f'  jaguar textures: partial overlay '
                  f'({len(map_overrides)}/{num_base_maps} maps) — keeping base '
                  f'texture namespace with shareware aliasing')

    texmap, texorder, texpatches = build_texture_map(data, lumps)
    if a.cull_graphics:
        lumps = cull_unreferenced(data, lumps, texorder, texpatches)
    cd_wad = a.cd_wad or a.cd_lz4          # --cd-lz4 implies --cd-wad
    blob, nmaps = build(data, lumps, texmap, extra, replace_by_name, map_overrides,
                        a.fix_index0, texpatches, sector_align=(2048 if cd_wad else 0),
                        compress_lumps=a.cd_lz4, pcfx_textures=a.pcfx_textures,
                        png_dir=a.png_dir, texture_png=parse_png_specs(a.texture_png),
                        flat_png=parse_png_specs(a.flat_png))

    if a.out.endswith('.bin'):
        with open(a.out, 'wb') as f:
            f.write(blob)
    else:
        emit_c(a.out, a.name, blob)
    if a.also_bin:
        with open(a.also_bin, 'wb') as f:
            f.write(blob)
    print(f'preprocessed [{a.endian}]: {len(lumps)} lumps (+{len(extra)} merged), {nmaps} maps, '
          f'{len(texmap)} textures, {len(blob)} bytes -> {a.out}')


if __name__ == '__main__':
    main()
