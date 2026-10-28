import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import docx_out as dx  # noqa: E402
import edition  # noqa: E402
import items  # noqa: E402
import layout  # noqa: E402
import templates  # noqa: E402
from grid import Geometry  # noqa: E402

ISSUE = layout.Issue(996, 5, "令和8年5月31日")


def sample():
    data = items.default_data(ISSUE)
    value = data["yosan"]
    value.update({"general_total": "５４億１，１３９万円", "headline": "見本村７２億円でスタート",
                  "previous_title": "令和７年度補正予算"})
    value["chart_items"] = [{"item": "総務費", "name": "見本納税関連事業", "text": "架空の説明です。"}]
    for account, amount in zip(value["accounts"], ("２億６，６６０万円", "６億９，７８３万円",
                                                   "７億　５１５万円", "１億１，８４５万円")):
        account["amount"] = amount
    value["focus"] = [{"name": "見本耐震対策事業", "amount": "７，２１７万円", "text": "架空の補助です。"}
                      for _ in range(5)]
    value["previous"] = [{"name": "見本小学校の改修", "amount": "１億２，２９７万円", "text": "架空です。"}]
    return data


class YosanTest(unittest.TestCase):
    def test_title_is_same_fiscal_year(self):
        self.assertEqual(templates.yosan_title(ISSUE), "令和８年度当初予算")

    def test_spring_issue_has_two_yosan_pages(self):
        plan = layout.make_plan(ISSUE)
        self.assertEqual([p.index for p in plan.pages if p.section == layout.YOSAN], [1, 2])
        self.assertEqual(plan.errors, [])
        self.assertNotIn(layout.YOSAN, [p.section for p in layout.make_plan(
            layout.Issue(996, 7, "令和8年7月31日")).pages])

    def test_two_pages_have_reference_shape_and_fit(self):
        form = items.yosan_form(sample(), ISSUE)
        g = Geometry()
        first = templates.build(layout.YOSAN, dict(form, page_index=1), ISSUE, None, None, g)
        second = templates.build(layout.YOSAN, dict(form, page_index=2), ISSUE, None, None, g)
        names1 = {getattr(i, "name", "") for i in first.page.items}
        names2 = {getattr(i, "name", "") for i in second.page.items}
        for name in ("当初予算の囲み", "当初予算の題", "円グラフの題", "円グラフの指示", "主な事業",
                     "各会計予算の見出し", "会計の金額"):
            self.assertIn(name, names1)
        for name in ("当初予算の大見出し", "注目する事業の見出し", "注目する事業", "前の年度の見出し"):
            self.assertIn(name, names2)
        self.assertEqual((first.overflow_lines, second.overflow_lines), (0, 0), first.warnings + second.warnings)
        self.assertEqual(dx.page_textbox_warnings(first.page) + dx.page_textbox_warnings(second.page), [])

    def test_edition_builds_both_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "第996号", ISSUE)
            work.save_items(sample())
            pages = [p for p in work.pages if p["section"] == layout.YOSAN]
            self.assertEqual(len(pages), 2)
            texts = [" ".join(line for item in work.compose(p["no"]).page.items
                              for line in getattr(item, "lines", []) or []) for p in pages]
            self.assertIn("令和８年度一般会計予算", texts[0])
            self.assertIn("令和８年度　注目する事業", texts[1])


if __name__ == "__main__":
    unittest.main()
