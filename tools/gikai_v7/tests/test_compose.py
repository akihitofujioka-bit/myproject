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
        parts = [I.Part("本文", "あ" * (self.g.chars_per_line * (self.g.lines_per_dan - 1))),
                 I.Part("中見出し", "次の見出し"), I.Part("本文", "本文")]
        result = C.compose_page(layout.GYOSEI, parts, {}, self.g)
        heading = next(p for p in result.placements if p.part.kind == "中見出し")
        self.assertEqual((heading.rect.dan_span, heading.rect.line_span), (1, 2))
        self.assertEqual((heading.rect.dan, heading.rect.line), (1, 0))

    def test_two_line_middle_heading_uses_three_grid_lines(self):
        # 16pt で 1 行 8 字の枠なので、2 行に収まる 16 字の見出し。
        parts = [I.Part("中見出し", "架空の取組を進める長い見出しです"),
                 I.Part("本文", "本文")]
        result = C.compose_page(layout.GYOSEI, parts, {}, self.g)
        heading = next(p for p in result.placements if p.part.kind == "中見出し")
        box = next(item for item in result.page.items
                   if isinstance(item, dx.TextBox) and item.name == "中見出し")
        self.assertEqual(len(box.lines), 2)
        self.assertEqual(heading.rect.line_span, 3)
        self.assertTrue(box.center)
        self.assertGreaterEqual(box.box.w,
                                len(box.lines) * dx.effective_pitch(box.pt, box.pitch_pt))
        body = next(p for p in result.placements if p.part.kind == "本文")
        self.assertFalse(heading.rect.overlaps(body.rect))

    def test_tatechuyoko_uses_vert_not_combine(self):
        # 2〜3 桁の数字は縦中横（w:vert）。割注（w:combine）だと字が小さく 2 行に潰れる。
        runs = "".join(dx._line_runs("約30分と100人", dx.GOTHIC, 11.0, [0]))
        self.assertEqual(runs.count('w:vert="1" w:vertCompress="1"'), 2)
        self.assertNotIn("w:combine", runs)

    def test_same_format_is_combined(self):
        parts = [I.Part("本文", "一つ目。"), I.Part("答弁", "答　二つ目。")]
        result = C.compose_page(layout.GYOSEI, parts, {}, self.g)
        boxes = [x for x in result.page.items if isinstance(x, dx.TextBox)]
        self.assertEqual(len(boxes), 1)
        self.assertEqual(len(boxes[0].lines), 2)

    def test_committee_reporter_line_and_long_committee_name(self):
        """委員会報告: 課長名は見出しにせず 1 行（次の行から説明）。長い委員会名は 1 行目上づめ・2 行目下づめ。"""
        parts = [I.Part("中見出し", "架空産業厚生常任委員会"), I.Part("中見出し", "総務課長"),
                 I.Part("本文", "架空の説明です。"), I.Part("中見出し", "所感"), I.Part("本文", "架空の所感です。")]
        result = C.compose_page(layout.IINKAI, parts, {}, self.g)
        boxes = [item for item in result.page.items if isinstance(item, dx.TextBox)]
        name = next(item for item in boxes if "委員会" in "".join(item.lines))
        self.assertEqual(len(name.lines), 2)
        self.assertEqual(name.align, "左")
        self.assertTrue(name.lines[1].startswith("　") and name.lines[1].endswith("委員会"))
        reporter = next(item for item in boxes if item.name == "報告者")
        self.assertEqual(reporter.lines[:2], ["総務課長", "　架空の説明です。"])
        self.assertEqual(reporter.font, dx.GOTHIC)
        self.assertIn("所感", [item.lines[0] for item in boxes if item.name == "中見出し"])

    def test_general_question_fonts_and_answer_runs(self):
        """一般質問は「質問　本文」、「答弁　答弁者」のあと行を変えて答弁の本文（明朝）。"""
        parts = [
            I.Part("質問", "問　架空の計画を伺います。"),
            I.Part("答弁", "答　総務課長　架空の計画を12月に進めます。"),
            I.Part("本文", "教育長"),
            I.Part("答弁", "答　架空の学校計画を進めます。"),
        ]
        result = C.compose_page(layout.IPPAN, parts, {}, self.g)
        boxes = [item for item in result.page.items if isinstance(item, dx.TextBox)]
        question = next(item for item in boxes if item.name == "質問")
        answers = [item for item in boxes if item.name == "答弁"]
        self.assertEqual((question.font, question.pt), (dx.GOTHIC, 11.0))
        self.assertTrue(question.lines[0].startswith("質問　架空の計画"))
        self.assertEqual(answers[0].lines[0], "答弁　総務課長")
        self.assertTrue(answers[0].lines[1].startswith("　架空の計画を"))
        self.assertEqual([runs[0][1] for runs in answers[0].line_runs[:2]], [dx.GOTHIC, dx.MINCHO])
        # 答の前の行に書いた答弁者も、「答弁」の次の行に入る（同じ書体の枠は 1 つにまとまるので、行を通して見る）
        lines = [line for item in answers for line in item.lines]
        second = lines.index("答弁　教育長")
        self.assertTrue(lines[second + 1].startswith("　架空の学校計画"))
        self.assertFalse(any(item.lines == ["教育長"] for item in boxes))

        doc = ET.fromstring(dx.document_xml(self.g, [result.page]).encode("utf-8"))
        text_fonts = []
        for run in doc.iter("{%s}r" % dx.W):
            text = run.find("{%s}t" % dx.W)
            fonts = run.find("{%s}rPr/{%s}rFonts" % (dx.W, dx.W))
            if text is not None and fonts is not None:
                text_fonts.append((text.text or "", fonts.get("{%s}eastAsia" % dx.W)))
        self.assertIn(("答弁　総務課長", dx.GOTHIC), text_fonts)
        self.assertTrue(any("架空の計" in text and font == dx.MINCHO
                            for text, font in text_fonts), text_fonts)
        number_run = next(run for run in doc.iter("{%s}r" % dx.W)
                          if (run.find("{%s}t" % dx.W) is not None
                              and run.find("{%s}t" % dx.W).text == "12"))
        self.assertEqual(number_run.find("{%s}rPr/{%s}rFonts" % (dx.W, dx.W)).get(
            "{%s}eastAsia" % dx.W), dx.MINCHO)
        self.assertIsNotNone(number_run.find("{%s}rPr/{%s}eastAsianLayout" % (dx.W, dx.W)))

    def test_other_article_body_is_gothic(self):
        for section in (layout.GYOSEI, layout.YOSAN, layout.KESSAN,
                        layout.IINKAI, layout.TOKUSHU):
            with self.subTest(section=section):
                result = C.compose_page(section, [I.Part("本文", "架空の本文です。")], {}, self.g)
                box = next(item for item in result.page.items if isinstance(item, dx.TextBox))
                self.assertEqual((box.font, box.pt), (dx.GOTHIC, 11.0))

    def test_placed_photo_stays_when_text_overflows(self):
        # 本文があふれても、場所を決めて置いた写真はそのページに残る。
        parts = [I.Part("本文", "あ" * (self.g.chars_per_line * self.g.lines_per_dan * 6)),
                 I.Part("写真", image="photo.png"), I.Part("写真説明", "▲見本")]
        rect = C.photo_rect(self.g, "特大", 1, 6)
        result = C.compose_page(layout.GYOSEI, parts, {"photo.png": samples._png()}, self.g,
                                overrides={1: {"rect": rect, "size": "特大"}})
        self.assertGreater(result.overflow_lines, 0)
        photo = next(p for p in result.placements if p.part.kind == "写真")
        self.assertEqual(photo.rect, rect)
        self.assertFalse(any(p.kind in ("写真", "写真説明") for p in result.overflow_parts))

    def test_overflow_matches_grid_capacity(self):
        text = "あ" * (self.g.chars_per_line * (self.g.lines_per_dan * 5 + 7))
        result = C.compose_page(layout.GYOSEI, [I.Part("本文", text)], {}, self.g)
        expected = len(split_lines(text, self.g.chars_per_line)) - self.g.lines_per_dan * 5
        self.assertEqual(result.overflow_lines, expected)
        self.assertEqual(result.free_lines, 0)

    def test_photo_suggestion_is_shown(self):
        parts = [I.Part("写真", image="photo.png"), I.Part("写真説明", "▲見本"),
                 I.Part("本文", "あ" * (self.g.chars_per_line * (self.g.lines_per_dan * 5 - 4)))]
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
