import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dropfiles  # noqa: E402
import edition  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
import sources  # noqa: E402


class WordArticlesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.docx = samples.make_gyosei_two_photos_docx(self.root / "架空の行政報告.docx")

    def tearDown(self):
        self.temp.cleanup()

    def test_headings_split_articles(self):
        parsed = sources.read_word_articles(self.docx)
        self.assertEqual([a["heading"] for a in parsed["articles"]], ["交流施設の整備", "防災訓練を実施"])
        self.assertIn("交流施設の工事", parsed["articles"][0]["body"])
        # 写真の後ろの本文も、文字を落とさず同じ記事に入る
        self.assertIn("参加者から寄せられた意見", parsed["articles"][1]["body"])
        self.assertEqual(parsed["titles"], ["町の取り組みを報告します"])
        self.assertEqual(len(parsed["photos"]), 2)

    def test_not_word_is_rejected(self):
        text = self.root / "原稿.txt"
        text.write_text("本文", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Word"):
            sources.read_word_articles(text)

    def test_import_copies_original_and_photos_without_changing_source(self):
        before = hashlib.sha256(self.docx.read_bytes()).hexdigest()
        work = edition.Edition.create(self.root / "第999号", layout.Issue(999, 4))
        first = work.import_word_articles(self.docx, "行政報告")
        second = work.import_word_articles(self.docx, "行政報告")
        self.assertEqual(hashlib.sha256(self.docx.read_bytes()).hexdigest(), before)
        self.assertTrue(Path(first["copy_path"]).is_file())
        names = [p["file"] for p in first["photos"] + second["photos"]]
        self.assertEqual(len(set(names)), 4)          # 2 回読んでも上書きしない
        self.assertTrue(all((work.folder / "写真" / n).is_file() for n in names))
        self.assertTrue(all(n.startswith("行政報告_Word_") for n in names))


class DropFilesTest(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "Windows では実際の画面で確かめる")
    def test_other_platforms_do_nothing(self):
        self.assertFalse(dropfiles.enable(object(), lambda paths: None))


if __name__ == "__main__":
    unittest.main()


class CoverCaptionTest(unittest.TestCase):
    def test_cover_caption_survives_placing_photo(self):
        # 表紙の手順で入れた写真の説明が、写真を置いても消えない。
        import items
        import samples as s
        from grid import Rect
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "第999号", layout.Issue(999, 4, "令和8年4月30日"))
            data = items.default_data(work.issue)
            data["cover"]["photo_caption"] = "架空の春まつり"
            work.save_items(data)
            (work.folder / "写真" / "表紙.png").write_bytes(s._png(1200, 800))
            work.place_photo(1, "表紙.png", Rect(0, 0, 1, 1))
            work.save_items(work.item_data())
            texts = [line for item in work.compose(1).page.items
                     for line in getattr(item, "lines", []) or []]
            self.assertIn("架空の春まつり", texts)
