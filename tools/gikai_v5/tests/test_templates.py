"""書き込み式ページと横書き Word 部品のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import docx_out as dx  # noqa: E402
import edition  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
import templates  # noqa: E402
from grid import Box, Geometry, text_width  # noqa: E402
from settings import Settings  # noqa: E402


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.issue = layout.Issue(204, 10, "令和８年１０月３１日", feature_pages=2)
        self.plan = layout.make_plan(self.issue)
        self.settings = Settings(samples.SAMPLE_MEMBERS, samples.SAMPLE_MEMBERS[0], "見本委員会")
        self.g = Geometry()

    def test_meeting_name_for_each_issue_month(self):
        expected = {4: ("令和８年", "第１回"), 7: ("令和８年", "第２回"),
                    10: ("令和８年", "第３回"), 1: ("令和７年", "第４回")}
        for month, pieces in expected.items():
            issue = layout.Issue(1, month, "令和８年１月３１日")
            name = templates.meeting_name(issue)
            self.assertIn(pieces[0], name)
            self.assertIn(pieces[1], name)

    def test_summary_normalizes_counts_and_total(self):
        counts = [{"kind": "報告", "count": 3}, {"kind": "条例関係", "count": 12}]
        self.assertEqual(templates.summary_text(counts, 9),
                         "９月議会では、報告３件、条例関係12件の計15件の議案等が決まった。")

    def test_cover_toc_uses_feature_page_labels(self):
        result = templates.build(layout.COVER,
                                 {"feature_titles": "第一特集\n第二特集"},
                                 self.issue, self.plan, self.settings, self.g)
        toc = next(item for item in result.page.items
                   if isinstance(item, dx.TextBox) and item.name == "特集目次")
        feature = self.plan.page_range(layout.TOKUSHU)
        self.assertEqual(toc.lines[0], f"特集　第一特集……{layout.page_label(feature[0], feature[0])}")
        self.assertEqual(toc.lines[1], f"　　　第二特集……{layout.page_label(feature[1], feature[1])}")

    def test_cover_uses_fullwidth_digits_and_calculated_one_line_boxes(self):
        issue = layout.Issue(999, 4, "令和8年4月30日")
        result = templates.build(layout.COVER, {}, issue, layout.make_plan(issue),
                                 self.settings, self.g)
        by_name = {item.name: item for item in result.page.items if isinstance(item, dx.TextBox)}
        self.assertEqual(by_name["号数"].lines, ["第９９９号"])
        self.assertEqual(by_name["発行日"].lines, ["令和８年４月３０日"])
        for name in ("号数", "発行日", "題字（ひだか）", "題字（議会だより）"):
            item = by_name[name]
            self.assertGreaterEqual(item.box.w, text_width(item.lines[0]) * item.pt)

    def test_shingi_heading_placements_do_not_overlap(self):
        body = "【区分】予　算\n◎議案\n質疑\n問　見本の質問です。\n答　見本の答弁です。"
        result = templates.build(layout.SHINGI, {"body": body}, self.issue,
                                 self.plan, self.settings, self.g)
        rects = [placement.rect for placement in result.placements]
        for index, rect in enumerate(rects):
            self.assertFalse(any(rect.overlaps(other) for other in rects[index + 1:]))
        headings = [placement for placement in result.placements
                    if placement.part.kind in ("中見出し", "議案")]
        self.assertTrue(headings)
        self.assertTrue(all(placement.rect.line_span >= 2 for placement in headings))
        boxes = [item for item in result.page.items if isinstance(item, dx.TextBox)
                 and item.name in ("中見出し", "議案")]
        self.assertEqual([item.border for item in boxes], [True, False, False])

    def test_shingi_answer_and_last_page_body_are_gothic(self):
        shingi = templates.build(
            layout.SHINGI, {"body": "問　架空の質問です。\n答　架空の答弁です。"},
            self.issue, self.plan, self.settings, self.g)
        answer = next(item for item in shingi.page.items
                      if isinstance(item, dx.TextBox) and item.name == "答弁")
        self.assertEqual((answer.font, answer.pt), (dx.GOTHIC, 11.0))

        last = templates.build(layout.LAST,
                               {"editorial": "架空の編集後記です。",
                                "free": "架空のお知らせです。"},
                               self.issue, self.plan, self.settings, self.g)
        bodies = [item for item in last.page.items
                  if isinstance(item, dx.TextBox)
                  and item.name in ("編集後記本文", "自由欄")]
        self.assertTrue(bodies)
        self.assertTrue(all(item.font == dx.GOTHIC and item.pt == 11 for item in bodies))

    def test_last_page_hearing_notice_is_horizontal(self):
        result = templates.build(layout.LAST, samples.sample_forms()[layout.LAST], self.issue,
                                 self.plan, self.settings, self.g)
        hearing = [item for item in result.page.items if isinstance(item, dx.TextBox)
                   and item.name.startswith("傍聴")]
        self.assertTrue(hearing)
        self.assertTrue(all(not item.vertical for item in hearing))
        self.assertTrue(next(item for item in hearing if item.name == "傍聴案内見出し").bold)

    def test_overlong_horizontal_and_vertical_text_add_warnings(self):
        result = templates.build(layout.LAST,
                                 {"hearing_title": "見出し" * 30,
                                  "opinion": "ご意見をお寄せください。" * 30},
                                 self.issue, self.plan, self.settings, self.g)
        self.assertTrue(any("傍聴案内見出し" in warning for warning in result.warnings))
        self.assertTrue(any("意見・提言" in warning for warning in result.warnings))

    def test_all_template_text_fits_its_frame(self):
        forms = samples.sample_forms()
        for section in templates.FORM_SECTIONS:
            result = templates.build(section, forms.get(section, {}), self.issue,
                                     self.plan, self.settings, self.g)
            for item in result.page.items:
                if not isinstance(item, dx.TextBox):
                    continue
                if item.vertical:
                    self.assertLessEqual(len(item.lines) * max(item.pitch_pt, item.pt),
                                         item.box.w + 1e-6, item.name)
                    for line in item.lines:
                        self.assertLessEqual(text_width(line) * item.pt,
                                             item.box.h + 1e-6, item.name)
                else:
                    self.assertLessEqual(len(item.lines) * item.pitch_pt,
                                         item.box.h + 1e-6, item.name)
                    for line in item.lines:
                        self.assertLessEqual(text_width(line) * item.pt,
                                             item.box.w + 1e-6, item.name)

    def test_vote_table_has_member_columns_and_rows(self):
        votes = [{"kind": "条例", "title": "見本条例", "result": "可決",
                  "marks": {name: "○" for name in self.settings.members}}]
        result = templates.build(layout.SHINGI, {"votes": votes}, self.issue,
                                 self.plan, self.settings, self.g)
        table = next(item for item in result.page.items if isinstance(item, dx.Table))
        self.assertEqual(len(table.column_widths), len(self.settings.members) + 3)
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[0][2:-1], self.settings.members)

    def test_empty_members_shows_instruction(self):
        result = templates.build(layout.SHINGI, {}, self.issue, self.plan,
                                 Settings(), self.g)
        labels = [line for item in result.page.items if isinstance(item, dx.TextBox)
                  for line in item.lines]
        self.assertIn("設定で議員名簿を入れてください", labels)


class FormEditionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.issue = layout.Issue(999, 4, "令和８年４月３０日", questioners=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_clears_issue_values_and_keeps_structure(self):
        previous = edition.Edition.create(self.root / "前号", self.issue)
        forms = samples.sample_forms()
        for page in previous.pages:
            if page["section"] in forms:
                value = dict(forms[page["section"]])
                if page["section"] == layout.COVER:
                    value["photo"] = "見本.png"
                previous.set_form(page["no"], value)
        current = edition.Edition.create(self.root / "今号", self.issue)
        current.copy_forms_from(previous.folder)
        by_section = {p["section"]: p["form"] for p in current.pages if "form" in p}
        self.assertEqual(by_section[layout.COVER]["photo"], "")
        self.assertEqual(by_section[layout.COVER]["feature_titles"], "暮らしを考える特集\n地域の取り組み")
        self.assertEqual(by_section[layout.SHINGI]["counts"], [])
        self.assertEqual(by_section[layout.SHINGI]["votes"][0]["title"], "見本条例")
        self.assertEqual(by_section[layout.SHINGI]["votes"][0]["marks"], {})
        self.assertEqual(by_section[layout.SHINGI]["body"], "")
        self.assertEqual(by_section[layout.LAST]["editorial"], "")
        self.assertIn("地域の話題", by_section[layout.LAST]["free"])
        self.assertTrue(by_section[layout.LAST]["invitation"])

    def test_set_form_can_be_undone_and_redone(self):
        work = edition.Edition.create(self.root / "号", self.issue)
        cover = next(p for p in work.pages if p["section"] == layout.COVER)
        work.set_form(cover["no"], {"feature_titles": "見本特集"})
        self.assertEqual(work.pages[cover["no"] - 1]["form"]["feature_titles"], "見本特集")
        self.assertTrue(work.undo())
        self.assertEqual(work.pages[cover["no"] - 1]["form"]["feature_titles"], "")
        self.assertTrue(work.redo())
        self.assertEqual(work.pages[cover["no"] - 1]["form"]["feature_titles"], "見本特集")

    def test_export_contains_all_three_form_pages_and_valid_xml(self):
        work = edition.Edition.create(self.root / "号", self.issue)
        work.settings = Settings(samples.SAMPLE_MEMBERS, samples.SAMPLE_MEMBERS[0], "見本委員会")
        forms = samples.sample_forms()
        for page in work.pages:
            if page["section"] in forms:
                work.set_form(page["no"], forms[page["section"]])
        docx = work.export()[0]
        with zipfile.ZipFile(docx) as package:
            data = package.read("word/document.xml")
        ET.fromstring(data)
        text = data.decode("utf-8")
        self.assertIn("議会だより", text)
        self.assertIn("議案・発議案と賛否", text)
        self.assertIn("編集後記", text)


class HorizontalXmlTest(unittest.TestCase):
    def test_horizontal_textbox_and_table_xml(self):
        page = dx.Page([
            dx.TextBox(Box(10, 10, 200, 30), ["横書き123"], vertical=False, align="中央"),
            dx.Table(Box(10, 50, 200, 80), [80, 120], [["区分", "件名"], ["条例", "見本条例"]]),
        ])
        xml = dx.document_xml(Geometry(), [page])
        ET.fromstring(xml.encode("utf-8"))
        self.assertIn('<w:jc w:val="center"/>', xml)
        self.assertIn('<w:autoSpaceDE w:val="0"/>', xml)
        self.assertIn('<w:tbl>', xml)
        self.assertIn('<w:tblLayout w:type="fixed"/>', xml)
        self.assertNotIn('vert="eaVert"', xml)
        self.assertNotIn("eastAsianLayout", xml)


if __name__ == "__main__":
    unittest.main()
