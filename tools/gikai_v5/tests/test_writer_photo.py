"""事務局原稿と写真配置一覧のテスト。"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import edition  # noqa: E402
import ingest  # noqa: E402
import layout  # noqa: E402
import photo_list  # noqa: E402
import samples  # noqa: E402
import writer  # noqa: E402


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        issue = layout.Issue(999, 4, "令和8年4月30日", questioners=1)
        self.work = edition.Edition.create(self.root / "第999号", issue)
        self.page_no = next(page["no"] for page in self.work.pages
                            if page["section"] == layout.GYOSEI)

    def tearDown(self):
        self.temp.cleanup()

    def test_insert_mark_at_current_line(self):
        text, cursor = writer.insert_mark("一行目\n二行目", 6, "問")
        self.assertEqual(text, "一行目\n問　二行目")
        self.assertEqual(cursor, 8)
        photo, _cursor = writer.insert_mark("本文", 0, "写真", "【写真】見本.png｜中｜説明")
        self.assertEqual(photo, "【写真】見本.png｜中｜説明本文")

    def test_save_assign_compose_and_undo(self):
        first = "【大見出し】架空の報告\n【見出し】見本事業\n本文です。"
        relative = self.work.save_writer(self.page_no, first)
        self.assertEqual(relative, "事務局原稿/%02d_行政報告.txt" % self.page_no)
        path = self.work.folder / relative
        self.assertEqual(path.read_text(encoding="utf-8"), first)
        self.assertEqual([part.kind for part in self.work.parts(self.page_no)],
                         ["大見出し", "中見出し", "本文"])
        self.assertTrue(self.work.compose(self.page_no).placements)

        second = "【大見出し】直した報告\n問　架空の質問です。\n答　架空の回答です。"
        self.work.save_writer(self.page_no, second)
        self.assertEqual(path.read_text(encoding="utf-8"), second)
        self.assertTrue(self.work.undo())
        self.assertEqual(path.read_text(encoding="utf-8"), first)
        self.assertEqual([part.kind for part in self.work.parts(self.page_no)],
                         ["大見出し", "中見出し", "本文"])
        self.assertTrue(self.work.redo())
        self.assertEqual(path.read_text(encoding="utf-8"), second)
        self.assertEqual([part.kind for part in self.work.parts(self.page_no)],
                         ["大見出し", "質問", "答弁"])

    def test_rewrite_keeps_ingested_part_kinds(self):
        source = samples.make_ippan_docx(self.root / "架空の原稿.docx")
        page_no = next(page["no"] for page in self.work.pages
                       if page["section"] == layout.IPPAN)
        self.work.assign(page_no, source)
        before = [part.kind for part in self.work.parts(page_no)]
        marked = self.work.writer_text(page_no)
        after = [part.kind for part in ingest.ingest_text(marked).parts]
        self.assertEqual(after, before)

    def test_writer_has_valid_python_syntax(self):
        ast.parse((HERE.parent / "writer.py").read_text(encoding="utf-8"))


class PhotoListTest(unittest.TestCase):
    def test_dpi_has_two_warning_levels(self):
        self.assertEqual(photo_list.dpi_warning(199), "画質が足りません（199dpi）")
        self.assertEqual(photo_list.dpi_warning(200), "画質が足りないおそれ（200dpi）")
        self.assertEqual(photo_list.dpi_warning(349), "画質が足りないおそれ（349dpi）")
        self.assertEqual(photo_list.dpi_warning(350), "")
        self.assertEqual(photo_list.dpi_warning(None), "画素数を読み取れません")

    def test_exported_list_has_photo_row_name_and_mm(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = edition.Edition.create(root / "第999号",
                                          layout.Issue(999, 4, "令和8年4月30日"))
            page_no = next(page["no"] for page in work.pages
                           if page["section"] == layout.GYOSEI)
            photo = root / "架空の風景.png"
            photo.write_bytes(samples._png(1000, 1000))
            name = work.keep_writer_photo(photo)
            work.save_writer(page_no,
                             f"【大見出し】架空の報告\n【写真】{name}｜中｜架空の風景")
            records, _written = work._photo_records()
            self.assertEqual(len(records), 1)
            paths = work.export()
            photo_docx = paths[2]
            with zipfile.ZipFile(photo_docx) as package:
                xml = package.read("word/document.xml").decode("utf-8")
            self.assertEqual(xml.count("<w:tr>"), 2)
            self.assertIn(f"p{page_no:02d}_写真1.png", xml)
            self.assertIn(f"{records[0].width_mm:.1f}", xml)
            self.assertIn(f"{records[0].height_mm:.1f}", xml)
            self.assertIn("架空の風景", xml)

    def test_unreadable_pixels_are_listed_and_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = edition.Edition.create(root / "第999号",
                                          layout.Issue(999, 4, "令和8年4月30日"))
            page_no = next(page["no"] for page in work.pages
                           if page["section"] == layout.GYOSEI)
            bad = work.folder / "写真" / "壊れた見本.png"
            bad.write_bytes(b"not a png")
            work.save_writer(page_no,
                             "【大見出し】架空の報告\n【写真】壊れた見本.png｜小｜確認用")
            records, _written = work._photo_records()
            self.assertEqual(records[0].warning, "画素数を読み取れません")
            self.assertTrue(any("画素数を読み取れません" in item for item in work.check()))

    def test_form_page_photos_are_included(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = edition.Edition.create(root / "第999号",
                                          layout.Issue(999, 4, "令和8年4月30日"))
            photo = root / "架空の表紙.png"
            photo.write_bytes(samples._png(1200, 800))
            cover = next(page for page in work.pages if page["section"] == layout.COVER)
            work.set_form(cover["no"], {"photo": str(photo),
                                        "photo_caption": "架空の催し"})
            records, _written = work._photo_records()
            item = next(record for record in records if record.page_no == cover["no"])
            self.assertEqual(item.size, "表紙")
            self.assertEqual(item.original_name, "架空の表紙.png")
            self.assertEqual(item.caption, "架空の催し")


if __name__ == "__main__":
    unittest.main()
