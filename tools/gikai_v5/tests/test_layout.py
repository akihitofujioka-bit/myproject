"""号の構成とページ割り（layout.py）のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import layout as L  # noqa: E402
from grid import Geometry  # noqa: E402


def plan(month, q, **kw):
    return L.make_plan(L.Issue(200, month, questioners=q, **kw))


class OrderTest(unittest.TestCase):
    def test_october_order(self):
        p = plan(10, 5)
        names = [s.name for s in p.sections]
        self.assertEqual(names, [L.COVER, L.GYOSEI, L.KESSAN, L.SHINGI, L.IINKAI,
                                 L.IPPAN, L.TOKUSHU, L.LAST])

    def test_april_has_budget_july_has_neither(self):
        self.assertIn(L.YOSAN, [s.name for s in plan(4, 5).sections])
        names = [s.name for s in plan(7, 5).sections]
        self.assertNotIn(L.YOSAN, names)
        self.assertNotIn(L.KESSAN, names)

    def test_page_numbers_are_continuous(self):
        p = plan(1, 7)
        self.assertEqual([x.no for x in p.pages], list(range(1, p.total + 1)))
        self.assertEqual(p.pages[0].section, L.COVER)
        self.assertEqual(p.pages[-1].section, L.LAST)


class CountTest(unittest.TestCase):
    def test_always_even_when_auto(self):
        for m in L.MONTHS:
            for q in range(0, L.MAX_QUESTIONERS + 1):
                p = plan(m, q)
                if p.total <= L.MAX_PAGES:
                    self.assertEqual(p.total % 2, 0, (m, q))
                    self.assertEqual(p.errors, [], (m, q))

    def test_feature_chosen_for_even(self):
        # 7 月号・5 人: 特集以外で 1+2+1+2+5+1 = 12 → 特集は 2 で合計 14
        p = plan(7, 5)
        fixed = 1 + 2 + 1 + 2 + 5 + 1
        feature = p.page_range(L.TOKUSHU)
        self.assertEqual(p.total, fixed + feature[1] - feature[0] + 1)
        self.assertEqual(p.total, 14)

    def test_questioner_limit_is_10(self):
        for m in L.MONTHS:
            self.assertEqual(L.max_questioners(m), 10)
            self.assertEqual(plan(m, 10).errors, [])
            self.assertTrue(any("10 人まで" in e for e in plan(m, 11).errors))
        self.assertLessEqual(plan(10, 10).total, 22)

    def test_manual_feature_odd_is_error(self):
        p = plan(10, 5, feature_pages=3)        # 1+2+1+1+2+5+3+1 = 16 → 偶数
        self.assertEqual(p.errors, [])
        p = plan(10, 5, feature_pages=2)        # 15 → 奇数
        self.assertTrue(any("奇数" in e for e in p.errors))

    def test_committee_pages_change(self):
        a, b = plan(1, 5), plan(1, 5, committee_pages=3)
        self.assertEqual(b.page_range(L.IINKAI)[1] - b.page_range(L.IINKAI)[0], 2)
        self.assertEqual(a.total % 2, 0)
        self.assertEqual(b.total % 2, 0)

    def test_bad_month(self):
        self.assertTrue(plan(5, 3).errors)


class TocTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(L.page_label(14, 14), "１４Ｐ")
        self.assertEqual(L.page_label(16, 17), "１６～１７Ｐ")
        self.assertEqual(L.toc_line("新年の抱負", 14, 15), "特集　新年の抱負……１４～１５Ｐ")


class IssueFileTest(unittest.TestCase):
    def test_roundtrip(self):
        issue = L.Issue(205, 4, "令和８年４月３０日", questioners=6, feature_title="入学おめでとう")
        with tempfile.TemporaryDirectory() as d:
            issue.save(Path(d))
            self.assertEqual(L.Issue.load(Path(d)), issue)


class FixedAreaTest(unittest.TestCase):
    def test_last_page_rows(self):
        g = Geometry()
        a = L.fixed_areas(L.LAST, g)
        self.assertEqual(a["編集後記"].dan, 0)
        self.assertEqual(a["傍聴の案内・署名"].dan, 4)
        self.assertEqual((a["自由"].dan, a["自由"].dan_span), (1, 3))


if __name__ == "__main__":
    unittest.main()
