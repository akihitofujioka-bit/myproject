"""段階 4 の自動配置・あふれ計算・写真入り Word のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import compose as C  # noqa: E402
import docx_out as dx  # noqa: E402
import ingest as I  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
from grid import Box, Geometry, Rect, mm2pt, split_lines  # noqa: E402


class PlacementTest(unittest.TestCase):
    def setUp(self):
        self.g = Geometry()
        self.png = samples._png(60, 80)

    def test_no_overlap_and_all_inside(self):
        parts = [I.Part("大見出し", "見本の大見出し"),
                 I.Part("本文", "本文です。" * 20),
                 I.Part("写真", image="one.png"), I.Part("写真説明", "▲説明"),
                 I.Part("中見出し", "次の項目"), I.Part("本文", "続きです。" * 20)]
        result = C.compose_page(layout.GYOSEI, parts, {"one.png": self.png}, self.g)
        rects = [p.rect for p in result.placements]
        for n, rect in enumerate(rects):
            self.assertGreaterEqual(rect.dan, 0)
            self.assertGreaterEqual(rect.line, 0)
            self.assertLessEqual(rect.dan + rect.dan_span, self.g.dans)
            self.assertLessEqual(rect.line + rect.line_span, self.g.lines_per_dan)
            for other in rects[n + 1:]:
                self.assertFalse(rect.overlaps(other), (rect, other))

    def test_face_position_and_caption_not_flowed(self):
        face = I.Part("写真", image="face.png")
        caption = I.Part("写真説明", "▲架空　太郎議員")
        parts = [I.Part("大見出し", "暮らしを守る"), face, caption,
                 I.Part("質問", "問　備えは十分ですか。")]
        result = C.compose_page(layout.IPPAN, parts, {"face.png": self.png}, self.g)
        placed = next(p for p in result.placements if p.part is face)
        self.assertEqual(placed.rect, Rect(0, 4, 1, 5))
        self.assertFalse(any(p.part is caption for p in result.placements))
        picture = next(x for x in result.page.items if isinstance(x, dx.Picture))
        self.assertEqual(picture.caption, "架空　太郎議員")
        self.assertAlmostEqual(picture.box.w, mm2pt(26))

    def test_middle_heading_is_atomic(self):
        parts = [I.Part("本文", "あ" * (self.g.chars_per_line * 29)),
                 I.Part("中見出し", "次の見出し"), I.Part("本文", "本文")]
        result = C.compose_page(layout.GYOSEI, parts, {}, self.g)
        heading = next(p for p in result.placements if p.part.kind == "中見出し")
        self.assertEqual((heading.rect.dan_span, heading.rect.line_span), (1, 2))
        self.assertEqual((heading.rect.dan, heading.rect.line), (1, 0))

    def test_same_format_is_combined(self):
        parts = [I.Part("本文", "一つ目。"), I.Part("答弁", "答　二つ目。")]
        result = C.compose_page(layout.GYOSEI, parts, {}, self.g)
        boxes = [x for x in result.page.items if isinstance(x, dx.TextBox)]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(len(boxes[0].lines), 2)

    def test_overflow_matches_grid_capacity(self):
        text = "あ" * (self.g.chars_per_line * 157)
        result = C.compose_page(layout.GYOSEI, [I.Part("本文", text)], {}, self.g)
        expected = len(split_lines(text, self.g.chars_per_line)) - 150
        self.assertEqual(result.overflow_lines, expected)
        self.assertEqual(result.free_lines, 0)

    def test_photo_suggestion_is_shown(self):
        parts = [I.Part("写真", image="photo.png"), I.Part("写真説明", "▲見本"),
                 I.Part("本文", "あ" * (self.g.chars_per_line * 146))]
        result = C.compose_page(layout.GYOSEI, parts, {"photo.png": samples._png()}, self.g)
        self.assertGreater(result.overflow_lines, 0)
        self.assertTrue(any("写真1 を" in w and "行入ります" in w for w in result.warnings),
                        result.warnings)


class PictureDocxTest(unittest.TestCase):
    @staticmethod
    def _jpeg() -> bytes:
        # SOF0 に 幅64・高さ32 を持つ、ヘッダー確認用の最小データ。
        return (b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x20\x00\x40\x01\x01\x11\x00"
                b"\xff\xd9")

    def test_header_sizes(self):
        self.assertEqual(dx.image_size(samples._png(8, 6), "png"), (8, 6))
        self.assertEqual(dx.image_size(self._jpeg(), "jpeg"), (64, 32))

    def test_picture_package_is_valid(self):
        page = dx.Page([
            dx.Picture(Box(10, 20, 100, 80), samples._png(8, 6), "png", "PNG の説明", "写真1"),
            dx.Picture(Box(120, 20, 80, 60), self._jpeg(), "jpeg", "", "写真2"),
            dx.TextBox(Box(10, 110, 30, 132), ["本文"]),
        ])
        with tempfile.TemporaryDirectory() as d:
            path = dx.write_docx(Path(d) / "pictures.docx", Geometry(), [page])
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                document = ET.fromstring(z.read("word/document.xml"))
                rels = ET.fromstring(z.read("word/_rels/document.xml.rels"))
                types = ET.fromstring(z.read("[Content_Types].xml"))
        self.assertIn("word/media/image1.png", names)
        self.assertIn("word/media/image2.jpeg", names)
        ids = [e.get("id") for e in document.iter("{%s}docPr" % dx.WP)]
        self.assertEqual(len(ids), len(set(ids)))
        targets = {e.get("Target") for e in rels}
        self.assertIn("media/image1.png", targets)
        self.assertIn("media/image2.jpeg", targets)
        defaults = {(e.get("Extension"), e.get("ContentType")) for e in types}
        self.assertIn(("png", "image/png"), defaults)
        self.assertIn(("jpeg", "image/jpeg"), defaults)
        self.assertEqual(len(list(document.iter("{%s}pic" % dx.PIC))), 2)


if __name__ == "__main__":
    unittest.main()
