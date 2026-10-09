"""次ページ送りと部品前の空き行のテスト。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chat  # noqa: E402
import compose  # noqa: E402
import docx_out  # noqa: E402
import edition  # noqa: E402
import ingest  # noqa: E402
import layout  # noqa: E402
from grid import Geometry  # noqa: E402


def page_text(result) -> str:
    return "".join("".join(item.lines) for item in result.page.items
                   if isinstance(item, docx_out.TextBox))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        issue = layout.Issue(999, 7, "令和8年7月31日", questioners=1,
                             committee_pages=0, feature_pages=2)
        self.work = edition.Edition.create(self.root / "第999号", issue)
        self.gyosei = [p["no"] for p in self.work.pages
                       if p["section"] == layout.GYOSEI]

    def tearDown(self):
        self.temp.cleanup()

    def _source(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_overflow_continues_before_next_source_without_loss_or_duplication(self):
        long_text = "架空本文" * 500
        next_title = "架空の次ページ見出し"
        next_text = "次ページ固有の架空記事"
        self.work.assign(self.gyosei[0], self._source("架空の行政報告1.txt", long_text))
        self.work.assign(self.gyosei[1], self._source(
            "架空の行政報告2.txt", f"【大見出し】{next_title}\n{next_text}"))
        before = self.work.compose(self.gyosei[0])
        self.assertGreater(before.overflow_lines, 0)

        self.work.set_flow_to_next(self.gyosei[0], True)
        first = self.work.compose(self.gyosei[0])
        second = self.work.compose(self.gyosei[1])
        self.assertEqual(page_text(first) + page_text(second),
                         "　" + long_text + next_title + "　" + next_text)
        self.assertTrue(page_text(second).startswith(first.overflow_parts[0].text))
        self.assertEqual(self.work.pages[self.gyosei[0] - 1]["state"], "できた")
        self.assertFalse(any(f"{self.gyosei[0]}ページ" in message and "あふれ" in message
                             for message in self.work.check()))

    def test_flow_restrictions_undo_and_reopen(self):
        cover = next(p["no"] for p in self.work.pages if p["section"] == layout.COVER)
        ippan = next(p["no"] for p in self.work.pages if p["section"] == layout.IPPAN)
        for page_no in (cover, ippan):
            with self.subTest(page_no=page_no):
                with self.assertRaises(ValueError):
                    self.work.set_flow_to_next(page_no, True)

        self.work.set_flow_to_next(self.gyosei[0], True)
        self.assertTrue(self.work.pages[self.gyosei[0] - 1]["flow_to_next"])
        self.assertTrue(self.work.undo())
        self.assertFalse(self.work.pages[self.gyosei[0] - 1]["flow_to_next"])
        self.assertTrue(self.work.redo())
        reopened = edition.Edition.open(self.work.folder)
        self.assertTrue(reopened.pages[self.gyosei[0] - 1]["flow_to_next"])
        allowed, reason = reopened.can_flow_to_next(self.gyosei[1])
        self.assertFalse(allowed)
        self.assertIn("同じ区分", reason)

    def test_flow_can_chain_across_three_pages(self):
        issue = layout.Issue(998, 7, questioners=0, committee_pages=3,
                             feature_pages=2)
        work = edition.Edition.create(self.root / "第998号", issue)
        pages = [p["no"] for p in work.pages if p["section"] == layout.IINKAI]
        text = "連" * 4000
        work.assign(pages[0], self._source("架空の委員会報告.txt", text))
        work.set_flow_to_next(pages[0], True)
        work.set_flow_to_next(pages[1], True)
        results = [work.compose(page_no) for page_no in pages]
        self.assertEqual("".join(page_text(result) for result in results), "　" + text)
        self.assertEqual(results[-1].overflow_lines, 0)
        self.assertTrue(all(work.pages[page_no - 1]["state"] == "できた"
                            for page_no in pages))

    def test_chat_flow_and_stop_phrases(self):
        start = chat.interpret("次のページへ送る", self.work, self.gyosei[0], None)
        self.assertTrue(start.understood, start.reason)
        self.assertEqual(start.operations[0].kind, "flow")
        chat.execute(start, self.work)
        stop = chat.interpret("送るのをやめる", self.work, self.gyosei[0], None)
        self.assertTrue(stop.understood, stop.reason)
        chat.execute(stop, self.work)
        self.assertFalse(self.work.pages[self.gyosei[0] - 1]["flow_to_next"])


class SpacingTest(unittest.TestCase):
    def test_space_moves_following_part_and_changes_overflow(self):
        geometry = Geometry()
        parts = [ingest.Part("本文", "架" * (geometry.chars_per_line * 149 - 1)),
                 ingest.Part("本文", "空")]
        normal = compose.compose_page(layout.GYOSEI, parts, {}, geometry)
        spaced = compose.compose_page(
            layout.GYOSEI, parts, {}, geometry, {1: {"space_before": 1}})
        normal_second = next(p.rect for p in normal.placements if p.index == 1)
        spaced_second = next((p.rect for p in spaced.placements if p.index == 1), None)
        self.assertIsNotNone(normal_second)
        self.assertIsNone(spaced_second)
        self.assertEqual(spaced.overflow_lines, normal.overflow_lines + 1)
        self.assertEqual(spaced.overflow_parts[-1].text, "空")

    def test_spacing_never_below_zero_and_persists_with_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            issue = layout.Issue(999, 7, questioners=0, committee_pages=0,
                                 feature_pages=2)
            work = edition.Edition.create(root / "第999号", issue)
            page_no = next(p["no"] for p in work.pages
                           if p["section"] == layout.GYOSEI)
            source = root / "架空記事.txt"
            source.write_text("架空の本文です。", encoding="utf-8")
            work.assign(page_no, source)

            self.assertEqual(work.change_space_before(page_no, 0, -1), 0)
            before = work.history_index
            self.assertEqual(work.change_space_before(page_no, 0, 1), 1)
            self.assertEqual(work.history_index, before + 1)
            saved = json.loads((work.folder / "紙面.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["pages"][page_no - 1]["overrides"]["0"]["space_before"], 1)
            self.assertTrue(work.undo())
            self.assertEqual(work._overrides(work.pages[page_no - 1]).get(0, {}).get(
                "space_before", 0), 0)
            self.assertTrue(work.redo())
            reopened = edition.Edition.open(work.folder)
            self.assertEqual(reopened._overrides(reopened.pages[page_no - 1])[0][
                "space_before"], 1)

    def test_chat_spacing_phrases(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            work = edition.Edition.create(
                root / "第999号", layout.Issue(999, 7, questioners=0,
                                                committee_pages=0, feature_pages=2))
            page_no = next(p["no"] for p in work.pages
                           if p["section"] == layout.GYOSEI)
            source = root / "架空記事.txt"
            source.write_text("架空の本文です。", encoding="utf-8")
            work.assign(page_no, source)
            for phrase in ("1番の前を1行あける", "1番の前を詰める"):
                result = chat.interpret(phrase, work, page_no, None)
                self.assertTrue(result.understood, result.reason)
                self.assertEqual(result.operations[0].kind, "space")
                chat.execute(result, work)


if __name__ == "__main__":
    unittest.main()
