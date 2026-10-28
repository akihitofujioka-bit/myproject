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


if __name__ == "__main__":
    unittest.main()
