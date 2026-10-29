"""特集の表（Word・エクセルから読む、本文の【表】に入れる、紙面に置く）と、複数の特集のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import compose  # noqa: E402
import docx_out as dx  # noqa: E402
import ingest  # noqa: E402
import items  # noqa: E402
import layout  # noqa: E402
import tables  # noqa: E402
from grid import Geometry  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
X = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _cell(text, props=""):
    return f"<w:tc>{props}<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def _docx(path: Path) -> Path:
    span = '<w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
    body = ("<w:tbl>"
            f"<w:tr>{_cell('地区')}{_cell('避難所')}{_cell('定員')}</w:tr>"
            f"<w:tr>{_cell('見本地区')}{_cell('見本小学校　ほか', span)}</w:tr>"
            "</w:tbl>")
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return path


def _xlsx(path: Path) -> Path:
    rows = ('<row r="2"><c r="B2" t="inlineStr"><is><t>地区</t></is></c><c r="C2" t="inlineStr"><is><t>定員</t></is></c></row>'
            '<row r="3"><c r="B3" t="inlineStr"><is><t>架空地区</t></is></c><c r="C3"><v>120</v></c></row>'
            '<row r="4"><c r="B4" t="inlineStr"><is><t>見本地区</t></is></c><c r="C4"><v>1500.0</v></c></row>')
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("xl/workbook.xml", f'<workbook {X} {R}><sheets><sheet name="表" sheetId="1" r:id="rId1"/></sheets></workbook>')
        package.writestr("xl/_rels/workbook.xml.rels",
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        package.writestr("xl/worksheets/sheet1.xml", f"<worksheet {X}><sheetData>{rows}</sheetData></worksheet>")
    return path


class TableTest(unittest.TestCase):
    def test_parse_rows_tab_or_bar(self):
        self.assertEqual(tables.parse_rows("地区\t定員\n見本\t300"), [["地区", "定員"], ["見本", "300"]])
        self.assertEqual(tables.parse_rows("｜地区｜定員｜\n見本|300|備考"), [["地区", "定員", ""], ["見本", "300", "備考"]])

    def test_fill_marks_and_missing(self):
        body, missing = tables.fill_marks("前の文。\n【表】一覧\n【表】無い表", [{"name": "一覧", "data": "甲\t乙"}])
        lines = body.splitlines()
        self.assertEqual(lines[0], "前の文。")
        self.assertEqual(tables.decode(lines[1]), ("一覧", [["甲", "乙"]]))
        self.assertEqual(missing, ["無い表"])

    def test_read_word_and_excel(self):
        with tempfile.TemporaryDirectory() as folder:
            found = tables.read_word_tables(_docx(Path(folder) / "架空.docx"))
            self.assertEqual(found, [[["地区", "避難所", "定員"], ["見本地区", "見本小学校　ほか", ""]]])
            rows = tables.read_excel_table(_xlsx(Path(folder) / "架空.xlsx"))
            self.assertEqual(rows, [["地区", "定員"], ["架空地区", "120"], ["見本地区", "1500"]])

    def test_table_is_placed_in_free_width_below_text(self):
        g = Geometry()
        text = ("【大見出し】架空の特集\n" + "架空の本文です。" * 30 + "\n"
                + tables.encode("一覧", [["地区", "定員（人）"], ["見本地区", "300"]]) + "\n" + "表のあとの文。" * 5)
        parts = ingest.ingest_text(text).parts
        self.assertIn("表", [part.kind for part in parts])
        result = compose.compose_page(layout.TOKUSHU, parts, {}, g)
        table = next(item for item in result.page.items if isinstance(item, dx.Table))
        self.assertEqual(table.rows[1], ["見本地区", "300"])   # 数字は表に書いたまま
        width = compose.to_box(g, compose.Rect(0, 0, 1, g.lines_per_dan)).w
        # 大見出しの横の段でも、空いている幅（ページの幅の 6 割以上）に合わせて置く
        self.assertAlmostEqual(sum(table.column_widths), table.box.w, places=3)
        self.assertGreaterEqual(table.box.w, width * compose.TABLE_MIN_RATIO)
        # 表のあとの本文は、表より下の段に入る
        after = [p for p in result.placements if p.part.text.startswith("表のあと")]
        placed = next(p for p in result.placements if p.part.kind == "表")
        self.assertTrue(after and all(p.rect.dan > placed.rect.dan for p in after))
        self.assertEqual(result.overflow_lines, 0)


class FeaturesTest(unittest.TestCase):
    def test_several_features_follow_each_other(self):
        data = {"features": [{"title": "甲の特集", "body": "甲の本文。\n【表】一覧"},
                             {"title": "乙の特集", "body": "乙の本文。"}],
                "tables": [{"name": "一覧", "data": "地区\t定員"}]}
        text = items.marked_pages(data, layout.Issue(1, 4))[layout.TOKUSHU][0]
        self.assertTrue(text.startswith("【大見出し】甲の特集\n甲の本文。\n【表】{"))
        self.assertIn("\n【大見出し】乙の特集\n乙の本文。", text)

    def test_old_single_feature_still_works(self):
        data = {"feature": {"title": "前の特集", "body": "前の本文。"}}
        self.assertEqual([f["title"] for f in items.features(data)], ["前の特集"])
        self.assertIn("【大見出し】前の特集", items.features_text(data))



class FreeImageTest(unittest.TestCase):
    def test_free_images_fill_free_area_in_order(self):
        import samples
        import templates
        from settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            wide, tall = Path(folder) / "図形.png", Path(folder) / "写真.png"
            wide.write_bytes(samples._png(1600, 500))
            tall.write_bytes(samples._png(1200, 900))
            g = Geometry()
            result = templates.build(layout.LAST, {"free_images": [str(wide), str(tall)], "free": "出ない字"},
                                     layout.Issue(1, 4), layout.make_plan(layout.Issue(1, 4)),
                                     Settings(["見本 太郎"], "見本 太郎", "見本委員会"), g)
            pictures = [item for item in result.page.items if isinstance(item, dx.Picture)]
            self.assertEqual([p.name for p in pictures], ["自由欄の画像1", "自由欄の画像2"])
            area = compose.to_box(g, compose.Rect(1, 0, 3, g.lines_per_dan))
            self.assertGreaterEqual(pictures[0].box.y, area.y - 0.01)
            self.assertLessEqual(pictures[1].box.y + pictures[1].box.h, area.y + area.h + 0.01)
            self.assertFalse(any(getattr(item, "name", "") == "自由欄" for item in result.page.items))
            self.assertTrue(any("字と画像の両方" in warning for warning in result.warnings))


class FacePhotoTest(unittest.TestCase):
    def test_first_page_face_is_between_two_headings(self):
        """一般質問の最初のページは「一般質問に◯氏が立つ」→ 1 人目の顔写真 → 1 人目の題 の順（右から）。"""
        import edition
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
            work.save_settings(["見本 太郎", "見本 花子"], "見本 太郎")
            data = work.item_data()
            for heading in ("防災対策の強化を", "防災対策と避難所の備えを今後どう進めるのかを問う"):
                qs = [{"heading": heading, "heading_answer": "進める", "question": "架空の質問。", "answer": "架空の答弁。"}]
                data["questions"] = [{"member": n, "questions": qs, "qa_bulk": items.bulk_text(qs)}
                                     for n in ("見本 太郎", "見本 花子")]
                work.save_items(data)
                page = [p["no"] for p in work.pages if p["section"] == layout.IPPAN][0]
                placed = {p.part.kind + str(i): p.rect for i, p in enumerate(work.compose(page).placements)
                          if p.part.kind in ("大見出し", "写真")}
                titles = sorted((r for k, r in placed.items() if k.startswith("大見出し")), key=lambda r: r.line)
                face = next(r for k, r in placed.items() if k.startswith("写真"))
                self.assertEqual(face.dan, 0)
                self.assertLess(titles[0].line, face.line)
                self.assertLessEqual(face.line + face.line_span, titles[1].line)

    def test_face_size_can_change_and_stays_portrait(self):
        """顔写真の枠は縦長のまま大きさを変えられ、保存し直しても残る。"""
        import edition
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
            work.save_settings(["見本 太郎", "見本 花子"], "見本 太郎")
            data = work.item_data()
            qs = [{"heading": "架空", "question": "架空の質問。", "answer": "架空の答弁。"}]
            data["questions"] = [{"member": n, "questions": qs, "qa_bulk": items.bulk_text(qs)}
                                 for n in ("見本 太郎", "見本 花子")]
            work.save_items(data)
            page = [p["no"] for p in work.pages if p["section"] == layout.IPPAN][1]
            face = next(p for p in work.compose(page).placements if p.part.kind == "写真")
            self.assertTrue(work.resize_photo(page, face.index, "顔大"))
            work.save_items(work.item_data())
            frame = next(i for i in work.compose(page).page.items if isinstance(i, dx.Placeholder))
            self.assertAlmostEqual(frame.box.w * 25.4 / 72, 30.0, places=1)
            self.assertAlmostEqual(frame.box.h / frame.box.w, 4 / 3, places=2)

    def test_big_heading_can_be_dragged_and_is_left_aligned(self):
        """大見出しも紙面を見るのドラッグ（近くへ寄せて動かす）で動き、字は左づめ（縦書きは上づめ）。"""
        import edition
        from grid import Rect
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
            work.save_settings(["見本 太郎"], "見本 太郎")
            data = work.item_data()
            data["gyosei"]["reports"] = [{"heading": "架空の事業", "body": "架空の本文です。" * 40}]
            work.save_items(data)
            head = next(p for p in work.compose(2).placements if p.part.kind == "大見出し")
            moved, _shifted = work.move_part_near(2, head.index, Rect(2, 10, 1, 1))
            self.assertNotEqual(moved, head.rect)
            work.save_items(work.item_data())
            result = work.compose(2)
            self.assertEqual(next(p.rect for p in result.placements if p.index == head.index), moved)
            box = next(i for i in result.page.items if getattr(i, "name", "") == "大見出し")
            self.assertEqual(box.align, "左")

    def test_face_frame_has_name_and_keeps_moved_place_after_save(self):
        import edition
        from grid import Rect
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
            work.save_settings(["見本 太郎", "見本 花子"], "見本 花子")
            data = work.item_data()
            qa = "【見出し】架空の質問\n問　" + "架空の質問です。" * 10 + "\n答　" + "架空の答弁です。" * 20
            data["questions"] = [{"member": n, "qa_bulk": qa, "questions": items.parse_bulk(qa)["questions"]}
                                 for n in ("見本 太郎", "見本 花子")]
            work.save_items(data)
            page = [p["no"] for p in work.pages if p["section"] == layout.IPPAN][1]
            result = work.compose(page)
            names = ["".join(i.lines) for i in result.page.items if getattr(i, "name", "") == "顔写真の議員名"]
            self.assertEqual(names, ["見本 花子議員"])
            face = next(p for p in result.placements if p.part.kind == "写真")
            moved, _shifted = work.move_part_near(page, face.index, Rect(2, 10, 1, 1))
            work.save_items(work.item_data())   # 入力を保存し直しても、動かした位置は残る
            again = next(p for p in work.compose(page).placements if p.part.kind == "写真")
            self.assertEqual(again.rect, moved)

if __name__ == "__main__":
    unittest.main()
