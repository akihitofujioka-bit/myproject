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


class ChairColumnTest(unittest.TestCase):
    def test_chair_not_in_roster_is_added(self):
        from settings import Settings
        s = Settings(["見本 太郎", "見本 花子"], "見本　次郎")
        self.assertEqual(s.vote_members, ["見本 太郎", "見本 花子", "見本　次郎"])
        self.assertEqual(Settings(["見本 太郎", "見本 次郎"], "見本　次郎").vote_members,
                         ["見本 太郎", "見本 次郎"])

    def test_header_named_gichou_or_with_words(self):
        wanted = {votes_xlsx._plain(n): n for n in ["見本 太郎", "見本 次郎"]}
        self.assertEqual(votes_xlsx._member_for("議長", wanted, "見本 次郎"), "見本 次郎")
        self.assertEqual(votes_xlsx._member_for("議長見本次郎", wanted, "見本 次郎"), "見本 次郎")
        self.assertEqual(votes_xlsx._member_for("見本太郎議員", wanted, ""), "見本 太郎")
        self.assertIsNone(votes_xlsx._member_for("備考", wanted, ""))

    def test_old_sheet_with_chair_outside_roster(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _old_style_xlsx(Path(folder) / "議案と賛否_架空.xlsx")
            from settings import Settings
            s = Settings(["見本 太郎", "見本 花子"], "見本 次郎")
            votes, _counts, warnings = votes_xlsx.read_votes(path, s.vote_members, s.chair)
        self.assertEqual(votes[0]["marks"]["見本 次郎"], "議長")
        self.assertFalse(any("名簿" in w for w in warnings), warnings)


def _two_row_header_xlsx(path, subject_label="議案・発議案名"):
    """見出しが 2 段の架空のエクセル: 上の段に区分・件名・議決結果、下の段に議員名。"""
    import zipfile as z
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    def c(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
    rows = (f'<row r="1">{c("A1", "第３回定例会議案・発議案と賛否")}</row>'
            f'<row r="2">{c("A2", "区分")}{c("B2", subject_label)}{c("C2", "議員名")}{c("F2", "議決結果")}</row>'
            f'<row r="3">{c("C3", "見本太郎")}{c("D3", "見本花子")}{c("E3", "議長")}</row>'
            f'<row r="4">{c("A4", "議案")}{c("B4", "議案第１号　架空の条例")}{c("C4", "〇")}{c("D4", "○")}{c("F4", "原案可決")}</row>'
            f'<row r="5">{c("B5", "議案第２号　架空の予算")}{c("C5", "●")}{c("D5", "○")}{c("F5", "可決")}</row>')
    with z.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        package.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        package.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        package.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{rows}</sheetData></worksheet>')
    return path


class TwoRowHeaderTest(unittest.TestCase):
    def read(self, label):
        with tempfile.TemporaryDirectory() as folder:
            path = _two_row_header_xlsx(Path(folder) / "賛否_架空.xlsx", label)
            return votes_xlsx.read_votes(path, ["見本 太郎", "見本 花子", "見本 次郎"], "見本 次郎")

    def test_two_row_header_is_read(self):
        votes, counts, warnings = self.read("議案・発議案名")
        self.assertEqual([v["title"] for v in votes], ["議案第１号　架空の条例", "議案第２号　架空の予算"])
        self.assertEqual(votes[1]["kind"], "議案")                      # 区分の結合セルを引き継ぐ
        self.assertEqual(votes[0]["marks"], {"見本 太郎": "○", "見本 花子": "○", "見本 次郎": "議長"})
        self.assertEqual(counts, [{"kind": "議案", "count": 2}])
        self.assertFalse(any("名簿" in w or "件名" in w for w in warnings), warnings)

    def test_unknown_subject_label_is_guessed_and_told(self):
        votes, _counts, warnings = self.read("内容")
        self.assertEqual(len(votes), 2)
        self.assertTrue(any("B列を件名として読みました" in w for w in warnings), warnings)

    def test_nothing_read_is_explained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _two_row_header_xlsx(Path(folder) / "賛否_架空.xlsx")
            votes, _counts, warnings = votes_xlsx.read_votes(path, ["別人 一郎"], "")
        self.assertTrue(warnings and warnings[0].startswith("議案を1件も読めませんでした") or votes)


def _tall_header_xlsx(path):
    """第204号と同じ形の架空のエクセル: 見出しが 3〜7 行目、件名の見出しは B 列で文字は D 列、区分は見出しなしの A 列。"""
    import zipfile as z
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    def c(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
    rows = (f'<row r="1">{c("A1", "第３回定例会議案・発議案と賛否")}</row>'
            f'<row r="3">{c("O3", "見本太郎")}{c("P3", "見本花子")}{c("Q3", "見本次郎")}{c("R3", "議決結果")}</row>'
            f'<row r="4">{c("J4", "議員名")}</row>'
            f'<row r="6">{c("B6", "議案・発議案")}</row>'
            f'<row r="8">{c("A8", "議案")}{c("D8", "議案第１号&#10;架空の条例")}{c("O8", "〇")}{c("P8", "●")}{c("Q8", "議長")}{c("R8", "可決")}</row>'
            f'<row r="9">{c("A9", "発議案")}{c("D9", "発議第１号　架空の意見書")}{c("O9", "〇")}{c("P9", "〇")}{c("Q9", "議長")}{c("R9", "可決")}</row>')
    with z.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        package.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        package.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        package.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{rows}</sheetData></worksheet>')
    return path


class TallHeaderTest(unittest.TestCase):
    def test_reference_shape_is_read_without_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _tall_header_xlsx(Path(folder) / "賛否_架空.xlsx")
            votes, counts, warnings = votes_xlsx.read_votes(
                path, ["見本 太郎", "見本 花子", "見本 次郎"], "見本 次郎")
        self.assertEqual(warnings, [])
        self.assertEqual([v["kind"] for v in votes], ["議案", "発議案"])
        self.assertEqual(votes[0]["title"], "議案第１号\n架空の条例")
        self.assertEqual(votes[0]["marks"], {"見本 太郎": "○", "見本 花子": "●", "見本 次郎": "議長"})
        self.assertEqual(counts, [{"kind": "議案", "count": 1}, {"kind": "発議案", "count": 1}])


class VoteEditTest(unittest.TestCase):
    def test_edit_survives_reimport_and_marks_stay(self):
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "第999号", layout.Issue(999, 10, "令和8年10月31日"))
            work.save_settings(["見本 太郎", "見本 花子"], "見本 次郎")
            path = _tall_header_xlsx(Path(folder) / "賛否_架空.xlsx")
            data = work.item_data()
            work.import_votes(path, data)
            work.edit_vote(data, 1, "意見書", "発議第１号\n架空の意見書", "可決")
            self.assertEqual(data["votes"][1]["title"], "発議第１号\n架空の意見書")
            self.assertEqual(data["shingi"]["counts"], [{"kind": "議案", "count": 1}, {"kind": "意見書", "count": 1}])
            again = work.item_data()
            work.import_votes(path, again)          # 同じエクセルを取り込み直す
            self.assertEqual(again["votes"][1]["kind"], "意見書")
            self.assertEqual(again["votes"][1]["title"], "発議第１号\n架空の意見書")
            self.assertEqual(again["votes"][1]["marks"]["見本 太郎"], "○")   # ○・● はエクセルのまま
            # 種類と件数を手で直したら、議案の手直しや取り込み直しでも変わらない
            again["shingi"]["counts"] = [{"kind": "条例", "count": 3}]
            again["shingi"]["counts_manual"] = True
            work.edit_vote(again, 0, "議案", "議案第１号　架空", "可決")
            work.import_votes(path, again)
            self.assertEqual(again["shingi"]["counts"], [{"kind": "条例", "count": 3}])
