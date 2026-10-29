"""議会だより編集 V7。項目テンプレート入力と15手順の全行程ナビ。"""

from __future__ import annotations

import calendar
import datetime
import json
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

import dropfiles
import edition
import guide
import items
import layout
import sources
import tables
import tooltip
import templates
import docx_out as dx
from grid import TATECHUYOKO, Rect, to_box, unit_width, units


INPUT_PT = 12      # 記入欄の字の大きさ

COLORS = {"大見出し": "#ffd783", "中見出し": "#ffe9af", "質問": "#bfdefd",
          "答弁": "#c9e8c9", "本文": "#eeeeee", "議案": "#dccbf3",
          "写真": "#9bd8ea", "写真説明": "#d4edf2", "表": "#f3e6f7"}
MARKS = ("○", "●", "欠席", "議長")


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("議会だより編集 V7")
        root.geometry("1320x730")
        root.minsize(1100, 680)
        self.work = None
        self.data = items.default_data()
        self.step = 0
        self.getters = []
        # 手順ごとに、紙面を見るで最後に見ていたページ（次に開くときはそこから出す）
        self.preview_pages = {}
        # 手順ごとに、一覧で選んでいる件の番号（一般質問なら何人目か）
        self.list_selection = {}
        self.font = "TkDefaultFont"
        self._style()
        self._build()
        self.drop_ready = dropfiles.enable(root, self.on_drop)
        # マウスのホイール（トラックパッド）を、画面のどこで回してもその場所をスクロールする。
        root.bind_all("<MouseWheel>", self._on_wheel)
        root.bind_all("<Shift-MouseWheel>", lambda e: self._on_wheel(e, across=True))
        root.bind_all("<Button-4>", lambda e: self._on_wheel(e, step=-1))
        root.bind_all("<Button-5>", lambda e: self._on_wheel(e, step=1))
        # ボタンにマウスを合わせると、そのボタンの働きを出す
        self.tooltips = tooltip.Tooltips(root, self._tip_for)
        # 複数行の欄でも TAB で次の欄、Shift+TAB で前の欄へ移る（字の間にタブを入れない）。
        root.bind_class("Text", "<Tab>", _focus_next)
        root.bind_class("Text", "<Shift-Tab>", _focus_previous)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if len(sys.argv) > 1:
            self.open_issue(sys.argv[1])
        else:
            self._resume()

    # ---- 閉じたところから再開する ----
    def _resume(self) -> None:
        """前に閉じたときの号と手順を開く。号フォルダが無くなっていれば最初の画面にする。"""
        last = _read_resume()
        folder = Path(last.get("folder", "")) if last.get("folder") else None
        try:
            found = bool(folder) and (folder / "号情報.json").is_file()
        except OSError:   # 前の号のフォルダが読めない（消えた・権限が無い・ネットワークが切れた）
            found = False
        if not found:
            self.show(0)
            if folder:
                self.fit_label.configure(text="前回の号のフォルダが見つかりません: " + str(folder))
            return
        self.open_issue(str(folder), step=_number(last.get("step")) or 1)
        if self.work:
            self.fit_label.configure(
                text=f"前回の続き（{self.work.issue.title}・{self.step + 1}. {guide.STEPS[self.step]}）から開きました")

    def _remember(self) -> None:
        if not self.work:
            return
        try:
            RESUME_PATH.write_text(json.dumps({"folder": str(self.work.folder), "step": self.step},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass   # 覚えられなくても作業は続けられる

    def close(self) -> None:
        """閉じる前に入力中の内容を保存し、次に開く場所を覚える。"""
        if self.work and not self.save(silent=True):
            if not messagebox.askyesno("保存できませんでした",
                                       "入力中の内容を保存できませんでした。このまま閉じますか？",
                                       parent=self.root):
                return
        self._remember()
        self.root.destroy()

    def _style(self) -> None:
        style = ttk.Style()
        style.configure("TLabel", font=(self.font, 11))
        style.configure("TButton", font=(self.font, 11), padding=4)
        style.configure("TEntry", font=(self.font, 11))
        style.configure("Title.TLabel", font=(self.font, 16, "bold"))
        style.configure("Now.TButton", font=(self.font, 11, "bold"))

    def _build(self) -> None:
        head = ttk.Frame(self.root, padding=(12, 7))
        head.pack(fill="x")
        ttk.Label(head, text="議会だより編集 V7", style="Title.TLabel").pack(side="left")
        self.issue_label = ttk.Label(head, text="号を作るか開いてください")
        self.issue_label.pack(side="right")
        shell = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        shell.pack(fill="both", expand=True)
        self.nav = ttk.Frame(shell, width=225)
        self.nav.pack(side="left", fill="y", padx=(0, 10))
        self.nav.pack_propagate(False)
        self.nav_buttons = []
        for number, name in enumerate(guide.STEPS):
            button = ttk.Button(self.nav, text=f"{number + 1}. {name}",
                                command=lambda n=number: self._go(n))
            button.pack(fill="x", pady=1)
            self.nav_buttons.append(button)
        right = ttk.Frame(shell)
        right.pack(side="left", fill="both", expand=True)
        box = ttk.LabelFrame(right, text="いまやること", padding=7)
        box.pack(fill="x")
        self.guide_label = ttk.Label(box, wraplength=1000, justify="left")
        self.guide_label.pack(anchor="w")
        center = ttk.Frame(right)
        center.pack(fill="both", expand=True, pady=6)
        self.canvas = tk.Canvas(center, highlightthickness=0)
        scrollbar = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(4, 2, 12, 4))
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        bottom = ttk.Frame(right)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="紙面を見る", command=self.preview).pack(side="left")
        self.fit_label = ttk.Label(bottom)
        self.fit_label.pack(side="left", padx=10)
        # 右から詰めて置くので、先に「次へ」を置くと左から「戻る」「次へ」の順になる。
        ttk.Button(bottom, text="次へ", command=self.next).pack(side="right")
        ttk.Button(bottom, text="戻る", command=self.back).pack(side="right", padx=6)

    def _on_wheel(self, event, across: bool = False, step: int = 0):
        """ホイールの位置にある、スクロールできる部品を動かす。中身が入りきっている部品は飛ばして外側を動かす。"""
        if not step:
            delta = getattr(event, "delta", 0)
            if not delta:
                return None
            step = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            # 紙面を見るの紙面は、下の端（上の端）まで来てさらに回すと、次（前）のページへ送る
            turn = getattr(widget, "_turn_page", None)
            if turn is not None and not across:
                try:
                    top, bottom = widget.yview()
                except tk.TclError:
                    top, bottom = 0.0, 1.0
                if (step > 0 and bottom >= 0.999) or (step < 0 and top <= 0.001):
                    turn(1 if step > 0 else -1)
                    return "break"
            view = None
            try:
                if across and hasattr(widget, "xview"):
                    view = widget.xview()
                elif not across and hasattr(widget, "yview") and widget.winfo_class() in (
                        "Text", "Listbox", "Treeview", "Canvas"):
                    view = widget.yview()
            except tk.TclError:
                view = None
            if view and (view[0] > 0.0 or view[1] < 1.0):
                (widget.xview_scroll if across else widget.yview_scroll)(step, "units")
                return "break"
            widget = widget.master
        return None

    def _go(self, number: int) -> None:
        if self.work and self.step != number:
            self.save(silent=True)
        self.show(number)

    def show(self, number: int) -> None:
        self.step = max(0, min(number, len(guide.STEPS) - 1))
        self.getters = []
        for child in self.inner.winfo_children():
            child.destroy()
        name = guide.STEPS[self.step]
        self.guide_label.configure(text=guide.text(name))
        completed = set(self.data.get("completed", []))
        for index, button in enumerate(self.nav_buttons):
            mark = "✓ " if guide.STEPS[index] in completed else ""
            button.configure(text=f"{mark}{index + 1}. {guide.STEPS[index]}",
                             style="Now.TButton" if index == self.step else "TButton")
        if self.step > 0 and not self.work:
            # 号を開く前は入力欄を出さない（号の情報が無いと作れない欄がある）。
            ttk.Label(self.inner, text="最初の「1. はじめに」で、新しい号を作るか、続きを開いてください。",
                      font=(self.font, 12)).pack(anchor="w", pady=20)
            return
        getattr(self, "_step_" + str(self.step), self._not_ready)()
        self._remember()
        self.canvas.yview_moveto(0)
        self._fit_summary()

    def _title(self, text: str) -> None:
        ttk.Label(self.inner, text=text, style="Title.TLabel").pack(anchor="w", pady=(2, 8))

    def _entry(self, label: str, value, setter) -> None:
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=20).pack(side="left")
        var = tk.StringVar(value=str(value or ""))
        ttk.Entry(row, textvariable=var, font=(self.font, INPUT_PT)).pack(side="left", fill="x", expand=True, ipady=2)
        self.getters.append(lambda v=var, s=setter: s(v.get().strip()))

    def _month_choice(self, value: dict) -> None:
        """発行月は決まった月だけから選ぶ。打ち間違いをなくすため、手で書き込めない形にする。"""
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="発行月", width=20).pack(side="left")
        labels = [_month_label(month) for month in layout.MONTHS]
        current = int(value.get("month") or 4)
        var = tk.StringVar(value=_month_label(current) if current in layout.MONTHS else "")
        box = ttk.Combobox(row, textvariable=var, values=labels, state="readonly", width=34)
        box.pack(side="left")
        self.getters.append(lambda v=var: value.__setitem__("month", _number(v.get().split("月")[0])))
        return var

    def _year_choice(self, value: dict) -> tk.StringVar:
        """発行年を令和で選ぶ。前に入れた発行日があればその年、無ければ今年を最初に出す。"""
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="発行年", width=20).pack(side="left")
        this_year = datetime.date.today().year - 2018
        match = re.search(r"令和\s*([0-9０-９]+)年", str(value.get("date", "")))
        current = _number(match.group(1)) if match else this_year
        years = [f"令和{year}年" for year in range(this_year - 1, this_year + 3)]
        if f"令和{current}年" not in years:
            years.insert(0, f"令和{current}年")
        var = tk.StringVar(value=f"令和{current}年")
        ttk.Combobox(row, textvariable=var, values=years, state="readonly", width=12).pack(side="left")
        return var

    def _text(self, label: str, value, setter, height: int = 5) -> None:
        row = ttk.Frame(self.inner)
        row.pack(fill="both", expand=True, pady=3)
        ttk.Label(row, text=label, width=20).pack(side="left", anchor="n")
        # 書きやすいよう、指定の約 1.6 倍（最低 6 行）の高さにし、スクロールバーを付ける
        widget = tk.Text(row, height=max(6, int(height * 1.6)), wrap="word",
                         font=(self.font, INPUT_PT), undo=True, padx=6, pady=4,
                         relief="solid", borderwidth=1, highlightthickness=1)
        widget.insert("1.0", str(value or ""))
        bar = ttk.Scrollbar(row, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        widget.pack(side="left", fill="both", expand=True)
        self.getters.append(lambda w=widget, s=setter: s(w.get("1.0", "end-1c").strip()))

    def _list_editor(self, label, values, fields, summary, max_items=None) -> None:
        box = ttk.LabelFrame(self.inner, text=label, padding=7)
        box.pack(fill="both", expand=True, pady=5)
        listing = tk.Listbox(box, height=min(12, max(4, len(values) + 1)),
                             font=(self.font, INPUT_PT), exportselection=False)
        listing.pack(side="left", fill="both", expand=True)
        controls = ttk.Frame(box)
        controls.pack(side="left", fill="y", padx=(7, 0))

        step = self.step

        def refresh(select=0):
            listing.delete(0, "end")
            for index, value in enumerate(values):
                listing.insert("end", f"{index + 1}. {summary(value)}")
            if values:
                listing.selection_set(min(select, len(values) - 1))
                # 紙面を見るで、選んでいる（足したばかりの）件のページから開くために覚えておく
                self.list_selection[step] = min(select, len(values) - 1)
        listing.bind("<<ListboxSelect>>", lambda _e: listing.curselection() and
                     self.list_selection.__setitem__(step, listing.curselection()[0]))

        def edit(new=False):
            if new and max_items and len(values) >= max_items:
                messagebox.showwarning("追加できません", f"最大{max_items}件です。", parent=self.root)
                return
            selected = listing.curselection()
            if not new and not selected:
                return
            value = {field[0]: "" for field in fields} if new else values[selected[0]]
            dialog = tk.Toplevel(self.root)
            dialog.title("項目を入力")
            # 画面の高さいっぱいに広げ、複数行の欄が残りの高さを分け合う（本文・問・答が書きやすいように）
            width = min(self.root.winfo_screenwidth() - 60, 1000)
            height = max(560, self.root.winfo_screenheight() - 100)
            dialog.geometry(f"{width}x{height}+20+10")
            dialog.transient(self.root)
            # 「この内容にする」ボタンは窓の下に固定して、欄が多くても隠れないようにする
            footer = ttk.Frame(dialog, padding=(12, 6))
            footer.pack(side="bottom", fill="x")
            body = ttk.Frame(dialog, padding=(12, 12, 12, 0))
            body.pack(fill="both", expand=True)
            widgets = {}
            for field in fields:
                key, title, multiline = field[:3]
                choices = field[3] if len(field) > 3 else None
                ttk.Label(body, text=title, font=(self.font, INPUT_PT)).pack(anchor="w", pady=(6, 2))
                if multiline:
                    frame = ttk.Frame(body)
                    frame.pack(fill="both", expand=True)
                    widget = tk.Text(frame, height=4, wrap="word", font=(self.font, INPUT_PT),
                                     undo=True, padx=6, pady=4,
                         relief="solid", borderwidth=1, highlightthickness=1)
                    widget.insert("1.0", str(value.get(key, "")))
                    bar = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
                    widget.configure(yscrollcommand=bar.set)
                    bar.pack(side="right", fill="y")
                    widget.pack(side="left", fill="both", expand=True)
                elif choices:
                    widget = ttk.Combobox(body, values=choices, font=(self.font, INPUT_PT),
                                          state="normal" if len(field) > 4 and field[4] else "readonly")
                    widget.set(str(value.get(key, "")))
                    widget.pack(fill="x")
                else:
                    widget = ttk.Entry(body, font=(self.font, INPUT_PT))
                    widget.insert(0, str(value.get(key, "")))
                    widget.pack(fill="x", ipady=2)
                widgets[key] = (widget, multiline)

            def accept():
                for key, (widget, multiline) in widgets.items():
                    value[key] = (widget.get("1.0", "end-1c") if multiline else widget.get()).strip()
                if new:
                    values.append(value)
                refresh(len(values) - 1 if new else selected[0])
                dialog.destroy()
            ttk.Button(footer, text="この内容にする", command=accept).pack(side="right")
            ttk.Button(footer, text="やめる", command=dialog.destroy).pack(side="right", padx=6)
            first = next(iter(widgets.values()), None)
            if first:
                first[0].focus_set()
            dialog.grab_set()

        def remove():
            selected = listing.curselection()
            if selected:
                values.pop(selected[0])
                refresh(max(0, selected[0] - 1))

        def move(delta):
            selected = listing.curselection()
            if not selected:
                return
            old, new = selected[0], selected[0] + delta
            if 0 <= new < len(values):
                values[old], values[new] = values[new], values[old]
                refresh(new)
        listing.bind("<Double-Button-1>", lambda _e: edit())   # 行をダブルクリックしても編集
        for text, command in (("＋追加", lambda: edit(True)), ("編集", edit), ("削除", remove),
                              ("上へ", lambda: move(-1)), ("下へ", lambda: move(1))):
            ttk.Button(controls, text=text, command=command).pack(fill="x", pady=2)
        refresh()

    def _step_0(self):
        self._title("はじめに")
        ttk.Label(self.inner, text="入力 → 写真 → 全ページ確認 → Word出力の順で進みます。\n"
                  "内容は号フォルダの「項目.json」、紙面は「紙面.json」に保存されます。",
                  justify="left").pack(anchor="w", pady=8)
        row = ttk.Frame(self.inner)
        row.pack(anchor="w", pady=8)
        ttk.Button(row, text="新しい号を作る", command=self.new_issue).pack(side="left")
        ttk.Button(row, text="続きを開く", command=self.open_issue).pack(side="left", padx=8)

    def _step_1(self):
        self._title("号の情報")
        value = self.data.setdefault("issue", {})
        self._entry("号数", value.get("number", ""), lambda v: value.__setitem__("number", _number(v)))
        year_var = self._year_choice(value)
        month_var = self._month_choice(value)
        # 発行日は発行月の末日に決まっているので、年と月から自動で決める。
        shown = ttk.Label(self.inner, text="")
        shown.pack(anchor="w", pady=8)

        def refresh(*_args) -> None:
            year, month = _number(year_var.get()), _number(month_var.get().split("月")[0])
            date = _last_day(year, month)
            value["date"] = date
            issue = layout.Issue(0, month, date)
            shown.configure(text=f"発行日（自動・月の末日）: {date}\n"
                                 f"定例会名（自動）: {items.templates.meeting_name(issue)}")

        year_var.trace_add("write", refresh)
        month_var.trace_add("write", refresh)
        refresh()
        self.getters.append(refresh)

    def _step_2(self):
        self._title("議員名簿")
        current = self.work.settings if self.work else None
        self._text("議員（1行に1人）", "\n".join(current.members if current else []),
                   lambda v: setattr(self, "_member_text", v), 9)
        self._entry("議長名", current.chair if current else "", lambda v: setattr(self, "_chair", v))
        ttk.Label(self.inner, text="議長が上の議員の一覧に無くても、賛否表と賛否のエクセルでは最後の列に議長として入ります。",
                  wraplength=900, justify="left").pack(anchor="w", pady=4)

    def _step_3(self):
        self._title("表紙")
        value = self.data.setdefault("cover", {})
        self._entry("写真の説明", value.get("photo_caption", ""), lambda v: value.__setitem__("photo_caption", v))
        self._text("特集の題名", value.get("feature_titles", ""), lambda v: value.__setitem__("feature_titles", v), 4)

    def _step_4(self):
        self._title("行政報告")
        value = self.data.setdefault("gyosei", {"title": items.GYOSEI_TITLE, "reports": []})
        if value.get("title", "") in ("", layout.GYOSEI):   # 前の決まり「行政報告」のままなら直す
            value["title"] = items.GYOSEI_TITLE
        self._entry("大見出し", value["title"], lambda v: value.__setitem__("title", v))
        self._list_editor("報告事項", value.setdefault("reports", []),
                          [("heading", "見出し", False), ("body", "本文", True)],
                          lambda v: v.get("heading") or "（見出しなし）")
        self._word_button()

    def _step_5(self):
        month = int(self.data.get("issue", {}).get("month", 4))
        if month == 10:
            self._kessan_step()
            return
        if month in (4, 5):
            self._yosan_step()
            return
        self._title("当初予算または決算")
        value = self.data.setdefault("budget", {"title": "", "summary": "", "questions": []})
        section = layout.YOSAN
        self._entry("大見出し", value.get("title") or section, lambda v: value.__setitem__("title", v))
        self._text("概要本文", value.get("summary", ""), lambda v: value.__setitem__("summary", v), 6)
        self._list_editor("質疑", value.setdefault("questions", []),
                          [("heading", "見出し", False), ("question", "問", True), ("answer", "答", True)],
                          lambda v: v.get("heading") or v.get("question", "")[:30])
        ttk.Button(self.inner, text="まとめて貼る", command=lambda: self.bulk_into(value)).pack(anchor="e")

    def _yosan_step(self):
        """4・5 月号の当初予算の見開き。第202号と同じ決まった型に入れる。"""
        self._title("当初予算（見開き2ページ）")
        value = self.data.setdefault("yosan", items.default_yosan())
        auto = items.templates.yosan_title(items.issue_from_data(self.data, self.work.issue))
        ttk.Label(self.inner, text="■ 1ページ目（円グラフと各会計予算）", font=(self.font, 12, "bold")).pack(anchor="w", pady=(6, 2))
        self._entry("題", value.get("title") or auto, lambda v: value.__setitem__("title", v))
        self._text("会計の種類（1行に1つ）", value.get("kinds", ""), lambda v: value.__setitem__("kinds", v), 3)
        self._entry("円グラフの題", value.get("chart_title") or auto.replace("当初予算", "一般会計予算"),
                    lambda v: value.__setitem__("chart_title", v))
        self._entry("円グラフの指示", value.get("chart_note", ""), lambda v: value.__setitem__("chart_note", v))
        self._entry("一般会計の歳出総額", value.get("general_total", ""), lambda v: value.__setitem__("general_total", v))
        self._list_editor("円グラフの横の主な事業", value.setdefault("chart_items", []),
                          [("item", "費目（例 総務費）", False), ("name", "事業名", False), ("text", "説明", True)],
                          lambda v: f"【{v.get('item', '')}】◉{v.get('name', '')}")
        self._list_editor("各会計予算", value.setdefault("accounts", []),
                          [("group", "まとめ（公営企業会計・特別会計）", False), ("name", "会計名", False),
                           ("amount", "金額（例 6億9,783万円）", False), ("note", "注（※の説明など）", True)],
                          lambda v: f"{v.get('group', '')}　◉{v.get('name', '')}　{v.get('amount', '') or '（空）'}")
        ttk.Label(self.inner, text="■ 2ページ目（注目する事業）", font=(self.font, 12, "bold")).pack(anchor="w", pady=(10, 2))
        self._entry("大見出し", value.get("headline", ""), lambda v: value.__setitem__("headline", v))
        self._list_editor("注目する事業", value.setdefault("focus", []),
                          [("name", "事業名", False), ("amount", "金額", False), ("text", "説明", True)],
                          lambda v: f"{v.get('name', '')}　{v.get('amount', '')}")
        self._entry("前の年度の欄の見出し", value.get("previous_title", ""),
                    lambda v: value.__setitem__("previous_title", v))
        self._list_editor("前の年度の事業", value.setdefault("previous", []),
                          [("name", "事業名", False), ("amount", "金額", False), ("text", "説明", True)],
                          lambda v: f"{v.get('name', '')}　{v.get('amount', '')}")

    def _kessan_step(self):
        """10 月号の決算のページ。第204号と同じ決まった型に入れる。"""
        self._title("決算")
        value = self.data.setdefault("kessan", items.default_kessan())
        auto = items.templates.kessan_title(items.issue_from_data(self.data, self.work.issue))
        self._entry("題", value.get("title") or auto, lambda v: value.__setitem__("title", v))
        self._text("会計の種類（1行に1つ）", value.get("kinds", ""), lambda v: value.__setitem__("kinds", v), 3)
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="写真", width=20).pack(side="left")
        names = [""] + [photo["name"] for photo in self.work.photo_files()]
        photo_var = tk.StringVar(value=value.get("photo", ""))
        ttk.Combobox(row, textvariable=photo_var, values=names, state="readonly", width=40).pack(side="left")
        ttk.Label(row, text="（写真は「写真」の手順か、ここへのドロップで写真フォルダに入れてから選ぶ）").pack(side="left", padx=6)
        self.getters.append(lambda: value.__setitem__("photo", photo_var.get()))
        self._entry("円グラフの指示", value.get("chart_note", ""), lambda v: value.__setitem__("chart_note", v))
        self._list_editor("会計別決算額", value.setdefault("accounts", []),
                          [("group", "まとめ（特別会計など）", False), ("name", "会計名", False),
                           ("revenue", "歳入（例 7億 731万円）", False), ("expense", "歳出", False)],
                          lambda v: f"{v.get('group', '')}　{v.get('name', '')}　歳入 {v.get('revenue', '') or '（空）'}"
                                    f"　歳出 {v.get('expense', '') or '（空）'}")
        self._list_editor("決算の質疑", value.setdefault("questions", []),
                          [("heading", "会計名（例 一般会計）", False), ("question", "問", True),
                           ("answer", "答", True)],
                          lambda v: f"【{v.get('heading', '')}】{v.get('question', '')[:24]}")
        ttk.Button(self.inner, text="まとめて貼る", command=lambda: self.bulk_into(value)).pack(anchor="e")

    def _step_6(self):
        self._title("議案と賛否(エクセル)")
        if not self.work:
            ttk.Label(self.inner, text="先に号を作るか開いてください。").pack(anchor="w")
            return
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="1. ひな形を作る", command=self.make_votes_template).pack(side="left")
        self.votes_path_label = ttk.Label(row, text="保存先を選ぶと、フルパスを表示します。",
                                          wraplength=700)
        self.votes_path_label.pack(side="left", padx=10)
        ttk.Label(self.inner, text=("2. エクセルで入力する：ひな形を開き、1行に議案1件を入力し、"
                                    "各議員の列へ ○・●・欠席 を入れて保存します。"),
                  wraplength=900, justify="left").pack(anchor="w", pady=8)
        ttk.Button(self.inner, text="3. エクセルを取り込む",
                   command=self.import_votes).pack(anchor="w", pady=5)
        info = self.data.get("votes_import", {})
        if info:
            ttk.Label(self.inner, text=(f"取込済み: {info.get('source_name', '')}\n"
                                        f"号フォルダの複製: {info.get('copy_name', '')}\n"
                                        f"日時: {info.get('imported_at', '')}"),
                      justify="left").pack(anchor="w", pady=5)
        votes = self.data.get("votes", [])
        if votes:
            # 議員ごとの ○・● も並べて、エクセルと見比べられるようにする
            box = ttk.Frame(self.inner)
            box.pack(fill="x", pady=(8, 0))
            # 議案を全件見せる（画面ごと下へスクロールして見る）
            self._votes_table(box, votes)
            ttk.Label(self.inner, text="行をダブルクリックすると、区分・件名（改行も）・議決結果を直せます。○・● はエクセルを直して取り込み直してください。",
                      wraplength=900).pack(anchor="w")
        warnings = self.data.get("votes_warnings", [])
        if warnings:
            ttk.Label(self.inner, text="注意\n・" + "\n・".join(warnings),
                      foreground="#a33", justify="left", wraplength=900).pack(anchor="w", pady=8)

    def _votes_table(self, parent, votes, height: int = 0) -> None:
        """取り込んだ賛否の確認用の表。紙面と同じく議員名は縦書き、件名は折り返し、画面の幅いっぱいに描く。"""
        members = list(self.work.settings.vote_members)
        self.root.update_idletasks()
        total = max(900, self.inner.winfo_width() - 30)
        size = 15                                  # 1 字の大きさ（画面の点）
        kind_w, result_w = 80, 80
        member_w = max(30, min(44, (total - kind_w - result_w - 260) // max(1, len(members))))
        title_w = max(260, total - kind_w - result_w - member_w * len(members))
        width = kind_w + title_w + member_w * len(members) + result_w

        def one_line(value) -> str:
            return "　".join(part.strip() for part in str(value or "").splitlines() if part.strip())

        def wrap(text: str, room: int) -> list:
            per = max(1, room // size)
            text = one_line(text)
            return [text[i:i + per] for i in range(0, len(text), per)] or [""]

        header_h = max(len(one_line(name)) for name in members + ["議決結果"]) * size + 14
        rows = []
        for vote in votes:
            marks = vote.get("marks", {})
            title = wrap(vote.get("title", ""), title_w - 12)
            rows.append((one_line(vote.get("kind", "")), title,
                         [one_line(marks.get(name, "")) for name in members],
                         one_line(items.templates.vote_result(vote.get("result", ""))),
                         len(title) * (size + 5) + 12))
        canvas = tk.Canvas(parent, width=width, height=header_h + sum(r[4] for r in rows) + 2,
                           bg="white", highlightthickness=0)
        canvas.pack(anchor="w")
        font, small = (self.font, 11), (self.font, 10)
        xs = [0, kind_w, kind_w + title_w] + [kind_w + title_w + member_w * (i + 1) for i in range(len(members))]
        xs.append(width)

        def cell(x1, y1, x2, y2, fill="white"):
            canvas.create_rectangle(x1, y1, x2, y2, outline="#555", fill=fill)

        cell(0, 0, kind_w, header_h, "#eef2f6")
        canvas.create_text(kind_w / 2, header_h / 2, text="区分", font=small)
        cell(kind_w, 0, kind_w + title_w, header_h, "#eef2f6")
        canvas.create_text(kind_w + title_w / 2, header_h / 2, text="議案番号・件名", font=small)
        for index, name in enumerate(members):
            x = xs[2 + index]
            cell(x, 0, x + member_w, header_h, "#eef2f6")
            canvas.create_text(x + member_w / 2, 7, text="\n".join("".join(one_line(name).split())),
                               font=small, anchor="n")
        cell(xs[-2], 0, width, header_h, "#eef2f6")
        canvas.create_text(xs[-2] + result_w / 2, 7, text="\n".join("議決結果"), font=small, anchor="n")
        y = header_h
        spans = []
        for kind, title, marks, result, row_h in rows:
            spans.append((y, y + row_h))
            cell(0, y, kind_w, y + row_h)
            canvas.create_text(kind_w / 2, y + row_h / 2, text=kind, font=font, width=kind_w - 6)
            cell(kind_w, y, kind_w + title_w, y + row_h)
            canvas.create_text(kind_w + 6, y + 6, text="\n".join(title), font=font, anchor="nw")
            for index, mark in enumerate(marks):
                x = xs[2 + index]
                cell(x, y, x + member_w, y + row_h)
                canvas.create_text(x + member_w / 2, y + row_h / 2, text=mark, font=small if len(mark) > 1 else font)
            cell(xs[-2], y, width, y + row_h)
            canvas.create_text(xs[-2] + result_w / 2, y + row_h / 2, text=result, font=font)
            y += row_h

        def open_row(event):
            y = canvas.canvasy(event.y)
            index = next((i for i, (top, bottom) in enumerate(spans) if top <= y < bottom), None)
            if index is not None:
                self._edit_vote(index)
        canvas.bind("<Double-Button-1>", open_row)

    def _edit_vote(self, index: int, parent=None, done=None) -> None:
        """確認の表（または紙面を見るの賛否表）で 1 件を手直しする窓。改行も入れられる。○・● はエクセルで直す。"""
        vote = self.data["votes"][index]
        dialog = tk.Toplevel(parent or self.root)
        dialog.title(f"{index + 1}件目を直す")
        dialog.geometry("720x380")
        if parent is not None:
            dialog.transient(parent)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        kind_var = tk.StringVar(value=vote.get("kind", ""))
        result_var = tk.StringVar(value=items.templates.vote_result(vote.get("result", "")))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="区分", width=12).pack(side="left")
        ttk.Entry(row, textvariable=kind_var, width=20).pack(side="left")
        ttk.Label(body, text="件名（Enter で改行。紙面でもその位置で改行します）").pack(anchor="w", pady=(8, 2))
        title = tk.Text(body, height=5, wrap="word", font=(self.font, 12), undo=True)
        title.insert("1.0", vote.get("title", ""))
        title.pack(fill="both", expand=True)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="議決結果", width=12).pack(side="left")
        ttk.Entry(row, textvariable=result_var, width=20).pack(side="left")
        ttk.Label(body, text="○・● はエクセルを直して取り込み直してください。ここで直した区分・件名・議決結果は、"
                             "取り込み直しても同じ件名の行に当て直します。", wraplength=680, foreground="#555").pack(anchor="w")

        def keep():
            self.save(silent=True)   # 元の画面で書きかけの内容を先に残す
            self.work.edit_vote(self.data, index, kind_var.get(), title.get("1.0", "end-1c"), result_var.get())
            dialog.destroy()
            self.show(self.step)
            if done:
                done()
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="直す", command=keep).pack(side="right")
        ttk.Button(buttons, text="やめる", command=dialog.destroy).pack(side="right", padx=6)
        title.focus_set()

    def _edit_bill_title(self, index: int, parent=None, done=None) -> None:
        """紙面を見るの審議本文（◎件名）から、審議した案件の件名を直す窓。"""
        bill = self.data["shingi"]["bills"][index]
        old = bill.get("title", "")
        dialog = tk.Toplevel(parent or self.root)
        dialog.title("審議した案件の件名を直す")
        dialog.geometry("720x330")
        if parent is not None:
            dialog.transient(parent)
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="件名（審議のページの「◎」の行になります）").pack(anchor="w", pady=(0, 2))
        title = tk.Text(body, height=4, wrap="word", font=(self.font, INPUT_PT), undo=True,
                        relief="solid", borderwidth=1)
        title.insert("1.0", old)
        title.pack(fill="both", expand=True)
        # 賛否表に同じ件名の行があれば、そちらもいっしょに直せるようにする
        votes = self.data.get("votes", []) or []
        same = next((i for i, vote in enumerate(votes)
                     if _plain_title(vote.get("title", "")) == _plain_title(old) and old.strip()), None)
        both = tk.BooleanVar(value=same is not None)
        if same is not None:
            ttk.Checkbutton(body, text="賛否表の同じ件名もいっしょに直す", variable=both).pack(anchor="w", pady=6)

        def keep():
            self.save(silent=True)
            new = title.get("1.0", "end-1c").strip("\n")
            bill["title"] = new
            if same is not None and both.get():
                vote = votes[same]
                self.work.edit_vote(self.data, same, vote.get("kind", ""), new,
                                    items.templates.vote_result(vote.get("result", "")))
            self.work.save_items(self.data)
            dialog.destroy()
            self.show(self.step)
            if done:
                done()
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="直す", command=keep).pack(side="right")
        ttk.Button(buttons, text="やめる", command=dialog.destroy).pack(side="right", padx=6)
        title.focus_set()

    def _edit_bill_qa(self, index: int, question: int, parent=None, done=None) -> None:
        """紙面を見るの審議本文から、1 件の案件の説明と質疑（問・答）を直す窓。

        question は何番目の問か（0 から。説明の所なら -1）。その問の行に字の入る位置を合わせる。
        """
        bill = self.data["shingi"]["bills"][index]
        dialog = tk.Toplevel(parent or self.root)
        dialog.title("説明と質疑を直す")
        screen_h = self.root.winfo_screenheight()
        dialog.geometry(f"860x{max(520, min(760, screen_h - 120))}")
        if parent is not None:
            dialog.transient(parent)
        # ボタンは窓の下に固定する（欄が大きくても隠れないように）
        buttons = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        buttons.pack(side="bottom", fill="x")
        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="件名: " + (bill.get("title", "") or "（件名なし）").replace("\n", " "),
                  wraplength=820).pack(anchor="w")

        def field(label, text, height):
            ttk.Label(body, text=label).pack(anchor="w", pady=(8, 2))
            frame = ttk.Frame(body)
            frame.pack(fill="both", expand=True)
            widget = tk.Text(frame, height=height, wrap="word", font=(self.font, INPUT_PT), undo=True,
                             relief="solid", borderwidth=1, padx=6, pady=4)
            bar = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
            widget.configure(yscrollcommand=bar.set)
            bar.pack(side="right", fill="y")
            widget.pack(side="left", fill="both", expand=True)
            widget.insert("1.0", text)
            return widget
        description = field("説明", bill.get("description", ""), 5)
        qa = field("質疑（問は「問　」、答は「答　」で始めます。Enter で改行）", _qa_text(bill), 12)

        def keep():
            self.save(silent=True)   # 元の画面で書きかけの内容を先に残す
            bill["description"] = description.get("1.0", "end-1c").strip()
            text = qa.get("1.0", "end-1c").strip()
            bill["qa_bulk"] = text
            bill["questions"] = items.parse_bulk(text)["questions"] if text else []
            self._prepare_nested()
            self.work.save_items(self.data)
            dialog.destroy()
            self.show(self.step)
            if done:
                done()
        ttk.Button(buttons, text="直す", command=keep).pack(side="right")
        ttk.Button(buttons, text="やめる", command=dialog.destroy).pack(side="right", padx=6)
        if question < 0:
            description.focus_set()
            return
        # 押した問の行へ字の入る位置を移す
        count = -1
        for number, line in enumerate(qa.get("1.0", "end-1c").splitlines(), 1):
            if line.lstrip().startswith("問"):
                count += 1
                if count == question:
                    qa.mark_set("insert", f"{number}.0")
                    qa.see(f"{number}.0")
                    break
        qa.focus_set()

    def _step_7(self):
        self._title("審議したこと")
        value = self.data.setdefault("shingi", {"counts": [], "bills": []})
        self._entry("定例会名", value.get("meeting", ""), lambda v: value.__setitem__("meeting", v))
        self._period_choice(value)
        self._counts_editor(value)
        # 審議ページに入りきらない行数を、その場で知らせる（1 ページに収める決まり）
        page = next((p for p in self.work.pages if p["section"] == layout.SHINGI), None)
        if page is not None:
            result = self.work.compose(page["no"])
            lost = [w for w in result.warnings if "入りません" in w]
            ttk.Label(self.inner, text=("・" + "\n・".join(lost)) if lost else
                      "審議の本文と賛否表は、審議ページ（1ページ）に入っています。",
                      foreground="#a33" if lost else "#363", wraplength=900,
                      justify="left").pack(anchor="w", pady=4)
        vote_titles = [v.get("title", "") for v in self.data.get("votes", []) if v.get("title")]
        # 審議するのは議案だけではない（発議案・請願・陳情・報告・認定・同意なども入る）
        self._list_editor("審議した案件（議案・発議案・請願・陳情・報告など）", value.setdefault("bills", []),
                          [("kind", "区分（例 条例・補正予算・請願）", False), ("title", "件名", False,
                            vote_titles, True), ("description", "説明", True),
                           ("qa_bulk", "質疑（問・答で開始）", True)],
                          lambda v: v.get("title") or "（件名なし）")

    def _period_choice(self, value: dict) -> None:
        """会期（例 Ｒ８．９．４～９．１１）を、始まりと終わりの年月日のプルダウンで選ぶ。"""
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="会期", width=20).pack(side="left")
        old = str(value.get("period", "") or "")
        parsed = parse_period(old)
        if parsed is None:
            # まだ入っていなければ、定例会の月を最初に出す（日は選んでもらう）
            issue = self.work.issue
            match = re.search(r"令和\s*([0-9０-９]+)年", issue.date)
            year = _number(match.group(1)) if match else datetime.date.today().year - 2018
            month = layout.TEIREIKAI.get(issue.month, issue.month)
            if issue.month == 1:
                year -= 1
            parsed = (year, month, 0, year, month, 0)
        start_year, start_month, start_day, end_year, end_month, end_day = parsed
        this_year = datetime.date.today().year - 2018
        years = sorted({this_year - 1, this_year, this_year + 1, start_year, end_year})
        boxes = {}

        def choice(name, current, labels, width):
            var = tk.StringVar(value=current)
            ttk.Combobox(row, textvariable=var, values=labels, state="readonly", width=width,
                         font=(self.font, INPUT_PT)).pack(side="left", padx=(0, 2))
            boxes[name] = var

        year_labels = [f"令和{y}年" for y in years]
        month_labels = [f"{m}月" for m in range(1, 13)]
        day_labels = [f"{d}日" for d in range(1, 32)]
        choice("start_year", f"令和{start_year}年", year_labels, 9)
        choice("start_month", f"{start_month}月", month_labels, 5)
        choice("start_day", f"{start_day}日" if start_day else "", day_labels, 5)
        ttk.Label(row, text="から").pack(side="left", padx=4)
        choice("end_year", f"令和{end_year}年", year_labels, 9)
        choice("end_month", f"{end_month}月", month_labels, 5)
        choice("end_day", f"{end_day}日" if end_day else "", day_labels, 5)
        ttk.Label(row, text="まで").pack(side="left", padx=4)
        shown = ttk.Label(self.inner, foreground="#555")
        shown.pack(anchor="w", padx=(150, 0))

        def build():
            numbers = [_number(boxes[name].get()) for name in
                       ("start_year", "start_month", "start_day", "end_year", "end_month", "end_day")]
            return format_period(*numbers)

        def refresh(*_args):
            text = build()
            if text:
                shown.configure(text="紙面の会期: " + text, foreground="#555")
            elif _number(boxes["start_day"].get()) and _number(boxes["end_day"].get()):
                shown.configure(text="その日付はありません。終わりの日が始まりより前でないか、"
                                     "月の日数（2月30日など）を確かめてください。", foreground="#a33")
            elif old and parse_period(old) is None:
                shown.configure(text="前に書いた会期: " + old + "（日まで選ぶと置き換わります）", foreground="#955")
            else:
                shown.configure(text="始まりと終わりの日を選んでください。", foreground="#955")
        def follow(start, end):
            # 終わりの日をまだ選んでいなければ、終わりの年・月も始まりにそろえる
            if not _number(boxes["end_day"].get()):
                boxes[end].set(boxes[start].get())
        boxes["start_year"].trace_add("write", lambda *_a: follow("start_year", "end_year"))
        boxes["start_month"].trace_add("write", lambda *_a: follow("start_month", "end_month"))
        for var in boxes.values():
            var.trace_add("write", refresh)
        refresh()

        def keep():
            text = build()
            if text or parse_period(old) is not None:
                value["period"] = text
        self.getters.append(keep)

    def _counts_editor(self, value: dict) -> None:
        """審議ページの「○月議会では、条例３件…の計○件」の種類と件数を、表で直せるようにする。

        ふだんはエクセルから数えた件数が入る。ここで直すと「手で直した件数」になり、
        議案と賛否を直したり取り込み直したりしても変わらない（「エクセルから数え直す」で戻す）。
        """
        box = ttk.LabelFrame(self.inner, text="案件の種類と件数（紙面の一番上のまとめ文になります）", padding=6)
        box.pack(fill="x", pady=5)
        manual = bool(value.get("counts_manual"))
        ttk.Label(box, text=("手で直した件数です。エクセルを取り込み直しても変わりません。" if manual else
                             "エクセルから自動で数えた件数です。違うときは、ここで直せます。"),
                  foreground="#955" if manual else "#555").pack(anchor="w")
        table = ttk.Frame(box)
        table.pack(fill="x", pady=4)
        ttk.Label(table, text="種類（例 条例・補正予算・請願）").grid(row=0, column=0, sticky="w")
        ttk.Label(table, text="件数").grid(row=0, column=1, sticky="w", padx=6)
        rows = []
        sentence = ttk.Label(box, wraplength=900, justify="left")

        def current():
            result = []
            for kind_var, count_var, _parts in rows:
                kind = kind_var.get().strip()
                count = _number(count_var.get())
                if kind or count:
                    result.append({"kind": kind, "count": count})
            return result

        def show_sentence(*_args):
            text = templates.summary_text(current(), self.work.issue.month if self.work else None)
            sentence.configure(text="紙面のまとめ文: " + (text or "（件数が0なので出ません）"))

        def add_row(kind="", count=1):
            index = len(rows) + 1
            kind_var, count_var = tk.StringVar(value=kind), tk.StringVar(value=str(count))
            entry = ttk.Entry(table, textvariable=kind_var, font=(self.font, INPUT_PT), width=30)
            spin = tk.Spinbox(table, from_=0, to=999, textvariable=count_var, width=5,
                              font=(self.font, INPUT_PT), command=show_sentence)
            parts = []
            remove = ttk.Button(table, text="この行を消す", command=lambda: delete(record))
            record = (kind_var, count_var, parts)
            parts.extend([entry, spin, remove])
            entry.grid(row=index, column=0, sticky="we", pady=2, ipady=2)
            spin.grid(row=index, column=1, sticky="w", padx=6)
            remove.grid(row=index, column=2, sticky="w")
            for var in (kind_var, count_var):
                var.trace_add("write", show_sentence)
            rows.append(record)
            return entry

        def delete(record):
            for widget in record[2]:
                widget.destroy()
            rows.remove(record)
            show_sentence()

        for item in value.get("counts", []) or []:
            add_row(str(item.get("kind", "")), int(item.get("count") or 0))
        table.columnconfigure(0, weight=1)
        buttons = ttk.Frame(box)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="種類を足す", command=lambda: (add_row("", 1).focus_set(), show_sentence())
                   ).pack(side="left")

        def recount():
            value["counts"] = edition.vote_counts(self.data.get("votes", []))
            value.pop("counts_manual", None)
            self.work.save_items(self.data)
            self.show(self.step)
        ttk.Button(buttons, text="エクセルから数え直す", command=recount).pack(side="left", padx=6)
        sentence.pack(anchor="w", pady=(6, 0))
        if not rows and not self.data.get("votes"):
            ttk.Label(box, text="議案と賛否のエクセルを取り込むと自動で入ります。手で足すこともできます。",
                      foreground="#955").pack(anchor="w")
        show_sentence()

        def keep():
            counts = current()
            if counts != (value.get("counts") or []):
                value["counts"] = counts
                value["counts_manual"] = True
        self.getters.append(keep)

    def _step_8(self):
        self._title("委員会報告")
        ttk.Label(self.inner, text="ページの大見出しは「" + items.IINKAI_TITLE + "」に決まっています（入力は要りません）。",
                  foreground="#555").pack(anchor="w", pady=(0, 4))
        self._list_editor("報告", self.data.setdefault("committees", []),
                          [("committee", "委員会名（見出しになる。例 総務常任委員会）", False),
                           ("heading", "記事の見出し（任意。委員会名の次に入る。例 国・省等にも要望）", False),
                           ("body", "本文（途中の小見出しは、行の頭に【見出し】を付ける）", True)],
                          lambda v: f"{v.get('committee', '')}　{v.get('heading', '')}".strip() or "（名称なし）")
        self._word_button()

    def _step_9(self):
        self._title("一般質問")
        members = self.work.settings.members if self.work else []
        statuses = sources.reception_status(members, self.data.setdefault("questions", []))
        if statuses:
            ttk.Label(self.inner, text="受付状況: " + "／".join(
                f"{v['member']} {v['status']}" for v in statuses), wraplength=900,
                justify="left").pack(anchor="w", pady=5)
        ttk.Label(self.inner, text="最初のページの大見出しは「" + items.ippan_title(len(self.data.get("questions", []) or []))
                  + "」になります（質問者の数から自動。入力は要りません）。", foreground="#555").pack(anchor="w")
        self._list_editor("質問者", self.data.setdefault("questions", []),
                          [("member", "議員名", False,
                            members),
                           ("confirmed", "議員の確認", False, ("未", "済")),
                           ("qa_bulk", "質問（質問ごとに【見出し】大まかな質問、【見出しの答】それへの答、"
                                       "問、答、答弁者 の順。1番目の見出しが大見出しになります）", True)],
                          _question_summary, max_items=10)
        ttk.Label(self.inner, text=("書き方の例:\n"
                                    "【見出し】防災対策の強化を（大まかな質問。紙面では青字）\n"
                                    "【見出しの答】計画的に進める（それへの答）\n"
                                    "問　詳しい質問\n答　詳しい答\n答弁者　見本課長\n"
                                    "（2番目の質問も【見出し】から同じように続けます）"),
                  foreground="#555", justify="left").pack(anchor="w", pady=(0, 4))
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=5)
        bulk = ttk.Button(row, text="まとめて貼る", command=self.bulk_question)
        bulk.pack(side="left")
        bulk._tip = ("1人分の原稿の文章をまとめて貼ると、質問ごとに見出し・問・答・答弁者に分けて入れます。"
                     "【見出し】の行は大まかな質問、【見出しの答】の行はそれへの答、"
                     "「問　」「答　」で始まる行は詳しい問と答、「答弁者」で始まる行は答弁した人です。")
        word = ttk.Button(row, text="Word から読み込む", command=self.import_question_word)
        word.pack(side="left")
        word._tip = "議員から Word で届いた1人分の原稿を読み込み、問と答に分けて入れます。"
        ttk.Button(row, text="メール本文を貼る", command=self.import_question_email).pack(side="left", padx=5)
        ttk.Button(row, text="確認用に印刷（1人）",
                   command=lambda: self.print_question_confirmation(True)).pack(side="left")
        ttk.Button(row, text="確認用に印刷（全員）", command=self.print_question_confirmation).pack(side="left")
        ttk.Label(self.inner, text=("取り込み後は必ず、問と答の分け方が正しいか原稿と見比べてください。"
                                    "手書きは見ながら入力し、確認用に印刷して議員に見てもらいます。"
                                    "顔写真枠は自動で入ります。"),
                  wraplength=900).pack(anchor="w", pady=5)

    def _features(self) -> list:
        """特集の一覧（前の版の 1 つだけの特集は、一覧の 1 件目に移す）。"""
        values = self.data.get("features")
        if not isinstance(values, list):
            values = []
        if not values:
            old = self.data.get("feature") or {}
            if old.get("title") or old.get("body"):
                values.append(dict(old))
        self.data["features"] = values
        self.data.pop("feature", None)
        return values

    def _step_10(self):
        self._title("特集")
        features = self._features()
        self._list_editor("特集（いくつでも入れられます。上から順に、特集のページへ続けて入ります）", features,
                          [("title", "題（大見出し）", False),
                           ("body", "本文（表を入れたい所に、行の頭から【表】表の名前 と書きます）", True)],
                          lambda v: v.get("title") or "（題なし）")
        self._word_button()
        table_list = self.data.setdefault("tables", [])
        self._list_editor("表（Word・エクセルで作った表。本文の【表】表の名前 の所に、ページの幅いっぱいで入ります）",
                          table_list,
                          [("name", "表の名前（本文の【表】の後ろに書く名前）", False),
                           ("data", "表の中身（1行が表の1行。列はタブか｜で区切ります。エクセルや Word の表をコピーして貼れます）", True)],
                          _table_summary)
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Word の表を読み込む", command=self.import_table_word).pack(side="left")
        ttk.Button(row, text="エクセルの表を読み込む", command=self.import_table_excel).pack(side="left", padx=5)
        ttk.Label(row, text="エクセルのファイルはこの画面へドロップしても読み込めます。").pack(side="left", padx=8)
        # 本文の【表】名前 と、表の一覧の名前が合っているかを知らせる
        names = {str(t.get("name", "")).strip() for t in table_list}
        problems = []
        used = set()
        for value in features:
            _body, missing = tables.fill_marks(value.get("body", ""), table_list)
            problems.extend(f"「{value.get('title') or '題なし'}」の本文の【表】{name} に合う表がありません" for name in missing)
            used.update(line.strip()[len(tables.MARK):].strip() for line in str(value.get("body", "")).splitlines()
                        if line.strip().startswith(tables.MARK))
        problems.extend(f"表「{name}」は、どの本文にも【表】{name} がないので紙面に出ません" for name in sorted(names - used) if name)
        if problems:
            ttk.Label(self.inner, text="・" + "\n・".join(problems), foreground="#a33",
                      wraplength=900, justify="left").pack(anchor="w", pady=4)

    def _add_tables(self, found, stem: str) -> None:
        """読み込んだ表を一覧に足し、最後の特集の本文の終わりに【表】名前 を書き足す。"""
        table_list = self.data.setdefault("tables", [])
        features = self._features()
        if not features:
            features.append({"title": "", "body": ""})
        names = {str(t.get("name", "")) for t in table_list}
        added = []
        for number, rows in enumerate(found, 1):
            name = stem if len(found) == 1 else f"{stem}の表{number}"
            base, extra = name, 2
            while name in names:
                name, extra = f"{base}_{extra}", extra + 1
            names.add(name)
            table_list.append({"name": name, "data": tables.rows_text(rows)})
            features[-1]["body"] = (str(features[-1].get("body", "")).rstrip() + "\n" + tables.MARK + name).strip()
            added.append(f"{name}（{len(rows)}行×{len(rows[0]) if rows else 0}列）")
        self.save(silent=True)
        self.show(self.step)
        messagebox.showinfo("表を読み込みました",
                            "\n".join(added) + "\n\n最後の特集の本文の終わりに【表】の行を書き足しました。"
                            "表を入れたい所へ、その行を動かしてください。", parent=self.root)

    def import_table_word(self, path=None) -> None:
        path = path or filedialog.askopenfilename(title="表のある Word を選ぶ", parent=self.root,
                                                  filetypes=[("Word", "*.docx")])
        if not path:
            return
        try:
            found = tables.read_word_tables(path)
        except Exception as error:
            messagebox.showerror("表を読めません", str(error), parent=self.root)
            return
        if not found:
            messagebox.showinfo("表がありません", "この Word には表が見つかりませんでした。", parent=self.root)
            return
        self._add_tables(found, Path(path).stem)

    def import_table_excel(self, path=None) -> None:
        path = path or filedialog.askopenfilename(title="表のエクセルを選ぶ", parent=self.root,
                                                  filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            rows = tables.read_excel_table(path)
        except Exception as error:
            messagebox.showerror("表を読めません", str(error), parent=self.root)
            return
        if not rows:
            messagebox.showinfo("表がありません", "このエクセルの最初のシートに字が見つかりませんでした。", parent=self.root)
            return
        self._add_tables([rows], Path(path).stem)

    def _step_11(self):
        self._title("最終ページ")
        value = self.data.setdefault("last", {})
        for key, label, height in (("editorial", "編集後記", 5), ("free", "自由欄", 7)):
            self._text(label, value.get(key, ""), lambda v, k=key: value.__setitem__(k, v), height)
        self._free_images(value)
        self._text("次回定例会", value.get("next_meeting", ""),
                   lambda v: value.__setitem__("next_meeting", v), 2)
        # 意見・提言は決まった文を使う。変える時だけ書く（空のままなら決まった文が入る）
        standard = templates.default_opinion(self.work.settings) if self.work else ""
        ttk.Label(self.inner, text="意見・提言は、ふだんは決まった文が入ります（下の欄は空のままで構いません）。"
                                   "変える時だけ書いてください。\n決まった文: " + standard,
                  foreground="#555", wraplength=900, justify="left").pack(anchor="w", pady=(6, 0))
        self._text("意見・提言（変える時だけ）", value.get("opinion", ""),
                   lambda v: value.__setitem__("opinion", "" if v.strip() == standard.strip() else v), 3)
        self._entry("傍聴案内の見出し", value.get("hearing_title", "議会を傍聴してみませんか"),
                    lambda v: value.__setitem__("hearing_title", v))
        self._entry("傍聴の呼びかけ", value.get("invitation", "お気軽に傍聴に、お越し下さい。"),
                    lambda v: value.__setitem__("invitation", v))

    def _free_images(self, value: dict) -> None:
        """自由欄に、写真や Word の図形を画像にしたものを、そのまま置く。"""
        images = value.setdefault("free_images", [])
        box = ttk.LabelFrame(self.inner, text="自由欄の画像（写真や、Word の四角い図形を画像にしたものを、そのまま置きます）",
                             padding=7)
        box.pack(fill="x", pady=5)
        listing = tk.Listbox(box, height=max(2, min(5, len(images))), font=(self.font, INPUT_PT),
                             exportselection=False)
        listing.pack(side="left", fill="x", expand=True)
        for name in images:
            listing.insert("end", name)
        buttons = ttk.Frame(box)
        buttons.pack(side="left", padx=(7, 0))

        def add(path=None):
            paths = [path] if path else filedialog.askopenfilenames(
                title="自由欄に置く画像を選ぶ", parent=self.root,
                filetypes=[("画像", "*.png *.jpg *.jpeg"), ("すべて", "*.*")])
            if not paths:
                return
            try:
                images.extend(self.work.add_photos([Path(p) for p in paths]))
            except Exception as error:
                messagebox.showerror("画像を入れられません", str(error), parent=self.root)
                return
            self.save(silent=True)
            self.show(self.step)

        def remove():
            selected = listing.curselection()
            if selected:
                images.pop(selected[0])
                self.save(silent=True)
                self.show(self.step)

        def move(delta):
            selected = listing.curselection()
            if selected and 0 <= selected[0] + delta < len(images):
                index = selected[0]
                images[index], images[index + delta] = images[index + delta], images[index]
                self.save(silent=True)
                self.show(self.step)
        self._free_image_add = add
        ttk.Button(buttons, text="画像を足す", command=add).pack(fill="x", pady=2)
        ttk.Button(buttons, text="外す", command=remove).pack(fill="x", pady=2)
        ttk.Button(buttons, text="上へ", command=lambda: move(-1)).pack(fill="x", pady=2)
        ttk.Button(buttons, text="下へ", command=lambda: move(1)).pack(fill="x", pady=2)
        ttk.Label(self.inner, text=("画像を入れると、自由欄（2〜4段目）に、縦横の割合を保って入るだけ大きく置きます。"
                                    "何枚かあるときは上から順に並べます。画像を入れたときは、上の自由欄の字は紙面に出ません。\n"
                                    "Word の四角い図形は、図形を右クリック →『図として保存』で PNG にしてから足します。"
                                    "画像のファイルは、この画面へドロップしても足せます。"),
                  foreground="#555", wraplength=900, justify="left").pack(anchor="w")

    def _step_12(self):
        self._title("写真")
        if not self.work:
            ttk.Label(self.inner, text="先に号を作るか開いてください。").pack(anchor="w")
            return
        ttk.Button(self.inner, text="写真を追加（誰の・どの記事かを指定）",
                   command=self.add_photos).pack(anchor="w", pady=5)
        photo_values = self.work.photo_files()
        names = [value["name"] for value in photo_values]
        self.photo_var = tk.StringVar(value=names[0] if names else "")
        self.photo_page = tk.StringVar(value="1")
        ttk.Label(self.inner, text="写真").pack(anchor="w")
        ttk.Combobox(self.inner, textvariable=self.photo_var, values=names, state="readonly").pack(fill="x")
        ttk.Label(self.inner, text="置くページ番号").pack(anchor="w", pady=(8, 0))
        ttk.Combobox(self.inner, textvariable=self.photo_page,
                     values=[str(p["no"]) for p in self.work.pages], state="readonly").pack(fill="x")
        self.photo_size = tk.StringVar(value="中")
        sizes = ttk.Frame(self.inner)
        sizes.pack(anchor="w", pady=6)
        ttk.Label(sizes, text="大きさ").pack(side="left")
        for size in ("特大", "大", "中", "小", "顔"):
            ttk.Radiobutton(sizes, text=size, value=size, variable=self.photo_size).pack(side="left", padx=4)
        self.photo_caption = tk.StringVar()
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="写真の説明", width=20).pack(side="left")
        ttk.Entry(row, textvariable=self.photo_caption).pack(side="left", fill="x", expand=True)
        ttk.Button(self.inner, text="このページの空いている所へ置く",
                   command=self.place_photo).pack(anchor="e", pady=8)
        ttk.Label(self.inner, text=("『紙面を見る』では、写真を置きたい所をクリックできます。"
                                    "置いた写真はドラッグで動かせ、本文が自動でよけ直します。"),
                  wraplength=900).pack(anchor="w")
        messages = [f"{v['name']}: {v['message']}" for v in photo_values if v.get("message")]
        if messages:
            ttk.Label(self.inner, text="\n".join(messages), foreground="#a33").pack(anchor="w", pady=5)

    def _step_13(self):
        self._title("全ページの確認")
        messages = self.work.check() if self.work else ["号を作るか開いてください。"]
        if self.work:
            if not self.data.get("votes_import"):
                messages.insert(0, "議案と賛否のExcelが未取り込みです")
            messages[0:0] = ["議案と賛否: " + warning
                             for warning in self.data.get("votes_warnings", [])]
            messages.extend(f"一般質問受付: {value['member']} {value['status']}"
                            for value in sources.reception_status(
                                self.work.settings.members, self.data.get("questions", []))
                            if value["status"] != "確認済み")
        listing = tk.Listbox(self.inner, height=20, font=(self.font, 11), exportselection=False)
        listing.pack(fill="both", expand=True)
        for message in messages or ["問題はありません。"]:
            listing.insert("end", message)

        def jump():
            selected = listing.curselection()
            if not selected or not self.work:
                return
            import re
            match = re.match(r"(?:× |・)?(\d+)ページ", listing.get(selected[0]))
            if not match:
                return
            section = self.work.pages[int(match.group(1)) - 1]["section"]
            target = self.SECTION_STEPS.get(section, 13)
            self.show(target)
        ttk.Button(self.inner, text="選んだページの入力へ戻る", command=jump).pack(anchor="e", pady=5)

    def _step_14(self):
        self._title("Word 出力")
        ttk.Button(self.inner, text="Wordを出力", command=self.export).pack(anchor="w", pady=10)
        self.output_label = ttk.Label(self.inner, text="出力すると、ここに保存先のフルパスを表示します。",
                                      wraplength=900, justify="left")
        self.output_label.pack(anchor="w")

    def _not_ready(self):
        self._title(guide.STEPS[self.step])

    def make_votes_template(self) -> None:
        path = filedialog.asksaveasfilename(title="ひな形の保存先", parent=self.root,
                                            defaultextension=".xlsx",
                                            filetypes=(("Excel ブック", "*.xlsx"),))
        if not path:
            return
        try:
            made = self.work.make_votes_template(Path(path))
            self.votes_path_label.configure(text=str(made))
        except Exception as error:
            messagebox.showerror("ひな形を作れません", str(error), parent=self.root)

    def import_votes(self, path=None) -> None:
        path = path or filedialog.askopenfilename(title="議案と賛否のExcelを選ぶ", parent=self.root,
                                                  filetypes=(("Excel ブック", "*.xlsx"),
                                                             ("すべて", "*.*")))
        if not path:
            return
        try:
            self.work.import_votes(Path(path), self.data)
            self.data = self.work.item_data()
            self.show(6)
        except Exception as error:
            messagebox.showerror("取り込めません", str(error), parent=self.root)

    def _person(self, member: str) -> dict:
        people = self.data.setdefault("questions", [])
        found = next((value for value in people if value.get("member") == member), None)
        if found is None:
            found = {"member": member, "title": "", "questions": [],
                     "confirmed": "未"}
            people.append(found)
        return found

    def _choose_member(self) -> str:
        members = self.work.settings.members if self.work else []
        value = simpledialog.askstring("議員を選ぶ", "議員名を入力してください。\n" +
                                       "／".join(members), parent=self.root)
        return str(value or "").strip()

    def _preview_source(self, member: str, parsed: dict, delivery: str,
                        original: str = "") -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("取り込む前の確認")
        self._big_window(dialog)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="問と答の分け方が正しいか、原稿と見比べてください。",
                  foreground="#933").pack(anchor="w")
        preview = tk.Text(body, height=8, wrap="word", font=(self.font, INPUT_PT))
        preview.insert("1.0", parsed.get("cleaned") or parsed.get("text") or original)
        preview.configure(state="disabled")
        preview.pack(fill="both", expand=True, pady=6)
        ttk.Label(body, text=("分割結果: " +
                              "／".join(f"問 {q.get('question', '')[:24]}・答 {q.get('answer', '')[:24]}"
                                        for q in parsed.get("questions", []))) or "問答を見つけられませんでした。",
                  wraplength=720, justify="left").pack(anchor="w")

        def accept():
            person = self._person(member)
            person["delivery"] = delivery
            person["confirmed"] = "未"
            person["questions"] = items.limit_questions(parsed.get("questions", []))
            person["qa_bulk"] = parsed.get("cleaned") or parsed.get("text") or original
            if original:
                saved = self.work.save_email_source(original, member)
                person["source_copy"] = saved.name
            elif parsed.get("copy_path"):
                person["source_copy"] = Path(parsed["copy_path"]).name
            dialog.destroy()
            self.show(9)
        ttk.Button(body, text="これで入れる", command=accept).pack(anchor="e", pady=6)
        dialog.grab_set()

    def import_question_word(self, path=None) -> None:
        member = self._choose_member()
        if not member:
            return
        path = path or filedialog.askopenfilename(title="Word 原稿を選ぶ", parent=self.root,
                                                  filetypes=(("Word", "*.docx *.doc"),))
        if not path:
            return
        try:
            parsed = self.work.import_word_source(Path(path), member)
            self._preview_source(member, parsed, "Word")
        except Exception as error:
            messagebox.showerror("Wordを読み込めません", str(error), parent=self.root)

    def bulk_question(self) -> None:
        member = self._choose_member()
        if not member:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("まとめて貼る")
        self._big_window(dialog)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="見出し、問、答を含む原稿を貼ってください。").pack(anchor="w")
        widget = tk.Text(body, height=8, wrap="word", font=(self.font, INPUT_PT), undo=True)
        widget.pack(fill="both", expand=True, pady=6)

        def preview():
            text = widget.get("1.0", "end-1c")
            parsed = items.parse_bulk(text)
            parsed["text"] = text
            dialog.destroy()
            self._preview_source(member, parsed, "その他")
        ttk.Button(body, text="分け方を確認する", command=preview).pack(anchor="e")
        dialog.grab_set()

    def import_question_email(self) -> None:
        member = self._choose_member()
        if not member:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("メール本文を貼る")
        self._big_window(dialog)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="メール本文をそのまま貼ってください。候補は勝手に消しません。").pack(anchor="w")
        widget = tk.Text(body, height=8, wrap="word", font=(self.font, INPUT_PT), undo=True)
        widget.pack(fill="both", expand=True, pady=6)

        def next_step():
            original = widget.get("1.0", "end-1c")
            candidates = sources.email_candidates(original)
            dialog.destroy()
            choice = tk.Toplevel(self.root)
            choice.title("外す候補と整えた結果")
            self._big_window(choice)
            frame = ttk.Frame(choice, padding=10)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="外す行だけにチェックしてください。チェックしない行は残ります。").pack(anchor="w")
            flags = []
            for candidate in candidates:
                var = tk.BooleanVar(value=False)
                flags.append((var, candidate["line"]))
                ttk.Checkbutton(frame, variable=var,
                                text=f"{candidate['line']}行目 {candidate['reason']}: {candidate['text'][:70]}").pack(anchor="w")
            preview = tk.Text(frame, height=8, wrap="word", font=(self.font, INPUT_PT))
            preview.pack(fill="both", expand=True, pady=6)

            def refresh():
                parsed = sources.prepare_email(original, [line for var, line in flags if var.get()])
                preview.configure(state="normal")
                preview.delete("1.0", "end")
                preview.insert("1.0", parsed["cleaned"])
                preview.configure(state="disabled")
                choice._parsed = parsed
            for var, _line in flags:
                var.trace_add("write", lambda *_args: refresh())
            refresh()
            ttk.Label(frame, text="問と答の分け方が正しいか、原稿と見比べてください。",
                      foreground="#933").pack(anchor="w")

            def accept():
                parsed = choice._parsed
                person = self._person(member)
                person.update({"delivery": "メール", "confirmed": "未",
                               "questions": items.limit_questions(parsed["questions"]),
                               "qa_bulk": parsed["cleaned"]})
                person["source_copy"] = self.work.save_email_source(original, member).name
                choice.destroy()
                self.show(9)
            ttk.Button(frame, text="これで入れる", command=accept).pack(anchor="e")
            choice.grab_set()
        ttk.Button(body, text="外す候補と整えた結果を見る", command=next_step).pack(anchor="e")
        dialog.grab_set()

    def print_question_confirmation(self, one: bool = False) -> None:
        try:
            people = self.data.get("questions", [])
            member = "全員"
            if one:
                member = self._choose_member()
                if not member:
                    return
                people = [value for value in people if value.get("member") == member]
                if not people:
                    raise ValueError("その議員の入力内容がありません。")
            path = self.work.write_question_confirmation(people, member)
            messagebox.showinfo("確認用Wordを作りました", str(path), parent=self.root)
        except Exception as error:
            messagebox.showerror("確認用Wordを作れません", str(error), parent=self.root)

    # ---- 行政報告・委員会報告・特集の Word ----
    ARTICLE_STEPS = {4: "行政報告", 8: "委員会報告", 10: "特集"}

    def _big_window(self, dialog) -> None:
        """取り込み・貼り付けの窓を、画面の高さいっぱいにする（役場の 1366×768 の画面でも欄が広く、ボタンも隠れない）。"""
        width = min(self.root.winfo_screenwidth() - 60, 1000)
        height = max(520, self.root.winfo_screenheight() - 100)
        dialog.geometry(f"{width}x{height}+20+10")

    @staticmethod
    def _tip_for(widget) -> str:
        """マウスを合わせた部品の説明。widget._tip があればそれ、無ければボタンの字から探す。"""
        own = getattr(widget, "_tip", None)
        if own:
            return own
        if widget.winfo_class() in ("TButton", "TCheckbutton"):
            return guide.button_tip(str(widget.cget("text")))
        return ""

    def _word_button(self) -> None:
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="Word から読み込む", command=self.import_article_word).pack(side="left")
        hint = ("Word ファイルをこの画面へドロップしても読み込めます。" if self.drop_ready
                else "Word ファイルを選んで読み込みます。")
        ttk.Label(row, text=hint + "見出しごとに分けて、今の内容の後ろに足します。").pack(side="left", padx=8)

    def import_article_word(self, path=None) -> None:
        label = self.ARTICLE_STEPS.get(self.step)
        if not label or not self.work:
            return
        path = path or filedialog.askopenfilename(title=label + "の Word を選ぶ", parent=self.root,
                                                  filetypes=(("Word", "*.docx *.doc"),))
        if not path:
            return
        try:
            parsed = sources.read_word_articles(Path(path))
        except Exception as error:
            messagebox.showerror("Wordを読み込めません", str(error), parent=self.root)
            return
        self._preview_articles(label, Path(path), parsed)

    def _preview_articles(self, label: str, path: Path, parsed: dict) -> None:
        """読み込んだ中身を見せ、「これで入れる」を押したときだけ入れる。"""
        dialog = tk.Toplevel(self.root)
        dialog.title(label + "の Word を確かめる")
        self._big_window(dialog)
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        articles = parsed["articles"]
        notes = [f"{len(articles)} 件に分けました。見出しと本文の分け方が原稿と合っているか見比べてください。"]
        if parsed["titles"]:
            notes.append("大見出し『" + "』『".join(parsed["titles"]) + "』は本文に入れません（大見出しは欄で決めます）。")
        if parsed["photos"]:
            notes.append(f"Word の中の写真 {len(parsed['photos'])} 枚は号の「写真」フォルダへ写します。"
                         "紙面には「写真」の手順で置いてください。")
        notes.extend(parsed["warnings"])
        ttk.Label(body, text="\n".join(notes), wraplength=720, justify="left").pack(anchor="w")
        view = tk.Text(body, height=8, wrap="word", font=(self.font, INPUT_PT))
        for article in articles:
            view.insert("end", "■ " + (article["heading"] or "（見出しなし）") + "\n")
            view.insert("end", article["body"] + "\n\n")
        view.configure(state="disabled")
        view.pack(fill="both", expand=True, pady=6)

        def accept() -> None:
            try:
                result = self.work.import_word_articles(path, label)
            except Exception as error:
                messagebox.showerror("Wordを読み込めません", str(error), parent=dialog)
                return
            self._add_articles(label, result)
            self.data.setdefault("photos", []).extend(
                {"file": photo["file"], "member": label, "article": label}
                for photo in result["photos"])
            self.work.save_items(self.data)
            dialog.destroy()
            self.show(self.step)
            self.fit_label.configure(text=f"{label}に {len(result['articles'])} 件を足しました")

        row = ttk.Frame(body)
        row.pack(fill="x")
        ttk.Button(row, text="これで入れる", command=accept).pack(side="right")
        ttk.Button(row, text="やめる", command=dialog.destroy).pack(side="right", padx=6)

    def _add_articles(self, label: str, result: dict) -> None:
        articles, titles = result["articles"], result["titles"]
        if label == "行政報告":
            self.data.setdefault("gyosei", {"title": items.GYOSEI_TITLE, "reports": []}) \
                .setdefault("reports", []).extend(articles)
        elif label == "委員会報告":
            committee = titles[0] if titles else ""
            self.data.setdefault("committees", []).extend(
                {"committee": committee, "heading": a["heading"], "body": a["body"]} for a in articles)
        else:
            # Word の特集は、新しい特集として一覧の終わりに足す
            feature = {"title": titles[0] if titles else "", "body": ""}
            self._features().append(feature)
            lines = [feature.get("body", "")] if feature.get("body") else []
            for article in articles:
                if article["heading"]:
                    lines.append("【見出し】" + article["heading"])
                lines.append(article["body"])
            feature["body"] = "\n".join(line for line in lines if line)

    # ---- ドロップ ----
    def on_drop(self, paths) -> None:
        """落とされたファイルを、いまの手順に合う取り込みへ渡す。"""
        if not paths:
            return
        if not self.work:
            messagebox.showinfo("号を選んでください", "最初に新しい号を作るか、続きを開いてください。", parent=self.root)
            return
        if len(paths) > 1:
            messagebox.showinfo("1つずつ落としてください",
                                "一度に読み込めるのは1つのファイルです。", parent=self.root)
            return
        path = Path(paths[0])
        suffix = path.suffix.lower()
        self.save(silent=True)
        if suffix in (".docx", ".doc") and self.step in self.ARTICLE_STEPS:
            self.import_article_word(path)
        elif suffix in (".docx", ".doc") and self.step == 9:
            self.import_question_word(path)
        elif suffix in (".xlsx", ".xls") and self.step == 6:
            self.import_votes(path)
        elif suffix in (".xlsx", ".xls") and self.step == 10:
            self.import_table_excel(path)
        elif suffix in (".jpg", ".jpeg", ".png", ".heic") and self.step in (5, 12):
            self.add_photos(path)
        elif suffix in (".jpg", ".jpeg", ".png") and self.step == 11:
            self._free_image_add(path)
        else:
            messagebox.showinfo(
                "この手順では読み込めません",
                "落とせるファイルは手順ごとに決まっています。\n"
                "・Word: 行政報告・委員会報告・一般質問・特集\n"
                "・エクセル: 議案と賛否・特集（表）\n"
                "・写真: 写真（10月号は 予算・決算 でも）・最終ページ（自由欄の画像）", parent=self.root)

    def bulk_into(self, value: dict) -> None:
        text = simpledialog.askstring("まとめて貼る", "見出し、問、答を含む文章を貼り付けてください。", parent=self.root)
        if text is not None:
            parsed = items.parse_bulk(text)
            value["summary"] = (value.get("summary", "") + "\n" + parsed["body"]).strip()
            value.setdefault("questions", []).extend(parsed["questions"])
            self.show(self.step)

    def _prepare_nested(self) -> None:
        for bill in self.data.get("shingi", {}).get("bills", []):
            if bill.get("qa_bulk"):
                parsed = items.parse_bulk(bill["qa_bulk"])
                bill["questions"] = parsed["questions"]
                if parsed["body"] and parsed["body"] not in bill.get("description", ""):
                    bill["description"] = (bill.get("description", "") + "\n" + parsed["body"]).strip()
        for person in self.data.get("questions", []):
            if person.get("qa_bulk"):
                person["questions"] = items.limit_questions(
                    items.parse_bulk(person["qa_bulk"])["questions"])

    def save(self, silent=False, complete=False) -> bool:
        if not self.work:
            return True
        try:
            for getter in self.getters:
                getter()
            if self.step == 2:
                members = [line.strip() for line in getattr(self, "_member_text", "").splitlines() if line.strip()]
                self.work.save_settings(members, getattr(self, "_chair", ""))
            self._prepare_nested()
            if complete and guide.STEPS[self.step] not in self.data.setdefault("completed", []):
                self.data["completed"].append(guide.STEPS[self.step])
            self.work.save_items(self.data)
            self.issue_label.configure(text=self.work.issue.title)
            if not silent:
                self.fit_label.configure(text="保存しました")
            return True
        except Exception as error:
            if not silent:
                messagebox.showerror("保存できません", str(error), parent=self.root)
            return False

    def next(self) -> None:
        if not self.work and self.step > 0:
            messagebox.showinfo("号を選んでください", "最初に新しい号を作るか、続きを開いてください。")
            self.show(0)
            return
        # 入力欄の内容を先に読み込んでから空欄を確かめる（読む前だと入れた値も空に見える）。
        try:
            for getter in self.getters:
                getter()
        except Exception as error:
            messagebox.showerror("入力を確かめてください", str(error), parent=self.root)
            return
        missing = self._missing_reason()
        if missing and not messagebox.askyesno("空欄があります", missing + "\n\n空のまま進みますか？", parent=self.root):
            return
        if self.save(complete=True):
            self.show(min(self.step + 1, len(guide.STEPS) - 1))

    def back(self) -> None:
        self.save(silent=True)
        self.show(max(0, self.step - 1))

    def _missing_reason(self) -> str:
        if self.step == 1:
            issue = self.data.get("issue", {})
            if int(issue.get("month") or 0) not in layout.MONTHS:
                return "発行月は 4・5・7・10・1 のどれかを数字で入れてください。"
            if not issue.get("number") or not issue.get("date"):
                return "号数または発行日が空です。表紙と出力名に必要です。"
        if self.step == 2 and not getattr(self, "_member_text", "").strip():
            return "議員名簿が空です。賛否表の列を作れません。"
        if self.step == 9 and not self.data.get("questions"):
            return "一般質問が0人です。一般質問ページは作られません。"
        return ""

    def new_issue(self) -> None:
        folder = filedialog.askdirectory(title="新しい号を保存するフォルダを選ぶ", parent=self.root)
        if not folder:
            return
        try:
            self.work = edition.Edition.create(Path(folder), layout.Issue(0, 4))
            self.data = items.default_data(self.work.issue)
            self.work.save_items(self.data)
            self.issue_label.configure(text=self.work.issue.title)
            self.show(1)
        except Exception as error:
            messagebox.showerror("作成できません", str(error), parent=self.root)

    def open_issue(self, folder=None, step: int = 1) -> None:
        folder = folder or filedialog.askdirectory(title="号フォルダを選ぶ", parent=self.root)
        if not folder:
            return
        try:
            self.work = edition.Edition.open(Path(folder))
            self.data = self.work.item_data()
            self.issue_label.configure(text=self.work.issue.title)
            self.show(step)
        except Exception as error:
            messagebox.showerror("開けません", str(error), parent=self.root)

    def add_photos(self, path=None) -> None:
        path = path or filedialog.askopenfilename(title="JPEGまたはPNGを選ぶ", parent=self.root,
                                                  filetypes=(("写真", "*.jpg *.jpeg *.png"),
                                                             ("すべて", "*.*")))
        if not path:
            return
        member = simpledialog.askstring("誰の写真か", "議員名（または担当名）を入力してください。",
                                        parent=self.root)
        if member is None:
            return
        articles = [v.get("title", "") for v in self.data.get("questions", [])]
        articles += [v.get("title", "") for v in self.data.get("shingi", {}).get("bills", [])]
        article = simpledialog.askstring("どの記事か", "記事名を入力してください。\n" +
                                         "／".join(v for v in articles if v), parent=self.root)
        if article is None:
            return
        try:
            result = self.work.add_received_photo(Path(path), member, article)
            self.data.setdefault("photos", []).append({
                "file": result["name"], "member": member, "article": article})
            self.work.save_items(self.data)
            notice = result["warning"] or f"解像度の目安は {result['dpi']}dpi です。"
            messagebox.showinfo("写真を追加しました", f"{result['path']}\n{notice}", parent=self.root)
            self.show(self.step)
        except Exception as error:
            messagebox.showerror("写真を追加できません", str(error), parent=self.root)

    def place_photo(self) -> None:
        try:
            page = int(self.photo_page.get())
            actual, shifted = self.work.place_photo_near(
                page, self.photo_var.get(), Rect(0, 0, 1, 1),
                self.photo_size.get(), self.photo_caption.get())
            if shifted:
                self.fit_label.configure(text=(f"置ける所へ寄せました: {actual.dan + 1}段目・"
                                               f"右から{actual.line + 1}行目"))
            self._fit_summary()
        except Exception as error:
            messagebox.showerror("配置できません", str(error), parent=self.root)

    def _fit_summary(self) -> None:
        if not self.work or self.step in (0, 14):
            self.fit_label.configure(text="")
            return
        try:
            results = [self.work.compose(page["no"]) for page in self.work.pages]
            overflow = sum(value.overflow_lines for value in results)
            free = sum(value.free_lines for value in results)
            self.fit_label.configure(text=f"全体: あふれ {overflow}行（約{overflow * 12}字）／余り {free}行")
        except Exception as error:
            self.fit_label.configure(text=str(error))

    def preview(self) -> None:
        if not self.work:
            messagebox.showinfo("紙面", "先に号を作るか開いてください。")
            return
        if not self.save():   # 保存できない（ページ割りの決まりに合わない等）ときは、理由を出して止める
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("紙面を見る")
        # 画面の高さいっぱいの窓にする（紙面の字が読める大きさで描くため）
        screen_h = self.root.winfo_screenheight()
        height = max(600, screen_h - 90)
        width = min(self.root.winfo_screenwidth() - 40, 1100)
        dialog.geometry(f"{width}x{height}+20+10")
        top = ttk.Frame(dialog, padding=(6, 6, 6, 0))
        top.pack(fill="x")
        page_var = tk.IntVar(value=self._preview_page())
        # ページの状況（あふれ・余り）は、ボタンの下の段に出す（窓が狭くてもボタンが隠れないように）
        # 写真を置く: ここで写真を選んでから、紙面の置きたい所をクリックする（どの手順からでも置ける）
        NONE = "（置かない）"
        photo_row = ttk.Frame(dialog, padding=(6, 4, 6, 0))
        photo_row.pack(fill="x")
        ttk.Label(photo_row, text="置く写真").pack(side="left")
        photo_names = [value["name"] for value in self.work.photo_files()]
        chosen = getattr(self, "photo_var", None)
        place_var = tk.StringVar(value=NONE)
        place_box = ttk.Combobox(photo_row, textvariable=place_var, values=[NONE] + photo_names,
                                 state="readonly", width=34)
        place_box.pack(side="left", padx=4)
        place_size = tk.StringVar(value=getattr(self, "photo_size", None).get()
                                  if getattr(self, "photo_size", None) else "中")
        ttk.Label(photo_row, text="大きさ").pack(side="left", padx=(8, 0))
        ttk.Combobox(photo_row, textvariable=place_size, values=["特大", "大", "中", "小", "顔"],
                     state="readonly", width=5).pack(side="left", padx=4)
        ttk.Label(dialog, text="写真を選んでから、紙面の置きたい所をクリックします。置いた写真はドラッグで動かせます。"
                               "（写真は『写真』の手順の『写真を追加』で号に入れておきます）",
                  foreground="#555", padding=(8, 2, 8, 0)).pack(fill="x")
        if self.step == 12 and chosen is not None and chosen.get() in photo_names:
            place_var.set(chosen.get())
        status = ttk.Label(dialog, padding=(8, 2, 8, 4))
        status.pack(fill="x")
        drag = {"part": None}
        # 最初は窓の幅いっぱいに描く（字が読める大きさ。上下はホイールでスクロール）。
        view = {"zoom": 1.0, "mode": "width", "scale": 1.0, "ox": 12.0, "oy": 12.0}
        area = ttk.Frame(dialog)
        area.pack(fill="both", expand=True)
        paper = tk.Canvas(area, bg="#d9dde3", highlightthickness=0)
        down = ttk.Scrollbar(area, orient="vertical", command=paper.yview)
        across = ttk.Scrollbar(area, orient="horizontal", command=paper.xview)
        paper.configure(yscrollcommand=down.set, xscrollcommand=across.set)
        paper.grid(row=0, column=0, sticky="nsew")
        down.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)

        def draw():
            number = page_var.get()
            self.preview_pages[self.step] = number
            result = self.work.compose(number)
            paper.delete("all")
            dialog.update_idletasks()
            # 「幅」は紙面の幅が窓の幅に、「全体」は紙面の高さが窓の高さに入る倍率。拡大・縮小はそれに掛ける。
            if view["mode"] == "width":
                fit = max(0.4, (paper.winfo_width() - 24) / 595)
            else:
                fit = max(0.4, (paper.winfo_height() - 24) / 842)
            scale = fit * view["zoom"]
            page_w, page_h = 595 * scale, 842 * scale
            ox = max(12, (paper.winfo_width() - page_w) / 2)
            oy = 12
            view.update(scale=scale, ox=ox, oy=oy)
            paper.create_rectangle(ox, oy, ox + page_w, oy + page_h, fill="white", outline="#777")
            paper.configure(scrollregion=(0, 0, ox + page_w + 12, oy + page_h + 12))
            # 部品の種類ごとの色を薄く敷き、その上に Word へ出すのと同じ枠・文字・表・写真を描く。
            # 決まった型のページ（表紙・審議・最終）は格子と枠の位置が違うので、色は敷かない。
            flow_page = "form" not in self.work.pages[number - 1]
            for placement in (result.placements if flow_page else []):
                actual = to_box(self.work.geometry, placement.rect)
                x1, y1 = ox + actual.x * scale, oy + actual.y * scale
                x2, y2 = x1 + actual.w * scale, y1 + actual.h * scale
                paper.create_rectangle(x1, y1, x2, y2, outline="",
                                       fill=COLORS.get(placement.part.kind, "#eeeeee"))
            _draw_items(paper, result.page.items, scale, ox, oy, self.font)
            status.configure(text=(f"{number}ページ　あふれ {result.overflow_lines}行"
                                   f"（約{result.overflow_lines * 12}字）／余り {result.free_lines}行"))
        def turn(delta: int) -> None:
            """前のページ・次のページへ。最初と最後では止まる。"""
            page_var.set(max(1, min(len(self.work.pages), page_var.get() + delta)))
            draw()
            paper.yview_moveto(0)

        wheel_turn = {"at": 0.0}

        def turn_by_wheel(delta: int) -> None:
            """ホイールでのページ送り。次のページは上から、前のページは下から見せる。
            続けて回したときに何ページも飛ばないよう、送ったあと少しのあいだは送らない。"""
            import time
            now = time.monotonic()
            if now - wheel_turn["at"] < 0.6:
                return
            number = page_var.get() + delta
            if not 1 <= number <= len(self.work.pages):
                return
            wheel_turn["at"] = now
            page_var.set(number)
            draw()
            paper.yview_moveto(0 if delta > 0 else 1)
        paper._turn_page = turn_by_wheel
        ttk.Button(top, text="◀ 前のページ", command=lambda: turn(-1)).pack(side="left", padx=(0, 4))
        chooser = ttk.Combobox(top, textvariable=page_var, values=[p["no"] for p in self.work.pages],
                               state="readonly", width=5)
        chooser.pack(side="left")
        chooser.bind("<<ComboboxSelected>>", lambda _e: (draw(), paper.yview_moveto(0)))

        def catch_up(event):
            """紙面を見るの窓へ戻ってきたら、元の画面で足した・直した内容で描き直す
            （一般質問に議員を足すとページが増えるので、ページの一覧も作り直す）。"""
            if event.widget is not dialog or not self.save(silent=True):
                return
            chooser.configure(values=[p["no"] for p in self.work.pages])
            if page_var.get() > len(self.work.pages):
                page_var.set(len(self.work.pages))
            draw()
        dialog.bind("<FocusIn>", catch_up)
        ttk.Button(top, text="次のページ ▶", command=lambda: turn(1)).pack(side="left", padx=4)
        # キーボードの ← → と PageUp・PageDown でもページを送る
        for key, delta in (("<Left>", -1), ("<Right>", 1), ("<Prior>", -1), ("<Next>", 1)):
            dialog.bind(key, lambda _e, d=delta: turn(d))
        ttk.Button(top, text="元に戻す", command=lambda: (self.work.undo(), draw())).pack(side="left")
        ttk.Button(top, text="やり直す", command=lambda: (self.work.redo(), draw())).pack(side="left", padx=4)

        def zoom(factor=None, mode=None):
            if mode:
                view.update(mode=mode, zoom=1.0)
            else:
                view["zoom"] = max(0.3, min(4.0, view["zoom"] * factor))
            draw()
            if mode:
                paper.yview_moveto(0)
        ttk.Button(top, text="拡大", command=lambda: zoom(1.25)).pack(side="left", padx=(12, 2))
        ttk.Button(top, text="縮小", command=lambda: zoom(0.8)).pack(side="left", padx=2)
        ttk.Button(top, text="幅に合わせる", command=lambda: zoom(mode="width")).pack(side="left", padx=2)
        ttk.Button(top, text="全体", command=lambda: zoom(mode="page")).pack(side="left", padx=2)
        paper.bind("<Control-MouseWheel>", lambda e: (zoom(1.1 if e.delta > 0 else 0.9), "break")[1])
        resize = {"size": None}

        def on_resize(event):
            # 窓の大きさを変えたら描き直す（全体表示のときだけ。拡大中は位置を保つ）
            if event.widget is dialog and view["zoom"] == 1.0 and resize["size"] != (event.width, event.height):
                resize["size"] = (event.width, event.height)
                draw()
        dialog.bind("<Configure>", on_resize)

        def page_point(event):
            """画面の点を、紙面の位置（pt）に直す。スクロールと拡大を考える。"""
            x, y = paper.canvasx(event.x), paper.canvasy(event.y)
            return (x - view["ox"]) / view["scale"], (y - view["oy"]) / view["scale"]

        def grid_at(event):
            point_x, point_y = page_point(event)
            g = self.work.geometry
            dan = round((point_y - g.margin_top_mm * 72 / 25.4) / (g.dan_h_pt + g.gap_pt))
            right = (g.page_w_mm - g.margin_right_mm) * 72 / 25.4
            line = int((right - point_x) / g.line_pitch_pt)
            return Rect(max(0, min(g.dans - 1, dan)),
                        max(0, min(g.lines_per_dan - 1, line)), 1, 1)

        def press(event):
            point_x, point_y = page_point(event)
            result = self.work.compose(page_var.get())
            drag["part"] = None
            for placement in reversed(result.placements):
                if placement.part.kind != "写真":
                    continue
                box = to_box(self.work.geometry, placement.rect)
                if box.x <= point_x <= box.x + box.w and box.y <= point_y <= box.y + box.h:
                    drag["part"] = placement.index
                    return

        def release(event):
            try:
                target = grid_at(event)
                if drag["part"] is None:
                    if place_var.get() in ("", NONE):
                        return   # 写真を選んでいないクリックは何もしない（ダブルクリックで直す窓を開くため）
                    caption = self.photo_caption.get() if getattr(self, "photo_caption", None) else ""
                    actual, shifted = self.work.place_photo_near(
                        page_var.get(), place_var.get(), target, place_size.get(), caption)
                    place_var.set(NONE)   # 続けてクリックしても同じ写真が増えないように
                    self.save(silent=True)
                else:
                    actual, shifted = self.work.move_part_near(page_var.get(), drag["part"], target)
                if shifted:
                    status.configure(text=(f"置ける所へ寄せました: {actual.dan + 1}段目・"
                                           f"右から{actual.line + 1}行目"))
                draw()
                result = self.work.compose(page_var.get())
                if result.overflow_lines:
                    messagebox.showwarning("本文があふれました",
                                           f"{result.overflow_lines}行あふれています。\n"
                                           "写真を小さくする／次のページへ送る／本文を削る、のいずれかで直してください。",
                                           parent=dialog)
            except Exception as error:
                messagebox.showerror("写真を置けません", str(error), parent=dialog)
            finally:
                drag["part"] = None
        def jump_to_input(event):
            """ダブルクリックした所を直す。賛否表の行・審議の「◎件名」ならその件名を直す窓を開き、
            ほかはその入力欄の手順へ移る（賛否表の見出しなら議案と賛否の手順）。"""
            point_x, point_y = page_point(event)
            page = self.work.pages[page_var.get() - 1]
            result = self.work.compose(page_var.get())
            hit = [item for item in result.page.items
                   if getattr(item, "box", None) is not None
                   and item.box.x <= point_x <= item.box.x + item.box.w
                   and item.box.y <= point_y <= item.box.y + item.box.h]
            table = next((item for item in hit if isinstance(item, dx.Table) and item.name == "賛否表"), None)
            in_votes = table is not None
            if table is not None:
                row = _table_row(table, point_y)
                if row is not None and 1 <= row <= len(self.data.get("votes", []) or []):
                    self._edit_vote(row - 1, parent=dialog, done=draw)
                    return
            if page["section"] == layout.SHINGI:
                bills = self.data.get("shingi", {}).get("bills", []) or []
                heading = next((item for item in hit if isinstance(item, dx.TextBox) and item.name == "議案"), None)
                index = _bill_index(bills, heading, result.page.items)
                if index is not None:
                    self._edit_bill_title(index, parent=dialog, done=draw)
                    return
                # 説明・質疑・問・答の所なら、その案件の説明と質疑を直す窓を開く
                spot = _shingi_spot(bills, self.work, result.placements, point_x, point_y)
                if spot is not None:
                    self._edit_bill_qa(spot[0], spot[1], parent=dialog, done=draw)
                    return
            target = 6 if in_votes else self.SECTION_STEPS.get(page["section"], self.step)
            self.save(silent=True)
            self.show(target)
            self.root.lift()
            self.fit_label.configure(text=f"{page_var.get()}ページの入力欄です。直したら『紙面を見る』で確かめてください。")
        paper.bind("<Double-Button-1>", jump_to_input)
        paper.bind("<ButtonPress-1>", press)
        paper.bind("<ButtonRelease-1>", release)
        draw()

    # 区分ごとの入力欄の手順（紙面を見るのダブルクリック・全ページの確認から戻るときに使う）
    SECTION_STEPS = {layout.COVER: 3, layout.GYOSEI: 4, layout.YOSAN: 5, layout.KESSAN: 5,
                     layout.SHINGI: 7, layout.IINKAI: 8, layout.IPPAN: 9, layout.TOKUSHU: 10,
                     layout.LAST: 11}

    # 手順ごとに、紙面を見るで最初に出す区分（名簿・議案と賛否は賛否表のある審議のページ）
    PREVIEW_SECTIONS = {1: (layout.COVER,), 2: (layout.SHINGI,), 3: (layout.COVER,),
                        4: (layout.GYOSEI,), 5: (layout.YOSAN, layout.KESSAN),
                        6: (layout.SHINGI,), 7: (layout.SHINGI,), 8: (layout.IINKAI,),
                        9: (layout.IPPAN,), 10: (layout.TOKUSHU,), 11: (layout.LAST,)}

    def _preview_page(self) -> int:
        """紙面を見るで最初に出すページ。今編集している手順の項目のページから出す。

        同じ手順で前に見ていたページがその項目のページなら、そこから出す（一般質問が
        何ページもあるとき、毎回先頭に戻らないように）。写真の手順は選んでいるページ。
        """
        pages = self.work.pages
        numbers = [p["no"] for p in pages]
        if self.step == 12:
            try:
                page = int(self.photo_page.get())
            except (AttributeError, ValueError, tk.TclError):
                page = None
            if page in numbers:
                return page
        last = self.preview_pages.get(self.step)
        sections = self.PREVIEW_SECTIONS.get(self.step)
        if sections is None:
            # 写真・全ページの確認など、決まった項目のない手順は前に見ていたページから
            return last if last in numbers else 1
        mine = [p["no"] for p in pages if p["section"] in sections]
        # 一般質問は 1 人 1 ページなので、一覧で選んでいる（足したばかりの）人のページから出す
        chosen = self.list_selection.get(self.step)
        if self.step == 9 and chosen is not None and chosen < len(mine):
            return mine[chosen]
        if last in mine:
            return last
        return mine[0] if mine else 1

    def export(self) -> None:
        if not self.work or not self.save():
            return
        try:
            paths = self.work.export()
            self.output_label.configure(text="出力先:\n" + "\n".join(str(path) for path in paths))
        except Exception as error:
            messagebox.showerror("出力できません", str(error), parent=self.root)


def main() -> int:
    try:
        root = tk.Tk()
        App(root)
    except Exception:
        _report_start_error()
        return 1
    root.mainloop()
    return 0


def _report_start_error() -> None:
    """app.pyw は黒い窓を出さないので、起動で失敗した理由をファイルと窓で知らせる。"""
    import traceback
    detail = traceback.format_exc()
    path = Path(__file__).resolve().parent / "起動エラー.txt"
    try:
        path.write_text(detail, encoding="utf-8")
    except OSError:
        pass
    try:
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror("議会だより編集 V7 を起動できません",
                             "起動の途中で止まりました。次のファイルの中身を担当者に見せてください。\n"
                             f"{path}\n\n{detail[-600:]}")
        window.destroy()
    except Exception:
        pass


# 最後に開いていた号フォルダと手順。号の中身は入れない（号フォルダの項目.json にある）。
RESUME_PATH = Path(__file__).resolve().parent / "前回の続き.json"


def _read_resume() -> dict:
    try:
        value = json.loads(RESUME_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# 縦書きで向きを変えて描く字（Word は縦書きの枠で自動で回す）。
TURN_IN_VERTICAL = set("ー―‐－-～〜…‥（）()「」『』【】〔〕［］[]｛｝{}＜＞<>《》〈〉＝=")


def _draw_items(canvas, items, scale: float, ox: float, oy: float, family: str) -> None:
    """紙面の枠・文字・表・写真を、確認用に大まかに描く。最終の見た目は Word で確かめる。"""
    for item in items:
        box = getattr(item, "box", None)
        if box is None or isinstance(item, dx.Guide):
            continue
        x1, y1 = ox + box.x * scale, oy + box.y * scale
        x2, y2 = x1 + box.w * scale, y1 + box.h * scale
        if isinstance(item, dx.TextBox):
            if item.border:
                draw = canvas.create_oval if getattr(item, "shape", "rect") == "ellipse" else canvas.create_rectangle
                draw(x1, y1, x2, y2, outline="#222")
            _draw_text(canvas, item, x1, y1, x2, y2, scale, family)
        elif isinstance(item, dx.Table):
            _draw_table(canvas, item, x1, y1, scale, family)
        elif isinstance(item, dx.Picture):
            try:   # 縦横の割合を保って枠に収めた、実際に入る大きさで描く
                width, height = dx.picture_size(item)
                x1 = x1 + (box.w - width) / 2 * scale
                x2, y2 = x1 + width * scale, y1 + height * scale
            except (ValueError, ZeroDivisionError):
                pass
            canvas.create_rectangle(x1, y1, x2, y2, fill="#9bd8ea", outline="#5a9fb5")
            canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="写真\n" + (item.caption or "")[:20],
                               width=max(20, x2 - x1 - 4), font=(family, -9))
        elif isinstance(item, dx.Placeholder):
            canvas.create_rectangle(x1, y1, x2, y2, outline="#5a9fb5", dash=(3, 2), fill="#eef8fb")
            canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=item.label[:12],
                               width=max(20, x2 - x1 - 4), font=(family, -8))


def _draw_text(canvas, item, x1, y1, x2, y2, scale, family) -> None:
    """文字の枠を描く。画面の字の形は Word と少し違うので、字が枠からはみ出さないよう
    1 行が枠に入りきらないときは字を詰めて小さくする（Word の紙面は変えない）。"""
    size = max(4, round(item.pt * scale))
    weight = "bold" if item.bold else "normal"
    pitch = dx.effective_pitch(item.pt, item.pitch_pt) * scale
    colors = getattr(item, "line_colors", None) or []

    def color(index):
        return "#" + colors[index] if index < len(colors) and colors[index] else "black"
    if item.vertical:
        total = len(item.lines) * pitch
        first = ((x1 + x2) / 2 + total / 2 - pitch / 2) if item.center else (x2 - pitch / 2)
        room = max(1.0, (y2 - y1) - 2)
        for index, line in enumerate(item.lines):
            pieces = units(line)
            need = sum(unit_width(unit) for unit in pieces) * size
            step = min(1.0, room / need) if need else 1.0
            # 字の大きさは送りより少し小さくし、隣の字や枠の下端に重ならないようにする
            glyph = max(4, int(size * step * 0.92))
            font = (family, -glyph, weight)
            x, y = first - index * pitch, y1 + 1
            fill = color(index)
            for unit in pieces:
                height = unit_width(unit) * size * step
                if TATECHUYOKO.fullmatch(unit):
                    canvas.create_text(x, y + height / 2, text=unit, fill=fill,
                                       font=_tcy_font(family, glyph, item.bold, unit))
                elif unit in TURN_IN_VERTICAL or (len(unit) > 1 or ord(unit[0]) < 0x80):
                    _turned(canvas, x, y + height / 2, unit, font, fill)
                else:
                    canvas.create_text(x, y + height / 2, text=unit, font=font, fill=fill)
                y += height
        return
    anchor, x = {"中央": ("center", (x1 + x2) / 2), "右": ("e", x2 - 2)}.get(item.align, ("w", x1 + 2))
    total = len(item.lines) * pitch
    # 見出しの囲み（center）は、行のかたまりを枠の上下の真ん中に置く（Word と同じ）
    top = y1 + max(0.0, (y2 - y1 - total) / 2) if item.center else y1
    room = max(1.0, (x2 - x1) - 4)
    for index, line in enumerate(item.lines):
        glyph = size
        try:
            width = _measure(family, glyph, weight, line)
            if width > room:
                glyph = max(4, int(glyph * room / width))
        except tk.TclError:
            pass
        canvas.create_text(x, top + pitch / 2 + index * pitch, text=line, anchor=anchor,
                           font=(family, -glyph, weight), fill=color(index))


_MEASURE_FONTS = {}


def _measure(family, size: int, weight: str, text: str) -> int:
    """画面の字で text を描いたときの幅（画素）。"""
    key = (family, size, weight)
    if key not in _MEASURE_FONTS:
        _MEASURE_FONTS[key] = tkfont.Font(family=family, size=-size, weight=weight)
    return _MEASURE_FONTS[key].measure(text)


_TCY_FONTS = {}


def _tcy_font(family, size: int, bold: bool, digits: str):
    """縦中横の数字の字の大きさ。Word と同じく、本文と同じ高さのまま1字分の幅に収める。

    半角の数字2桁はふつう本文と同じ大きさで1字分に入る。3桁は入るところまで小さくする
    （Word は字の高さを変えずに幅だけ縮めるが、画面では幅だけ縮められないため）。
    行と行の間が空いているので、1字分より少しだけ広くてもよいことにする。
    """
    weight = "bold" if bold else "normal"
    key = (family, size, weight, len(digits))
    if key not in _TCY_FONTS:
        measure = "0" * len(digits)
        chosen = max(4, size)
        try:
            while chosen > 4 and tkfont.Font(family=family, size=-chosen, weight=weight).measure(measure) > size * 1.15:
                chosen -= 1
        except tk.TclError:
            chosen = max(4, int(size * 0.8))
        _TCY_FONTS[key] = (family, -chosen, weight)
    return _TCY_FONTS[key]


def _turned(canvas, x, y, text, font, fill="black") -> None:
    try:
        canvas.create_text(x, y, text=text, font=font, angle=-90, fill=fill)
    except tk.TclError:   # 字を回せない古い Tk では、そのまま描く
        canvas.create_text(x, y, text=text, font=font, fill=fill)


def _draw_table(canvas, table, x, y, scale, family) -> None:
    widths = [width * scale for width in (table.column_widths or [table.box.w])]
    heights = []
    for index, _row in enumerate(table.rows):
        given = table.row_heights[index] if table.row_heights and index < len(table.row_heights) else None
        heights.append((given or 15.0) * scale)
    spans, merges = table.col_spans or {}, table.v_merge or {}
    top = y
    for row_index, row in enumerate(table.rows):
        left = x
        covered = set()
        for (r, c), count in spans.items():
            if r == row_index:
                covered.update(range(c + 1, c + count))
        for column, width in enumerate(widths):
            if column in covered:
                continue
            span = spans.get((row_index, column), 1)
            width = sum(widths[column:column + span])
            if merges.get((row_index, column)) == "continue":
                left += width
                continue
            height = heights[row_index]
            if merges.get((row_index, column)) == "restart":
                below = row_index + 1
                while merges.get((below, column)) == "continue":
                    height += heights[below]
                    below += 1
            canvas.create_rectangle(left, top, left + width, top + height, outline="#444")
            diagonal = (table.diagonal_cells or {}).get((row_index, column))
            if diagonal:
                canvas.create_line(left, top, left + width, top + height, fill="#444")
                small = (family, -max(4, round(table.pt * scale)))
                canvas.create_text(left + width - 3, top + 2, text=diagonal[0], font=small, anchor="ne")
                canvas.create_text(left + 3, top + height - 2, text=diagonal[1], font=small, anchor="sw")
                left += width
                continue
            value = row[column] if column < len(row) else ""
            pt = table.pt
            if table.cell_pts and row_index < len(table.cell_pts) and column < len(table.cell_pts[row_index]):
                pt = table.cell_pts[row_index][column]
            size = max(4, round(pt * scale))
            vertical = bool(table.vertical_cells) and (row_index, column) in table.vertical_cells
            text = "\n".join(value) if vertical else value
            canvas.create_text(left + width / 2, top + height / 2, text=text,
                               font=(family, -size), width=max(10, width - 2))
            left += width
        top += heights[row_index]


def _focus_next(event):
    event.widget.tk_focusNext().focus_set()
    return "break"


def _focus_previous(event):
    event.widget.tk_focusPrev().focus_set()
    return "break"


def _last_day(reiwa_year: int, month: int) -> str:
    """令和の年と月から、その月の末日を「令和8年10月31日」の形で返す。"""
    if not reiwa_year or month not in range(1, 13):
        return ""
    last = calendar.monthrange(2018 + reiwa_year, month)[1]
    return f"令和{reiwa_year}年{month}月{last}日"


def _table_summary(value: dict) -> str:
    rows = tables.parse_rows(value.get("data", ""))
    columns = len(rows[0]) if rows else 0
    return f"{value.get('name') or '（名前なし）'}　{len(rows)}行×{columns}列"


def _question_summary(value: dict) -> str:
    """質問者の一覧に出す 1 行（議員名と 1 番目の大まかな質問）。"""
    questions = value.get("questions") or []
    first = questions[0].get("heading", "") if questions else ""
    if not first and value.get("qa_bulk"):
        parsed = items.parse_bulk(value["qa_bulk"])["questions"]
        first = parsed[0].get("heading", "") if parsed else ""
    return f"{value.get('member', '')}　{first or value.get('title', '')}".strip() or "（議員名なし）"


def _plain_title(text: str) -> str:
    """件名を比べるとき、改行と空白の違いは見ない。"""
    return re.sub(r"\s", "", str(text or "")).lstrip("◎")


def _table_row(table, y: float):
    """表の中の高さ y（pt）が何行目か（0 が見出し行）。表の外なら None。"""
    top = table.box.y
    heights = table.row_heights or []
    for row in range(len(table.rows)):
        height = heights[row] if row < len(heights) and heights[row] else 15.0
        if top <= y < top + height:
            return row
        top += height
    return None


def _bill_index(bills, heading, page_items):
    """審議本文の「◎件名」の枠から、何件目の案件かを求める。件名で探し、同じ件名がなければ並び順で。"""
    if heading is None:
        return None
    text = _plain_title("".join(heading.lines))
    for index, bill in enumerate(bills):
        if _plain_title(bill.get("title", "")) == text:
            return index
    order = [item for item in page_items if isinstance(item, dx.TextBox) and item.name == "議案"]
    position = next((i for i, item in enumerate(order) if item is heading), None)
    return position if position is not None and position < len(bills) else None


def _qa_text(bill: dict) -> str:
    """案件の質疑を、まとめ欄の形（問　…／答　…）で返す。"""
    if bill.get("qa_bulk"):
        return str(bill["qa_bulk"])
    lines = []
    for value in bill.get("questions", []) or []:
        if value.get("heading"):
            lines.append("【" + value["heading"] + "】")
        if value.get("question"):
            lines.append("問　" + value["question"])
        if value.get("answer"):
            lines.append("答　" + value["answer"])
    return "\n".join(lines)


def _shingi_spot(bills, work, placements, x: float, y: float):
    """審議本文のダブルクリックした所が、何件目の案件の何番目の問か。(案件, 問) を返す。

    説明の所なら問は -1。見つからなければ None。本文は案件ごとに並ぶので、
    案件 1 件ずつ部品の数を数えて、押した部品が何件目のものかを求める。
    """
    hit = next((p for p in placements
                if _inside(to_box(work.geometry, p.rect), x, y)), None)
    if hit is None or hit.part.kind == "議案":
        return None
    start = 0
    for index, bill in enumerate(bills):
        one = items.shingi_form({"shingi": {"bills": [bill]}}, work.issue)["body"]
        parts = templates._body_parts(one)
        if start <= hit.index < start + len(parts):
            mine = parts[:hit.index - start + 1]
            if hit.part.kind in ("中見出し",) and hit.part.reason != "質疑の印":
                return None   # 区分の囲みは入力欄の手順へ
            asked = sum(1 for part in mine if part.kind == "質問")
            return index, (asked - 1 if asked else (0 if hit.part.reason == "質疑の印" else -1))
        start += len(parts)
    return None


def _inside(box, x: float, y: float) -> bool:
    return box.x <= x <= box.x + box.w and box.y <= y <= box.y + box.h


def parse_period(text: str):
    """「Ｒ８．９．４～９．１１」を (開始の年, 月, 日, 終わりの年, 月, 日) にする。読めなければ None。"""
    plain = str(text or "").translate(_ZEN_TO_HAN).translate(str.maketrans("Ｒ．～〜", "R.~~"))
    match = re.fullmatch(r"\s*R(\d+)\.(\d+)\.(\d+)\s*[~\-－]\s*(?:R(\d+)\.)?(\d+)\.(\d+)\s*", plain)
    if not match:
        return None
    year, month, day, end_year, end_month, end_day = match.groups()
    year = int(year)
    end_year = int(end_year) if end_year else (year + 1 if int(end_month) < int(month) else year)
    return year, int(month), int(day), end_year, int(end_month), int(end_day)


def format_period(year, month, day, end_year, end_month, end_day) -> str:
    """年月日から会期の文を作る（全角）。日がそろっていない・ありえない日付なら空。"""
    try:
        start = datetime.date(2018 + year, month, day)
        end = datetime.date(2018 + end_year, end_month, end_day)
    except ValueError:
        return ""
    if end < start:
        return ""
    tail = f"{end_month}.{end_day}" if end_year == year else f"R{end_year}.{end_month}.{end_day}"
    text = f"R{year}.{month}.{day}~{tail}"
    return text.translate(str.maketrans("0123456789R.~", "０１２３４５６７８９Ｒ．～"))


def _month_label(month: int) -> str:
    """プルダウンに出す文。どの定例会を載せる号かを添える。"""
    meeting = layout.TEIREIKAI.get(month)
    note = "（議長改選で4月号が遅れる年）" if month == 5 else ""
    return f"{month}月号　{meeting}月定例会{note}"


def _number(text) -> int:
    """「２０５」「第205号」「4月」のように書いても数字だけを読む。空なら 0。"""
    digits = "".join(ch for ch in str(text).translate(_ZEN_TO_HAN) if ch.isdigit())
    return int(digits) if digits else 0


_ZEN_TO_HAN = str.maketrans("０１２３４５６７８９", "0123456789")


if __name__ == "__main__":
    raise SystemExit(main())
