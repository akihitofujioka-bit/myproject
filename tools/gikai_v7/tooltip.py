"""ボタンにマウスを合わせると、そのボタンの働きを小さな窓で出す。

ボタンごとに設定しなくてよいよう、画面全体でマウスの出入りを見て、
ボタンの字（または widget._tip に入れた文）から説明を探す。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

DELAY_MS = 500     # マウスを合わせてから出すまで
WRAP_PX = 380


class Tooltips:
    def __init__(self, root: tk.Misc, lookup: Callable[[tk.Misc], Optional[str]]):
        self.root = root
        self.lookup = lookup
        self.window: Optional[tk.Toplevel] = None
        self.waiting = None
        root.bind_all("<Enter>", self._enter, add="+")
        root.bind_all("<Leave>", self._hide, add="+")
        root.bind_all("<ButtonPress>", self._hide, add="+")

    def _enter(self, event) -> None:
        widget = event.widget
        if not isinstance(widget, tk.Misc):   # 「all」などの名前で来ることがある
            return
        try:
            text = self.lookup(widget)
        except (tk.TclError, AttributeError):
            text = None
        if not text:
            return
        self._hide()
        self.waiting = self.root.after(DELAY_MS, lambda: self._show(widget, text))

    def _show(self, widget, text: str) -> None:
        self.waiting = None
        try:
            if not widget.winfo_exists():
                return
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 4
        except tk.TclError:
            return
        window = tk.Toplevel(widget)
        window.wm_overrideredirect(True)
        try:
            window.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        label = tk.Label(window, text=text, justify="left", wraplength=WRAP_PX,
                         background="#ffffe8", foreground="#222", relief="solid", borderwidth=1,
                         padx=8, pady=5)
        label.pack()
        window.update_idletasks()
        # 画面の右端・下端からはみ出さないようにする
        x = min(x, widget.winfo_screenwidth() - window.winfo_width() - 8)
        if y + window.winfo_height() > widget.winfo_screenheight() - 8:
            y = widget.winfo_rooty() - window.winfo_height() - 4
        window.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        self.window = window

    def _hide(self, _event=None) -> None:
        if self.waiting is not None:
            try:
                self.root.after_cancel(self.waiting)
            except tk.TclError:
                pass
            self.waiting = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None
