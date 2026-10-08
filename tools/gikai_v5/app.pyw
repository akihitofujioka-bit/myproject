"""議会だより編集ツール V5 の画面。"""

from __future__ import annotations

import base64
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional, Tuple

import docx_out as dx
import edition
import layout
from grid import Rect, TATECHUYOKO, mm2pt, to_box


FONT_SIZE = 12
FONT = ("TkDefaultFont", FONT_SIZE)
SMALL_FONT = ("TkDefaultFont", max(9, FONT_SIZE - 2))

COLORS = {
    "大見出し": "#ffd166", "中見出し": "#ffe8a3", "写真": "#8ecae6",
    "質問": "#bde0fe", "答弁": "#cdeac0", "本文": "#eeeeee",
    "議案": "#d9c2f0", "写真説明": "#d7eef7",
}
LABELS = {"質問": "問", "答弁": "答"}
KIND_BUTTONS = ("大見出し", "中見出し", "質問", "答弁", "本文", "写真説明", "議案")
HELP_TEXT = """①「新しい号」を押し、号数と月などを入れます。前の号を続けるときは「号を開く」を押します。

② 左のページ一覧で ○ のページを選び、「原稿を入れる」を押します。

③ 紙面と「このページの部品」で内容を確かめます。写真と大見出しはドラッグで動かせます。緑は置ける場所、赤は置けない場所です。写真は「大・中・小・顔」で大きさを変えられます。

④ 種類が違う部品を選び、「種類を直す」で正しい種類を押します。「元に戻す」で直前の操作を戻し、「やり直す」で戻す前の状態へ進めます。

⑤「確かめる」で未入力やあふれを確認し、「Word に書き出す」を押します。

印の意味: ○ は原稿が未入力、✓ はできたページ、！ は紙面からあふれたページです。部品の ✓ は確かな判断、？ は確認が必要な推測です。

色と札: 問・答・大見出しなど、部品の種類を色と右上の札で示します。？付きの札と点線の枠は推測された部品です。

保存場所: 選んだ号フォルダの「原稿」「写真」「出力」に保存されます。完成した Word は「出力」に入ります。"""


class App:
    """画面表示と利用者の操作を Edition へつなぐ。"""

    PAPER_W = 510.0
    PAPER_H = 765.0
    # 標準は 1366×768 の画面でも紙面が縦に収まる大きさ。字を読みたいときは「大」
    ZOOMS = (0.72, 0.95, 1.25)

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("議会だより編集ツール V5")
        self.edition = None  # type: Optional[edition.Edition]
        self.page_no = 0
        self.selected_part = None  # type: Optional[int]
        self.part_items = {}  # type: Dict[int, List[Rect]]
        self.caption_items = {}  # type: Dict[int, Rect]
        self.drag = None
        self.shadow = None
        self.step = 1
        self.zoom_level = 1
        self.photo_images = []  # type: List[tk.PhotoImage]
        self.default_family = tkfont.nametofont("TkDefaultFont").actual("family")
        self._build()

    @property
    def scale(self) -> float:
        return self.ZOOMS[self.zoom_level]

    def _build(self) -> None:
        self.steps = []
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        for text in ("①号を作る", "②原稿を入れる", "③並べる", "④確かめる", "⑤書き出す"):
            label = tk.Label(top, text=text, font=FONT, padx=12, pady=5)
            label.pack(side="left")
            self.steps.append(label)
        ttk.Button(top, text="使い方", command=self._show_help).pack(side="right", padx=3)
        ttk.Button(top, text="新しい号", command=self.create_edition).pack(side="right", padx=3)
        ttk.Button(top, text="号を開く", command=self.open_edition).pack(side="right", padx=3)

        hint_frame = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        hint_frame.pack(fill="x")
        ttk.Label(hint_frame, text="いまやること：",
                  font=(self.default_family, FONT_SIZE, "bold")).pack(side="left")
        self.hint = ttk.Label(hint_frame, text=edition.next_hint(None), font=FONT)
        self.hint.pack(side="left", fill="x", expand=True)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        left = ttk.Frame(body, width=240, padding=5)
        center = ttk.Frame(body, padding=5)
        right = ttk.Frame(body, width=300, padding=5)
        body.add(left, weight=1)
        body.add(center, weight=3)
        body.add(right, weight=2)

        ttk.Label(left, text="ページ一覧", font=FONT).pack(anchor="w")
        self.page_list = tk.Listbox(left, font=SMALL_FONT, width=28, exportselection=False)
        self.page_list.pack(fill="both", expand=True, pady=5)
        ttk.Label(left, text="○ 未入力　✓ できた　！ あふれ", font=SMALL_FONT).pack(anchor="w")
        self.page_list.bind("<<ListboxSelect>>", self._select_page)

        zoom = ttk.Frame(center)
        zoom.pack(fill="x", pady=(0, 4))
        ttk.Label(zoom, text="紙面", font=FONT).pack(side="left")
        # あふれ・余りは紙面の上に重ねると本文が読めないので、見出しの横に出す
        self.fit_label = tk.Label(zoom, text="", font=FONT)
        self.fit_label.pack(side="left", padx=10)
        ttk.Button(zoom, text="縮小 −", command=lambda: self._zoom(-1)).pack(side="right", padx=2)
        ttk.Button(zoom, text="拡大 ＋", command=lambda: self._zoom(1)).pack(side="right", padx=2)
        self.zoom_text = ttk.Label(zoom, text="標準", font=SMALL_FONT)
        self.zoom_text.pack(side="right", padx=5)
        self.canvas = tk.Canvas(center, bg="white", highlightthickness=1,
                                highlightbackground="#777777")
        self.canvas.pack(anchor="n")
        self.canvas.bind("<Button-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        legend = ttk.Frame(center)
        legend.pack(fill="x", pady=(5, 0))
        for kind in COLORS:
            tk.Label(legend, text=LABELS.get(kind, kind), bg=COLORS[kind],
                     font=(self.default_family, 8), padx=2).pack(side="left", padx=1)

        ttk.Label(right, text="このページの部品", font=FONT).pack(anchor="w")
        self.part_list = tk.Listbox(right, font=SMALL_FONT, width=38, height=12,
                                    exportselection=False)
        self.part_list.pack(fill="both", expand=True, pady=(3, 5))
        self.part_list.bind("<<ListboxSelect>>", self._select_part_from_list)
        ttk.Label(right, text="選んだ部品", font=FONT).pack(anchor="w")
        self.selection = ttk.Label(right, text="なし", font=SMALL_FONT,
                                   wraplength=285, justify="left")
        self.selection.pack(fill="x", pady=(3, 6))

        ttk.Label(right, text="種類を直す", font=SMALL_FONT).pack(anchor="w")
        kinds = ttk.Frame(right)
        kinds.pack(fill="x", pady=(2, 6))
        for number, kind in enumerate(KIND_BUTTONS):
            ttk.Button(kinds, text=kind,
                       command=lambda value=kind: self._set_kind(value)).grid(
                           row=number // 3, column=number % 3,
                           sticky="ew", padx=1, pady=1)
        for column in range(3):
            kinds.columnconfigure(column, weight=1)

        ttk.Label(right, text="写真の大きさ", font=SMALL_FONT).pack(anchor="w")
        size_frame = ttk.Frame(right)
        size_frame.pack(fill="x", pady=(2, 0))
        for size in ("大", "中", "小", "顔"):
            ttk.Button(size_frame, text=size,
                       command=lambda value=size: self._resize(value)).pack(side="left", padx=2)
        ttk.Button(right, text="写真を外す", command=self._remove).pack(fill="x", pady=(6, 2))
        ttk.Button(right, text="写真を戻す", command=self._restore).pack(fill="x", pady=2)
        ttk.Separator(right).pack(fill="x", pady=6)
        actions = ttk.Frame(right)
        actions.pack(fill="x")
        ttk.Button(actions, text="元に戻す", command=self._undo).pack(
            side="left", fill="x", expand=True, padx=1)
        ttk.Button(actions, text="やり直す", command=self._redo).pack(
            side="left", fill="x", expand=True, padx=1)
        ttk.Button(right, text="原稿を入れる", command=self._assign).pack(fill="x", pady=(6, 2))
        ttk.Button(right, text="確かめる", command=self._check).pack(fill="x", pady=2)
        ttk.Button(right, text="Word に書き出す", command=self._export).pack(fill="x", pady=2)
        self.status = ttk.Label(right, text="新しい号を作るか、号フォルダを開いてください。",
                                font=SMALL_FONT, wraplength=285)
        self.status.pack(fill="x", pady=8)
        self._show_step()
        self._set_canvas_size()
        self._draw()

    def _show_step(self) -> None:
        for n, label in enumerate(self.steps, 1):
            label.configure(bg="#ffe08a" if n == self.step else self.root.cget("bg"),
                            relief="solid" if n == self.step else "flat")

    def _show_help(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("使い方")
        window.transient(self.root)
        ttk.Label(window, text="議会だより編集ツールの使い方",
                  font=(self.default_family, 15, "bold")).pack(
                      anchor="w", padx=14, pady=(14, 6))
        ttk.Label(window, text=HELP_TEXT, font=FONT, wraplength=650,
                  justify="left").pack(fill="both", expand=True, padx=14, pady=(0, 14))
        ttk.Button(window, text="閉じる", command=window.destroy).pack(pady=(0, 14))

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
        for index, page in enumerate(self.edition.pages):
            self.page_list.insert("end", f"{page['no']:>2} {page['label']} {marks[page['state']]}")
            if page["state"] == "あふれ":
                self.page_list.itemconfigure(index, foreground="#c1121f")

    def _select_page(self, _event=None) -> None:
        selected = self.page_list.curselection()
        if selected:
            self.page_no = selected[0] + 1
            self.selected_part = None
            self._draw()

    def _set_canvas_size(self) -> None:
        self.canvas.configure(width=round(self.PAPER_W * self.scale),
                              height=round(self.PAPER_H * self.scale))
        self.zoom_text.configure(text=("小", "標準", "大")[self.zoom_level])

    def _zoom(self, change: int) -> None:
        level = max(0, min(len(self.ZOOMS) - 1, self.zoom_level + change))
        if level != self.zoom_level:
            self.zoom_level = level
            self._set_canvas_size()
            self._draw()

    def _box(self, rect: Rect) -> Tuple[float, float, float, float]:
        return self._paper_box(to_box(self.edition.geometry, rect))

    def _paper_box(self, box) -> Tuple[float, float, float, float]:
        left = mm2pt(self.edition.geometry.margin_left_mm) if self.edition else 0.0
        top = mm2pt(self.edition.geometry.margin_top_mm) if self.edition else 0.0
        x1 = (box.x - left) * self.scale
        y1 = (box.y - top) * self.scale
        return x1, y1, x1 + box.w * self.scale, y1 + box.h * self.scale

    @staticmethod
    def _vertical_cells(text: str) -> List[str]:
        """縦中横の数字を一つのマスとして、縦書きのマスへ分ける。"""
        cells = []
        pos = 0
        for match in TATECHUYOKO.finditer(text):
            cells.extend(text[pos:match.start()])
            cells.append(match.group(0))
            pos = match.end()
        cells.extend(text[pos:])
        return cells

    def _draw_vertical(self, item: dx.TextBox) -> None:
        x1, y1, x2, _ = self._paper_box(item.box)
        pitch = item.pitch_pt * self.scale
        total = len(item.lines) * pitch
        right = ((x1 + x2 + total) / 2 if item.center else x2) - pitch / 2
        size = max(6, round(item.pt * self.scale))
        bold = item.font == dx.GOTHIC or item.name in ("大見出し", "中見出し")
        font = (self.default_family, -size, "bold" if bold else "normal")
        advance = max(5, item.pt * self.scale)
        for column, line in enumerate(item.lines):
            x = right - column * pitch
            for row, cell in enumerate(self._vertical_cells(line)):
                y = y1 + 2 + row * advance + advance / 2
                self.canvas.create_text(x, y, text=cell, font=font, anchor="center")

    @staticmethod
    def _boxes_overlap(first, second) -> bool:
        return not (first.x + first.w <= second.x or second.x + second.w <= first.x
                    or first.y + first.h <= second.y or second.y + second.h <= first.y)

    def _draw_picture(self, item: dx.Picture, x1: float, y1: float,
                      x2: float, y2: float, filename: str) -> None:
        caption_h = min(30, max(16, (y2 - y1) * 0.18)) if item.caption else 16
        if item.ext.lower() == "png":
            try:
                photo = tk.PhotoImage(data=base64.b64encode(item.data).decode("ascii"))
                ratio = max(photo.width() / max(1, x2 - x1 - 6),
                            photo.height() / max(1, y2 - y1 - caption_h - 6), 1)
                sample = max(1, int(ratio + 0.999))
                if sample > 1:
                    photo = photo.subsample(sample, sample)
                self.photo_images.append(photo)
                self.canvas.create_image((x1 + x2) / 2, y1 + 3,
                                         image=photo, anchor="n")
            except tk.TclError:
                pass
        text = "写真：" + Path(filename).name
        if item.caption:
            self.canvas.create_rectangle(x1, y2 - caption_h, x2, y2,
                                         fill=COLORS["写真説明"], outline="")
            text += "\n" + item.caption
        self.canvas.create_text((x1 + x2) / 2, y2 - 2, text=text, anchor="s",
                                font=(self.default_family, -max(7, round(9 * self.scale))),
                                width=max(20, x2 - x1 - 4))

    def _draw_page_item(self, item, result) -> None:
        if isinstance(item, dx.TextBox):
            kind = item.name if item.name in COLORS else "本文"
        elif isinstance(item, (dx.Picture, dx.Placeholder)) and item.name.startswith("写真"):
            kind = "写真"
        else:
            kind = "本文"
        x1, y1, x2, y2 = self._paper_box(item.box)
        if isinstance(item, dx.Placeholder):
            self.canvas.create_rectangle(x1, y1, x2, y2,
                                         fill=COLORS.get(kind, "#f5f5f5"),
                                         outline="#a0a0a0")
        if isinstance(item, dx.TextBox):
            self._draw_vertical(item)
        elif isinstance(item, dx.Picture):
            placement = next((p for p in result.placements
                              if p.part.kind == "写真" and self._boxes_overlap(
                                  item.box, to_box(self.edition.geometry, p.rect))), None)
            filename = placement.part.image if placement and placement.part.image else item.name
            self._draw_picture(item, x1, y1, x2, y2, filename)
        elif isinstance(item, dx.Placeholder):
            self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2,
                                    text=item.label,
                                    font=(self.default_family,
                                          -max(7, round(10 * self.scale))),
                                    width=max(20, x2 - x1 - 4))

    def _draw_part_marks(self, parts, result) -> None:
        self.part_items.clear()
        self.caption_items.clear()
        for placement in result.placements:
            self.part_items.setdefault(placement.index, []).append(placement.rect)
        for index, part in enumerate(parts):
            if (part.kind == "写真説明" and index not in self.part_items and index > 0
                    and parts[index - 1].kind == "写真"):
                previous = self.part_items.get(index - 1, [])
                if previous:
                    self.caption_items[index] = previous[0]
        for index, rects in self.part_items.items():
            part = parts[index]
            for rect_no, rect in enumerate(rects):
                x1, y1, x2, y2 = self._box(rect)
                self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill="", outline="#111111",
                    width=4 if index == self.selected_part else 1,
                    dash=() if part.sure else (5, 3))
                if rect_no == 0:
                    label = LABELS.get(part.kind, part.kind) + ("" if part.sure else "？")
                    anchor = "se" if part.kind == "写真説明" else "ne"
                    label_y = y2 if part.kind == "写真説明" else y1
                    # 1〜2 行の細い枠では横書きの札が隣の行にかぶるので、縦に並べる
                    if x2 - x1 < 40:
                        label = "\n".join(label)
                    tag = self.canvas.create_text(x2 - 1, label_y, text=label, anchor=anchor,
                                                  fill="#222222",
                                                  font=(self.default_family, -9, "bold"))
                    # 下の本文と混ざらないよう、札の後ろを白く抜く
                    bg = self.canvas.create_rectangle(*self.canvas.bbox(tag), fill="#ffffff",
                                                      outline="#888888")
                    self.canvas.tag_lower(bg, tag)
        for index, rect in self.caption_items.items():
            x1, _, x2, y2 = self._box(rect)
            y1 = max(0, y2 - max(14, 22 * self.scale))
            part = parts[index]
            self.canvas.create_rectangle(
                x1, y1, x2, y2, fill="", outline="#111111",
                width=4 if index == self.selected_part else 1,
                dash=() if part.sure else (5, 3))
            label = "写真説明" + ("" if part.sure else "？")
            self.canvas.create_text(x2, y1, text=label, anchor="ne",
                                    font=(self.default_family, -8, "bold"))

    def _draw(self) -> None:
        self.canvas.delete("all")
        self.fit_label.configure(text="")
        self.photo_images = []
        self.part_items.clear()
        self.caption_items.clear()
        self.hint.configure(text=edition.next_hint(self.edition))
        if not self.edition or not self.page_no:
            self.part_list.delete(0, "end")
            self.selection.configure(text="なし")
            self.canvas.create_text(
                self.PAPER_W * self.scale / 2, self.PAPER_H * self.scale / 2,
                text="はじめに\n\n「新しい号」：号数と月を入れて作り始めます\n「号を開く」：保存した号の続きを開きます",
                font=FONT, justify="center", width=self.PAPER_W * self.scale - 30)
            return
        page = self.edition.pages[self.page_no - 1]
        if not page["source"]:
            self._refresh_parts([])
            self.canvas.create_text(self.PAPER_W * self.scale / 2,
                                    self.PAPER_H * self.scale / 2,
                                    text=page["label"] + "\n原稿が未入力です",
                                    font=FONT, justify="center")
            return
        try:
            parts = self.edition.parts(self.page_no)
            result = self.edition.compose(self.page_no)
        except (OSError, ValueError) as error:
            messagebox.showerror("紙面を作れませんでした", str(error))
            return
        for placement in result.placements:
            self.canvas.create_rectangle(*self._box(placement.rect),
                                         fill=COLORS.get(placement.part.kind, "#eeeeee"),
                                         outline="")
        for item in result.page.items:
            if isinstance(item, (dx.TextBox, dx.Picture, dx.Placeholder)):
                self._draw_page_item(item, result)
        self._draw_part_marks(parts, result)
        self._refresh_parts(parts)
        color = "#d62828" if result.overflow_lines else "#946200"
        text = (f"あふれ {result.overflow_lines} 行" if result.overflow_lines
                else f"余り {result.free_lines} 行")
        self.fit_label.configure(text=text, fg=color)
        self._refresh_pages()
        self.hint.configure(text=edition.next_hint(self.edition))

    def _refresh_parts(self, parts) -> None:
        self.part_list.delete(0, "end")
        for index, part in enumerate(parts):
            text = part.text or ("写真：" + Path(part.image or "ファイルなし").name)
            short = " ".join(text.split())[:20]
            mark = "✓" if part.sure else "？"
            self.part_list.insert("end", f"{index + 1:>2} {part.kind} {mark} {short}")
        if self.selected_part is not None and self.selected_part < len(parts):
            self.part_list.selection_set(self.selected_part)
            self.part_list.see(self.selected_part)
            self._show_selection(parts[self.selected_part], self.selected_part)
        else:
            self.selection.configure(text="なし")

    def _show_selection(self, part, index: int) -> None:
        text = part.text or ("写真：" + Path(part.image or "ファイルなし").name)
        if len(text) > 200:
            text = text[:200] + "…"
        mark = "✓" if part.sure else "？"
        reason = part.reason or "理由なし"
        self.selection.configure(
            text=f"{index + 1}. {part.kind} {mark}\n{text}\n理由：{reason}")

    def _select_part_from_list(self, _event=None) -> None:
        selected = self.part_list.curselection()
        if selected:
            self.selected_part = selected[0]
            self._draw()

    def _part_at(self, x: float, y: float) -> Optional[int]:
        for index, rect in self.caption_items.items():
            x1, _, x2, y2 = self._box(rect)
            y1 = y2 - max(14, 22 * self.scale)
            if x1 <= x <= x2 and y1 <= y <= y2:
                return index
        for index, rects in reversed(list(self.part_items.items())):
            for rect in rects:
                x1, y1, x2, y2 = self._box(rect)
                if x1 <= x <= x2 and y1 <= y <= y2:
                    return index
        return None

    def _drag_start(self, event) -> None:
        part = self._part_at(event.x, event.y)
        if part is None or not self.edition:
            return
        self.selected_part = part
        parts = self.edition.parts(self.page_no)
        self._show_selection(parts[part], part)
        self._draw()
        if parts[part].kind in ("写真", "大見出し") and self.part_items.get(part):
            rect = self.part_items[part][0]
            self.drag = (part, rect, event.x, event.y)

    def _snap(self, x: float, y: float, rect: Rect) -> Rect:
        g = self.edition.geometry
        left = mm2pt(g.margin_left_mm)
        top = mm2pt(g.margin_top_mm)
        paper_x = x / self.scale + left
        paper_y = y / self.scale + top
        right = mm2pt(g.page_w_mm - g.margin_right_mm)
        line = round((right - paper_x - rect.line_span * g.line_pitch_pt)
                     / g.line_pitch_pt)
        dan = round((paper_y - top) / (g.dan_h_pt + g.gap_pt))
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
            messagebox.showinfo("部品を選ぶ", "紙面または部品一覧から部品を選んでください。")
        return self.selected_part

    def _set_kind(self, kind: str) -> None:
        part = self._selected()
        if part is None or not self.edition:
            return
        try:
            self.edition.set_kind(self.page_no, part, kind)
        except ValueError as error:
            messagebox.showinfo("種類を直す", str(error))
            return
        self.step = 3
        self._show_step()
        self._draw()

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
        self.selected_part = None
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
