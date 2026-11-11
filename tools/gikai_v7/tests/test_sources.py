"""原稿の届き方と確認用 Word のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import sources  # noqa: E402


def make_docx(path: Path) -> Path:
    document = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>見本の備え</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>問　架空の備えは。</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>答　見本倉庫にあります。</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
    return path


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_word_import_and_archive_do_not_change_source(self):
        path = make_docx(self.root / "架空原稿.docx")
        before = path.read_bytes()
        parsed = sources.read_word(path)
        copied = sources.archive_file(path, self.root / "第999号", "見本 太郎")
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(copied.is_file())
        self.assertEqual(parsed["questions"][0]["question"], "架空の備えは。")
        self.assertEqual(parsed["questions"][0]["answer"], "見本倉庫にあります。")

    def test_email_candidates_joining_and_normalizing(self):
        text = ("From: sample@example.invalid\n件名: 架空の質問\n"
                "問　備えは\nありますか。\n\n答　見本倉庫に\nあります。\n"
                "> 引用です\n--\n見本 太郎")
        candidates = sources.email_candidates(text)
        reasons = "\n".join(value["reason"] for value in candidates)
        self.assertIn("ヘッダ", reasons)
        self.assertIn("引用", reasons)
        self.assertIn("署名", reasons)
        parsed = sources.prepare_email(text, [v["line"] for v in candidates])
        self.assertIn("問　備えは\nありますか。", parsed["cleaned"])
        self.assertIn("答　見本倉庫に\nあります。", parsed["cleaned"])
        self.assertIn("\n\n答", parsed["cleaned"])

    def test_reception_status_and_confirmation_never_overwrite(self):
        members = ["見本 太郎", "見本 花子", "見本 次郎"]
        questions = [
            {"member": "見本 太郎", "qa_bulk": "", "confirmed": "未"},
            {"member": "見本 花子", "qa_bulk": "問　架空です。", "confirmed": "未"},
            {"member": "見本 次郎", "qa_bulk": "問　見本です。", "confirmed": "済"},
        ]
        self.assertEqual([v["status"] for v in sources.reception_status(members, questions)],
                         ["入力中", "議員確認待ち", "確認済み"])
        people = [{"member": "見本 太郎", "title": "架空の防災", "questions": [
            {"heading": "備え", "question": "備えは。", "answer": "進めます。"}]}]
        first = sources.write_confirmation(self.root / "確認用.docx", people)
        before = first.read_bytes()
        second = sources.write_confirmation(self.root / "確認用.docx", people)
        self.assertEqual(first.name, "確認用.docx")
        self.assertEqual(second.name, "確認用_2.docx")
        self.assertEqual(first.read_bytes(), before)
        with zipfile.ZipFile(first) as package:
            xml = package.read("word/document.xml").decode("utf-8")
        self.assertIn("1. 備え", xml)   # 1 番目の大まかな質問
        self.assertIn('w:sz w:val="22"', xml)
        self.assertIn('w:lineRule="atLeast"', xml)


if __name__ == "__main__":
    unittest.main()
