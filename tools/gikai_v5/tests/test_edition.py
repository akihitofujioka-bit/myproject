"""段階 5 の号フォルダ・手操作・書き出しのテスト。"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import edition  # noqa: E402
import compose  # noqa: E402
import docx_out  # noqa: E402
import ingest  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
from grid import Geometry, Rect  # noqa: E402


class EditionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = samples.make_ingest_image_docx(self.root / "画像取り込み確認原稿.docx")
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
        self.assertTrue((self.edition.folder / "原稿" / "画像取り込み確認原稿.docx").is_file())
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
                         ["画像取り込み確認原稿.docx", "別の見本原稿.docx", None])
        self.assertTrue(self.edition.undo())
        self.assertEqual(len([p for p in self.edition.pages
                              if p["section"] == layout.IPPAN]), 2)

    def test_export_has_all_pages_photos_and_checklist(self):
        self.edition.assign(self.ippan[0], self.source)
        hidden = self.edition.folder / "写真" / ".縮小"
        hidden.mkdir()
        (hidden / "画面だけ.png").write_bytes(samples._png(48, 48))
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
        self.assertFalse((self.edition.folder / "出力" / "写真" / "画面だけ.png").exists())
        self.assertTrue(all(".縮小" not in str(path) for path in paths))
        text = checklist.read_text(encoding="utf-8")
        self.assertIn("原稿が未入力です", text)

    def test_set_kind_undo_redo_and_reopen(self):
        page_no = self.ippan[0]
        self.edition.assign(page_no, self.source)
        original = self.edition.parts(page_no)
        part_no = next(n for n, part in enumerate(original) if part.kind == "質問")

        self.edition.set_kind(page_no, part_no, "答弁")
        changed = self.edition.parts(page_no)[part_no]
        self.assertEqual(changed.kind, "答弁")
        self.assertTrue(changed.sure)
        self.assertEqual(changed.reason, "人が直した")
        saved = json.loads((self.edition.folder / "紙面.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["pages"][page_no - 1]["overrides"][str(part_no)]["kind"], "答弁")

        self.assertTrue(self.edition.undo())
        self.assertEqual(self.edition.parts(page_no)[part_no].kind, "質問")
        self.assertTrue(self.edition.redo())
        self.assertEqual(self.edition.parts(page_no)[part_no].kind, "答弁")
        reopened = edition.Edition.open(self.edition.folder)
        self.assertEqual(reopened.parts(page_no)[part_no].kind, "答弁")

    def test_next_hint_follows_edition_state(self):
        self.assertIn("新しい号", edition.next_hint(None))
        self.assertIn("○", edition.next_hint(self.edition))
        for page in self.edition.pages:
            page["state"] = "できた"
        self.edition.pages[0]["state"] = "あふれ"
        self.assertIn("写真を小さく", edition.next_hint(self.edition))
        self.edition.pages[0]["state"] = "できた"
        self.assertIn("Word に書き出す", edition.next_hint(self.edition))

    def test_photo_folder_list_and_placed_photo_lifecycle(self):
        page_no = next(p["no"] for p in self.edition.pages if p["section"] == layout.GYOSEI)
        photo = self.edition.folder / "写真" / "架空の風景.png"
        photo.write_bytes(samples._png(640, 480))
        jpeg = self.edition.folder / "写真" / "架空の会場.jpg"
        jpeg.write_bytes(b"\xff\xd8\xff\xc0\x00\x0b\x08\x01\xe0\x02\x80\x03\x01\x11\x00")
        (self.edition.folder / "写真" / "架空.heic").write_bytes(b"unreadable")
        hidden = self.edition.folder / "写真" / ".縮小"
        hidden.mkdir()
        (hidden / "画面用.png").write_bytes(samples._png(48, 48))
        listed = {item["name"]: item for item in self.edition.photo_files()}
        self.assertNotIn("画面用.png", listed)
        self.assertEqual(listed["架空の風景.png"]["pixels"], (640, 480))
        self.assertEqual(listed["架空の会場.jpg"]["pixels"], (640, 480))
        if sys.platform == "darwin":
            self.assertEqual(listed["架空.heic"]["message"], "")
        else:
            self.assertIn("JPEG か PNG", listed["架空.heic"]["message"])

        target = Rect(2, 12, 1, 1)
        self.assertTrue(self.edition.place_photo(page_no, photo.name, target))
        part_no = next(i for i, part in enumerate(self.edition.parts(page_no))
                       if part.kind == "写真")
        self.assertFalse(self.edition.place_photo(page_no, photo.name, target))
        self.assertTrue(self.edition.resize_photo(page_no, part_no, "小"))
        self.edition.set_photo_caption(page_no, part_no, "架空の催し")
        self.assertEqual(self.edition.pages[page_no - 1]["placed_photos"][0]["caption"],
                         "架空の催し")
        self.edition.remove_photo(page_no, part_no)
        self.assertFalse(self.edition.compose(page_no).placements)
        self.assertTrue(self.edition.undo())
        self.assertTrue(self.edition.compose(page_no).placements)
        reopened = edition.Edition.open(self.edition.folder)
        self.assertEqual(reopened.pages[page_no - 1]["placed_photos"][0]["size"], "小")

    def test_placed_photos_on_cover_last_and_export(self):
        photo = self.edition.folder / "写真" / "架空の会場.png"
        photo.write_bytes(samples._png(1200, 800))
        cover = next(p["no"] for p in self.edition.pages if p["section"] == layout.COVER)
        last = next(p["no"] for p in self.edition.pages if p["section"] == layout.LAST)
        self.assertTrue(self.edition.place_photo(cover, photo.name, Rect(0, 0, 1, 1)))
        self.assertTrue(self.edition.place_photo(last, photo.name, Rect(0, 0, 1, 1)))
        self.assertTrue(self.edition.place_photo(last, photo.name, Rect(0, 8, 1, 1)))
        with self.assertRaisesRegex(ValueError, "2枚まで"):
            self.edition.place_photo(last, photo.name, Rect(0, 16, 1, 1))
        self.assertTrue(self.edition.pages[cover - 1]["form"]["photo"].endswith(photo.name))
        self.assertEqual(len(self.edition.pages[last - 1]["form"]["editorial_photos"]), 2)
        paths = self.edition.export()
        with zipfile.ZipFile(paths[0]) as package:
            names = package.namelist()
        self.assertTrue(any(name.startswith("word/media/") for name in names))
        records, _ = self.edition._photo_records()
        self.assertEqual(len([r for r in records if r.page_no in (cover, last)]), 3)


class ComposeOverrideTest(unittest.TestCase):
    def test_manual_photo_and_bad_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            source = samples.make_ingest_image_docx(Path(folder) / "画像取り込み確認.docx")
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

    def test_kind_override_is_used_for_composition(self):
        parts = [ingest.Part("本文", "架空の質問です。", False, "推測")]
        result = compose.compose_page(layout.IPPAN, parts, {}, Geometry(),
                                      {0: {"kind": "質問"}})
        self.assertEqual(result.placements[0].part.kind, "質問")
        self.assertTrue(result.placements[0].part.sure)
        self.assertEqual(result.placements[0].part.reason, "人が直した")
        box = next(item for item in result.page.items
                   if isinstance(item, docx_out.TextBox))
        self.assertEqual(box.font, docx_out.GOTHIC)

    def test_override_without_kind_keeps_composition_same(self):
        parts = [ingest.Part("本文", "架空の本文です。", True, "見本")]
        plain = compose.compose_page(layout.IPPAN, parts, {}, Geometry())
        legacy = compose.compose_page(
            layout.IPPAN, parts, {}, Geometry(),
            {0: {"rect": None, "size": None, "removed": False}})
        self.assertEqual(plain, legacy)


class AppSyntaxTest(unittest.TestCase):
    def test_app_has_valid_python_syntax(self):
        source = (HERE.parent / "app.pyw").read_text(encoding="utf-8")
        ast.parse(source)


if __name__ == "__main__":
    unittest.main()
