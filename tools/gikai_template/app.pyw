"""議会だより 前年同月号 差し込みツール（画面）。

前年の同じ月の号（4月号・7月号・10月号・1月号）を様式にして、
欄ごとに今年の原稿を入れ、Word を作る。インターネットには何も送らない。

画面は 1 つ:
  左   様式の欄の一覧（紙面の順・見出しごと）
  右上 前年の文章（見本。書き換えられない）
  右下 今年の原稿（手で書く／Word・テキストから取り込む）
  下   Word を作る
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core  # noqa: E402
from core import EMPTY, KEEP, NEW, SAME, TABLE, MODE_LABEL  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / "様式"          # 登録した前年の号（4月号.docx など）
SETTINGS = APP_DIR / "設定.json"         # 最後に開いた号のフォルダだけを覚える

STATUS_MARK = {NEW: "✎", KEEP: "・", SAME: "＝", EMPTY: "✕", TABLE: "▦"}

HELP = """議会だより 前年同月号 差し込みツール　使い方

■ はじめに 1 回だけ ― 様式を登録する
　「様式を登録」で、前年の 4 つの号を月ごとに選びます。
　　4月号 ← 第198号　7月号 ← 第199号　10月号 ← 第200号　1月号 ← 第201号
　.doc を選ぶと、このパソコンの Word で .docx に変換して登録します。
　（毎年、発行が済んだ号で登録し直すと、次の年はその号が様式になります）

■ 号ごとに
　1. 「新しい号を作る」― 号数・発行日・月号を入れ、フォルダを作る場所を選ぶ
　2. 左の一覧から欄を選ぶ。右上に前年の文章が出る
　3. 右下に今年の原稿を書く。議員から届いた Word は
　　「Word・テキストを取り込む」でカーソルの位置に入る
　　　・前年の文を少し直すだけなら「↓ 前年の文を写す」を押してから直す
　　　・ふりがなは ｜山田《やまだ》 のように書く
　　　・名前（1字ずつ）の欄は「高橋次郎　議員」のように 1 行で書けばよい
　4. 賛否一覧表は、「別添１：…賛否」の枠を選んで「Excel の賛否表を選ぶ」
　5. 「Word を作る」― 出力フォルダに第○号.docx ができる

■ 欄の状態（一覧の左の印）
　✎ 今年の原稿　　・ 前年のまま（Word では黄色の印が付く）
　＝ 毎号同じ（発行元など。印を付けない）　✕ 空にする　▦ 賛否表

■ 紙面がずれないしくみ
　記事が前年より長く（短く）なると、すぐ後ろの空行を減らして（足して）
　以降の記事の位置を保ちます。空行が足りないときは、どれだけ
　あふれたかを最後に知らせます。仕上げは Word で整えてください。

■ 前年に無い記事を足す
　同じ形の欄を選んで「この欄を複製」。文字枠は 10mm 下にずらして
　複製するので、Word で正しい場所へ動かしてください。
"""


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — 利用者が選んだ出力を開くだけ
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    try:
        SETTINGS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def registered_templates() -> dict[str, Path]:
    return {s: TEMPLATE_DIR / f"{s}.docx" for s in core.SEASONS
            if (TEMPLATE_DIR / f"{s}.docx").exists()}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("議会だより 前年同月号 差し込みツール")
        self.geometry("1200x780")
        self.minsize(980, 620)
        self.issue: core.Issue | None = None
        self.tpl: core.Template | None = None
        self.current: str | None = None
        self._loading = False
        self.mode = tk.StringVar(value=KEEP)
        self.only_todo = tk.BooleanVar(value=False)
        self.mark_keep = tk.BooleanVar(value=True)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        last = load_settings().get("last_issue")
        if last and Path(last, core.INFO_NAME).exists():
            self.after(100, lambda: self.open_issue(Path(last)))

    # ------------------------------------------------------------ 画面の組み立て

    def _build(self) -> None:
        font = ("Meiryo UI", 10) if sys.platform == "win32" else ("", 12)
        self.option_add("*Font", font)
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Button(top, text="新しい号を作る", command=self.new_issue).pack(side="left")
        ttk.Button(top, text="号を開く", command=self.pick_issue).pack(side="left", padx=4)
        ttk.Button(top, text="様式を登録", command=self.register_templates).pack(side="left")
        self.title_lbl = ttk.Label(top, text="号を作るか、開いてください", font=(font[0], 12, "bold"))
        self.title_lbl.pack(side="left", padx=16)
        ttk.Button(top, text="使い方", command=self.show_help).pack(side="right")

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6)

        left = ttk.Frame(pane)
        pane.add(left, weight=2)
        ttk.Checkbutton(left, text="まだ前年のままの欄だけ出す", variable=self.only_todo,
                        command=self.refresh_tree).pack(anchor="w")
        self.tree = ttk.Treeview(left, columns=("kind", "text"), show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="状態")
        self.tree.heading("kind", text="種類")
        self.tree.heading("text", text="前年の文章")
        self.tree.column("#0", width=150, stretch=False)
        self.tree.column("kind", width=90, stretch=False)
        self.tree.column("text", width=260)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = ttk.Frame(pane, padding=(8, 0, 0, 0))
        pane.add(right, weight=3)
        self.slot_lbl = ttk.Label(right, text="", font=(font[0], 11, "bold"))
        self.slot_lbl.pack(anchor="w")
        ttk.Label(right, text="前年の文章（見本・書き換えられません）").pack(anchor="w", pady=(4, 0))
        self.old = tk.Text(right, height=9, wrap="char", background="#f3f3f3")
        self.old.pack(fill="x")
        self.old.configure(state="disabled")

        row = ttk.Frame(right)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="↓ 前年の文を写す", command=self.copy_old).pack(side="left")
        ttk.Button(row, text="Word・テキストを取り込む（カーソル位置）",
                   command=self.import_file).pack(side="left", padx=4)
        ttk.Button(row, text="Excel の賛否表を選ぶ", command=self.pick_vote).pack(side="left")

        ttk.Label(right, text="今年の原稿").pack(anchor="w")
        self.new = tk.Text(right, height=14, wrap="char", undo=True)
        self.new.pack(fill="both", expand=True)
        self.new.bind("<<Modified>>", self.on_modified)
        self.count_lbl = ttk.Label(right, text="")
        self.count_lbl.pack(anchor="w")

        modes = ttk.LabelFrame(right, text="この欄をどうするか", padding=4)
        modes.pack(fill="x", pady=4)
        for m in (NEW, KEEP, SAME, EMPTY, TABLE):
            ttk.Radiobutton(modes, text=MODE_LABEL[m], value=m, variable=self.mode,
                            command=self.on_mode).pack(side="left", padx=4)
        row2 = ttk.Frame(right)
        row2.pack(fill="x")
        ttk.Button(row2, text="この欄を複製（前年に無い記事を足す）",
                   command=self.duplicate).pack(side="left")
        ttk.Button(row2, text="この枠を消す", command=self.remove_box).pack(side="left", padx=4)

        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Word を作る", command=self.build).pack(side="left")
        ttk.Button(bottom, text="出力フォルダを開く", command=self.open_out).pack(side="left", padx=4)
        ttk.Checkbutton(bottom, text="前年のままの欄に黄色の印を付ける",
                        variable=self.mark_keep).pack(side="left", padx=12)
        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="left", padx=12)

    # ------------------------------------------------------------ 号

    def new_issue(self) -> None:
        tpls = registered_templates()
        if not tpls:
            messagebox.showinfo("様式がありません",
                                "先に「様式を登録」で、前年の号（4月号・7月号・10月号・1月号）を登録してください。")
            return
        d = NewIssueDialog(self, list(tpls))
        if not d.result:
            return
        gou, hakkoubi, season = d.result
        parent = filedialog.askdirectory(title="号のフォルダを作る場所を選んでください")
        if not parent:
            return
        try:
            issue = core.Issue.create(parent, gou, hakkoubi, season, tpls[season])
        except (OSError, ValueError) as e:
            messagebox.showerror("号を作れませんでした", str(e))
            return
        self.open_issue(issue.folder)

    def pick_issue(self) -> None:
        folder = filedialog.askdirectory(title="号のフォルダ（第○号）を選んでください")
        if folder:
            self.open_issue(Path(folder))

    def open_issue(self, folder: Path) -> None:
        self.save_current()
        try:
            self.issue = core.Issue.open(folder)
            self.tpl = self.issue.load_template()
        except (OSError, ValueError) as e:
            messagebox.showerror("開けませんでした", str(e))
            return
        i = self.issue
        self.title_lbl.config(text=f"第{i.gou}号　{i.season}　{i.hakkoubi}")
        s = load_settings()
        s["last_issue"] = str(folder)
        save_settings(s)
        self.current = None
        self.refresh_tree()

    # ------------------------------------------------------------ 一覧

    def refresh_tree(self) -> None:
        if not self.tpl:
            return
        self.tree.delete(*self.tree.get_children())
        groups: dict[str, str] = {}
        todo = self.only_todo.get()
        for s in self.tpl.slots():
            e = self.issue.entries.get(s.id) or core.Entry()
            if todo and e.mode != KEEP:
                continue
            if s.group not in groups:
                groups[s.group] = self.tree.insert("", "end", text=s.group, open=True)
            label = f"{STATUS_MARK[e.mode]} {s.id}" + ("（複製）" if s.copy_of else "")
            self.tree.insert(groups[s.group], "end", iid=s.id, text=label,
                             values=(s.kind_label, s.short))
        if self.current and self.tree.exists(self.current):
            self.tree.selection_set(self.current)
            self.tree.see(self.current)
        self.update_status()

    def update_status(self) -> None:
        if not self.tpl:
            return
        counts = {m: 0 for m in STATUS_MARK}
        for s in self.tpl.slots():
            counts[(self.issue.entries.get(s.id) or core.Entry()).mode] += 1
        self.status.config(text=f"全 {len(self.tpl.order)} 欄　今年の原稿 {counts[NEW]}　"
                                f"前年のまま {counts[KEEP]}　毎号同じ {counts[SAME]}　"
                                f"空 {counts[EMPTY]}　表 {counts[TABLE]}")

    def mark_row(self, sid: str) -> None:
        if self.tree.exists(sid):
            s = self.tpl.refs[sid].slot
            e = self.issue.entries.get(sid) or core.Entry()
            self.tree.item(sid, text=f"{STATUS_MARK[e.mode]} {sid}" + ("（複製）" if s.copy_of else ""))
        self.update_status()

    # ------------------------------------------------------------ 欄

    def on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel or sel[0] not in self.tpl.refs:
            return
        self.save_current()
        sid = sel[0]
        self.current = sid
        s = self.tpl.refs[sid].slot
        e = self.issue.entry(sid)
        self._loading = True
        size = f"　枠 {s.box_mm[0]:.0f}×{s.box_mm[1]:.0f}mm" if s.box_mm else ""
        self.slot_lbl.config(text=f"{s.group} ／ {s.kind_label}{size}")
        self.old.configure(state="normal")
        self.old.delete("1.0", "end")
        self.old.insert("1.0", s.old_text)
        self.old.configure(state="disabled")
        self.new.delete("1.0", "end")
        self.new.insert("1.0", e.text)
        self.new.edit_reset()
        self.new.edit_modified(False)
        self.mode.set(e.mode)
        self._loading = False
        self.update_count()

    def save_current(self) -> None:
        if not (self.issue and self.current and self.current in self.tpl.refs):
            return
        e = self.issue.entry(self.current)
        e.text = self.new.get("1.0", "end-1c")
        e.mode = self.mode.get()
        try:
            self.issue.save()
        except OSError as ex:
            messagebox.showerror("保存できませんでした", str(ex))

    def on_modified(self, _event=None) -> None:
        if not self.new.edit_modified():
            return
        self.new.edit_modified(False)
        if self._loading or not self.current:
            return
        # 書き始めたら「今年の原稿」に切り替える（前年のままと書いた文が食い違わないように）
        if self.mode.get() in (KEEP, SAME, EMPTY) and self.new.get("1.0", "end-1c").strip():
            self.mode.set(NEW)
            self.on_mode()
        self.update_count()

    def on_mode(self) -> None:
        if not self.current:
            return
        e = self.issue.entry(self.current)
        e.mode = self.mode.get()
        e.text = self.new.get("1.0", "end-1c")
        self.mark_row(self.current)

    def update_count(self) -> None:
        if not self.current:
            self.count_lbl.config(text="")
            return
        s = self.tpl.refs[self.current].slot
        text = self.new.get("1.0", "end-1c")
        n_new = sum(core.text_width(t, s.vertical) for t in text.split("\n"))
        n_old = sum(core.text_width(t, s.vertical) for t in s.old_text.split("\n"))
        diff = n_new - n_old
        sign = "＋" if diff > 0 else "－" if diff < 0 else "±"
        msg = f"今年 {n_new:.0f} 字　前年 {n_old:.0f} 字（{sign}{abs(diff):.0f} 字）"
        if s.kind == "body" and s.vertical:
            per = self.tpl.geometry(s.section).chars_per_line(s.size_pt if s.size_pt < 13 else 11)
            msg += f"　／ 1 行 {per} 字の紙面で およそ {diff / per:+.0f} 行"
        self.count_lbl.config(text=msg)

    def copy_old(self) -> None:
        if not self.current:
            return
        s = self.tpl.refs[self.current].slot
        if self.new.get("1.0", "end-1c").strip() and not messagebox.askyesno(
                "写す", "今年の原稿に書いてある文を、前年の文章で置き換えます。よろしいですか？"):
            return
        self.new.delete("1.0", "end")
        self.new.insert("1.0", s.old_text)
        self.mode.set(NEW)
        self.on_mode()

    def import_file(self) -> None:
        if not self.current:
            messagebox.showinfo("欄を選んでください", "左の一覧から、取り込む先の欄を選んでください。")
            return
        path = filedialog.askopenfilename(
            title="原稿を選んでください",
            filetypes=[("原稿", "*.docx *.doc *.txt"), ("すべて", "*.*")])
        if not path:
            return
        try:
            text = core.import_manuscript(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("取り込めませんでした", str(e))
            return
        self.new.insert("insert", text)
        self.new.focus_set()

    def pick_vote(self) -> None:
        if not self.issue:
            return
        path = filedialog.askopenfilename(title="賛否一覧表の Excel を選んでください",
                                          filetypes=[("Excel", "*.xlsx *.xlsm"), ("すべて", "*.*")])
        if not path:
            return
        try:
            vote = core.read_vote_table(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("読めませんでした", str(e))
            return
        # 号のフォルダの「別添」に写しておく（印刷所に渡すものが 1 か所にそろうように）
        dst = self.issue.folder / core.ATTACH_DIR / Path(path).name
        try:
            if Path(path).resolve() != dst.resolve():
                dst.parent.mkdir(exist_ok=True)
                dst.write_bytes(Path(path).read_bytes())
        except OSError as e:
            messagebox.showerror("写せませんでした", str(e))
            return
        self.issue.vote_xlsx = f"{core.ATTACH_DIR}/{dst.name}"
        msg = f"{vote.summary()}\n\n"
        if self.current and self.tpl.refs[self.current].slot.kind == "box":
            self.mode.set(TABLE)
            self.on_mode()
            msg += "いま選んでいる枠に、この表を入れます。"
        else:
            msg += "表を入れる枠（「別添１：…賛否」など）を選んで、「賛否表を入れる」を選んでください。"
        self.issue.save()
        messagebox.showinfo("賛否表を読みました", msg)

    def duplicate(self) -> None:
        if not self.current:
            return
        self.save_current()
        src = self.current
        new_id = self.issue.next_copy_id(src)
        try:
            self.tpl.duplicate(src, new_id)
        except ValueError as e:
            messagebox.showerror("複製できませんでした", str(e))
            return
        self.issue.copies.append({"src": src, "id": new_id})
        self.issue.save()
        self.current = new_id
        self.refresh_tree()
        self.on_select()

    def remove_box(self) -> None:
        if not self.current:
            return
        s = self.tpl.refs[self.current].slot
        if s.kind != "box":
            messagebox.showinfo("消せません", "消せるのは文字枠だけです。本文の記事は「空にする」を選んでください"
                                "（空いた行は空行で埋めて、以降の位置を保ちます）。")
            return
        if not messagebox.askyesno("枠を消す", f"「{s.short}」の枠を、できあがる Word から消します。\n"
                                   "様式や前年の号は変わりません。あとで戻すには、号のフォルダの"
                                   f"{core.DATA_NAME} から消した記録を外します。よろしいですか？"):
            return
        self.tpl.remove_box(self.current)
        self.issue.removed.append(self.current)
        self.issue.save()
        self.current = None
        self.refresh_tree()

    # ------------------------------------------------------------ Word を作る

    def build(self) -> None:
        if not self.issue:
            return
        self.save_current()
        try:
            rep = self.issue.build(mark_keep=self.mark_keep.get())
        except (OSError, ValueError) as e:
            messagebox.showerror("Word を作れませんでした", str(e))
            return
        ReportWindow(self, rep)

    def open_out(self) -> None:
        if self.issue:
            out = self.issue.folder / core.OUT_DIR
            out.mkdir(exist_ok=True)
            open_path(out)

    # ------------------------------------------------------------ 様式の登録

    def register_templates(self) -> None:
        RegisterDialog(self)

    def show_help(self) -> None:
        w = tk.Toplevel(self)
        w.title("使い方")
        t = tk.Text(w, width=78, height=36, wrap="char")
        t.insert("1.0", HELP)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)

    def on_close(self) -> None:
        self.save_current()
        self.destroy()


class NewIssueDialog(tk.Toplevel):
    def __init__(self, master: App, seasons: list[str]) -> None:
        super().__init__(master)
        self.title("新しい号を作る")
        self.result = None
        self.transient(master)
        f = ttk.Frame(self, padding=12)
        f.pack()
        self.gou = tk.StringVar()
        self.date = tk.StringVar()
        self.season = tk.StringVar(value=seasons[0])
        ttk.Label(f, text="号数（数字）").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.gou, width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(f, text="発行日（例: 令和９年４月30日）").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.date, width=24).grid(row=1, column=1, sticky="w")
        ttk.Label(f, text="月号（様式にする前年の号）").grid(row=2, column=0, sticky="w")
        box = ttk.Frame(f)
        box.grid(row=2, column=1, sticky="w")
        for s in seasons:
            ttk.Radiobutton(box, text=f"{s}（{core.SEASON_NOTE[s]}）", value=s,
                            variable=self.season).pack(anchor="w")
        ttk.Button(f, text="作る", command=self.ok).grid(row=3, column=1, sticky="e", pady=8)
        self.grab_set()
        self.wait_window()

    def ok(self) -> None:
        if not self.gou.get().strip():
            messagebox.showinfo("号数", "号数を入れてください。", parent=self)
            return
        self.result = (self.gou.get(), self.date.get(), self.season.get())
        self.destroy()


class RegisterDialog(tk.Toplevel):
    """前年の 4 つの号を月ごとに登録する。.doc なら Word で .docx に変換する。"""

    def __init__(self, master: App) -> None:
        super().__init__(master)
        self.title("様式を登録")
        self.transient(master)
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="前年の号を、月ごとに選んでください（.docx または .doc）。\n"
                          "選んだファイルはツールの「様式」フォルダに写します（元のファイルはそのまま）。"
                  ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.labels = {}
        have = registered_templates()
        for k, s in enumerate(core.SEASONS, start=1):
            ttk.Label(f, text=s, width=7).grid(row=k, column=0, sticky="w")
            lbl = ttk.Label(f, text="登録済み" if s in have else "（まだ）", width=24)
            lbl.grid(row=k, column=1, sticky="w")
            self.labels[s] = lbl
            ttk.Button(f, text="選ぶ…", command=lambda s=s: self.pick(s)).grid(row=k, column=2)
        ttk.Button(f, text="閉じる", command=self.destroy).grid(row=9, column=2, pady=8)
        self.grab_set()

    def pick(self, season: str) -> None:
        path = filedialog.askopenfilename(parent=self, title=f"{season}の様式にする前年の号",
                                          filetypes=[("Word", "*.docx *.doc")])
        if not path:
            return
        src = Path(path)
        dst = TEMPLATE_DIR / f"{season}.docx"
        TEMPLATE_DIR.mkdir(exist_ok=True)
        try:
            if src.suffix.lower() == ".doc":
                self.config(cursor="watch")
                self.update()
                core.convert_doc_with_word(src, dst)
            else:
                dst.write_bytes(src.read_bytes())
            n = len(core.Template(dst).order)
        except (OSError, ValueError) as e:
            messagebox.showerror("登録できませんでした", str(e), parent=self)
            return
        finally:
            self.config(cursor="")
        self.labels[season].config(text=f"{src.name}（{n} 欄）")


class ReportWindow(tk.Toplevel):
    def __init__(self, master: App, rep: core.Report) -> None:
        super().__init__(master)
        self.title("Word を作りました")
        t = tk.Text(self, width=96, height=30, wrap="char")
        t.insert("1.0", rep.text())
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        row = ttk.Frame(self, padding=6)
        row.pack(fill="x")
        if rep.out:
            ttk.Button(row, text="Word を開く", command=lambda: open_path(rep.out)).pack(side="left")
        ttk.Button(row, text="閉じる", command=self.destroy).pack(side="right")


if __name__ == "__main__":
    App().mainloop()
