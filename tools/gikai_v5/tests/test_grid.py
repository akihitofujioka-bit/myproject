"""自動テスト（python -m unittest discover -s tests）。

格子の計算・行分け（禁則）・流し込み・Word の書き出しを確かめる。
Word での見え方そのものは、trial.py で作った Word を開いて目で確かめる（設計図 §15 段階 1）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import docx_out as dx  # noqa: E402
from grid import (GYOTO_KINSOKU, GYOMATSU_KINSOKU, Geometry, Rect, flow,  # noqa: E402
                  free_runs, layout_text, mm2pt, split_lines, text_width, to_box,
                  units, whole_page)


class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.g = Geometry()

    def test_standard_sizes(self):
        self.assertEqual(self.g.lines_per_dan, 30)
        self.assertEqual(self.g.dan_h_pt, 132)
        self.assertGreater(self.g.gap_pt, 0)
        self.assertEqual(self.g.check(), [])

    def test_too_many_dans(self):
        self.assertTrue(Geometry(dans=7).check())

    def test_page_fits_in_text_area(self):
        b = to_box(self.g, whole_page(self.g))
        self.assertAlmostEqual(b.y, mm2pt(15))
        self.assertAlmostEqual(b.y + b.h, mm2pt(297 - 12))
        self.assertAlmostEqual(b.x + b.w, mm2pt(210 - 15))
        self.assertGreaterEqual(b.x, mm2pt(15) - 1e-6)

    def test_lines_go_right_to_left(self):
        first = to_box(self.g, Rect(0, 0))
        second = to_box(self.g, Rect(0, 1))
        self.assertLess(second.x, first.x)
        self.assertAlmostEqual(first.x - second.x, self.g.line_pitch_pt)


class SplitLinesTest(unittest.TestCase):
    def test_indent_and_length(self):
        lines = split_lines("あ" * 30, 12)
        self.assertEqual(lines[0], "　" + "あ" * 11)
        self.assertTrue(all(len(x) <= 12 for x in lines))
        self.assertEqual("".join(lines), "　" + "あ" * 30)

    def test_no_kinsoku_at_line_head(self):
        text = "あいうえおかきくけこさし。すせそ、たちつてとなにぬねの」はひふへほ"
        for line in split_lines(text, 12, indent=False)[1:]:
            self.assertNotIn(line[0], GYOTO_KINSOKU, line)

    def test_no_open_bracket_at_line_end(self):
        text = "あいうえおかきくけこさ「しすせそ」たちつてと"
        for line in split_lines(text, 12, indent=False):
            self.assertNotIn(line[-1], GYOMATSU_KINSOKU, line)

    def test_long_run_of_kinsoku_gives_up(self):
        # 禁則の字ばかりでも、行は n 字を超えず、無限に回らない
        lines = split_lines("。" * 40, 12, indent=False)
        self.assertTrue(all(len(x) <= 12 for x in lines))
        self.assertEqual(sum(map(len, lines)), 40)

    def test_empty_paragraph(self):
        self.assertEqual(split_lines("", 12), [""])

    def test_tatechuyoko_is_one_char(self):
        self.assertEqual(units("第46回"), ["第", "46", "回"])
        self.assertEqual(text_width("第46回"), 3)
        self.assertEqual(text_width("131チーム"), 4)          # 3 桁も 1 字ぶん
        self.assertEqual(text_width("2025年"), 3)              # 4 桁は 0.5 × 4
        self.assertEqual(text_width("ＤＸとAI"), 4)
        self.assertEqual(text_width("〒781－2194"), 5.5)       # 「－」つなぎは縦中横にしない

    def test_tatechuyoko_not_split(self):
        lines = split_lines("あいうえおかきくけこさ46人", 12, indent=False)
        self.assertEqual(lines[0], "あいうえおかきくけこさ46")
        self.assertTrue(all(text_width(x) <= 12 for x in split_lines("ab" * 40, 12)))
        # 英単語は途中で分けない
        lines = split_lines("あいうえおかきくけこDXとAI。", 12, indent=False)
        self.assertTrue(all("DX" in x or "D" not in x for x in lines), lines)
        self.assertTrue(all("AI" in x or "A" not in x for x in lines), lines)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.g = Geometry()

    def test_photo_splits_dan(self):
        photo = Rect(0, 10, 2, 5)
        runs = free_runs(self.g, whole_page(self.g), [photo])
        dan0 = [r for r in runs if r.dan == 0]
        self.assertEqual([(r.line, r.line_span) for r in dan0], [(0, 10), (15, 15)])
        self.assertEqual(len([r for r in runs if r.dan == 2]), 1)

    def test_overflow_and_free(self):
        area = Rect(0, 0, 1, 30)
        r = flow(self.g, ["あ"] * 35, area, [])
        self.assertEqual(r.overflow_lines, 5)
        r = flow(self.g, ["あ"] * 20, area, [Rect(0, 0, 1, 4)])
        self.assertEqual(r.free_lines, 6)
        self.assertEqual(r.runs[0].rect.line, 4)

    def test_overlaps(self):
        self.assertTrue(Rect(0, 0, 2, 4).overlaps(Rect(1, 3)))
        self.assertFalse(Rect(0, 0, 2, 4).overlaps(Rect(2, 0)))


class DocxTest(unittest.TestCase):
    def test_writes_valid_package(self):
        g = Geometry()
        lines = layout_text(["本文の見本です。"] * 10, g.chars_per_line)
        res = flow(g, lines, whole_page(g), [])
        pages = [dx.Page([dx.TextBox(to_box(g, run.rect), run.lines) for run in res.runs]),
                 dx.Page([dx.Placeholder(to_box(g, Rect(0, 0, 2, 8)), "写真"),
                          dx.Guide(to_box(g, Rect(0, 0)))])]
        with tempfile.TemporaryDirectory() as d:
            out = dx.write_docx(Path(d) / "t.docx", g, pages)
            with zipfile.ZipFile(out) as z:
                names = set(z.namelist())
                doc = ET.fromstring(z.read("word/document.xml"))
            self.assertTrue({"[Content_Types].xml", "_rels/.rels", "word/document.xml",
                             "word/styles.xml"} <= names)
            w = "{%s}" % dx.W
            paras = doc.findall(f"{w}body/{w}p")
            self.assertEqual(len(paras), 2)                       # 1 ページ 1 段落
            self.assertIsNotNone(paras[1].find(f"{w}pPr/{w}pageBreakBefore"))
            ids = [e.get("id") for e in doc.iter("{%s}docPr" % dx.WP)]
            self.assertEqual(len(ids), len(set(ids)))             # ID が重ならない
            body = [e for e in doc.iter("{%s}bodyPr" % dx.WPS) if e.get("vert") == "eaVert"]
            self.assertEqual(len(body), len(res.runs))


if __name__ == "__main__":
    unittest.main()
