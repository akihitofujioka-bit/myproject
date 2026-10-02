"""段階 5 の号フォルダ・手操作・書き出しのテスト。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import edition  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
from grid import Rect  # noqa: E402


class EditionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = samples.make_ippan_docx(self.root / "見本原稿.docx")
        self.issue = layout.Issue(999, 4, "令和8年4月30日", questioners=2)
        self.edition = edition.Edition.create(self.root / "第999号", self.issue)
        self.ippan = [p["no"] for p in self.edition.pages
                      if p["section"] == layout.IPPAN]

    def tearDown(self):
        self.temp.cleanup()

    def test_create_save_open_keeps_same_contents(self):
        self.edition.assign(self.ippan[0], self.source)
        before = json.loads((self.edition.folder / "紙面.json").read_text(encoding="utf-8"))
        reopened = edition.Edition.open(self.edition.folder)
        reopened.save()
        after = json.loads((self.edition.folder / "紙面.json").read_text(encoding="utf-8"))
        self.assertEqual(before, after)
        self.assertEqual(reopened.issue, self.edition.issue)
        self.assertTrue((self.edition.folder / "原稿" / "見本原稿.docx").is_file())
        self.assertTrue((self.edition.folder / "写真").is_dir())

    def test_actions_undo_and_redo(self):
        page_no = self.ippan[0]
        self.edition.assign(page_no, self.source)
        result = self.edition.compose(page_no)
        photo = next(p for p in result.placements if p.part.kind == "写真")
        target = Rect(2, 20, photo.rect.dan_span, photo.rect.line_span)
        self.assertTrue(self.edition.move_part(page_no, photo.index, target))
        self.assertEqual(next(p.rect for p in self.edition.compose(page_no).placements
                              if p.index == photo.index), target)
        self.assertTrue(self.edition.resize_photo(page_no, photo.index, "小"))
        self.edition.remove_photo(page_no, photo.index)
        self.assertFalse(any(p.index == photo.index for p in self.edition.compose(page_no).placements))
        self.assertTrue(self.edition.undo())
        self.assertTrue(any(p.index == photo.index for p in self.edition.compose(page_no).placements))
        self.assertTrue(self.edition.redo())
        self.assertFalse(any(p.index == photo.index for p in self.edition.compose(page_no).placements))
        self.edition.restore_photo(page_no, photo.index)
        self.assertTrue(any(p.index == photo.index for p in self.edition.compose(page_no).placements))

    def test_overlapping_move_is_refused(self):
        page_no = self.ippan[0]
        self.edition.assign(page_no, self.source)
        result = self.edition.compose(page_no)
        title = next(p for p in result.placements if p.part.kind == "大見出し")
        photo = next(p for p in result.placements if p.part.kind == "写真")
        self.assertFalse(self.edition.move_part(page_no, photo.index, title.rect))
        current = next(p.rect for p in self.edition.compose(page_no).placements
                       if p.index == photo.index)
        self.assertEqual(current, photo.rect)

    def test_questioner_change_keeps_assignments_by_section_order(self):
        self.edition.assign(self.ippan[0], self.source)
        second = samples.make_overflow_ippan_docx(self.root / "別の見本原稿.docx")
        self.edition.assign(self.ippan[1], second)
        self.edition.change_issue(questioners=3)
        pages = [p for p in self.edition.pages if p["section"] == layout.IPPAN]
        self.assertEqual([p["source"] for p in pages],
                         ["見本原稿.docx", "別の見本原稿.docx", None])
        self.assertTrue(self.edition.undo())
        self.assertEqual(len([p for p in self.edition.pages
                              if p["section"] == layout.IPPAN]), 2)

    def test_export_has_all_pages_photos_and_checklist(self):
        self.edition.assign(self.ippan[0], self.source)
        paths = self.edition.export()
        docx, checklist = paths[:2]
        self.assertTrue(docx.is_absolute())
        self.assertTrue(checklist.is_absolute())
        with zipfile.ZipFile(docx) as package:
            names = package.namelist()
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("word/document.xml", names)
        self.assertEqual(xml.count("<w:pageBreakBefore/>"), len(self.edition.pages) - 1)
        self.assertTrue((self.edition.folder / "出力" / "写真" /
                         f"p{self.ippan[0]:02d}_写真1.png").is_file())
        text = checklist.read_text(encoding="utf-8")
        self.assertIn("原稿が未入力です", text)


class ComposeOverrideTest(unittest.TestCase):
    def test_manual_photo_and_bad_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            source = samples.make_ippan_docx(Path(folder) / "見本.docx")
            import ingest
            import compose
            from grid import Geometry

            loaded = ingest.ingest(source)
            photo_no = next(n for n, p in enumerate(loaded.parts) if p.kind == "写真")
            target = Rect(3, 20, 1, 5)
            moved = compose.compose_page(layout.IPPAN, loaded.parts, loaded.images,
                                         Geometry(), {photo_no: {"rect": target, "size": "顔",
                                                                 "removed": False}})
            self.assertEqual(next(p.rect for p in moved.placements if p.index == photo_no), target)
            bad = compose.compose_page(layout.IPPAN, loaded.parts, loaded.images,
                                       Geometry(), {photo_no: {"rect": Rect(-1, 0, 1, 5),
                                                               "size": "顔", "removed": False}})
            self.assertTrue(any("自動の位置に戻しました" in w for w in bad.warnings))
            self.assertNotEqual(next(p.rect for p in bad.placements if p.index == photo_no),
                                Rect(-1, 0, 1, 5))


if __name__ == "__main__":
    unittest.main()
