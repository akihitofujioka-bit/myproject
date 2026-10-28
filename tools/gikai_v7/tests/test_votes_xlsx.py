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


def _old_style_xlsx(path):
    """前から使っている形の架空のエクセル: 1 行目に題とふりがな、見出しは 3 行目、印は〇。"""
    import zipfile as z
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    shared = ["第３回定例会議案・発議案と賛否", "区分", "議案・発議案", "見本　太郎", "見本\n花子",
              "見本 次郎", "議決結果", "議案", "架空の条例", "〇", "●", "原案可決", "※注記"]
    si = []
    for index, text in enumerate(shared):
        if index == 0:   # ふりがな付き
            si.append(f'<si><t>{text}</t><rPh sb="0" eb="1"><t>ダイサンカイテイレイカイ</t></rPh></si>')
        else:
            si.append(f'<si><t xml:space="preserve">{text}</t></si>')
    def c(ref, index):
        return f'<c r="{ref}" t="s"><v>{index}</v></c>'
    rows = (f'<row r="1">{c("A1", 0)}</row>'
            f'<row r="3">{c("A3", 1)}{c("B3", 2)}{c("C3", 3)}{c("D3", 4)}{c("E3", 5)}{c("F3", 6)}</row>'
            f'<row r="4">{c("A4", 7)}{c("B4", 8)}{c("C4", 9)}{c("D4", 10)}{c("F4", 11)}</row>'
            f'<row r="6">{c("A6", 12)}</row>')
    with z.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        package.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        package.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        package.writestr("xl/sharedStrings.xml", f'<sst {ns}>{"".join(si)}</sst>')
        package.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{rows}</sheetData></worksheet>')
    return path


class OldStyleExcelTest(unittest.TestCase):
    def test_old_style_sheet_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _old_style_xlsx(Path(folder) / "議案と賛否_架空.xlsx")
            members = ["見本 太郎", "見本 花子", "見本 次郎"]
            votes, counts, warnings = votes_xlsx.read_votes(path, members, "見本 次郎")
        self.assertEqual(len(votes), 1)
        self.assertEqual(votes[0]["title"], "架空の条例")
        self.assertEqual(votes[0]["marks"], {"見本 太郎": "○", "見本 花子": "●", "見本 次郎": "議長"})
        self.assertEqual(counts, [{"kind": "議案", "count": 1}])
        self.assertFalse(any("名簿" in w for w in warnings), warnings)       # 列は全部見つかる
        self.assertFalse(any("ダイサン" in w for w in warnings), warnings)   # ふりがなは読まない
        self.assertTrue(any(w.startswith("6行目") for w in warnings), warnings)  # 行番号はエクセルどおり
