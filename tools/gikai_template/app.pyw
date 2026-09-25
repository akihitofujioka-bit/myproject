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
import flow  # noqa: E402
from core import EMPTY, KEEP, NEW, SAME, TABLE, MODE_LABEL  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / "様式"          # 登録した前年の号（4月号.docx など）
SETTINGS = APP_DIR / "設定.json"         # 最後に開いた号のフォルダだけを覚える

AUTO_KIND = "（自動で見分ける）"
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
　　　・見出しと本文がいくつも入った原稿は、最初の見出しを入れる欄を選んで
　　　　「Word を取り込んで、見出しと本文を欄に振り分ける」。確認の画面で
　　　　見出し／本文と入れる欄を確かめて（直して）から入れる
　　　・前年の文を少し直すだけなら「↓ 前年の文を写す」を押してから直す
　　　・ふりがなは ｜山田《やまだ》 のように書く
　　　・名前（1字ずつ）の欄は「高橋次郎　議員」のように 1 行で書けばよい
　4. 賛否一覧表は、「別添１：…賛否」の枠を選んで「Excel の賛否表を選ぶ」
　5. 「Word を作る」― 出力フォルダに第○号.docx ができる

■ 原稿から組み直す区分（行政報告・審議したこと・委員会報告・一般質問・特集）
　記事の数や議員の人数が毎回違う区分は、「原稿を選ぶ」で原稿（gikai_simple の区分の .txt や
　Word）を選ぶと、前年の欄（⇄ の印）は使わず、前年の書式の部品で必要な数だけ組み直します。
　「読み取りを確かめる・直す」で、見出し・名前・本文・写真の見分けを確かめて直せます。
　・行政報告 … ■ を付けた行か、本文より短い行が見出し
　・審議したこと … 「人事」「条例」「予算」などの区分の行、「◎議案名」「質疑」「問」「答」
　・委員会報告 … 委員会名の行、「委員長　山田太郎」の行、日時、課長名、本文
　・一般質問 … 「山田太郎議員」だけの行で 1 人ぶんが始まり、「質問」の直前の短い行が題
　・特集 … 「山田花子さん」の行で 1 人ぶんが始まり、前年の人ごとの枠に順に入る

■ 欄の状態（一覧の左の印）
　✎ 今年の原稿　　・ 前年のまま（Word では黄色の印が付く）
　＝ 毎号同じ（発行元など。印を付けない）　✕ 空にする　▦ 賛否表
　⇄ 原稿から組み直す区分の欄（この欄には差し込まない）

■ 紙面がずれないしくみ
　記事が前年より長く（短く）なると、すぐ後ろの空行を減らして（足して）
　以降の記事の位置を保ちます。空行が足りないときは、どれだけ
　あふれたかを最後に知らせます。仕上げは Word で整えてください。

■ 読み取りを直す（種類・分ける・つなげる）
　ツールは空行を区切りにして欄に分け、字の大きさなどで種類を見分けます。
　違っていたら「読み取りを直す・欄を組み替える」で直します。
　・種類 … 本文／見出し／名前（1字ずつ）から選び直す。
　　　見出し … 欄の中でいちばん大きい字の書式で今年の原稿を入れる
　　　名前（1字ずつ） … 1 行で書いた名前を 1 字ずつの行に組み直す
　　　（文字枠の縦・横は Word の枠で決まるので変えられません）
　・分ける … 見出しと本文、2 つの記事が 1 つの欄になっていたら、
　　前年の文章の「後ろの欄の 1 行目にしたい行」の行頭にカーソルを置いて
　　「カーソルの行から後ろを別の欄に分ける」
　・つなげる … 1 つの記事が 2 つの欄に分かれていたら、前の欄を選んで
　　「次の欄とつなげる」（間の空行は記事のすぐ後ろへ回ります）
　・どれも「組み替えを1つ戻す」で、新しいものから順に取り消せます

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
        self.flow_ids: dict[str, str] = {}  # 原稿から組み直す欄 → 区分
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

        ip = ttk.LabelFrame(self, text="原稿から組み直す区分（人数・記事の数が毎回違うもの。"
                                       "原稿を選ぶと前年の欄は使わず、前年の書式の部品で組み直す）",
                            padding=4)
        ip.pack(fill="x", padx=6)
        self.flow_lbl: dict[str, ttk.Label] = {}
        for r, key in enumerate(flow.FLOW_KEYS):
            ttk.Label(ip, text=key, width=10).grid(row=r, column=0, sticky="w")
            ttk.Button(ip, text="原稿を選ぶ…", command=lambda k=key: self.pick_flow(k)
                       ).grid(row=r, column=1, padx=2)
            ttk.Button(ip, text="読み取りを確かめる・直す", command=lambda k=key: self.check_flow(k)
                       ).grid(row=r, column=2, padx=2)
            ttk.Button(ip, text="組み直さない", command=lambda k=key: self.clear_flow(k)
                       ).grid(row=r, column=3, padx=2)
            lbl = ttk.Label(ip, text="")
            lbl.grid(row=r, column=4, sticky="w", padx=8)
            self.flow_lbl[key] = lbl

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
        ttk.Label(right, text="前年の文章（見本・書き換えられません。分ける位置はここにカーソルを置く）"
                  ).pack(anchor="w", pady=(4, 0))
        self.old = tk.Text(right, height=9, wrap="char", background="#f3f3f3")
        self.old.pack(fill="x")
        # 書き換えはさせないが、分ける位置を選べるようにカーソルは置けるようにする
        # （state="disabled" にするとクリックしてもカーソルが動かない）
        self.old.bind("<Key>", self._readonly_key)
        for ev in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<Button-2>"):
            self.old.bind(ev, lambda e: "break")

        row = ttk.Frame(right)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="↓ 前年の文を写す", command=self.copy_old).pack(side="left")
        ttk.Button(row, text="Word・テキストを取り込む（カーソル位置）",
                   command=self.import_file).pack(side="left", padx=4)
        ttk.Button(row, text="Excel の賛否表を選ぶ", command=self.pick_vote).pack(side="left")
        row_b = ttk.Frame(right)
        row_b.pack(fill="x", pady=(0, 4))
        ttk.Button(row_b, text="Word を取り込んで、見出しと本文を欄に振り分ける（この欄から後ろへ）",
                   command=self.distribute).pack(side="left")

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
        fix = ttk.LabelFrame(right, text="読み取りを直す・欄を組み替える", padding=4)
        fix.pack(fill="x")
        row2 = ttk.Frame(fix)
        row2.pack(fill="x")
        ttk.Label(row2, text="種類").pack(side="left")
        self.kind = tk.StringVar()
        self.kind_box = ttk.Combobox(row2, textvariable=self.kind, state="readonly", width=16,
                                     values=(AUTO_KIND,) + core.KIND_CHOICES)
        self.kind_box.pack(side="left", padx=(2, 12))
        self.kind_box.bind("<<ComboboxSelected>>", self.on_kind)
        ttk.Button(row2, text="カーソルの行から後ろを別の欄に分ける",
                   command=self.split).pack(side="left")
        ttk.Button(row2, text="次の欄とつなげる", command=self.merge).pack(side="left", padx=4)
        row3 = ttk.Frame(fix)
        row3.pack(fill="x", pady=(4, 0))
        ttk.Button(row3, text="この欄を複製（前年に無い記事を足す）",
                   command=self.duplicate).pack(side="left")
        ttk.Button(row3, text="この枠を消す", command=self.remove_box).pack(side="left", padx=4)
        ttk.Button(row3, text="組み替えを1つ戻す", command=self.undo_op).pack(side="left")

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
        self.refresh_flows()

    # ------------------------------------------------------------ 原稿から組み直す区分

    def refresh_flows(self) -> None:
        """区分ごとの原稿の状態を表示し、一覧で「組み直す」欄に印を付け直す。"""
        i = self.issue
        self.flow_ids = {}
        for key in flow.FLOW_KEYS:
            src = i.flow_source(key) if i else ""
            if not src:
                self.flow_lbl[key].config(text="（原稿を選ぶと組み直します。選ばなければ前年の欄に差し込みます）")
                continue
            for sid in flow.region_slot_ids(self.tpl, key):
                self.flow_ids[sid] = key
            try:
                _, _, warns, summ = i.flow_read(key)
                text = f"{Path(src).name}：{summ}"
                if warns:
                    text += f"　気になる点 {len(warns)} か所（「読み取りを確かめる」で見られます）"
            except (OSError, ValueError) as e:
                text = f"{Path(src).name} を読めません: {e}"
            self.flow_lbl[key].config(text=text)
        self.refresh_tree()

    def pick_flow(self, key: str) -> None:
        if not self.issue:
            return
        path = filedialog.askopenfilename(
            title=f"{key}の原稿（gikai_simple の区分の .txt や Word）",
            filetypes=[("原稿", "*.txt *.docx *.doc"), ("すべて", "*.*")])
        if not path:
            return
        self.save_current()
        self.issue.set_flow_source(key, path)
        self.issue.save()
        self.refresh_flows()
        self.check_flow(key)

    def check_flow(self, key: str) -> None:
        i = self.issue
        if not (i and i.flow_source(key)):
            messagebox.showinfo(key, f"先に{key}の「原稿を選ぶ」で原稿を選んでください。")
            return
        try:
            lines, _, _, _ = i.flow_read(key)
        except (OSError, ValueError) as e:
            messagebox.showerror("読めませんでした", str(e))
            return
        d = FlowDialog(self, key, Path(i.flow_source(key)).name, lines)
        if d.result is not None:
            i.flows.setdefault(key, {})["kinds"] = d.result
            i.save()
            self.refresh_flows()

    def clear_flow(self, key: str) -> None:
        if not (self.issue and self.issue.flow_source(key)):
            return
        if not messagebox.askyesno(
                "組み直さない", f"{key}を原稿から組み直すのをやめ、前年の欄に差し込む形に戻します。\n"
                "（原稿のファイルと、直した行の種類の記録は消えません。もう一度選べば戻せます）"):
            return
        self.issue.set_flow_source(key, "")
        self.issue.save()
        self.refresh_flows()

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
            if s.id in self.flow_ids:
                label = f"⇄ {s.id}（{self.flow_ids[s.id]}を組み直す）"
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
            text = f"{STATUS_MARK[e.mode]} {sid}" + ("（複製）" if s.copy_of else "")
            if sid in self.flow_ids:
                text = f"⇄ {sid}（{self.flow_ids[sid]}を組み直す）"
            self.tree.item(sid, text=text)
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
        self.old.delete("1.0", "end")
        self.old.insert("1.0", s.old_text)
        self.old.mark_set("insert", "1.0")
        self.kind.set(s.kind_override or AUTO_KIND)
        self.kind_box.configure(state="disabled" if s.kind == "box" else "readonly")
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

    def distribute(self) -> None:
        """原稿を見出しと本文のまとまりに分けて、選んだ欄から後ろの欄へ振り分ける。"""
        if not self.current:
            messagebox.showinfo("欄を選んでください",
                                "左の一覧から、原稿の最初の見出し（または本文）を入れる欄を選んでください。")
            return
        path = filedialog.askopenfilename(
            title="振り分ける原稿を選んでください",
            filetypes=[("原稿", "*.docx *.doc *.txt"), ("すべて", "*.*")])
        if not path:
            return
        try:
            blocks = core.split_manuscript(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("取り込めませんでした", str(e))
            return
        if not blocks:
            messagebox.showinfo("取り込めませんでした", "原稿に文字が見つかりませんでした。")
            return
        self.save_current()
        d = DistributeDialog(self, Path(path).name, blocks, self.tpl.slots(), self.current)
        if not d.result:
            return
        plan: dict[str, list[str]] = {}
        for block, sid in d.result:
            if sid:
                plan.setdefault(sid, []).append(block.text)
        busy = [sid for sid in plan
                if (e := self.issue.entries.get(sid)) and e.mode == NEW and e.text.strip()]
        if busy:
            names = "\n".join(f"・{self.tpl.refs[i].slot.short}" for i in busy[:15])
            if not messagebox.askyesno(
                    "上書きの確認",
                    f"次の {len(busy)} 欄には、もう今年の原稿が書いてあります。\n{names}\n\n"
                    "取り込んだ原稿で置き換えてよろしいですか？（「いいえ」なら何も変えません）"):
                return
        for sid, texts in plan.items():
            e = self.issue.entry(sid)
            e.text = "\n".join(texts)
            e.mode = NEW
        self.issue.save()
        first = next(iter(plan), None)
        self.current = None
        self.refresh_tree()
        if first:
            self.tree.selection_set(first)
            self.tree.see(first)
            self.on_select()
        messagebox.showinfo("振り分けました", f"{len(plan)} 欄に入れました。一覧の ✎ の欄を確かめてください。")

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

    # ------------------------------------------------------------ 欄の組み替え

    def _readonly_key(self, event) -> str | None:
        # 矢印・Home/End・ページ送り・コピー・すべて選択だけ通す
        if event.keysym in ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"):
            return None
        if (event.state & 0x4 or event.state & 0x8) and event.keysym.lower() in ("c", "a"):
            return None
        return "break"

    def _apply_op(self, op: dict, select: str, title: str) -> None:
        """組み替えを記録し、様式を開き直して一覧に反映する。"""
        self.issue.ops.append(op)
        self._reload(select, title)

    def _reload(self, select: str | None, title: str) -> None:
        try:
            self.tpl = self.issue.load_template()
        except (OSError, ValueError) as e:
            messagebox.showerror(title, str(e))
            return
        self.issue.save()
        # 画面の欄を先に外しておく（選び直したときに、前の欄の文が新しい欄へ保存されないように）
        self.current = None
        self.refresh_tree()
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)
            self.on_select()

    def on_kind(self, _event=None) -> None:
        if not self.current:
            return
        label = self.kind.get()
        try:
            self.tpl.set_kind(self.current, "" if label == AUTO_KIND else label)
        except ValueError as e:
            messagebox.showinfo("種類を変えられません", str(e))
            return
        if label == AUTO_KIND:
            self.issue.kinds.pop(self.current, None)
        else:
            self.issue.kinds[self.current] = label
        self.issue.save()
        s = self.tpl.refs[self.current].slot
        self.tree.item(self.current, values=(s.kind_label, s.short))
        self.slot_lbl.config(text=f"{s.group} ／ {s.kind_label}")

    def split(self) -> None:
        if not self.current:
            return
        ref = self.tpl.refs[self.current]
        line = int(self.old.index("insert").split(".")[0]) - 1
        # 画面の行 → 段落の番号（段落の中の改行も 1 行と数える）
        at, seen = None, 0
        for k, p in enumerate(ref.paras):
            if seen == line and k > 0:
                at = k
                break
            seen += core.para_text(p).count("\n") + 1
        if at is None:
            messagebox.showinfo("分ける位置", "前年の文章の中で、分けたい行（後ろの欄の 1 行目になる行）の"
                                "行頭にカーソルを置いてから押してください。\n"
                                "1 行目や、段落の途中の行では分けられません。")
            return
        self.save_current()
        sid = self.current
        new_id = self.issue.new_id(sid, "/", self.tpl)
        self._apply_op({"op": "split", "id": sid, "at": at, "new": new_id}, new_id,
                       "分けられませんでした")

    def merge(self) -> None:
        if not self.current:
            return
        self.save_current()
        sid = self.current
        ref = self.tpl.refs[sid]
        idx = self.tpl.order.index(sid)
        nxt = next((i for i in self.tpl.order[idx + 1:] if self.tpl.refs[i].parent is ref.parent), None)
        if nxt is None:
            messagebox.showinfo("つなげられません", "後ろに、同じ入れ物（本文どうし・同じ枠の中どうし）の欄がありません。")
            return
        other = self.tpl.refs[nxt].slot
        if not messagebox.askyesno(
                "次の欄とつなげる",
                f"「{ref.slot.short}」と、次の「{other.short}」を 1 つの欄にします。\n\n"
                "・間の空行（写真の場所など）は、つなげた記事のすぐ後ろへ回ります\n"
                "・次の欄に今年の原稿を書いていた場合は、この欄の原稿の後ろにつなげます\n"
                "・「組み替えを1つ戻す」で元に戻せます（つなげた原稿は戻りません）\n\n"
                "つなげてよろしいですか？"):
            return
        try:
            self.tpl.merge(sid)
        except ValueError as e:
            messagebox.showerror("つなげられませんでした", str(e))
            self._reload(sid, "つなげられませんでした")
            return
        e_other = self.issue.entries.get(nxt)
        if e_other and e_other.text.strip():
            e = self.issue.entry(sid)
            e.text = (e.text.rstrip("\n") + "\n" + e_other.text) if e.text.strip() else e_other.text
            e.mode = NEW
        self._apply_op({"op": "merge", "id": sid, "with": nxt}, sid, "つなげられませんでした")

    def undo_op(self) -> None:
        if not self.issue or not self.issue.ops:
            messagebox.showinfo("戻す", "戻せる組み替えはありません。")
            return
        op = self.issue.ops[-1]
        what = {"copy": "複製", "split": "分けた", "merge": "つなげた", "remove": "枠を消した"}.get(
            op.get("op"), op.get("op"))
        if not messagebox.askyesno("組み替えを1つ戻す", f"最後の組み替え（{what}: {op.get('id')}）を"
                                   "取り消します。よろしいですか？"):
            return
        self.save_current()
        self.issue.ops.pop()
        self._reload(op.get("id") if op.get("op") != "copy" else op.get("src"), "戻せませんでした")

    def duplicate(self) -> None:
        if not self.current:
            return
        self.save_current()
        src = self.current
        new_id = self.issue.new_id(src, "+", self.tpl)
        self._apply_op({"op": "copy", "src": src, "id": new_id}, new_id, "複製できませんでした")

    def remove_box(self) -> None:
        if not self.current:
            return
        s = self.tpl.refs[self.current].slot
        if s.kind != "box":
            messagebox.showinfo("消せません", "消せるのは文字枠だけです。本文の記事は「空にする」を選んでください"
                                "（空いた行は空行で埋めて、以降の位置を保ちます）。")
            return
        if not messagebox.askyesno("枠を消す", f"「{s.short}」の枠を、できあがる Word から消します。\n"
                                   "様式や前年の号は変わりません。「組み替えを1つ戻す」で元に戻せます。"
                                   "よろしいですか？"):
            return
        self.save_current()
        self._apply_op({"op": "remove", "id": self.current}, None, "消せませんでした")

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


class DistributeDialog(tk.Toplevel):
    """取り込んだ原稿のまとまりと、入れる欄の対応を確かめて直す画面。"""

    NONE = "（入れない）"

    def __init__(self, master: App, name: str, blocks: list, slots: list, start: str) -> None:
        super().__init__(master)
        self.title("見出しと本文を欄に振り分ける")
        self.geometry("1050x620")
        self.transient(master)
        self.result = None
        self.blocks = blocks
        self.slots = slots
        ids = [s.id for s in slots]
        self.start = start
        # 選べる欄は、選んだ欄から後ろだけ（前へ入れることはまずない）
        self.choices = [self.NONE] + [f"{s.id}　{s.kind_label}　{s.short}"
                                      for s in slots[ids.index(start):]]
        self.by_label = {c: c.split("　")[0] for c in self.choices[1:]}

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=f"{name} を {len(blocks)} のまとまりに分けました。"
                            "見出しか本文か・入れる欄を確かめて、違っていたら直してください。\n"
                            "同じ欄を 2 つ以上選ぶと、つなげて入れます。種類を直したら「振り分け直す」で"
                            "欄の案を作り直せます。", justify="left").pack(anchor="w")

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=8)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        for c, head in enumerate(("種類", "原稿のまとまり", "入れる欄")):
            ttk.Label(self.inner, text=head, font=("", 10, "bold")).grid(row=0, column=c, sticky="w", padx=4)
        self.kinds: list[tk.StringVar] = []
        self.targets: list[tk.StringVar] = []
        for i, b in enumerate(blocks, start=1):
            kv = tk.StringVar(value=b.kind)
            ttk.Combobox(self.inner, textvariable=kv, values=(core.HEADING, core.BODY),
                         state="readonly", width=6).grid(row=i, column=0, padx=4, pady=2, sticky="n")
            txt = tk.Text(self.inner, width=52, height=min(4, b.text.count("\n") + 1 + len(b.text) // 52),
                          wrap="char", background="#f7f7f7")
            txt.insert("1.0", b.text)
            txt.bind("<Key>", lambda e: "break")
            txt.grid(row=i, column=1, padx=4, pady=2, sticky="w")
            tv = tk.StringVar(value=self.NONE)
            ttk.Combobox(self.inner, textvariable=tv, values=self.choices, state="readonly",
                         width=46).grid(row=i, column=2, padx=4, pady=2, sticky="n")
            self.kinds.append(kv)
            self.targets.append(tv)
        self.reassign()

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="振り分け直す（種類を直したあと）", command=self.reassign).pack(side="left")
        ttk.Button(bottom, text="この振り分けで入れる", command=self.ok).pack(side="right")
        ttk.Button(bottom, text="やめる", command=self.destroy).pack(side="right", padx=6)
        self.grab_set()
        self.wait_window()

    def reassign(self) -> None:
        blocks = [core.Block(k.get(), b.text) for k, b in zip(self.kinds, self.blocks)]
        plan = core.assign_blocks(blocks, self.slots, self.start)
        label = {c.split("　")[0]: c for c in self.choices[1:]}
        for tv, sid in zip(self.targets, plan):
            tv.set(label.get(sid, self.NONE) if sid else self.NONE)

    def ok(self) -> None:
        self.result = [(core.Block(k.get(), b.text), self.by_label.get(t.get()))
                       for k, t, b in zip(self.kinds, self.targets, self.blocks)]
        self.destroy()


class FlowDialog(tk.Toplevel):
    """原稿の行ごとに、見分けた種類を確かめて直す画面（行政報告・委員会報告・一般質問）。"""

    def __init__(self, master: App, key: str, name: str, lines: list) -> None:
        super().__init__(master)
        self.title(f"{key}の読み取りを確かめる")
        self.geometry("980x640")
        self.transient(master)
        self.result = None
        self.key = key
        self.lines = lines
        self.kinds = {ln.no: ln.kind for ln in lines}
        self.names = flow.KIND_NAMES[key]                   # 種類 → 呼び名
        self.by_name = {v: k for k, v in self.names.items()}
        ttk.Label(self, padding=8, justify="left", text=(
            f"{name} の行ごとに、どう使うかを見分けました。違っていたら、行を選んで下で種類を"
            "直してください（Shift・Ctrl で複数選べます）。\n" + flow.HELP[key] + "\n"
            "・写真 … 【写真】ファイル名｜大きさ｜説明　の行。紙面に赤字で場所を示し、幅ぶん空ける"
        )).pack(anchor="w")
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8)
        self.tree = ttk.Treeview(body, columns=("kind", "text"), show="tree headings",
                                 selectmode="extended")
        self.tree.heading("#0", text="行")
        self.tree.heading("kind", text="種類")
        self.tree.heading("text", text="原稿")
        self.tree.column("#0", width=60, stretch=False)
        self.tree.column("kind", width=150, stretch=False)
        self.tree.column("text", width=680)
        self.tree.tag_configure("member", background="#e6f0ff")
        self.tree.tag_configure("title", background="#fff4d6")
        self.tree.tag_configure("changed", foreground="#c00000")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        for ln in lines:
            self.tree.insert("", "end", iid=str(ln.no), text=str(ln.no), values=("", ln.text))
        self.paint()

        row = ttk.Frame(self, padding=8)
        row.pack(fill="x")
        ttk.Label(row, text="選んだ行の種類を").pack(side="left")
        self.kind = tk.StringVar(value=self.names[flow.TEXT])
        ttk.Combobox(row, textvariable=self.kind, values=list(self.names.values()), state="readonly",
                     width=18).pack(side="left", padx=4)
        ttk.Button(row, text="にする", command=self.set_kind).pack(side="left")
        ttk.Button(row, text="自動の見分けに戻す", command=self.reset_kind).pack(side="left", padx=8)
        self.summary = ttk.Label(row, text="")
        self.summary.pack(side="left", padx=12)
        self.warn = tk.Text(self, height=4, wrap="char", background="#fff8f0")
        self.warn.pack(fill="x", padx=8)
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="これで決める", command=self.ok).pack(side="right")
        ttk.Button(bottom, text="やめる", command=self.destroy).pack(side="right", padx=6)
        self.update_summary()
        self.grab_set()
        self.wait_window()

    def paint(self) -> None:
        for ln in self.lines:
            k = self.kinds[ln.no]
            tags = []
            if k == flow.MEMBER:
                tags.append("member")
            elif k == flow.TITLE:
                tags.append("title")
            if k != ln.auto:
                tags.append("changed")
            name = flow.kind_name(self.key, k) + ("（直した）" if k != ln.auto else "")
            self.tree.item(str(ln.no), values=(name, ln.text), tags=tags)

    def _current_lines(self) -> list:
        return [flow.Line(ln.no, ln.text, self.kinds[ln.no], ln.auto, ln.raw) for ln in self.lines]

    def update_summary(self) -> None:
        _, warns, summ = flow.regroup(self.key, self._current_lines())
        self.summary.config(text=summ)
        self.warn.configure(state="normal")
        self.warn.delete("1.0", "end")
        self.warn.insert("1.0", "\n".join(warns) if warns else "気になる点はありません。")
        self.warn.configure(state="disabled")

    def set_kind(self) -> None:
        kind = self.by_name.get(self.kind.get(), flow.TEXT)
        for iid in self.tree.selection():
            self.kinds[int(iid)] = kind
        self.paint()
        self.update_summary()

    def reset_kind(self) -> None:
        auto = {ln.no: ln.auto for ln in self.lines}
        for iid in self.tree.selection():
            self.kinds[int(iid)] = auto[int(iid)]
        self.paint()
        self.update_summary()

    def ok(self) -> None:
        # 自動の見分けと違う行だけを、行の文字をキーにして覚える（原稿を直しても行番号に左右されない）
        self.result = {ln.text: self.kinds[ln.no] for ln in self.lines if self.kinds[ln.no] != ln.auto}
        self.destroy()


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
