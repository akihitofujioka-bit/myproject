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


if __name__ == "__main__":
    unittest.main()
