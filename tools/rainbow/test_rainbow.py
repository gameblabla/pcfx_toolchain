#!/usr/bin/env python3
"""Host regression tests for tools/rainbow.  Run: python3 tools/rainbow/test_rainbow.py

These pin the facts earlier sessions got wrong or never checked:
  * rainbow_codec is byte-identical to Doom's MPCONV-conformant encoder;
  * every emitted strip is strictly framed (stuffed sizes, word alignment,
    inner dummy, 3-word guard) and fully decodes;
  * the legacy layout (sizes counting UNSTUFFED bytes, no dummy/guard) is
    rejected by the strict gate and losslessly migrated by repair-legacy;
  * black frames are nearly free (null runs), and scale 0 is the finest.
They say nothing about hardware timing; see validate_still.py and the player's
emu_validate.py for emulator evidence.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pcfv  # noqa: E402
import rainbow  # noqa: E402
import rainbow_codec as codec  # noqa: E402
from rainbow_decode import decode_stream, to_rgb  # noqa: E402

DOOM_ENCODER = HERE.parents[1] / 'vendor/doompcfx/tools/gen_pcfx_rainbow_bg.py'


def test_card():
    img = Image.new('RGB', (256, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(8):
        d.rectangle([i * 32, 0, i * 32 + 31, 79], fill=((i & 1) * 255, (i >> 1 & 1) * 255, (i >> 2 & 1) * 255))
    for x in range(256):
        d.line([x, 80, x, 127], fill=(x, 255 - x, (x * 3) & 255))
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 256, (64, 256, 3), dtype=np.uint8)
    img.paste(Image.fromarray(noise), (0, 160))
    return img


def legacy_frame(strict):
    """Rebuild the pre-MPCONV C encoder's layout from a strict frame."""
    out, off = bytearray(), 0
    for strip in range(15):
        size = int.from_bytes(strict[off + 2:off + 4], 'big')
        tables = 128 if strip == 0 else 0
        entropy = strict[off + 4 + tables:off + 4 + size - 2]
        logical = len(entropy) - entropy.count(b'\xff\x00')
        out += strict[off:off + 2] + (2 + tables + logical).to_bytes(2, 'big')
        out += strict[off + 4:off + 4 + tables] + entropy
        off += 4 + size + 6
    return bytes(out)


class RainbowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.card = Path(cls.tmp.name) / 'card.png'
        test_card().save(cls.card)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @unittest.skipUnless(DOOM_ENCODER.exists(), 'vendor/doompcfx not checked out')
    def test_byte_identical_to_doom_encoder(self):
        spec = importlib.util.spec_from_file_location('doom_rainbow', DOOM_ENCODER)
        doom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(doom)
        for scale in (0, 5, 15):
            self.assertEqual(codec.encode_frame(str(self.card), scale), doom.encode_frame(str(self.card), scale),
                             f'scale {scale} diverged from Doom gen_pcfx_rainbow_bg.py')

    def test_strict_framing_and_decode(self):
        for scale in range(16):
            stream = codec.encode_frame(str(self.card), scale)
            spans = codec.analyze_stream(stream)
            self.assertEqual(len(spans), 15)
            self.assertTrue(all(s % 2 == 0 for s in spans), 'every strip must stay word aligned')
            y, _, _ = decode_stream(stream)
            self.assertEqual(y.shape, (240, 256))

    def test_scale_zero_is_finest(self):
        sizes = [len(codec.encode_frame(str(self.card), s)) for s in (0, 7, 15)]
        self.assertGreater(sizes[0], sizes[1])
        self.assertGreater(sizes[1], sizes[2])

    def test_black_frame_uses_null_runs(self):
        black = Path(self.tmp.name) / 'black.png'
        Image.new('RGB', (256, 240)).save(black)
        stream = codec.encode_frame(str(black), 0)
        # 15 strips x (4 header + null-run entropy + 2 dummy + 6 guard) + 128 tables.
        self.assertLess(len(stream), 128 + 15 * 20)
        y, _, _ = decode_stream(stream)
        self.assertLess(float(np.abs(y.astype(int) - int(y.mean())).max()), 2.0)

    def test_round_trip_is_close(self):
        rgb = np.asarray(Image.open(self.card).convert('RGB'), dtype=np.float64)
        out = to_rgb(*decode_stream(codec.encode_frame(str(self.card), 0))).astype(np.float64)
        top = np.abs(out[:128] - rgb[:128]).mean()   # bars and ramps; row 160+ is noise
        self.assertLess(top, 12.0)

    def test_legacy_layout_rejected_then_repaired(self):
        strict = codec.encode_frame(str(self.card), 0)
        legacy = legacy_frame(strict)
        self.assertGreater(legacy.count(b'\xff\x00'), 2, 'test card must contain stuffed bytes')
        with self.assertRaises(ValueError):
            decode_stream(legacy)
        self.assertEqual(rainbow.repair_frame(legacy), strict)

    def test_pcfv_round_trip(self):
        path = Path(self.tmp.name) / 'clip.pcfv'
        too_big = codec.encode_frame(str(self.card), 0)
        self.assertGreater(len(too_big), 4 * 2048)
        with self.assertRaises(ValueError):   # the player's KRAM slot is 4 sectors
            pcfv.write(path, [too_big], 15, 1)
        frames = [codec.encode_frame(str(self.card), s) for s in (12, 15)]
        pcfv.write(path, frames, 15, 1)
        back = pcfv.read(path)
        self.assertEqual(back['frames'], frames)
        self.assertEqual((back['fps_num'], back['fps_den']), (15, 1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
