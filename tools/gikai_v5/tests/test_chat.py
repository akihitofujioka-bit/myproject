"""段階 6（チャット段 1）の決まった言い方と実行のテスト。"""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import chat  # noqa: E402
import edition  # noqa: E402
import ingest  # noqa: E402
import layout  # noqa: E402
import samples  # noqa: E402
from grid import Rect  # noqa: E402


class ThreePhotoEdition:
    """写真番号の言い方だけを確かめる小さな代用品。"""

    def __init__(self):
        self.pages = [{"no": 1, "label": "見本", "section": layout.IPPAN,
                       "index": 1, "state": "できた"}]
        self._parts = [ingest.Part("写真", image=f"photo{number}.png")
                       for number in range(1, 4)]

    def parts(self, _page_no):
        return self._parts


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        issue = layout.Issue(999, 4, "令和8年4月30日", questioners=2)
        self.work = edition.Edition.create(root / "第999号", issue)
        source = samples.make_ingest_image_docx(root / "画像取り込み確認原稿.docx")
        self.ippan = [p["no"] for p in self.work.pages
                      if p["section"] == layout.IPPAN]
        self.page_no = self.ippan[0]
        self.work.assign(self.page_no, source)
        self.photo_part = next(index for index, part in enumerate(self.work.parts(self.page_no))
                               if part.kind == "写真")

    def tearDown(self):
        self.temp.cleanup()

    def assert_operation(self, phrase, kind, edition_value=None, page_no=None,
                         selected_part=None):
        target = edition_value or self.work
        current_page = self.page_no if page_no is None else page_no
        result = chat.interpret(phrase, target, current_page, selected_part)
        self.assertTrue(result.understood, result.reason)
        self.assertEqual(result.operations[0].kind, kind)
        return result.operations[0]

    def test_page_phrases_and_full_width_number(self):
        self.assertEqual(self.assert_operation("次のページ", "page").page_no,
                         self.page_no + 1)
        self.assertEqual(self.assert_operation("前のページ", "page").page_no,
                         self.page_no - 1)
        self.assertEqual(self.assert_operation("５ページ", "page").page_no, 5)
        self.assertEqual(self.assert_operation("五ページ", "page").page_no, 5)
        self.assertEqual(self.assert_operation("表紙", "page").page_no, 1)
        self.assertEqual(self.assert_operation("最終ページ", "page").page_no,
                         len(self.work.pages))

    def test_general_question_page(self):
        operation = self.assert_operation("一般質問の二人目", "page")
        self.assertEqual(operation.page_no, self.ippan[1])

    def test_photo_number_word_orders_and_politeness(self):
        work = ThreePhotoEdition()
        for phrase in ("写真3を小さくしてください", "3番の写真は小にして", "写真の三を小に"):
            operation = self.assert_operation(phrase, "resize", work, 1)
            self.assertEqual(operation.part_no, 2)
            self.assertEqual(operation.value, "小")

    def test_photo_sizes_and_selected_photo(self):
        for phrase, size in (("写真1を大きく", "大"), ("写真1を中に", "中"),
                             ("写真1を顔にして", "顔"), ("この写真を小さく", "小")):
            selected = self.photo_part if phrase.startswith("この") else None
            operation = self.assert_operation(phrase, "resize", selected_part=selected)
            self.assertEqual(operation.value, size)

    def test_photo_remove_and_restore(self):
        self.assert_operation("写真1を外して", "remove")
        self.assert_operation("写真1を戻す", "restore")

    def test_kind_phrases(self):
        for phrase, kind in (("3番を答弁に", "答弁"),
                             ("この部品を質問にしてください", "質問"),
                             ("7番は中見出し", "中見出し")):
            selected = 2 if phrase.startswith("この") else None
            operation = self.assert_operation(phrase, "kind", selected_part=selected)
            self.assertEqual(operation.value, kind)

    def test_move_to_left_and_right(self):
        left = self.assert_operation("写真1を二段目の左へ", "move")
        right = self.assert_operation("写真1を3段目の右端へ", "move")
        self.assertEqual(left.rect.dan, 1)
        self.assertEqual(right.rect.dan, 2)
        self.assertGreaterEqual(left.rect.line, right.rect.line)

    def test_undo_redo_check_and_export_phrases(self):
        for phrase, kind in (("元に戻して", "undo"), ("戻す", "undo"),
                             ("やり直し", "redo"), ("確かめて", "check"),
                             ("チェック", "check"),
                             ("Word に書き出してください", "export"),
                             ("書き出し", "export")):
            self.assert_operation(phrase, kind)

    def test_state_questions_have_no_operation(self):
        self.work.pages[0]["state"] = "あふれ"
        overflow = chat.interpret("あふれているページは？", self.work, self.page_no, None)
        self.assertFalse(overflow.operations)
        self.assertIn("1ページ", overflow.description)
        unfilled = chat.interpret("未入力のページは？", self.work, self.page_no, None)
        self.assertFalse(unfilled.operations)
        self.assertIn("未入力のページ", unfilled.description)

    def test_help_phrases(self):
        for phrase in ("使い方", "ヘルプ", "何ができる？"):
            result = chat.interpret(phrase, self.work, self.page_no, None)
            self.assertTrue(result.understood)
            self.assertFalse(result.operations)
            self.assertIn("写真2を小さく", result.description)

    def test_unreadable_phrase_has_three_examples(self):
        result = chat.interpret("いい感じに整えて", self.work, self.page_no, None)
        self.assertFalse(result.understood)
        self.assertIn("推測", result.reason)
        self.assertEqual(len(result.examples), 3)

    def test_photo_command_on_page_without_photo_is_clear(self):
        result = chat.interpret("写真1を小さく", self.work, 1, None)
        self.assertFalse(result.understood)
        self.assertIn("写真がありません", result.reason)

    def test_interpret_does_not_change_edition(self):
        before = self.work.history_index
        result = chat.interpret("写真1を小さく", self.work, self.page_no, None)
        self.assertTrue(result.understood)
        self.assertEqual(self.work.history_index, before)

    def test_execute_and_undo(self):
        result = chat.interpret("写真1を小さく", self.work, self.page_no, None)
        before = self.work.history_index
        message = chat.execute(result, self.work)
        self.assertIn("変えました", message)
        self.assertEqual(self.work.history_index, before + 1)
        undo = chat.interpret("元に戻して", self.work, self.page_no, None)
        self.assertIn("元に戻しました", chat.execute(undo, self.work))
        self.assertEqual(self.work.history_index, before)

    def test_chat_moves_photo_placed_from_photo_folder(self):
        page_no = next(p["no"] for p in self.work.pages if p["section"] == layout.GYOSEI)
        photo = self.work.folder / "写真" / "架空の風景.png"
        photo.write_bytes(samples._png(400, 300))
        self.assertTrue(self.work.place_photo(page_no, photo.name, Rect(0, 10, 1, 1)))
        result = chat.interpret("この写真を2段目の左へ", self.work, page_no, 0)
        self.assertTrue(result.understood, result.reason)
        self.assertIn("移動しました", chat.execute(result, self.work))

    def test_page_execute_returns_destination_without_changing_paper(self):
        before = self.work.history_index
        result = chat.interpret("次のページ", self.work, self.page_no, None)
        self.assertEqual(chat.execute(result, self.work),
                         f"{self.page_no + 1}ページへ移動します。")
        self.assertEqual(self.work.history_index, before)

    def test_python_files_parse(self):
        for name in ("chat.py", "app.pyw"):
            ast.parse((HERE.parent / name).read_text(encoding="utf-8"), filename=name)


if __name__ == "__main__":
    unittest.main()
