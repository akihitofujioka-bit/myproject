"""議案と賛否 Excel のテスト。名前と内容はすべて架空。"""

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
import items  # noqa: E402
import layout  # noqa: E402
import votes_xlsx  # noqa: E402


def add_rows(path: Path, rows: list[list[str]]) -> None:
    with zipfile.ZipFile(path) as package:
        files = {name: package.read(name) for name in package.namelist()}
    xml = files["xl/worksheets/sheet1.xml"].decode("utf-8")
    body = "".join(votes_xlsx._inline_row(number, row)
                   for number, row in enumerate(rows, 2))
    xml = xml.replace("</sheetData>", body + "</sheetData>")
    files["xl/worksheets/sheet1.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in files.items():
            package.writestr(name, data)


class VotesXlsxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.members = ["見本 太郎", "見本 花子", "見本 次郎"]

    def tearDown(self):
        self.temp.cleanup()

    def test_template_reads_back_and_never_overwrites(self):
        first = votes_xlsx.make_template(self.root / "賛否.xlsx", self.members, "見本 花子")
        before = first.read_bytes()
        second = votes_xlsx.make_template(self.root / "賛否.xlsx", self.members, "見本 花子")
        self.assertEqual(first.name, "賛否.xlsx")
        self.assertEqual(second.name, "賛否_2.xlsx")
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(votes_xlsx.read_votes(first, self.members, "見本 花子"), ([], [], []))
        with zipfile.ZipFile(first) as package:
            workbook = package.read("xl/workbook.xml").decode("utf-8")
        self.assertIn("議案と賛否", workbook)
        self.assertIn("書き方", workbook)

    def test_marks_mismatch_bad_mark_empty_subject_and_counts(self):
        path = votes_xlsx.make_template(self.root / "入力.xlsx",
                                        ["見本 太郎", "名簿外 三郎", "見本 花子"],
                                        "見本 花子")
        add_rows(path, [
            ["議案", "議案第1号", "架空条例", "原案可決", "○", "●", ""],
            ["発議案", "", "架空の発議", "可決", "×", "", ""],
            ["同意", "同意第1号", "", "同意", "○", "○", ""],
            ["報告", "", "架空の報告", "了承", "", "", ""],
        ])
        votes, counts, warnings = votes_xlsx.read_votes(path, self.members, "見本 花子")
        self.assertEqual(len(votes), 3)
        self.assertEqual(votes[0]["title"], "議案第1号　架空条例")
        self.assertEqual(votes[0]["marks"]["見本 花子"], "議長")
        self.assertEqual(votes[1]["marks"]["見本 太郎"], "×")
        self.assertEqual(counts, [{"kind": "議案", "count": 1},
                                  {"kind": "発議案", "count": 1},
                                  {"kind": "報告", "count": 1}])
        joined = "\n".join(warnings)
        self.assertIn("名簿に無い議員", joined)
        self.assertIn("名簿にある議員の列", joined)
        self.assertIn("○・●・欠席・議長 以外", joined)
        self.assertIn("件名が空", joined)
        self.assertIn("全員の印が空", joined)

    def test_old_excel_reason_and_import_keeps_source(self):
        old = self.root / "古い賛否.xls"
        old.write_bytes(b"unchanged")
        with self.assertRaisesRegex(ValueError, "名前を付けて保存"):
            votes_xlsx.read_votes(old, self.members, "見本 花子")
        issue_folder = self.root / "第999号"
        work = edition.Edition.create(issue_folder, layout.Issue(999, 4))
        work.save_settings(self.members, "見本 花子")
        path = votes_xlsx.make_template(self.root / "入力.xlsx", self.members, "見本 花子")
        add_rows(path, [["議案", "議案第1号", "架空条例", "原案可決", "○", "", "●"]])
        before = path.read_bytes()
        data = items.default_data(work.issue)
        _votes, _counts, _warnings, copied = work.import_votes(path, data)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(copied.is_file())
        saved = json.loads((issue_folder / "項目.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["votes_import"]["source_name"], path.name)
        self.assertEqual(saved["votes_import"]["copy_name"], copied.name)
        self.assertEqual(saved["shingi"]["counts"], [{"kind": "議案", "count": 1}])


if __name__ == "__main__":
    unittest.main()
