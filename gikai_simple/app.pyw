# -*- coding: utf-8 -*-
"""議会だより かんたん原稿ツール — 画面

画面は 1 つだけ。

    ┌ 号フォルダ ─────────────────────────────────────────────┐
    │ 区分（7つ） │ 選んだ区分の原稿              │ 写真フォルダの写真   │
    │ 字数・写真数│ （ここに文章を書く／貼る）    │ 選んで「入れる」     │
    └───────────────────────────────────────────────────────┘
    [Word を作る] [出力フォルダを開く]                      状態

写真は「写真」フォルダに入れ、右の一覧から選んで大きさと説明を決め、
「カーソル位置に入れる」を押すと原稿に 【写真】… の 1 行が入る。
それだけで、原稿 Word にはその場所に写真が貼られ、指示書にも載る。

起動:  python app.pyw   （Windows ではダブルクリック）
必要:  pip install python-docx Pillow
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402

try:
    from PIL import Image, ImageOps, ImageTk
    THUMB_OK = True
except ImportError:
    THUMB_OK = False

APP_NAME = "議会だより かんたん原稿ツール"
SETTINGS = Path.home() / ".gikai_simple.json"
THUMB_PX = 96
UI_FONT = ("Yu Gothic UI", 10) if sys.platform == "win32" else ("Hiragino Sans", 12)
TEXT_FONT = ("Yu Gothic", 11) if sys.platform == "win32" else ("Hiragino Sans", 13)

HELP = """使い方（5 つだけ）

1. 「新しい号を作る」で号数・発行日・号の種類（3月号／6月号／9月号／12月号）を入れる
   → 好きな場所に「第○号」フォルダができ、その号に合った区分がそろいます
   　3月号: 当初予算の概要　9月号: 決算の概要・議員行政視察研修報告
   　12月号: 行政視察・研修報告　など（毎号あるものは共通）
   区分は左の「区分を追加」「▲▼」「外す」で足したり順番を変えたりできます
   （外せるのは空の区分だけです）
   賛否一覧表の Excel など原稿以外のものは「別添フォルダ」に入れます

2. 左の区分を選び、中央に原稿を書く（または「原稿ファイルを取り込む」）
   議員から届いた Word（.docx / .doc）やテキストを、文字だけ貼り付けます

3. 写真は「写真フォルダを開く」で開いたフォルダに入れる
   入れたら「写真を読み直す」を押すと右に並びます

4. 写真を右で選び、大きさと説明を決めて「カーソル位置に入れる」
   原稿に 【写真】ファイル名｜大きさ｜説明 の行が入ります
   （この行は手で書いても、消しても、動かしてもかまいません）

5. 「Word を作る」
   出力フォルダに「原稿（写真入り）」と「写真配置指示書」ができます
   印刷所には、この Word 2 つと「写真」フォルダの中身を渡します

数字は縦書きの慣行に合わせて自動でそろえます（Word を作るとき・取り込むとき）
   1 桁は全角「４人」、2 桁以上は半角「第46回」。〒・℡・番地はそのまま
   手で書いた文章は「数字をそろえる」ボタンでもそろえられます（表紙は対象外）

大きさの目安（紙面は 5 段組・1 段 約 30mm）
   大 = 幅 80mm   中 = 幅 55mm   小 = 幅 38mm   顔 = 幅 26mm（顔写真）

原稿は区分を切り替えたとき・Word を作るときに自動で保存されます。
このツールはインターネットに何も送りません。
"""


def open_in_explorer(path: Path) -> None:
    """フォルダやファイルを OS 標準の方法で開く。"""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror(APP_NAME, f"開けませんでした:\n{path}\n{e}")


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class NewIssueDialog(simpledialog.Dialog):
    """号数・発行日・号の種類を 1 つの画面で聞く。"""

    def __init__(self, parent):
        self.result = None
        super().__init__(parent, title="新しい号を作る")

    def body(self, master):
        ttk.Label(master, text="号数（例: 204）").grid(row=0, column=0, sticky="w", pady=2)
        self.e_gou = ttk.Entry(master, width=24)
        self.e_gou.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(master, text="発行日（例: 令和８年７月31日）").grid(row=1, column=0, sticky="w", pady=2)
        self.e_date = ttk.Entry(master, width=24)
        self.e_date.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(master, text="号の種類（定例会）").grid(row=2, column=0, sticky="nw", pady=2)
        self.v_tmpl = tk.StringVar(value=core.DEFAULT_TEMPLATE)
        box = ttk.Frame(master)
        box.grid(row=2, column=1, sticky="w")
        for name in core.TEMPLATES:
            ttk.Radiobutton(box, text=name, value=name, variable=self.v_tmpl,
                            command=self._show_kubun).pack(anchor="w")
        self.lbl = ttk.Label(master, text="", foreground="#555555", wraplength=360, justify="left")
        self.lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._show_kubun()
        return self.e_gou

    def _show_kubun(self):
        names = core.TEMPLATES[self.v_tmpl.get()]
        self.lbl.config(text="区分: " + " → ".join(names) + "\n（あとから足したり順番を変えたりできます）")

    def validate(self):
        if not self.e_gou.get().strip():
            messagebox.showwarning(APP_NAME, "号数を入れてください", parent=self)
            return False
        return True

    def apply(self):
        self.result = (self.e_gou.get().strip(), self.e_date.get().strip(), self.v_tmpl.get())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x720")
        self.minsize(900, 560)
        self.issue: core.Issue | None = None
        self.current_kubun: str | None = None
        self.kubun_names: list[str] = []
        self.selected_photo: Path | None = None
        self._thumbs: list = []          # ImageTk を GC から守る
        self._photo_buttons: dict[str, tk.Button] = {}
        self.settings = load_settings()

        style = ttk.Style(self)
        style.configure(".", font=UI_FONT)
        self.option_add("*Font", UI_FONT)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        last = self.settings.get("last_issue")
        if last and Path(last).is_dir():
            self.open_issue(Path(last))

    # ------------------------------------------------------------ 画面の組み立て

    def _build(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Button(top, text="新しい号を作る", command=self.new_issue).pack(side="left")
        ttk.Button(top, text="号フォルダを開く", command=self.choose_issue).pack(side="left", padx=(6, 0))
        self.lbl_issue = ttk.Label(top, text="（号フォルダが選ばれていません）")
        self.lbl_issue.pack(side="left", padx=12)
        ttk.Button(top, text="使い方", command=self.show_help).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8)

        # 左: 区分
        left = ttk.Frame(body, padding=(0, 0, 6, 0))
        ttk.Label(left, text="区分（紙面の順）").pack(anchor="w")
        self.lst_kubun = tk.Listbox(left, height=12, exportselection=False,
                                    font=UI_FONT, activestyle="none")
        self.lst_kubun.pack(fill="both", expand=True)
        self.lst_kubun.bind("<<ListboxSelect>>", self.on_select_kubun)
        kb = ttk.Frame(left)
        kb.pack(fill="x", pady=(4, 0))
        ttk.Button(kb, text="▲", width=3, command=lambda: self.move_kubun(-1)).pack(side="left")
        ttk.Button(kb, text="▼", width=3, command=lambda: self.move_kubun(+1)).pack(side="left", padx=2)
        ttk.Button(kb, text="区分を追加", command=self.add_kubun).pack(side="left", padx=(6, 2))
        ttk.Button(kb, text="外す", command=self.remove_kubun).pack(side="left")
        body.add(left, weight=0)

        # 中央: 原稿
        mid = ttk.Frame(body, padding=(0, 0, 6, 0))
        bar = ttk.Frame(mid)
        bar.pack(fill="x")
        self.lbl_kubun = ttk.Label(bar, text="区分を選んでください", font=(UI_FONT[0], UI_FONT[1], "bold"))
        self.lbl_kubun.pack(side="left")
        self.lbl_hint = ttk.Label(mid, text="", foreground="#555555", wraplength=560, justify="left")
        self.lbl_hint.pack(fill="x", pady=(2, 2))
        ttk.Button(bar, text="保存", command=self.save_current).pack(side="right")
        ttk.Button(bar, text="数字をそろえる", command=self.fix_numbers).pack(side="right", padx=6)
        ttk.Button(bar, text="原稿ファイルを取り込む", command=self.import_files).pack(side="right")
        self.txt = tk.Text(mid, wrap="char", undo=True, font=TEXT_FONT, padx=8, pady=6)
        scroll = ttk.Scrollbar(mid, command=self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        self.txt.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.txt.bind("<<Modified>>", self.on_modified)
        body.add(mid, weight=3)

        # 右: 写真
        right = ttk.Frame(body)
        rbar = ttk.Frame(right)
        rbar.pack(fill="x")
        ttk.Label(rbar, text="写真").pack(side="left")
        ttk.Button(rbar, text="写真フォルダを開く", command=self.open_photo_dir).pack(side="right")
        ttk.Button(rbar, text="写真を読み直す", command=self.refresh_photos).pack(side="right", padx=4)

        gallery = ttk.Frame(right)
        gallery.pack(side="top", fill="both", expand=True)
        self.photo_canvas = tk.Canvas(gallery, width=330, highlightthickness=0)
        pscroll = ttk.Scrollbar(gallery, command=self.photo_canvas.yview)
        self.photo_canvas.configure(yscrollcommand=pscroll.set)
        self.photo_inner = ttk.Frame(self.photo_canvas)
        self.photo_canvas.create_window((0, 0), window=self.photo_inner, anchor="nw")
        self.photo_inner.bind("<Configure>",
                              lambda e: self.photo_canvas.configure(scrollregion=self.photo_canvas.bbox("all")))
        self.photo_canvas.pack(side="left", fill="both", expand=True)
        pscroll.pack(side="right", fill="y")

        # 選んだ写真の設定
        box = ttk.LabelFrame(right, text="選んだ写真をカーソル位置に入れる", padding=6)
        box.pack(fill="x", pady=(6, 0))
        self.lbl_photo = ttk.Label(box, text="（右上の一覧から写真を選んでください）", wraplength=300)
        self.lbl_photo.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="大きさ").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cmb_size = ttk.Combobox(box, values=list(core.SIZES), state="readonly", width=6)
        self.cmb_size.set(core.DEFAULT_SIZE)
        self.cmb_size.grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(box, text="説明").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.ent_caption = ttk.Entry(box, width=34)
        self.ent_caption.grid(row=2, column=1, sticky="we", pady=(4, 0))
        ttk.Button(box, text="カーソル位置に入れる", command=self.insert_photo).grid(
            row=3, column=0, columnspan=2, sticky="we", pady=(8, 0))
        box.columnconfigure(1, weight=1)
        body.add(right, weight=0)

        # 下: 出力
        bottom = ttk.Frame(self, padding=(8, 6))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Word を作る（原稿＋写真配置指示書）", command=self.build).pack(side="left")
        ttk.Button(bottom, text="出力フォルダを開く", command=self.open_out_dir).pack(side="left", padx=6)
        ttk.Button(bottom, text="別添フォルダを開く", command=self.open_attach_dir).pack(side="left")
        self.lbl_status = ttk.Label(bottom, text="")
        self.lbl_status.pack(side="left", padx=12)

    # ------------------------------------------------------------ 号

    def new_issue(self):
        ans = NewIssueDialog(self).result
        if not ans:
            return
        gou, hakkoubi, template = ans
        root = filedialog.askdirectory(parent=self, title="「第○号」フォルダを作る場所を選んでください",
                                       initialdir=self.settings.get("last_root") or str(Path.home()))
        if not root:
            return
        try:
            issue = core.Issue.create(root, gou, hakkoubi, template=template)
        except (FileExistsError, KeyError) as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.settings["last_root"] = root
        self.open_issue(issue.folder)
        messagebox.showinfo(APP_NAME, f"{issue.folder}\nを {template} の構成で作りました。\n\n"
                            "区分は左の一覧で足したり順番を変えたりできます。\n写真は「写真」フォルダに入れてください。")

    def choose_issue(self):
        folder = filedialog.askdirectory(parent=self, title="号フォルダ（第○号）を選んでください",
                                         initialdir=self.settings.get("last_root") or str(Path.home()))
        if folder:
            self.open_issue(Path(folder))

    def open_issue(self, folder: Path):
        self.save_current()
        try:
            self.issue = core.Issue.open(folder)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"開けませんでした:\n{e}")
            return
        self.settings["last_issue"] = str(folder)
        self.settings.setdefault("last_root", str(folder.parent))
        save_settings(self.settings)
        kind = f"（{self.issue.template}）" if self.issue.template else ""
        self.lbl_issue.config(text=f"{self.issue.title()}{kind}　発行日 {self.issue.hakkoubi or '（未入力）'}　— {folder}")
        self.current_kubun = None
        self.txt.delete("1.0", "end")
        self.refresh_kubun_list()
        self.refresh_photos()
        self.lst_kubun.selection_clear(0, "end")
        self.lst_kubun.selection_set(0)
        self.on_select_kubun()

    # ------------------------------------------------------------ 区分と原稿

    def refresh_kubun_list(self):
        if not self.issue:
            return
        sel = self.lst_kubun.curselection()
        self.lst_kubun.delete(0, "end")
        self.kubun_names = self.issue.kubun_list()
        for name, text in self.issue.all_texts():
            n = core.count_chars(text)
            p = len(core.photo_refs(text))
            mark = "" if n else "　（空）"
            self.lst_kubun.insert("end", f"{name}{mark}　{n}字・写真{p}")
        if sel and sel[0] < len(self.kubun_names):
            self.lst_kubun.selection_set(sel[0])

    def _select_kubun_by_name(self, name: str):
        if name in self.kubun_names:
            i = self.kubun_names.index(name)
            self.lst_kubun.selection_clear(0, "end")
            self.lst_kubun.selection_set(i)
            self.lst_kubun.see(i)

    def add_kubun(self):
        if not self.issue:
            return
        name = simpledialog.askstring(APP_NAME, "足す区分の名前（例: 視聴者の声）\n選んでいる区分の次に入ります", parent=self)
        if not name:
            return
        self.save_current()
        try:
            self.issue.add_kubun(name, after=self.current_kubun)
        except (FileExistsError, ValueError) as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.refresh_kubun_list()
        self._select_kubun_by_name(name.strip())
        self.on_select_kubun()

    def move_kubun(self, delta: int):
        if not self.issue or not self.current_kubun:
            return
        self.save_current()
        name = self.current_kubun
        self.issue.move_kubun(name, delta)
        self.refresh_kubun_list()
        self._select_kubun_by_name(name)

    def remove_kubun(self):
        if not self.issue or not self.current_kubun:
            return
        name = self.current_kubun
        self.save_current()
        if self.issue.read_text(name).strip():
            messagebox.showinfo(APP_NAME, f"「{name}」には原稿が入っているので外せません。\n中身を空にしてからにしてください。")
            return
        if not messagebox.askyesno(APP_NAME, f"区分「{name}」（空）を外しますか？\nファイル {self.issue.text_path(name).name} は削除されます。"):
            return
        try:
            self.issue.remove_kubun(name)
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        self.current_kubun = None
        self.txt.delete("1.0", "end")
        self.txt.edit_modified(False)
        self.refresh_kubun_list()
        if self.kubun_names:
            self.lst_kubun.selection_set(0)
            self.on_select_kubun()

    def on_select_kubun(self, _ev=None):
        if not self.issue:
            return
        sel = self.lst_kubun.curselection()
        if not sel:
            return
        if sel[0] >= len(self.kubun_names):
            return
        name = self.kubun_names[sel[0]]
        if name == self.current_kubun:
            return
        self.save_current()
        self.current_kubun = name
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", self.issue.read_text(name))
        self.txt.edit_reset()
        self.txt.edit_modified(False)
        self.lbl_kubun.config(text=name)
        hint = core.HINTS.get(name, "")
        self.lbl_hint.config(text=("載せるもの: " + hint) if hint else "")
        self.txt.focus_set()

    def on_modified(self, _ev=None):
        if self.txt.edit_modified():
            self.lbl_status.config(text="（未保存の変更があります）")

    def save_current(self):
        """いま開いている区分をファイルに書く。変更がなければ何もしない。"""
        if not self.issue or not self.current_kubun:
            return
        if not self.txt.edit_modified():
            return
        self.issue.write_text(self.current_kubun, self.txt.get("1.0", "end-1c"))
        self.txt.edit_modified(False)
        self.lbl_status.config(text=f"{self.current_kubun} を保存しました")
        self.refresh_kubun_list()
        self.mark_photo_usage()

    def import_files(self):
        if not self.issue or not self.current_kubun:
            messagebox.showinfo(APP_NAME, "先に号フォルダを開き、区分を選んでください。")
            return
        paths = filedialog.askopenfilenames(
            parent=self, title="取り込む原稿ファイル（複数可）",
            filetypes=[("原稿", "*.docx *.doc *.txt"), ("すべて", "*.*")])
        if not paths:
            return
        for p in paths:
            try:
                text = core.import_manuscript(p)
            except Exception as e:
                messagebox.showerror(APP_NAME, f"{Path(p).name} を取り込めませんでした。\n{e}")
                continue
            if self.txt.get("1.0", "end-1c").strip():
                self.txt.insert("end", "\n\n")
            self.txt.insert("end", text)
        self.txt.edit_modified(True)
        self.save_current()

    def fix_numbers(self):
        """いま開いている区分の数字を縦書きの慣行にそろえる（1 桁全角・2 桁以上半角）。"""
        if not self.issue or not self.current_kubun:
            return
        before = self.txt.get("1.0", "end-1c")
        after = core.normalize_numbers(before)
        if before == after:
            self.lbl_status.config(text="数字はそろっています")
            return
        pos = self.txt.index("insert")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", after)
        self.txt.mark_set("insert", pos)
        self.txt.edit_modified(True)
        self.save_current()
        self.lbl_status.config(text=f"{self.current_kubun} の数字をそろえました")

    # ------------------------------------------------------------ 写真

    def open_photo_dir(self):
        if self.issue:
            open_in_explorer(self.issue.photo_dir)

    def open_out_dir(self):
        if self.issue:
            open_in_explorer(self.issue.out_dir)

    def open_attach_dir(self):
        if self.issue:
            open_in_explorer(self.issue.attach_dir)

    def refresh_photos(self):
        for w in self.photo_inner.winfo_children():
            w.destroy()
        self._thumbs.clear()
        self._photo_buttons.clear()
        self.selected_photo = None
        if not self.issue:
            return
        files = self.issue.photo_files()
        if not files:
            ttk.Label(self.photo_inner, text="写真フォルダに写真がありません。\n「写真フォルダを開く」から入れて、\n「写真を読み直す」を押してください。",
                      wraplength=300).grid(row=0, column=0, padx=6, pady=6)
            return
        cols = 3
        for i, path in enumerate(files):
            cell = ttk.Frame(self.photo_inner, padding=3)
            cell.grid(row=i // cols, column=i % cols, sticky="n")
            img = self._thumb(path)
            btn = tk.Button(cell, image=img, text=path.name if img is None else "",
                            compound="top", relief="flat", bd=2, highlightthickness=2,
                            wraplength=THUMB_PX, command=lambda p=path: self.select_photo(p))
            btn.pack()
            ttk.Label(cell, text=path.name, wraplength=THUMB_PX, justify="center").pack()
            self._photo_buttons[path.name] = btn
        self.mark_photo_usage()

    def _thumb(self, path: Path):
        if not THUMB_OK:
            return None
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((THUMB_PX, THUMB_PX))
                tkimg = ImageTk.PhotoImage(im.convert("RGB"))
        except Exception:
            return None
        self._thumbs.append(tkimg)
        return tkimg

    def mark_photo_usage(self):
        """使用済みの写真は緑の枠、未使用は灰色にして見分けられるようにする。"""
        if not self.issue:
            return
        used = self.issue.photo_usage()
        for name, btn in self._photo_buttons.items():
            if name == (self.selected_photo.name if self.selected_photo else None):
                btn.config(highlightbackground="#1E88E5", highlightcolor="#1E88E5")
            elif name in used:
                btn.config(highlightbackground="#43A047", highlightcolor="#43A047")
            else:
                btn.config(highlightbackground="#BDBDBD", highlightcolor="#BDBDBD")

    def select_photo(self, path: Path):
        self.selected_photo = path
        used = self.issue.photo_usage().get(path.name) if self.issue else None
        info = core.photo_info(path)
        note = f"{path.name}"
        if info.width_px:
            note += f"　{info.width_px}×{info.height_px}px（{info.max_print_mm():.0f}mm 幅まで）"
        if used:
            note += "\n使用中: " + "、".join(used)
        self.lbl_photo.config(text=note)
        self.mark_photo_usage()
        self.ent_caption.focus_set()

    def insert_photo(self):
        if not self.issue or not self.current_kubun:
            messagebox.showinfo(APP_NAME, "先に区分を選んでください。")
            return
        if not self.selected_photo:
            messagebox.showinfo(APP_NAME, "右の一覧から写真を選んでください。")
            return
        ref = core.PhotoRef(self.selected_photo.name, self.cmb_size.get() or core.DEFAULT_SIZE,
                            self.ent_caption.get().strip())
        warn = core.photo_info(self.selected_photo).warning_for(ref.width_mm)
        if warn and not messagebox.askyesno(APP_NAME, f"{warn}\n\nこのまま入れますか？"):
            return
        # 空行ならそこに、文字のある行ならその行の次に、【写真】行を 1 行入れる
        line_start = self.txt.index("insert linestart")
        if self.txt.get(line_start, f"{line_start} lineend").strip():
            self.txt.insert(f"{line_start} lineend", "\n" + ref.to_line())
        else:
            self.txt.insert(line_start, ref.to_line())
        self.txt.edit_modified(True)
        self.ent_caption.delete(0, "end")
        self.save_current()
        self.txt.focus_set()

    # ------------------------------------------------------------ 出力

    def build(self):
        if not self.issue:
            messagebox.showinfo(APP_NAME, "先に号フォルダを開いてください。")
            return
        self.save_current()
        try:
            outs, warnings = core.build_all(self.issue)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Word を作れませんでした。\n{e}")
            return
        msg = "できました:\n" + "\n".join(f"・{p.name}" for p in outs)
        if warnings:
            msg += "\n\n確認してください:\n" + "\n".join("・" + w for w in warnings[:15])
            if len(warnings) > 15:
                msg += f"\n…ほか {len(warnings) - 15} 件"
        msg += "\n\n原稿の Word を開きますか？"
        self.lbl_status.config(text="Word を作りました")
        if messagebox.askyesno(APP_NAME, msg):
            open_in_explorer(outs[0])

    # ------------------------------------------------------------ その他

    def show_help(self):
        win = tk.Toplevel(self)
        win.title("使い方")
        win.geometry("640x560")
        t = tk.Text(win, wrap="word", font=TEXT_FONT, padx=12, pady=10)
        t.insert("1.0", HELP)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)

    def on_close(self):
        self.save_current()
        save_settings(self.settings)
        self.destroy()


def main():
    missing = []
    if not core.DOCX_OK:
        missing.append("python-docx")
    if not core.PIL_OK:
        missing.append("Pillow")
    app = App()
    if missing:
        messagebox.showwarning(
            APP_NAME,
            "次の部品が入っていません:\n  " + ", ".join(missing) +
            "\n\nコマンドプロンプトで\n  pip install " + " ".join(missing) +
            "\nを実行してください。\n（python-docx が無いと Word を作れません。Pillow が無いと写真の縮小表示ができません）")
    app.mainloop()


if __name__ == "__main__":
    main()
