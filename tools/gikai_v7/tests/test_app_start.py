"""画面が起動の途中で止まらないかを確かめる（app.pyw はエラーを表示せずに終わるため）。"""
import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


def _load_app():
    loader = importlib.machinery.SourceFileLoader("app_for_test", str(ROOT / "app.pyw"))
    spec = importlib.util.spec_from_loader("app_for_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class AppStartTest(unittest.TestCase):
    def setUp(self):
        if tk is None:
            self.skipTest("tkinter がありません")
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面を出せない環境です")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def test_app_starts_and_every_step_opens(self):
        app_module = _load_app()
        saved_argv = sys.argv
        sys.argv = ["app.pyw"]
        # 手元に残った「前回の続き」に左右されないよう、テストの間は空の一時ファイルを使う
        import tempfile
        temp = tempfile.TemporaryDirectory()
        resume = app_module.RESUME_PATH = Path(temp.name) / "前回の続き.json"
        before = None
        try:
            app = app_module.App(self.root)
            for number in range(len(app_module.guide.STEPS)):
                app.show(number)
                self.root.update_idletasks()
        finally:
            sys.argv = saved_argv
            temp.cleanup()


class PreviewStartPageTest(unittest.TestCase):
    """紙面を見るは、今編集している手順の項目のページから出す。"""

    def test_starts_from_section_of_current_step(self):
        app_module = _load_app()
        layout = app_module.layout
        sections = [layout.COVER, layout.GYOSEI, layout.SHINGI, layout.IPPAN, layout.IPPAN, layout.LAST]

        class Work:
            pages = [{"no": n, "section": s} for n, s in enumerate(sections, 1)]

        app = app_module.App.__new__(app_module.App)
        app.work = Work()
        app.preview_pages = {}
        app.list_selection = {}
        for step, page in ((3, 1), (4, 2), (6, 3), (7, 3), (9, 4), (11, 6), (13, 1)):
            app.step = step
            self.assertEqual(app._preview_page(), page, step)
        # 一般質問の2ページ目を見ていたら、次もそこから。ほかの項目のページなら項目の先頭から
        app.step = 9
        app.preview_pages[9] = 5
        self.assertEqual(app._preview_page(), 5)
        app.preview_pages[9] = 2
        self.assertEqual(app._preview_page(), 4)
        app.step = 13
        app.preview_pages[13] = 6
        self.assertEqual(app._preview_page(), 6)
        # 一般質問は、一覧で選んでいる（足したばかりの）人のページから
        app.step = 9
        app.list_selection[9] = 1
        self.assertEqual(app._preview_page(), 5)
        app.list_selection[9] = 0
        self.assertEqual(app._preview_page(), 4)


class PeriodTest(unittest.TestCase):
    """会期のプルダウンで選んだ年月日を、紙面の書き方（全角）にする。"""

    def test_format_and_parse(self):
        app_module = _load_app()
        self.assertEqual(app_module.format_period(8, 9, 4, 8, 9, 11), "Ｒ８．９．４～９．１１")
        self.assertEqual(app_module.parse_period("Ｒ８．９．４～９．１１"), (8, 9, 4, 8, 9, 11))
        self.assertEqual(app_module.format_period(8, 12, 25, 9, 1, 5), "Ｒ８．１２．２５～Ｒ９．１．５")
        self.assertEqual(app_module.parse_period("Ｒ８．１２．２５～１．５"), (8, 12, 25, 9, 1, 5))
        self.assertEqual(app_module.format_period(8, 2, 30, 8, 3, 1), "")   # 無い日
        self.assertEqual(app_module.format_period(8, 9, 11, 8, 9, 4), "")   # 終わりが前
        self.assertEqual(app_module.format_period(8, 9, 0, 8, 9, 11), "")   # 日を選んでいない
        self.assertIsNone(app_module.parse_period("９月４日から"))


class PreviewTitleHitTest(unittest.TestCase):
    """紙面を見るでダブルクリックした所が、賛否表の何行目・何件目の案件かを求める。"""

    def test_table_row_and_bill(self):
        app_module = _load_app()
        dx = app_module.dx
        from grid import Box
        table = dx.Table(Box(10, 100, 300, 60), [100, 200], [["", ""], ["議案", "甲"], ["予算", "乙"]],
                         8.0, dx.GOTHIC, True, "賛否表", None, None, [30, 15, 15])
        self.assertEqual([app_module._table_row(table, y) for y in (101, 131, 146, 161)], [0, 1, 2, None])
        heads = [dx.TextBox(Box(0, 0, 10, 10), [line], dx.GOTHIC, 11, 15.4, False, False, "議案")
                 for line in ("◎議案第１号　架空", "◎議案第２号　見本")]
        bills = [{"title": "議案第１号 架空"}, {"title": "議案第２号\n見本"}]
        self.assertEqual([app_module._bill_index(bills, h, heads) for h in heads], [0, 1])
        # 件名が合わなくても、並び順で見つける
        self.assertEqual(app_module._bill_index([{"title": "別"}, {"title": "別2"}], heads[1], heads), 1)
        self.assertIsNone(app_module._bill_index(bills, None, heads))


class PreviewQaHitTest(unittest.TestCase):
    """紙面を見るの審議本文で押した所が、何件目の案件の何番目の問かを求める。"""

    def test_shingi_spot(self):
        import tempfile
        app_module = _load_app()
        import edition, items, layout
        from grid import to_box
        from settings import Settings
        with tempfile.TemporaryDirectory() as folder:
            work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
            work.settings = Settings(["見本 太郎", "見本 花子"], "見本 花子", "見本")
            data = items.default_data(work.issue)
            data["shingi"]["bills"] = [
                {"kind": "議案", "title": "議案第１号　架空", "description": "説明。", "questions": [
                    {"question": "問一。", "answer": "答一。"}, {"question": "問二。", "answer": "答二。"}]},
                {"kind": "予算", "title": "議案第２号　見本", "questions": [{"question": "問三。", "answer": "答三。"}]}]
            work.save_items(data)
            page = next(p["no"] for p in work.pages if p["section"] == layout.SHINGI)
            result = work.compose(page)
            spots = {}
            for placement in result.placements:
                box = to_box(work.geometry, placement.rect)
                spots[placement.part.text] = app_module._shingi_spot(
                    data["shingi"]["bills"], work, result.placements, box.x + 2, box.y + 2)
            self.assertEqual(spots["説明。"], (0, -1))
            self.assertEqual(spots["答　答二。"], (0, 1))
            self.assertEqual(spots["問　問三。"], (1, 0))
            self.assertIsNone(spots["◎議案第１号　架空"])
        self.assertEqual(app_module._qa_text(data["shingi"]["bills"][1]), "問　問三。\n答　答三。")


class ButtonTipTest(unittest.TestCase):
    """ボタンにマウスを合わせたときの説明。"""

    def test_every_step_and_common_button_has_tip(self):
        import guide
        for number, name in enumerate(guide.STEPS, 1):
            self.assertTrue(guide.button_tip(f"{number}. {name}"), name)
        for text in ("紙面を見る", "次へ", "まとめて貼る", "Word から読み込む", "直す"):
            self.assertTrue(guide.button_tip(text), text)
        self.assertEqual(guide.button_tip("知らないボタン"), "")


class OpenFileTest(unittest.TestCase):
    """確認用の Word を作ったら、Windows では os.startfile で Word に開かせる。"""

    def test_open_file_uses_startfile_on_windows(self):
        import os
        app_module = _load_app()
        opened = []
        saved_platform, saved = app_module.sys.platform, getattr(os, "startfile", None)
        try:
            app_module.sys.platform = "win32"
            os.startfile = lambda path: opened.append(path)
            self.assertTrue(app_module._open_file(Path("確認用.docx")))
        finally:
            app_module.sys.platform = saved_platform
            if saved is None:
                del os.startfile
            else:
                os.startfile = saved
        self.assertEqual(opened, ["確認用.docx"])


class QuestionEditorTest(unittest.TestCase):
    """一般質問の入力の窓で、1 つの質問にやりとりを足して保存できる（窓は画面に出さない）。"""

    def test_add_exchange_and_save(self):
        if tk is None:
            self.skipTest("tkinter がありません")
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("画面を出せない環境です")
        root.withdraw()
        import tempfile
        app_module = _load_app()
        import edition
        import layout
        saved_argv = sys.argv
        sys.argv = ["app.pyw"]
        try:
            with tempfile.TemporaryDirectory() as folder:
                app_module.RESUME_PATH = Path(folder) / "前回の続き.json"
                app = app_module.App(root)
                app._big_window = lambda dialog: dialog.withdraw()
                app.work = edition.Edition.create(Path(folder) / "号", layout.Issue(998, 4, "令和8年4月30日"))
                app.work.save_settings(["見本 太郎"], "見本 太郎")
                app.data = app.work.item_data()
                value = {"member": "見本 太郎", "qa_bulk": "【見出し】架空の見出し\n問　最初。\n答　答え。"}
                finished = []
                app._question_editor(value, lambda: finished.append(True))
                top = next(w for w in root.winfo_children()
                           if isinstance(w, tk.Toplevel) and w.title() == "一般質問を入力")

                def find(widget, cls):
                    found = [widget] if widget.winfo_class() == cls else []
                    for child in widget.winfo_children():
                        found += find(child, cls)
                    return found
                next(b for b in find(top, "TButton") if b.cget("text") == "やりとりを足す").invoke()
                texts = find(top, "Text")
                texts[2].insert("1.0", "架空の再質問。")
                texts[3].insert("1.0", "架空の再答弁。")
                next(b for b in find(top, "TButton") if b.cget("text") == "この内容にする").invoke()
                self.assertEqual(finished, [True])
                self.assertEqual([q["question"] for q in value["questions"]], ["最初。", "架空の再質問。"])
                self.assertEqual(value["questions"][1]["heading"], "")
        finally:
            sys.argv = saved_argv
            root.destroy()


if __name__ == "__main__":
    unittest.main()
