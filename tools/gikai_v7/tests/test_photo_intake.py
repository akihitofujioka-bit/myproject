"""写真の受取名・簡単配置のテスト。すべて架空データ。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import edition  # noqa: E402
import items  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
from grid import Rect  # noqa: E402


class PhotoIntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = edition.Edition.create(self.root / "第999号", layout.Issue(999, 4))

    def tearDown(self):
        self.temp.cleanup()

    def test_received_photo_is_copied_with_meaningful_unique_name(self):
        source = self.root / "添付写真.png"
        source.write_bytes(samples._png(1200, 800))
        before = source.read_bytes()
        first = self.work.add_received_photo(source, "見本 太郎", "架空の防災")
        second = self.work.add_received_photo(source, "見本 太郎", "架空の防災")
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(first["name"], "写真_見本_太郎_架空の防災_1.png")
        self.assertEqual(second["name"], "写真_見本_太郎_架空の防災_2.png")
        self.assertGreater(first["dpi"], 0)

    def test_unreadable_format_explains_jpeg_conversion(self):
        source = self.root / "架空写真.heic"
        source.write_bytes(b"not-an-image")
        with self.assertRaisesRegex(ValueError, "JPEG に書き出し"):
            self.work.add_received_photo(source, "見本 花子", "架空記事")

    def test_click_like_placement_uses_nearest_space_and_word_name(self):
        source = self.root / "架空写真.png"
        source.write_bytes(samples._png(1600, 1200))
        result = self.work.add_received_photo(source, "見本 次郎", "架空記事")
        data = items.default_data(self.work.issue)
        data["photos"] = [{"file": result["name"], "member": "見本 次郎", "article": "架空記事"}]
        self.work.save_items(data)
        page = next(value["no"] for value in self.work.pages if value["section"] == layout.GYOSEI)
        actual, _shifted = self.work.place_photo_near(page, result["name"], Rect(0, 0), "小", "架空説明")
        self.assertGreaterEqual(actual.dan, 0)
        records, _ = self.work._photo_records()
        record = next(value for value in records if value.original_name == result["name"])
        self.assertEqual((record.member, record.article), ("見本 次郎", "架空記事"))
        paths = self.work.export()
        with zipfile.ZipFile(paths[0]) as package:
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("写真_見本_次郎_架空記事_1", xml)


if __name__ == "__main__":
    unittest.main()
