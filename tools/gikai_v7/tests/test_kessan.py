import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import docx_out as dx  # noqa: E402
import edition  # noqa: E402
import items  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
import templates  # noqa: E402
from grid import Geometry, Rect, to_box  # noqa: E402

ISSUE = layout.Issue(997, 10, "令和8年10月31日")


class KessanTemplateTest(unittest.TestCase):
    def build(self, data):
        form = items.kessan_form(data, ISSUE)
        return templates.build(layout.KESSAN, form, ISSUE, layout.make_plan(ISSUE), None, Geometry())

    def test_title_is_previous_fiscal_year(self):
        self.assertEqual(templates.kessan_title(ISSUE), "令和７年度決算認定")

    def test_page_has_reference_shape(self):
        data = items.default_data(ISSUE)
        data["kessan"]["questions"] = [{"heading": "一般会計", "question": "見本の質問は。",
                                        "answer": "見本の答えです。"}]
        result = self.build(data)
        names = [getattr(item, "name", "") for item in result.page.items]
        for name in ("決算の囲み", "決算の題", "会計の種類", "決算写真", "円グラフの指示",
                     "会計別決算額", "決算の質疑"):
            self.assertIn(name, names)
        note = next(item for item in result.page.items if getattr(item, "name", "") == "円グラフの指示")
        self.assertEqual(note.shape, "ellipse")
        texts = [line for item in result.page.items for line in getattr(item, "lines", []) or []]
        self.assertIn("【一般会計】", texts)
        self.assertEqual(result.overflow_lines, 0)

    def test_account_table_merges_groups(self):
        rows, spans, merges, vertical = templates._account_table(items.default_kessan()["accounts"])
        self.assertEqual(rows[1][:2], ["特別会計", "国民健康保険特別会計"])
        self.assertEqual(merges[(1, 0)], "restart")
        self.assertEqual(merges[(3, 0)], "continue")
        self.assertIn((1, 0), vertical)                    # 特別会計は縦書き
        self.assertEqual(spans[(4, 0)], 2)                 # 簡易水道事業会計は 2 列ぶん横書き
        self.assertNotIn((4, 0), vertical)

    def test_table_and_questions_do_not_overlap(self):
        result = self.build(items.default_data(ISSUE))
        table = next(item for item in result.page.items if isinstance(item, dx.Table))
        dan5 = to_box(Geometry(), Rect(4, 0, 1, 1))
        self.assertLessEqual(table.box.y + table.box.h, dan5.y)

    def test_word_has_ellipse_and_merged_cells(self):
        result = self.build(items.default_data(ISSUE))
        with tempfile.TemporaryDirectory() as folder:
            path = dx.write_docx(Path(folder) / "決算.docx", Geometry(), [result.page])
            xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        self.assertIn('prst="ellipse"', xml)
        self.assertIn('<w:vMerge w:val="restart"/>', xml)
        self.assertIn('<w:gridSpan w:val="2"/>', xml)


class KessanEditionTest(unittest.TestCase):
    def test_october_issue_uses_template_and_photo(self):
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "第997号", ISSUE)
            (work.folder / "写真" / "決算審査.png").write_bytes(samples._png(1600, 900))
            data = items.default_data(ISSUE)
            data["kessan"]["photo"] = "決算審査.png"
            work.save_items(data)
            page = next(p for p in work.pages if p["section"] == layout.KESSAN)
            self.assertIn("form", page)
            items_on_page = work.compose(page["no"]).page.items
            self.assertTrue(any(isinstance(x, dx.Picture) and x.name == "決算写真" for x in items_on_page))
            with self.assertRaisesRegex(ValueError, "予算・決算"):
                work.place_photo(page["no"], "決算審査.png", Rect(0, 0, 1, 1))


if __name__ == "__main__":
    unittest.main()
