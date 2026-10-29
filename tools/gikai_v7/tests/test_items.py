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
    def test_question_headings_summary_question_and_answer(self):
        """1 番目は大見出しに「大まかな質問｜答」、2 番目からは中見出しに同じ形、そのあと詳しい問と答。"""
        text = items.question_text({"member": "見本 太郎", "title": "使わない題", "questions": [
            {"heading": "防災対策の強化を", "heading_answer": "計画的に進める",
             "question": "備えは。", "answer": "増やす。", "answerer": "見本課長"},
            {"heading": "子育て支援は", "heading_answer": "拡充する", "question": "保育料は。", "answer": "下げる。"}]})
        self.assertEqual(text.splitlines(), [
            "【大見出し】防災対策の強化を｜計画的に進める", "【顔写真枠】", "▲見本 太郎議員",
            "問　備えは。", "答　見本課長　増やす。",
            "【見出し】子育て支援は｜拡充する", "問　保育料は。", "答　下げる。"])
        # 前の版の「題」だけのデータも大見出しに出す
        self.assertIn("【大見出し】古い題", items.question_text({"title": "古い題", "questions": []}))

    def test_question_fields_round_trip_through_bulk_text(self):
        """質問ごとの欄の内容をまとめ欄の形にしても、読み直すと同じ欄に戻る。"""
        questions = [{"heading": "防災は", "heading_answer": "進める", "question": "備えは。\n二行目。",
                      "answer": "増やす。", "answerer": "見本課長"},
                     {"heading": "子育て", "heading_answer": "", "question": "保育は。", "answer": "下げる。", "answerer": ""}]
        back = items.parse_bulk(items.bulk_text(questions))["questions"]
        for before, after in zip(questions, back):
            for key in ("heading", "question", "answer", "answerer"):
                self.assertEqual(after.get(key, ""), before[key])
            self.assertEqual(after.get("heading_answer", ""), before["heading_answer"])

    def test_committee_sections_round_trip(self):
        body = "前置きの文。\n【見出し】調査日\n令和８年１月\n【見出し】所感\n架空の所感。\n二行目。"
        sections = items.split_sections(body)
        self.assertEqual(sections, [("", "前置きの文。"), ("調査日", "令和８年１月"), ("所感", "架空の所感。\n二行目。")])
        self.assertEqual(items.join_sections(sections + [("", "")]), body)

    def test_one_question_can_have_several_exchanges(self):
        """見出しのない問答は、前の質問の続きのやりとり。質問の数（4 つまで）にも数えない。"""
        pairs = [{"heading": "甲", "question": "問1", "answer": "答1"},
                 {"heading": "", "question": "再質問", "answer": "再答弁"},
                 {"heading": "乙", "question": "問2", "answer": "答2"}]
        self.assertEqual([len(g) for g in items.group_questions(pairs)], [2, 1])
        many = [{"heading": f"見出し{n}", "question": f"問{n}", "answer": f"答{n}"} for n in range(4)]
        many[1:1] = [{"heading": "", "question": "再質問", "answer": "再答弁"}] * 3
        self.assertEqual(len(items.limit_questions(many)), 7)   # 4 つの質問のまま、やりとりも残す
        back = items.parse_bulk(items.bulk_text(pairs))["questions"]
        self.assertEqual([len(g) for g in items.group_questions(back)], [2, 1])

    def test_bulk_reads_newsletter_style_labels(self):
        """紙面と同じ「質問　」「答弁　村長」や「【質問】」「Ｑ．」「答弁（教育長）」も読み、答のあとの見出しも分ける。"""
        text = ("防災対策の強化を\n質問　避難所の備えは十分か。\n答弁　村長\n　今年度中に備蓄を増やす。\n"
                "子育て支援について\n質問　保育料はどうか。\n答弁（教育長）下げる方向で検討する。\n"
                "再質問　時期は。\n再答弁　教育長\n　来年度からです。\n"
                "道路の整備\nＱ．舗装は。\nＡ．建設課長　計画的に進める。")
        found = items.parse_bulk(text)["questions"]
        self.assertEqual([(q["heading"], q["question"], q["answerer"]) for q in found], [
            ("防災対策の強化を", "避難所の備えは十分か。", "村長"),
            ("子育て支援について", "保育料はどうか。", "教育長"),
            ("", "時期は。", "教育長"),
            ("道路の整備", "舗装は。", "建設課長")])
        self.assertEqual(found[0]["answer"], "今年度中に備蓄を増やす。")
        self.assertEqual(found[1]["answer"], "下げる方向で検討する。")
        self.assertEqual(items.parse_bulk("問題は山積だ")["questions"], [])   # 「問題」は問の印にしない

    def test_bulk_reads_summary_answer(self):
        parsed = items.parse_bulk("【見出し】防災対策の強化を\n【見出しの答】計画的に進める\n"
                                  "問　備えは。\n答　増やす。\n答弁者　見本課長\n"
                                  "【子育て支援は】\n【見出しの答】拡充する\n問　保育料は。\n答　下げる。")
        self.assertEqual([(q["heading"], q.get("heading_answer"), q["question"]) for q in parsed["questions"]],
                         [("防災対策の強化を", "計画的に進める", "備えは。"), ("子育て支援は", "拡充する", "保育料は。")])
        self.assertEqual(parsed["questions"][0]["answerer"], "見本課長")

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
        # 当初予算は決まった型の見開きなので、流し込みの原稿は作らない
        self.assertNotIn(layout.YOSAN, pages)
        # 大見出しは「閉会中の委員会活動報告」に決まっている。その下に委員会名、記事の見出しの順
        self.assertIn("【大見出し】閉会中の委員会活動報告\n【見出し】見本委員会\n【見出し】調査",
                      pages[layout.IINKAI][0])
        # 1 番目の質問の大まかな質問が大見出しになる（題は使わない）
        self.assertIn("【大見出し・横】備え\n【顔写真枠】", pages[layout.IPPAN][0])
        # 一般質問の最初のページの頭は「一般質問に◯氏が立つ」（◯は質問者の数）
        self.assertTrue(pages[layout.IPPAN][0].startswith("【大見出し】一般質問に１氏が立つ\n"))
        self.assertEqual(items.ippan_title(12), "一般質問に１２氏が立つ")
        two = items.ippan_texts([{"member": "見本 太郎", "title": "甲"}, {"member": "見本 花子", "title": "乙"}])
        self.assertIn("一般質問に２氏が立つ", two[0])
        self.assertNotIn("氏が立つ", two[1])
        # 1 番目の見出しは、1 人目が横書き、2 人目が縦書き、3 人目が横書き…と交互
        three = items.ippan_texts([{"questions": [{"heading": name}]} for name in ("甲", "乙", "丙")])
        self.assertIn("【大見出し・横】甲", three[0])
        self.assertIn("【大見出し】乙", three[1])
        self.assertIn("【大見出し・横】丙", three[2])
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


class GyoseiTitleTest(unittest.TestCase):
    def test_default_title_is_youshi(self):
        data = items.default_data(layout.Issue(999, 4))
        self.assertEqual(data["gyosei"]["title"], "行政報告（要旨）")
        self.assertIn("【大見出し】行政報告（要旨）", items.gyosei_text({"reports": []}))
