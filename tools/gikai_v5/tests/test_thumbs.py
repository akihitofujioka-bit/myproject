"""画面用縮小画像のテスト。"""

from __future__ import annotations

import shutil
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import thumbs  # noqa: E402


def _segment(marker: int, value: bytes) -> bytes:
    return b"\xff" + bytes((marker,)) + struct.pack(">H", len(value) + 2) + value


def _jpeg(width: int, height: int, color: bool, orientation: int = 1,
          restart: bool = False) -> bytes:
    """DC=0、AC=EOB だけの小さなベースライン JPEG。"""
    app1 = b""
    if orientation != 1:
        tiff = (b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
                + struct.pack("<H", 1)
                + struct.pack("<HHI", 0x0112, 3, 1)
                + struct.pack("<H", orientation) + b"\x00\x00"
                + struct.pack("<I", 0))
        app1 = _segment(0xe1, b"Exif\x00\x00" + tiff)
    dqt = _segment(0xdb, b"\x00" + bytes([1]) * 64)
    if color:
        components = b"\x01\x22\x00\x02\x11\x00\x03\x11\x00"
        scan_components = b"\x01\x00\x02\x00\x03\x00"
        blocks = 6
    else:
        components = b"\x01\x11\x00"
        scan_components = b"\x01\x00"
        blocks = ((width + 7) // 8) * ((height + 7) // 8)
    sof = _segment(0xc0, b"\x08" + struct.pack(">HHB", height, width,
                                                3 if color else 1) + components)
    counts = b"\x01" + b"\x00" * 15
    dht = _segment(0xc4, b"\x00" + counts + b"\x00"
                   + b"\x10" + counts + b"\x00")
    sos = _segment(0xda, bytes((3 if color else 1,)) + scan_components
                   + b"\x00\x3f\x00")
    dri = _segment(0xdd, struct.pack(">H", 1)) if restart else b""
    if restart:
        entropy = b"".join((b"" if index == 0 else b"\xff" + bytes((0xd0 + index - 1,)))
                           + b"\x3f" for index in range(blocks))
    else:
        bit_count = blocks * 2
        value = bytearray((bit_count + 7) // 8)
        if bit_count % 8:
            value[-1] = (1 << (8 - bit_count % 8)) - 1
        entropy = bytes(value)
    return b"\xff\xd8" + app1 + dqt + sof + dht + dri + sos + entropy + b"\xff\xd9"


class ThumbnailTest(unittest.TestCase):
    def test_write_and_read_png(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "架空の色.png"
            pixels = bytes([255, 0, 0, 0, 128, 255])
            thumbs.write_png(path, 2, 1, pixels)
            self.assertEqual(thumbs.read_png(path), (2, 1, pixels))

    def test_baseline_jpeg_dc_grayscale_and_420(self):
        gray = thumbs.decode_jpeg_dc(_jpeg(16, 16, False))
        color = thumbs.decode_jpeg_dc(_jpeg(16, 16, True))
        self.assertEqual(gray[:2], (2, 2))
        self.assertEqual(color[:2], (2, 2))
        self.assertEqual(set(gray[2]), {128})
        self.assertEqual(set(color[2]), {128})

    def test_exif_orientation_rotates_pixels(self):
        data = _jpeg(16, 8, False, orientation=6)
        self.assertEqual(thumbs.exif_orientation(data), 6)
        width, height, pixels = thumbs.decode_jpeg_dc(data)
        rotated = thumbs.orient_pixels(width, height, pixels, 6)
        self.assertEqual((width, height), (2, 1))
        self.assertEqual(rotated[:2], (1, 2))

    def test_restart_markers_and_progressive_rejection(self):
        width, height, _pixels = thumbs.decode_jpeg_dc(_jpeg(16, 8, False, restart=True))
        self.assertEqual((width, height), (2, 1))
        progressive = _jpeg(8, 8, False).replace(b"\xff\xc0", b"\xff\xc2", 1)
        with self.assertRaisesRegex(ValueError, "プログレッシブ"):
            thumbs.decode_jpeg_dc(progressive)

    def test_thumbnail_reuses_cache_until_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "架空の写真.png"
            thumbs.write_png(source, 20, 10, bytes([20, 40, 60]) * 200)
            first = thumbs.thumbnail(source, 8)
            self.assertIsNotNone(first)
            first_time = first.stat().st_mtime_ns
            self.assertEqual(thumbs.read_png(first)[:2], (8, 4))
            self.assertEqual(thumbs.thumbnail(source, 8), first)
            self.assertEqual(first.stat().st_mtime_ns, first_time)
            time.sleep(0.002)
            thumbs.write_png(source, 10, 20, bytes([60, 40, 20]) * 200)
            second = thumbs.thumbnail(source, 8)
            self.assertNotEqual(second, first)
            self.assertEqual(thumbs.read_png(second)[:2], (4, 8))

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("sips"),
                         "sips がある Mac だけで確かめます")
    def test_sips_conversion_when_available(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "架空.png"
            target = Path(folder) / "結果.png"
            thumbs.write_png(source, 12, 6, bytes([1, 2, 3]) * 72)
            self.assertTrue(thumbs._sips_thumbnail(source, target, 6))
            self.assertLessEqual(max(thumbs.read_png(target)[:2]), 6)

    @unittest.skipUnless(sys.platform.startswith("win") and shutil.which("powershell"),
                         "PowerShell がある Windows だけで確かめます")
    def test_powershell_conversion_when_available(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "架空.png"
            target = Path(folder) / "結果.png"
            thumbs.write_png(source, 12, 6, bytes([1, 2, 3]) * 72)
            self.assertTrue(thumbs._powershell_thumbnail(source, target, 6))
            self.assertLessEqual(max(thumbs.read_png(target)[:2]), 6)


if __name__ == "__main__":
    unittest.main()
