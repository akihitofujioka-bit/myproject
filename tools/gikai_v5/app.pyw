"""議会だより編集ツール V5 の画面。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, Optional, Tuple

import edition
import layout
from grid import Rect


FONT_SIZE = 12
FONT = ("TkDefaultFont", FONT_SIZE)
SMALL_FONT = ("TkDefaultFont", max(9, FONT_SIZE - 2))

COLORS = {
    "大見出し": "#ffd166", "中見出し": "#ffe8a3", "写真": "#8ecae6",
    "質問": "#bde0fe", "答弁": "#cdeac0", "本文": "#eeeeee",
    "議案": "#d9c2f0", "写真説明": "#d7eef7",
}


class App:
    """画面表示と利用者の操作を Edition へつなぐ。"""

    CANVAS_W = 620
    CANVAS_H = 700
    GRID_LEFT = 10
    GRID_TOP = 10
    GRID_W = 600
    GRID_H = 675

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("議会だより編集ツール V5")
        self.edition = None  # type: Optional[edition.Edition]
        self.page_no = 0
        self.selected_part = None  # type: Optional[int]
        self.part_items = {}  # type: Dict[int, Tuple[int, Rect]]
        self.drag = None
        self.shadow = None
        self.step = 1
        self._build()

    def _build(self) -> None:
        self.steps = []
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        for text in ("①号を作る", "②原稿を入れる", "③並べる", "④確かめる", "⑤書き出す"):
            label = tk.Label(top, text=text, font=FONT, padx=12, pady=5)
            label.pack(side="left")
            self.steps.append(label)
        ttk.Button(top, text="新しい号", command=self.create_edition).pack(side="right", padx=3)
        ttk.Button(top, text="号を開く", command=self.open_edition).pack(side="right", padx=3)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(body, width=250, padding=5)
        center = ttk.Frame(body, padding=5)
        right = ttk.Frame(body, width=230, padding=5)
        body.add(left, weight=1)
        body.add(center, weight=4)
        body.add(right, weight=1)

        ttk.Label(left, text="ページ一覧", font=FONT).pack(anchor="w")
        self.page_list = tk.Listbox(left, font=SMALL_FONT, width=28, exportselection=False)
        self.page_list.pack(fill="both", expand=True, pady=5)
        ttk.Label(left, text="○ 未入力　✓ できた　！ あふれ", font=SMALL_FONT).pack(anchor="w")
        self.page_list.bind("<<ListboxSelect>>", self._select_page)

        self.canvas = tk.Canvas(center, width=self.CANVAS_W, height=self.CANVAS_H,
                                bg="white", highlightthickness=1)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)

        ttk.Label(right, text="選んだ部品", font=FONT).pack(anchor="w")
        self.selection = ttk.Label(right, text="なし", font=SMALL_FONT, wraplength=210)
        self.selection.pack(fill="x", pady=(3, 8))
        size_frame = ttk.Frame(right)
        size_frame.pack(fill="x")
        for size in ("大", "中", "小", "顔"):
            ttk.Button(size_frame, text=size,
                       command=lambda value=size: self._resize(value)).pack(side="left", padx=2)
        ttk.Button(right, text="写真を外す", command=self._remove).pack(fill="x", pady=(8, 2))
        ttk.Button(right, text="写真を戻す", command=self._restore).pack(fill="x", pady=2)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="元に戻す", command=self._undo).pack(fill="x", pady=2)
        ttk.Button(right, text="やり直す", command=self._redo).pack(fill="x", pady=2)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Button(right, text="原稿を入れる", command=self._assign).pack(fill="x", pady=2)
        ttk.Button(right, text="確かめる", command=self._check).pack(fill="x", pady=2)
        ttk.Button(right, text="Word に書き出す", command=self._export).pack(fill="x", pady=2)
        self.status = ttk.Label(right, text="新しい号を作るか、号フォルダを開いてください。",
                                font=SMALL_FONT, wraplength=210)
        self.status.pack(fill="x", pady=10)
        self._show_step()

    def _show_step(self) -> None:
        for n, label in enumerate(self.steps, 1):
            label.configure(bg="#ffe08a" if n == self.step else self.root.cget("bg"),
                            relief="solid" if n == self.step else "flat")

    def create_edition(self) -> None:
        folder = filedialog.askdirectory(title="新しい号を作る場所を選ぶ")
        if not folder:
            return
        number = simpledialog.askinteger("号を作る", "号数", parent=self.root, minvalue=0)
        if number is None:
            return
        month = simpledialog.askinteger("号を作る", "月（4・7・10・1）", parent=self.root)
        if month is None:
            return
        date = simpledialog.askstring("号を作る", "発行日", parent=self.root) or ""
        questioners = simpledialog.askinteger("号を作る", "一般質問の人数", parent=self.root,
                                              minvalue=0, maxvalue=10)
        if questioners is None:
            return
        committees = simpledialog.askinteger("号を作る", "委員会報告のページ数", parent=self.root,
                                             minvalue=0)
        if committees is None:
            return
        target = Path(folder) / f"第{number}号"
        try:
            self.edition = edition.Edition.create(
                target, layout.Issue(number, month, date, questioners, committees))
        except (OSError, ValueError) as error:
            messagebox.showerror("作れませんでした", str(error))
            return
        self.step = 2
        self._load_edition()

    def open_edition(self, folder: Optional[str] = None) -> None:
        folder = folder or filedialog.askdirectory(title="号フォルダを選ぶ")
        if not folder:
            return
        try:
            self.edition = edition.Edition.open(Path(folder))
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("開けませんでした", str(error))
            return
        self.step = 2
        self._load_edition()

    def _load_edition(self) -> None:
        self.page_no = 1 if self.edition and self.edition.pages else 0
        self.selected_part = None
        self._refresh_pages()
        if self.page_no:
            self.page_list.selection_set(0)
        self._draw()
        self.status.configure(text=str(self.edition.folder) if self.edition else "")
        self._show_step()

    def _refresh_pages(self) -> None:
        self.page_list.delete(0, "end")
        if not self.edition:
            return
        marks = {"未入力": "○", "あふれ": "！", "できた": "✓"}
        for page in self.edition.pages:
            self.page_list.insert("end", f"{page['no']:>2} {page['label']} {marks[page['state']]}")

    def _select_page(self, _event=None) -> None:
        selected = self.page_list.curselection()
        if selected:
            self.page_no = selected[0] + 1
            self.selected_part = None
            self._draw()

    def _draw_grid(self) -> None:
        cw = self.GRID_W / 30
        dh = self.GRID_H / 5
        for line in range(31):
            x = self.GRID_LEFT + line * cw
            self.canvas.create_line(x, self.GRID_TOP, x, self.GRID_TOP + self.GRID_H,
                                    fill="#e8e8e8")
        for dan in range(6):
            y = self.GRID_TOP + dan * dh
            self.canvas.create_line(self.GRID_LEFT, y, self.GRID_LEFT + self.GRID_W, y,
                                    fill="#d0d0d0", width=2)

    def _box(self, rect: Rect) -> Tuple[float, float, float, float]:
        cw = self.GRID_W / 30
        dh = self.GRID_H / 5
        x1 = self.GRID_LEFT + (30 - rect.line - rect.line_span) * cw
        y1 = self.GRID_TOP + rect.dan * dh
        return x1, y1, x1 + rect.line_span * cw, y1 + rect.dan_span * dh

    def _draw(self) -> None:
        self.canvas.delete("all")
        self.part_items.clear()
        self._draw_grid()
        if not self.edition or not self.page_no:
            return
        page = self.edition.pages[self.page_no - 1]
        if not page["source"]:
            self.canvas.create_text(self.CANVAS_W / 2, self.CANVAS_H / 2,
                                    text=page["label"] + "\n原稿が未入力です", font=FONT)
            return
        try:
            result = self.edition.compose(self.page_no)
        except (OSError, ValueError) as error:
            messagebox.showerror("紙面を作れませんでした", str(error))
            return
        for placement in result.placements:
            x1, y1, x2, y2 = self._box(placement.rect)
            color = COLORS.get(placement.part.kind, "#eeeeee")
            width = 3 if placement.index == self.selected_part else 1
            item = self.canvas.create_rectangle(x1, y1, x2, y2, fill=color,
                                                outline="#555555", width=width,
                                                tags=(f"part:{placement.index}",))
            self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2,
                                    text=placement.part.kind[:1], font=SMALL_FONT,
                                    tags=(f"part:{placement.index}",))
            if placement.part.kind in ("写真", "大見出し"):
                self.part_items[placement.index] = (item, placement.rect)
        color = "#d62828" if result.overflow_lines else "#d4a017"
        text = (f"あふれ {result.overflow_lines} 行" if result.overflow_lines
                else f"余り {result.free_lines} 行")
        self.canvas.create_text(self.GRID_LEFT + 5, self.GRID_TOP + 5, text=text,
                                fill=color, font=FONT, anchor="nw")
        self._refresh_pages()

    def _part_at(self, x: float, y: float) -> Optional[int]:
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("part:"):
                    return int(tag.split(":", 1)[1])
        return None

    def _drag_start(self, event) -> None:
        part = self._part_at(event.x, event.y)
        if part is None:
            return
        self.selected_part = part
        self.selection.configure(text=f"部品 {part + 1}")
        self._draw()
        if part in self.part_items:
            rect = self.part_items[part][1]
            self.drag = (part, rect, event.x, event.y)

    def _snap(self, x: float, y: float, rect: Rect) -> Rect:
        cw = self.GRID_W / 30
        dh = self.GRID_H / 5
        left_line = round((x - self.GRID_LEFT) / cw)
        line = 30 - left_line - rect.line_span
        dan = round((y - self.GRID_TOP) / dh)
        return Rect(dan, line, rect.dan_span, rect.line_span)

    def _drag_motion(self, event) -> None:
        if not self.drag or not self.edition:
            return
        part, rect, start_x, start_y = self.drag
        x1, y1, _, _ = self._box(rect)
        target = self._snap(x1 + event.x - start_x, y1 + event.y - start_y, rect)
        if self.shadow:
            self.canvas.delete(self.shadow)
        color = "#39a852" if self.edition.can_move_part(self.page_no, part, target) else "#d62828"
        self.shadow = self.canvas.create_rectangle(*self._box(target), outline=color,
                                                   width=4, dash=(6, 3))

    def _drag_end(self, event) -> None:
        if not self.drag or not self.edition:
            return
        part, rect, start_x, start_y = self.drag
        x1, y1, _, _ = self._box(rect)
        target = self._snap(x1 + event.x - start_x, y1 + event.y - start_y, rect)
        if not self.edition.move_part(self.page_no, part, target):
            self.status.configure(text="そこには置けません。赤い場所は避けてください。")
        self.drag = None
        self.shadow = None
        self.step = 3
        self._show_step()
        self._draw()

    def _selected(self) -> Optional[int]:
        if self.selected_part is None:
            messagebox.showinfo("部品を選ぶ", "紙面の写真または大見出しを選んでください。")
        return self.selected_part

    def _resize(self, size: str) -> None:
        part = self._selected()
        if part is None or not self.edition:
            return
        try:
            changed = self.edition.resize_photo(self.page_no, part, size)
            if not changed:
                self.status.configure(text="その大きさでは、ほかの部品と重なります。")
        except ValueError as error:
            messagebox.showinfo("写真を選ぶ", str(error))
        self._draw()

    def _remove(self) -> None:
        part = self._selected()
        if part is not None and self.edition:
            try:
                self.edition.remove_photo(self.page_no, part)
                self._draw()
            except ValueError as error:
                messagebox.showinfo("写真を選ぶ", str(error))

    def _restore(self) -> None:
        part = self._selected()
        if part is not None and self.edition:
            try:
                self.edition.restore_photo(self.page_no, part)
            except ValueError as error:
                messagebox.showinfo("写真を選ぶ", str(error))
            self._draw()

    def _undo(self) -> None:
        if self.edition and self.edition.undo():
            self._draw()

    def _redo(self) -> None:
        if self.edition and self.edition.redo():
            self._draw()

    def _assign(self) -> None:
        if not self.edition or not self.page_no:
            return
        source = filedialog.askopenfilename(title="原稿を選ぶ",
                                            filetypes=[("原稿", "*.docx *.doc *.txt")])
        if not source:
            return
        try:
            self.edition.assign(self.page_no, Path(source))
        except (OSError, ValueError) as error:
            messagebox.showerror("取り込めませんでした", str(error))
            return
        self.step = 3
        self._show_step()
        self._draw()

    def _check(self) -> None:
        if not self.edition:
            return
        messages = self.edition.check()
        self.step = 4
        self._show_step()
        messagebox.showinfo("確認リスト", "\n".join(messages) if messages else "問題はありません。")
        self._draw()

    def _export(self) -> None:
        if not self.edition:
            return
        try:
            paths = self.edition.export()
        except (OSError, ValueError) as error:
            messagebox.showerror("書き出せませんでした", str(error))
            return
        self.step = 5
        self._show_step()
        text = "書き出しました。\n" + "\n".join(str(path) for path in paths[:2])
        self.status.configure(text=text)
        messagebox.showinfo("書き出し完了", text)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    style.configure("TLabel", font=FONT)
    style.configure("TButton", font=FONT)
    app = App(root)
    # 号フォルダを渡されたら（起動.bat にフォルダを落としたときなど）すぐ開く
    if len(sys.argv) > 1:
        app.open_edition(sys.argv[1])
    root.mainloop()


if __name__ == "__main__":
    main()
