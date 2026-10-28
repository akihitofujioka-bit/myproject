"""V7 の項目テンプレート変換と Edition 連携のテスト。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import edition  # noqa: E402
import items  # noqa: E402
import layout  # noqa: E402


class ConversionTest(unittest.TestCase):
    def test_each_section_becomes_marked_text(self):
        issue = layout.Issue(999, 4, questioners=1, committee_pages=1)
        data = items.default_data(issue)
        data["gyosei"] = {"title": "架空の行政報告", "reports": [
            {"heading": "見本事業", "body": "架空の報告本文です。"}]}
        data["budget"] = {"title": "架空の当初予算", "summary": "架空の概要。", "questions": [
            {"heading": "見本費", "question": "内容は。", "answer": "架空の内容です。"}]}
        data["committees"] = [{"committee": "見本委員会", "heading": "調査",
                                "body": "架空の調査です。"}]
        data["questions"] = [{"member": "見本 太郎", "title": "架空の防災", "questions": [
            {"heading": "備え", "question": "備えは。", "answer": "進めます。",
             "answerer": "見本課長"}]}]
        data["feature"] = {"title": "架空の特集", "body": "架空の特集本文。"}
        pages = items.marked_pages(data, issue)
        self.assertIn("【大見出し】架空の行政報告", pages[layout.GYOSEI][0])
        self.assertIn("問　内容は。", pages[layout.YOSAN][0])
        self.assertIn("【大見出し】見本委員会", pages[layout.IINKAI][0])
        self.assertIn("【大見出し】架空の防災", pages[layout.IPPAN][0])
        self.assertIn("【顔写真枠】", pages[layout.IPPAN][0])
        self.assertIn("答　見本課長　進めます。", pages[layout.IPPAN][0])
        self.assertIn("【大見出し】架空の特集", pages[layout.TOKUSHU][0])

    def test_shingi_form_contains_bills_and_questions(self):
        issue = layout.Issue(999, 4, "令和8年4月30日")
        data = items.default_data(issue)
        data["shingi"]["bills"] = [{"kind": "条例", "title": "架空条例",
                                      "description": "架空の説明。", "questions": [
                                          {"question": "理由は。", "answer": "見本の理由です。"}]}]
        form = items.shingi_form(data, issue)
        self.assertIn("【区分】条例", form["body"])
        self.assertIn("◎架空条例", form["body"])
        self.assertIn("問　理由は。", form["body"])

    def test_bulk_keeps_unclassified_text_and_splits_qa(self):
        source = ("概要として残す長い架空の文章です。\n防災の備え\n問　備蓄はありますか。\n"
                  "答弁者　見本課長\n答　見本倉庫にあります。")
        parsed = items.parse_bulk(source)
        joined = parsed["body"] + json.dumps(parsed["questions"], ensure_ascii=False)
        for word in ("概要として残す", "防災の備え", "備蓄はありますか", "見本倉庫"):
            self.assertIn(word, joined)
        self.assertEqual(parsed["questions"][0]["answerer"], "見本課長")

    def test_more_than_four_questions_are_kept_in_fourth(self):
        values = [{"heading": f"見出し{n}", "question": f"質問{n}", "answer": f"答え{n}"}
                  for n in range(1, 6)]
        limited = items.limit_questions(values)
        self.assertEqual(len(limited), 4)
        self.assertIn("質問5", limited[-1]["answer"])
        self.assertIn("答え5", limited[-1]["answer"])


class VoteAndEditionTest(unittest.TestCase):
    def test_votes_follow_roster_and_default_marks(self):
        rows = [{"kind": "議案", "title": "架空議案"}]
        votes = items.build_votes(rows, ["見本 太郎", "見本 花子"], "見本 花子")
        self.assertEqual(votes[0]["marks"], {"見本 太郎": "○", "見本 花子": "議長"})

    def test_people_and_committee_count_rebuild_plan_and_enable_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "第999号", layout.Issue(999, 4))
            data = items.default_data(work.issue)
            data["questions"] = [
                {"member": "見本 太郎", "title": "見本1", "questions": []},
                {"member": "見本 花子", "title": "見本2", "questions": []}]
            data["committees"] = [
                {"committee": "見本委員会一", "heading": "", "body": "架空本文"},
                {"committee": "見本委員会二", "heading": "", "body": "架空本文"}]
            work.save_items(data)
            self.assertEqual(work.issue.questioners, 2)
            self.assertEqual(work.issue.committee_pages, 2)
            self.assertEqual(len([p for p in work.pages if p["section"] == layout.IPPAN]), 2)
            committee = [p for p in work.pages if p["section"] == layout.IINKAI]
            self.assertTrue(committee[0]["flow_to_next"])
            self.assertFalse(committee[-1]["flow_to_next"])

    def test_previous_items_file_is_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            first = {"version": 1, "feature": {"title": "前の架空題"}}
            second = {"version": 1, "feature": {"title": "新しい架空題"}}
            items.save(target, first)
            items.save(target, second)
            previous = json.loads((target / items.PREVIOUS_FILE).read_text(encoding="utf-8"))
            current = json.loads((target / items.ITEMS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(previous["feature"]["title"], "前の架空題")
            self.assertEqual(current["feature"]["title"], "新しい架空題")


if __name__ == "__main__":
    unittest.main()
