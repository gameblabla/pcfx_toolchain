#!/usr/bin/env python3
"""Focused host tests for bake_wad.py's PC-FX texture-page conversion."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import bake_wad


def make_patch(width, height, post_height=None):
    post_height = height if post_height is None else post_height
    header = bytearray(struct.pack('<hhhh', width, height, 0, 0))
    header += bytes(width * 4)
    columns = bytearray()
    offsets = []
    for x in range(width):
        offsets.append(len(header) + len(columns))
        columns += bytes((0, post_height, 0))
        columns += bytes(((x * 3 + y * 5) % 254) + 1 for y in range(post_height))
        columns += b'\0\xff'
    for x, offset in enumerate(offsets):
        struct.pack_into('<I', header, 8 + x * 4, offset)
    return bytes(header + columns)


def make_texture1(width=64, height=64):
    record = struct.pack('<8s4shh4shhhhhh', b'TESTWALL', b'\0' * 4,
                         width, height, b'\0' * 4, 1,
                         0, 0, 0, 0, 0)
    return struct.pack('<II', 1, 8) + record


def base_entries(patch):
    palette = bytes(i for i in range(256) for _ in range(3))
    flat = bytes(((x * 7 + y * 11) % 255) + 1
                 for y in range(64) for x in range(64))
    return [
        ('PLAYPAL', palette),
        ('PNAMES', struct.pack('<I8s', 1, b'PATCHA')),
        ('TEXTURE1', make_texture1()),
        ('P_START', b''), ('PATCHA', patch), ('P_END', b''),
        ('F_START', b''), ('F1_START', b''), ('TESTFLAT', flat),
        ('F1_END', b''), ('F_END', b''),
    ], flat


class PCFXTextureTests(unittest.TestCase):
    def test_solid_wall_refs_expand_to_runtime_animation_and_switch_states(self):
        texorder = [
            'BLODGR1', 'BLODGR2', 'BLODGR3', 'BLODGR4',
            'SW1BRCOM', 'SW2BRCOM', 'UNRELATED',
        ]
        expanded = bake_wad.expand_solid_wall_refs({'BLODGR2', 'SW1BRCOM'},
                                                   texorder)

        self.assertEqual(expanded,
                         {'BLODGR1', 'BLODGR2', 'BLODGR3', 'BLODGR4',
                          'SW1BRCOM', 'SW2BRCOM'})

    def test_dense_wall_and_flat_pages_are_exact_and_oriented(self):
        patch = make_patch(64, 64)
        entries, flat = base_entries(patch)
        pages = dict(bake_wad.build_pcfx_texture_pages(entries))

        wall = pages['PWT00000']
        pcflat = pages['PFT00001']
        self.assertEqual(len(wall), 2048)
        self.assertEqual(len(pcflat), 2048)

        # Nearest downsample takes original source columns 0,2,4,... and walls
        # transpose those rows into contiguous 64-byte columns.
        _w, _h, pixels, _opaque = bake_wad.decode_patch_image(patch)
        self.assertEqual(wall[9 * 64 + 17], pixels[17 * 64 + 18])
        self.assertEqual(pcflat[17 * 32 + 9], flat[17 * 64 + 18])

    def test_masked_wall_is_omitted_for_original_fallback(self):
        entries, _flat = base_entries(make_patch(64, 64, post_height=63))
        pages = dict(bake_wad.build_pcfx_texture_pages(entries))
        self.assertNotIn('PWT00000', pages)
        self.assertIn('PFT00001', pages)
        self.assertNotIn('PFT00000', pages)

    def test_small_opaque_wall_still_gets_dense_page(self):
        patch = make_patch(32, 8)
        entries, _flat = base_entries(patch)
        entries = [(name, make_texture1(32, 8) if name == 'TEXTURE1' else data)
                   for name, data in entries]
        pages = dict(bake_wad.build_pcfx_texture_pages(entries))

        self.assertIn('PWT00000', pages)
        self.assertEqual(len(pages['PWT00000']), bake_wad.PCFX_TEX_BYTES)

    def test_png_wall_override_is_mapped_through_playpal(self):
        from PIL import Image

        entries, _flat = base_entries(make_patch(64, 64))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'wall.png')
            Image.new('RGB', (80, 96), (37, 37, 37)).save(path)
            pages = dict(bake_wad.build_pcfx_texture_pages(
                entries, texture_png={'TESTWALL': path}))
        self.assertEqual(len(pages['PWT00000']), 2048)
        self.assertTrue(all(pixel == 37 for pixel in pages['PWT00000']))


if __name__ == '__main__':
    unittest.main()
