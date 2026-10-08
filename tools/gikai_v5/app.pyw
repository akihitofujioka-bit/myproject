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
import chat
import edition
import ingest
import layout
import templates
import writer
from settings import Settings
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

② 左のページ一覧で ○ のページを選びます。表紙・審議・最終ページは、右の「ページ」タブの「入力欄を開く」で書き込みます。ほかは、同じタブの「原稿を入れる」、または「書いて直す」でツールの中に原稿を書きます。

「書いて直す」では、大見出し・中見出し・問・答・本文・写真のボタンで今の行へ印を付けます。入力中も紙面、あふれ、余りが変わります。保存先は号フォルダの「事務局原稿」です。原稿ファイルを入れたページも、元ファイルを書き換えずに書き直せます。

③ 紙面と、右の「部品」タブの「このページの部品」で内容を確かめます。写真と大見出しはドラッグで動かせます。緑は置ける場所、赤は置けない場所です。写真は同じタブの「大・中・小・顔」で大きさを変えられます。

④ 種類が違う部品を選び、右の「部品」タブの「種類を直す」で正しい種類を押します。タブの下の「元に戻す」で直前の操作を戻し、「やり直す」で戻す前の状態へ進めます。

⑤ 右側のタブの下にある「確かめる」で未入力やあふれを確認し、「Word に書き出す」を押します。

右の「チャット」タブには「次のページ」「写真2を小さく」「3番を答弁に」などと入力できます。内容を読み取ると「こうします」と表示します。[実行]を押すまでは紙面を変えません。読み取れないときは、推測せず言い方の例を表示します。

印の意味: ○ は原稿が未入力、✓ はできたページ、！ は紙面からあふれたページです。部品の ✓ は確かな判断、？ は確認が必要な推測です。

色と札: 問・答・大見出しなど、部品の種類を色と右上の札で示します。？付きの札と点線の枠は推測された部品です。

保存場所: 選んだ号フォルダの「原稿」「事務局原稿」「写真」「出力」に保存されます。完成した Word、写真配置一覧、確認リストは「出力」に入ります。"""


class FormEditor:
    """書き込み式ページの入力欄を別窓に表示する。"""

    MARKS = ("", "○", "●", "議長", "欠席")

    def __init__(self, app: "App", page_no: int) -> None:
        self.app = app
        self.page_no = page_no
        self.page = app.edition.pages[page_no - 1]
        self.form = dict(self.page["form"])
        self.widgets = {}
        self.pending = None
        self.window = tk.Toplevel(app.root)
        self.window.title(self.page["label"] + "の入力欄")
        self.window.geometry("760x720")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas)
        self.body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        if self.page["section"] == layout.SHINGI:
            ttk.Label(self.body, text="本文の印： 【区分】予算／◎議案名／質疑／問　…／答　…",
                      font=FONT).pack(anchor="w", pady=(0, 8))
        for field in templates.FIELDS[self.page["section"]]:
            if field.name in ("counts", "votes", "editorial_photos", "photo"):
                continue
            self._text_field(field)
        if self.page["section"] == layout.COVER:
            self._single_photo("photo", "表紙写真を選ぶ")
        elif self.page["section"] == layout.SHINGI:
            self._counts()
            self._votes()
        elif self.page["section"] == layout.LAST:
            self._photos()
            ttk.Button(self.body, text="自由欄へ原稿を入れる",
                       command=self._load_free_source).pack(anchor="w", pady=4)
        ttk.Button(self.body, text="閉じる", command=self.close).pack(anchor="e", pady=10)

    def _label(self, field) -> None:
        ttk.Label(self.body, text=field.label, font=(self.app.default_family, FONT_SIZE, "bold")).pack(anchor="w", pady=(8, 0))
        detail = field.description + (("　例：" + field.example) if field.example else "")
        ttk.Label(self.body, text=detail, font=SMALL_FONT, wraplength=700).pack(anchor="w")

    def _text_field(self, field) -> None:
        self._label(field)
        value = str(self.form.get(field.name, "") or "")
        if field.multiline:
            widget = tk.Text(self.body, height=5, width=80, font=FONT, wrap="word")
            widget.insert("1.0", value)
            widget.bind("<KeyRelease>", lambda _e, name=field.name, item=widget:
                        self._changed(name, item.get("1.0", "end-1c")))
        else:
            variable = tk.StringVar(value=value)
            widget = ttk.Entry(self.body, textvariable=variable, width=85, font=FONT)
            variable.trace_add("write", lambda *_a, name=field.name, var=variable:
                               self._changed(name, var.get()))
        widget.pack(fill="x", pady=(2, 3))
        self.widgets[field.name] = widget

    def _changed(self, name: str, value) -> None:
        self.form[name] = value
        if self.pending:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(350, self._save)

    def _save(self) -> None:
        self.pending = None
        self.app.edition.set_form(self.page_no, self.form)
        self.app._draw()

    def _single_photo(self, name: str, label: str) -> None:
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text=label, command=lambda: self._choose_photo(name)).pack(side="left")
        self.photo_label = ttk.Label(row, text=Path(str(self.form.get(name, ""))).name, font=SMALL_FONT)
        self.photo_label.pack(side="left", padx=8)

    def _choose_photo(self, name: str) -> None:
        path = filedialog.askopenfilename(parent=self.window, title="写真を選ぶ",
                                          filetypes=[("画像", "*.png *.jpg *.jpeg")])
        if path:
            self.photo_label.configure(text=Path(path).name)
            self._changed(name, path)

    def _counts(self) -> None:
        ttk.Label(self.body, text="議案等の種類と件数", font=(self.app.default_family, FONT_SIZE, "bold")).pack(anchor="w", pady=(8, 0))
        text = "\n".join(f"{item.get('kind', '')}={item.get('count', 0)}" for item in self.form.get("counts", []))
        widget = tk.Text(self.body, height=4, width=80, font=FONT)
        widget.insert("1.0", text)
        widget.pack(fill="x")
        def changed(_event=None):
            rows = []
            for line in widget.get("1.0", "end-1c").splitlines():
                if "=" in line:
                    kind, count = line.split("=", 1)
                    try:
                        rows.append({"kind": kind.strip(), "count": int(count.strip())})
                    except ValueError:
                        pass
            self._changed("counts", rows)
        widget.bind("<KeyRelease>", changed)
        ttk.Label(self.body, text="1行に「種類=件数」の形で入力します。例：条例関係=3", font=SMALL_FONT).pack(anchor="w")

    def _votes(self) -> None:
        ttk.Label(self.body, text="議案・発議案と賛否", font=(self.app.default_family, FONT_SIZE, "bold")).pack(anchor="w", pady=(10, 2))
        self.vote_frame = ttk.Frame(self.body)
        self.vote_frame.pack(fill="x")
        ttk.Button(self.body, text="行を追加", command=self._add_vote).pack(anchor="w", pady=4)
        self._draw_votes()

    def _draw_votes(self) -> None:
        for child in self.vote_frame.winfo_children():
            child.destroy()
        members = self.app.edition.settings.members
        for row_no, row in enumerate(self.form.get("votes", [])):
            line = ttk.Frame(self.vote_frame)
            line.pack(fill="x", pady=2)
            for key, width in (("kind", 10), ("title", 28), ("result", 10)):
                var = tk.StringVar(value=row.get(key, ""))
                ttk.Entry(line, textvariable=var, width=width).pack(side="left", padx=1)
                var.trace_add("write", lambda *_a, n=row_no, k=key, v=var: self._vote_text(n, k, v.get()))
            for member in members:
                mark = row.setdefault("marks", {}).get(member, "")
                ttk.Button(line, text=mark or "－", width=4,
                           command=lambda n=row_no, m=member: self._cycle_mark(n, m)).pack(side="left", padx=1)
            ttk.Button(line, text="削除", command=lambda n=row_no: self._delete_vote(n)).pack(side="left", padx=2)

    def _vote_text(self, row_no: int, key: str, value: str) -> None:
        self.form["votes"][row_no][key] = value
        self._changed("votes", self.form["votes"])

    def _cycle_mark(self, row_no: int, member: str) -> None:
        current = self.form["votes"][row_no].setdefault("marks", {}).get(member, "")
        mark = self.MARKS[(self.MARKS.index(current) + 1) % len(self.MARKS)] if current in self.MARKS else ""
        self.form["votes"][row_no]["marks"][member] = mark
        self._changed("votes", self.form["votes"])
        self._draw_votes()

    def _add_vote(self) -> None:
        self.form.setdefault("votes", []).append({"kind": "", "title": "", "result": "", "marks": {}})
        self._changed("votes", self.form["votes"])
        self._draw_votes()

    def _delete_vote(self, row_no: int) -> None:
        del self.form["votes"][row_no]
        self._changed("votes", self.form["votes"])
        self._draw_votes()

    def _photos(self) -> None:
        ttk.Label(self.body, text="編集後記の写真（0～2枚）", font=(self.app.default_family, FONT_SIZE, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Button(self.body, text="写真を追加", command=self._add_photo).pack(anchor="w", pady=3)
        ttk.Button(self.body, text="写真をすべて外す", command=self._clear_photos).pack(anchor="w", pady=3)
        self.photos_label = ttk.Label(self.body, text=self._photo_names(), font=SMALL_FONT)
        self.photos_label.pack(anchor="w")

    def _photo_names(self) -> str:
        return "、".join(Path(item.get("path", "")).name for item in self.form.get("editorial_photos", [])) or "写真なし"

    def _add_photo(self) -> None:
        if len(self.form.setdefault("editorial_photos", [])) >= 2:
            messagebox.showinfo("写真", "編集後記の写真は2枚までです。", parent=self.window)
            return
        path = filedialog.askopenfilename(parent=self.window, title="写真を選ぶ",
                                          filetypes=[("画像", "*.png *.jpg *.jpeg")])
        if path:
            caption = simpledialog.askstring("写真の説明", "短い説明", parent=self.window) or ""
            self.form["editorial_photos"].append({"path": path, "caption": caption})
            self.photos_label.configure(text=self._photo_names())
            self._changed("editorial_photos", self.form["editorial_photos"])

    def _clear_photos(self) -> None:
        self.form["editorial_photos"] = []
        self.photos_label.configure(text=self._photo_names())
        self._changed("editorial_photos", [])

    def _load_free_source(self) -> None:
        path = filedialog.askopenfilename(parent=self.window, title="自由欄の原稿を選ぶ",
                                          filetypes=[("原稿", "*.docx *.doc *.txt")])
        if not path:
            return
        try:
            result = ingest.ingest(Path(path))
        except (OSError, ValueError) as error:
            messagebox.showerror("取り込めませんでした", str(error), parent=self.window)
            return
        text = "\n".join(part.text for part in result.parts if part.text)
        widget = self.widgets.get("free")
        if isinstance(widget, tk.Text):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        self._changed("free", text)

    def close(self) -> None:
        if self.pending:
            self.window.after_cancel(self.pending)
            self._save()
        self.app.form_editor = None
        self.window.destroy()


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
        self.zoom_level = 0
        self.photo_images = []  # type: List[tk.PhotoImage]
        self.form_editor = None  # type: Optional[FormEditor]
        self.writer_editor = None  # type: Optional[writer.WriterEditor]
        self.pending_chat = None  # type: Optional[chat.Interpretation]
        self.default_family = tkfont.nametofont("TkDefaultFont").actual("family")
        families = set(tkfont.families(root))
        self.gothic_family = next((name for name in
                                   ("ＭＳ ゴシック", "MS Gothic", "Yu Gothic", "Hiragino Sans", "Arial")
                                   if name in families), self.default_family)
        self.mincho_family = next((name for name in
                                   ("ＭＳ 明朝", "MS Mincho", "Yu Mincho", "Hiragino Mincho ProN", "Times New Roman")
                                   if name in families), self.default_family)
        self._build()

    @property
    def scale(self) -> float:
        return self.ZOOMS[self.zoom_level]

    def _build(self) -> None:
        self.root.geometry("1366x740")
        self.root.minsize(1024, 640)
        self.steps = []
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        for text in ("①号を作る", "②原稿を入れる", "③並べる", "④確かめる", "⑤書き出す"):
            label = tk.Label(top, text=text, font=FONT, padx=12, pady=5)
            label.pack(side="left")
            self.steps.append(label)
        ttk.Button(top, text="使い方", command=self._show_help).pack(side="right", padx=3)
        ttk.Button(top, text="設定", command=self._settings).pack(side="right", padx=3)
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
        right = ttk.Frame(body, width=380, padding=5)
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

        self.right_notebook = ttk.Notebook(right)
        self.right_notebook.pack(fill="both", expand=True)
        self.parts_tab = ttk.Frame(self.right_notebook, padding=5)
        self.chat_tab = ttk.Frame(self.right_notebook, padding=5)
        self.page_tab = ttk.Frame(self.right_notebook, padding=5)
        self.right_notebook.add(self.parts_tab, text="部品")
        self.right_notebook.add(self.chat_tab, text="チャット")
        self.right_notebook.add(self.page_tab, text="ページ")

        ttk.Label(self.parts_tab, text="このページの部品", font=FONT).pack(anchor="w")
        self.part_list = tk.Listbox(self.parts_tab, font=SMALL_FONT, width=38, height=7,
                                    exportselection=False)
        self.part_list.pack(fill="x", pady=(3, 5))
        self.part_list.bind("<<ListboxSelect>>", self._select_part_from_list)
        ttk.Label(self.parts_tab, text="選んだ部品（全文と理由）", font=FONT).pack(anchor="w")
        selection_frame = ttk.Frame(self.parts_tab)
        selection_frame.pack(fill="both", expand=True, pady=(3, 6))
        self.selection = tk.Text(selection_frame, height=5, width=36, font=SMALL_FONT,
                                 wrap="word", state="disabled")
        selection_scroll = ttk.Scrollbar(selection_frame, orient="vertical",
                                         command=self.selection.yview)
        self.selection.configure(yscrollcommand=selection_scroll.set)
        self.selection.pack(side="left", fill="both", expand=True)
        selection_scroll.pack(side="right", fill="y")
        self._set_selection_text("なし")

        ttk.Label(self.parts_tab, text="種類を直す", font=SMALL_FONT).pack(anchor="w")
        kinds = ttk.Frame(self.parts_tab)
        kinds.pack(fill="x", pady=(2, 6))
        for number, kind in enumerate(KIND_BUTTONS):
            ttk.Button(kinds, text=kind,
                       command=lambda value=kind: self._set_kind(value)).grid(
                           row=number // 3, column=number % 3,
                           sticky="ew", padx=1, pady=1)
        for column in range(3):
            kinds.columnconfigure(column, weight=1)

        ttk.Label(self.parts_tab, text="写真の大きさ", font=SMALL_FONT).pack(anchor="w")
        size_frame = ttk.Frame(self.parts_tab)
        size_frame.pack(fill="x", pady=(2, 0))
        for size in ("大", "中", "小", "顔"):
            ttk.Button(size_frame, text=size,
                       command=lambda value=size: self._resize(value)).pack(side="left", padx=2)
        photo_actions = ttk.Frame(self.parts_tab)
        photo_actions.pack(fill="x", pady=(6, 0))
        ttk.Button(photo_actions, text="写真を外す", command=self._remove).pack(
            side="left", fill="x", expand=True, padx=(0, 1))
        ttk.Button(photo_actions, text="写真を戻す", command=self._restore).pack(
            side="left", fill="x", expand=True, padx=(1, 0))

        ttk.Button(self.page_tab, text="原稿を入れる", command=self._assign).pack(
            fill="x", pady=(2, 4))
        ttk.Button(self.page_tab, text="書いて直す", command=self._open_writer).pack(
            fill="x", pady=4)
        ttk.Button(self.page_tab, text="入力欄を開く", command=self._open_form).pack(
            fill="x", pady=4)
        ttk.Button(self.page_tab, text="前の号から写す", command=self._copy_forms).pack(
            fill="x", pady=4)

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(5, 0))
        ttk.Button(actions, text="元に戻す", command=self._undo).grid(
            row=0, column=0, sticky="ew", padx=1, pady=1)
        ttk.Button(actions, text="やり直す", command=self._redo).grid(
            row=0, column=1, sticky="ew", padx=1, pady=1)
        ttk.Button(actions, text="確かめる", command=self._check).grid(
            row=1, column=0, sticky="ew", padx=1, pady=1)
        ttk.Button(actions, text="Word に書き出す", command=self._export).grid(
            row=1, column=1, sticky="ew", padx=1, pady=1)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.status = tk.Label(right, text="新しい号を作るか、号フォルダを開いてください。",
                               font=SMALL_FONT, anchor="nw", justify="left", height=2,
                               wraplength=360)
        self.status.pack(fill="x", pady=(3, 0))

        chat_frame = self.chat_tab
        self.chat_history = tk.Text(chat_frame, height=5, width=36, font=SMALL_FONT,
                                    wrap="word", state="disabled")
        self.chat_history.pack(fill="both", expand=True)
        self.chat_confirm = ttk.Label(chat_frame, text="", font=SMALL_FONT,
                                      wraplength=340, justify="left")
        self.chat_confirm.pack(fill="x", pady=(4, 2))
        confirm_buttons = ttk.Frame(chat_frame)
        confirm_buttons.pack(fill="x")
        self.chat_execute = ttk.Button(confirm_buttons, text="実行",
                                       command=self._chat_execute, state="disabled")
        self.chat_execute.pack(side="left", fill="x", expand=True, padx=1)
        self.chat_cancel = ttk.Button(confirm_buttons, text="やめる",
                                      command=self._chat_cancel, state="disabled")
        self.chat_cancel.pack(side="left", fill="x", expand=True, padx=1)
        entry_row = ttk.Frame(chat_frame)
        entry_row.pack(fill="x", pady=(4, 2))
        self.chat_input = ttk.Entry(entry_row, font=FONT)
        self.chat_input.pack(side="left", fill="x", expand=True)
        self.chat_input.bind("<Return>", self._chat_send)
        ttk.Button(entry_row, text="送信", command=self._chat_send).pack(side="left", padx=(3, 0))
        quick = ttk.Frame(chat_frame)
        quick.pack(fill="x")
        for number, phrase in enumerate(("次のページ", "写真を小さく", "元に戻して",
                                         "あふれているページは？", "確かめて")):
            ttk.Button(quick, text=phrase,
                       command=lambda value=phrase: self._chat_send(text=value)).grid(
                           row=number // 2, column=number % 2,
                           sticky="ew", padx=1, pady=1)
        for column in range(2):
            quick.columnconfigure(column, weight=1)
        self._chat_add("ツール", "決まった言い方で操作できます。「使い方」で一覧を表示します。")
        self._show_step()
        self._set_canvas_size()
        self._draw()

    def _chat_add(self, speaker: str, text: str) -> None:
        """チャット履歴へ発言を追加する。"""
        self.chat_history.configure(state="normal")
        self.chat_history.insert("end", f"{speaker}: {text}\n")
        self.chat_history.see("end")
        self.chat_history.configure(state="disabled")

    def _set_selection_text(self, text: str) -> None:
        """選んだ部品の全文を、編集できない欄へ表示する。"""
        self.selection.configure(state="normal")
        self.selection.delete("1.0", "end")
        self.selection.insert("1.0", text)
        self.selection.configure(state="disabled")

    def _chat_send(self, _event=None, text: Optional[str] = None) -> None:
        """入力を読み取り、操作なら確認待ちにする。"""
        value = text if text is not None else self.chat_input.get()
        value = value.strip()
        if not value:
            return
        self.chat_input.delete(0, "end")
        self._chat_add("あなた", value)
        result = chat.interpret(value, self.edition, self.page_no, self.selected_part)
        self.pending_chat = None
        self.chat_execute.configure(state="disabled")
        self.chat_cancel.configure(state="disabled")
        if not result.understood:
            examples = "／".join(result.examples)
            self.chat_confirm.configure(text="")
            self._chat_add("ツール", result.reason + "\n例: " + examples)
        elif not result.operations:
            self.chat_confirm.configure(text="")
            self._chat_add("ツール", result.description)
        else:
            self.pending_chat = result
            self.chat_confirm.configure(text="こうします：" + result.description)
            self.chat_execute.configure(state="normal")
            self.chat_cancel.configure(state="normal")

    def _chat_cancel(self) -> None:
        """確認中の操作を取り消す。"""
        self.pending_chat = None
        self.chat_confirm.configure(text="")
        self.chat_execute.configure(state="disabled")
        self.chat_cancel.configure(state="disabled")
        self._chat_add("ツール", "操作をやめました。")

    def _chat_execute(self) -> None:
        """確認済みのチャット操作を Edition へ渡す。"""
        if self.pending_chat is None or self.edition is None:
            return
        pending = self.pending_chat
        result = chat.execute(pending, self.edition)
        page_operation = next((op for op in pending.operations if op.kind == "page"), None)
        if any(op.kind == "check" for op in pending.operations):
            self.step = 4
            self._show_step()
        elif any(op.kind == "export" for op in pending.operations):
            self.step = 5
            self._show_step()
        if page_operation is not None:
            self.page_no = page_operation.page_no
            self.selected_part = None
            self.page_list.selection_clear(0, "end")
            self.page_list.selection_set(self.page_no - 1)
            self.page_list.see(self.page_no - 1)
        self.pending_chat = None
        self.chat_confirm.configure(text="")
        self.chat_execute.configure(state="disabled")
        self.chat_cancel.configure(state="disabled")
        self._chat_add("ツール", result)
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
        self.right_notebook.select(self.parts_tab)
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
            if "form" in self.edition.pages[self.page_no - 1]:
                self._open_form()

    def _open_form(self) -> None:
        if not self.edition or not self.page_no:
            return
        page = self.edition.pages[self.page_no - 1]
        if "form" not in page:
            messagebox.showinfo("入力欄", "このページは原稿ファイルを入れるページです。")
            return
        if self.form_editor:
            if self.form_editor.page_no == self.page_no:
                self.form_editor.window.lift()
                return
            self.form_editor.close()
        self.form_editor = FormEditor(self, self.page_no)

    def _open_writer(self) -> None:
        if not self.edition or not self.page_no:
            return
        page = self.edition.pages[self.page_no - 1]
        if "form" in page:
            messagebox.showinfo("書いて直す", "このページは「入力欄を開く」で書きます。")
            return
        if self.writer_editor:
            if self.writer_editor.page_no == self.page_no:
                self.writer_editor.window.lift()
                return
            self.writer_editor.close()
        self.writer_editor = writer.WriterEditor(self, self.page_no)

    def _copy_forms(self) -> None:
        if not self.edition:
            return
        folder = filedialog.askdirectory(title="前の号のフォルダを選ぶ")
        if not folder:
            return
        try:
            self.edition.copy_forms_from(Path(folder))
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror("写せませんでした", str(error))
            return
        self._draw()

    def _settings(self) -> None:
        current = Settings.load()
        window = tk.Toplevel(self.root)
        window.title("設定")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="議員名簿（賛否表の列順、1行に1人）", font=FONT).pack(anchor="w")
        members = tk.Text(frame, width=45, height=12, font=FONT)
        members.insert("1.0", "\n".join(current.members))
        members.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(frame, text="議長の名前", font=FONT).pack(anchor="w")
        chair = ttk.Entry(frame, width=45, font=FONT)
        chair.insert(0, current.chair)
        chair.pack(fill="x", pady=(2, 8))
        ttk.Label(frame, text="委員会名", font=FONT).pack(anchor="w")
        committee = ttk.Entry(frame, width=60, font=FONT)
        committee.insert(0, current.committee)
        committee.pack(fill="x", pady=(2, 8))
        def save_settings():
            value = Settings([line.strip() for line in members.get("1.0", "end-1c").splitlines() if line.strip()],
                             chair.get().strip(), committee.get().strip())
            value.save()
            if self.edition:
                self.edition.settings = value
                self._draw()
            window.destroy()
        ttk.Button(frame, text="保存", command=save_settings).pack(side="right")

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
        advance = max(5, item.pt * self.scale)
        for column, line in enumerate(item.lines):
            x = right - column * pitch
            row = 0
            styled = item.line_runs[column] if item.line_runs and column < len(item.line_runs) else [(line, item.font)]
            for text, font_name in styled:
                family = self.gothic_family if font_name == dx.GOTHIC else self.mincho_family
                font = (family, -size, "bold" if item.bold else "normal")
                for cell in self._vertical_cells(text):
                    y = y1 + 2 + row * advance + advance / 2
                    self.canvas.create_text(x, y, text=cell, font=font, anchor="center")
                    row += 1

    def _draw_horizontal(self, item: dx.TextBox) -> None:
        x1, y1, x2, y2 = self._paper_box(item.box)
        anchor = {"左": "nw", "中央": "n", "右": "ne"}.get(item.align, "nw")
        x = {"左": x1 + 2, "中央": (x1 + x2) / 2, "右": x2 - 2}.get(item.align, x1 + 2)
        family = self.gothic_family if item.font == dx.GOTHIC else self.mincho_family
        font = (family, -max(6, round(item.pt * self.scale)),
                "bold" if item.bold else "normal")
        self.canvas.create_text(x, y1 + 2, text="\n".join(item.lines), anchor=anchor,
                                justify={"左": "left", "中央": "center", "右": "right"}.get(item.align, "left"),
                                font=font, width=max(10, x2 - x1 - 4))
        if item.border:
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#333333")

    def _draw_table(self, item: dx.Table) -> None:
        x1, y1, x2, y2 = self._paper_box(item.box)
        rows = max(1, len(item.rows))
        row_h = (y2 - y1) / rows
        total = sum(item.column_widths) or 1
        x = x1
        for width in item.column_widths:
            self.canvas.create_line(x, y1, x, y2, fill="#333333")
            x += (x2 - x1) * width / total
        self.canvas.create_line(x2, y1, x2, y2, fill="#333333")
        for row_no, values in enumerate(item.rows):
            top = y1 + row_no * row_h
            self.canvas.create_line(x1, top, x2, top, fill="#333333")
            x = x1
            for index, width in enumerate(item.column_widths):
                cell_w = (x2 - x1) * width / total
                text = values[index] if index < len(values) else ""
                self.canvas.create_text(x + cell_w / 2, top + row_h / 2, text=text,
                                        font=(self.gothic_family, -max(5, round(item.pt * self.scale))),
                                        width=max(4, cell_w - 2))
                x += cell_w
        self.canvas.create_line(x1, y2, x2, y2, fill="#333333")

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
            if item.vertical:
                self._draw_vertical(item)
            else:
                self._draw_horizontal(item)
        elif isinstance(item, dx.Table):
            self._draw_table(item)
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

    def _draw(self, preview=None, preview_parts=None) -> None:
        self.canvas.delete("all")
        self.fit_label.configure(text="")
        self.photo_images = []
        self.part_items.clear()
        self.caption_items.clear()
        self.hint.configure(text=edition.next_hint(self.edition))
        if not self.edition or not self.page_no:
            self.part_list.delete(0, "end")
            self._set_selection_text("なし")
            self.canvas.create_text(
                self.PAPER_W * self.scale / 2, self.PAPER_H * self.scale / 2,
                text="はじめに\n\n「新しい号」：号数と月を入れて作り始めます\n「号を開く」：保存した号の続きを開きます",
                font=FONT, justify="center", width=self.PAPER_W * self.scale - 30)
            return
        page = self.edition.pages[self.page_no - 1]
        if preview is None and not page["source"] and "form" not in page:
            self._refresh_parts([])
            self.canvas.create_text(self.PAPER_W * self.scale / 2,
                                    self.PAPER_H * self.scale / 2,
                                    text=page["label"] + "\n原稿が未入力です",
                                    font=FONT, justify="center")
            return
        try:
            parts = preview_parts if preview_parts is not None else self.edition.parts(self.page_no)
            result = preview if preview is not None else self.edition.compose(self.page_no)
        except (OSError, ValueError) as error:
            messagebox.showerror("紙面を作れませんでした", str(error))
            return
        for placement in result.placements:
            self.canvas.create_rectangle(*self._box(placement.rect),
                                         fill=COLORS.get(placement.part.kind, "#eeeeee"),
                                         outline="")
        for item in result.page.items:
            if isinstance(item, (dx.TextBox, dx.Picture, dx.Placeholder, dx.Table)):
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
            self._set_selection_text("なし")

    def _show_selection(self, part, index: int) -> None:
        text = part.text or ("写真：" + Path(part.image or "ファイルなし").name)
        mark = "✓" if part.sure else "？"
        reason = part.reason or "理由なし"
        self._set_selection_text(
            f"{index + 1}. {part.kind} {mark}\n{text}\n理由：{reason}")

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
        text = "書き出しました。\n" + "\n".join(str(path) for path in paths[:3])
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
