"""議会だより編集 V7。項目テンプレート入力と15手順の全行程ナビ。"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import edition
import guide
import items
import layout
import sources
from grid import Rect, to_box


COLORS = {"大見出し": "#ffd783", "中見出し": "#ffe9af", "質問": "#bfdefd",
          "答弁": "#c9e8c9", "本文": "#eeeeee", "議案": "#dccbf3",
          "写真": "#9bd8ea", "写真説明": "#d4edf2"}
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
        self.font = "TkDefaultFont"
        self._style()
        self._build()
        if len(sys.argv) > 1:
            self.open_issue(sys.argv[1])
        else:
            self.show(0)

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
        getattr(self, "_step_" + str(self.step), self._not_ready)()
        self.canvas.yview_moveto(0)
        self._fit_summary()

    def _title(self, text: str) -> None:
        ttk.Label(self.inner, text=text, style="Title.TLabel").pack(anchor="w", pady=(2, 8))

    def _entry(self, label: str, value, setter) -> None:
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=20).pack(side="left")
        var = tk.StringVar(value=str(value or ""))
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        self.getters.append(lambda v=var, s=setter: s(v.get().strip()))

    def _text(self, label: str, value, setter, height: int = 5) -> None:
        row = ttk.Frame(self.inner)
        row.pack(fill="both", expand=True, pady=3)
        ttk.Label(row, text=label, width=20).pack(side="left", anchor="n")
        widget = tk.Text(row, height=height, wrap="word", font=(self.font, 11), undo=True)
        widget.insert("1.0", str(value or ""))
        widget.pack(side="left", fill="both", expand=True)
        self.getters.append(lambda w=widget, s=setter: s(w.get("1.0", "end-1c").strip()))

    def _list_editor(self, label, values, fields, summary, max_items=None) -> None:
        box = ttk.LabelFrame(self.inner, text=label, padding=7)
        box.pack(fill="both", expand=True, pady=5)
        listing = tk.Listbox(box, height=min(8, max(3, len(values) + 1)),
                             font=(self.font, 11), exportselection=False)
        listing.pack(side="left", fill="both", expand=True)
        controls = ttk.Frame(box)
        controls.pack(side="left", fill="y", padx=(7, 0))

        def refresh(select=0):
            listing.delete(0, "end")
            for index, value in enumerate(values):
                listing.insert("end", f"{index + 1}. {summary(value)}")
            if values:
                listing.selection_set(min(select, len(values) - 1))

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
            dialog.geometry("720x560")
            dialog.transient(self.root)
            body = ttk.Frame(dialog, padding=12)
            body.pack(fill="both", expand=True)
            widgets = {}
            for field in fields:
                key, title, multiline = field[:3]
                choices = field[3] if len(field) > 3 else None
                ttk.Label(body, text=title).pack(anchor="w", pady=(4, 1))
                if multiline:
                    widget = tk.Text(body, height=5, wrap="word", font=(self.font, 11))
                    widget.insert("1.0", str(value.get(key, "")))
                elif choices:
                    widget = ttk.Combobox(body, values=choices,
                                          state="normal" if len(field) > 4 and field[4] else "readonly")
                    widget.set(str(value.get(key, "")))
                else:
                    widget = ttk.Entry(body)
                    widget.insert(0, str(value.get(key, "")))
                widget.pack(fill="x")
                widgets[key] = (widget, multiline)

            def accept():
                for key, (widget, multiline) in widgets.items():
                    value[key] = (widget.get("1.0", "end-1c") if multiline else widget.get()).strip()
                if new:
                    values.append(value)
                refresh(len(values) - 1 if new else selected[0])
                dialog.destroy()
            ttk.Button(body, text="この内容にする", command=accept).pack(anchor="e", pady=8)
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
        self._entry("発行月", value.get("month", 4), lambda v: value.__setitem__("month", _number(v)))
        self._entry("発行日", value.get("date", ""), lambda v: value.__setitem__("date", v))
        if self.work:
            name = items.templates.meeting_name(items.issue_from_data(self.data, self.work.issue))
            ttk.Label(self.inner, text="定例会名（自動）: " + name).pack(anchor="w", pady=8)

    def _step_2(self):
        self._title("議員名簿")
        current = self.work.settings if self.work else None
        self._text("議員（1行に1人）", "\n".join(current.members if current else []),
                   lambda v: setattr(self, "_member_text", v), 9)
        self._entry("議長名", current.chair if current else "", lambda v: setattr(self, "_chair", v))

    def _step_3(self):
        self._title("表紙")
        value = self.data.setdefault("cover", {})
        self._entry("写真の説明", value.get("photo_caption", ""), lambda v: value.__setitem__("photo_caption", v))
        self._text("特集の題名", value.get("feature_titles", ""), lambda v: value.__setitem__("feature_titles", v), 4)

    def _step_4(self):
        self._title("行政報告")
        value = self.data.setdefault("gyosei", {"title": layout.GYOSEI, "reports": []})
        self._entry("大見出し", value.get("title", layout.GYOSEI), lambda v: value.__setitem__("title", v))
        self._list_editor("報告事項", value.setdefault("reports", []),
                          [("heading", "見出し", False), ("body", "本文", True)],
                          lambda v: v.get("heading") or "（見出しなし）")

    def _step_5(self):
        self._title("当初予算または決算")
        value = self.data.setdefault("budget", {"title": "", "summary": "", "questions": []})
        section = layout.KESSAN if int(self.data.get("issue", {}).get("month", 4)) == 10 else layout.YOSAN
        self._entry("大見出し", value.get("title") or section, lambda v: value.__setitem__("title", v))
        self._text("概要本文", value.get("summary", ""), lambda v: value.__setitem__("summary", v), 6)
        self._list_editor("質疑", value.setdefault("questions", []),
                          [("heading", "見出し", False), ("question", "問", True), ("answer", "答", True)],
                          lambda v: v.get("heading") or v.get("question", "")[:30])
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
            table = ttk.Treeview(self.inner, columns=("kind", "title", "result"),
                                 show="headings", height=min(8, len(votes)))
            for key, text, width in (("kind", "区分", 100), ("title", "議案番号・件名", 500),
                                     ("result", "議決結果", 130)):
                table.heading(key, text=text)
                table.column(key, width=width)
            for vote in votes:
                table.insert("", "end", values=(vote.get("kind", ""), vote.get("title", ""),
                                                  vote.get("result", "")))
            table.pack(fill="x", pady=5)
            ttk.Label(self.inner, text="この表は確認用です。直すときはExcelを直して、もう一度取り込んでください。",
                      wraplength=900).pack(anchor="w")
        warnings = self.data.get("votes_warnings", [])
        if warnings:
            ttk.Label(self.inner, text="注意\n・" + "\n・".join(warnings),
                      foreground="#a33", justify="left", wraplength=900).pack(anchor="w", pady=8)

    def _step_7(self):
        self._title("審議したこと")
        value = self.data.setdefault("shingi", {"counts": [], "bills": []})
        self._entry("定例会名", value.get("meeting", ""), lambda v: value.__setitem__("meeting", v))
        self._entry("会期", value.get("period", ""), lambda v: value.__setitem__("period", v))
        counts = value.setdefault("counts", [])
        if counts:
            ttk.Label(self.inner, text="議案の種類と件数（取り込んだExcelから自動）: " +
                      "、".join(f"{v.get('kind') or '区分なし'} {v.get('count')}件" for v in counts),
                      wraplength=900).pack(anchor="w", pady=5)
        else:
            ttk.Label(self.inner, text="先に議案と賛否のエクセルを取り込むと自動で入ります。",
                      foreground="#955").pack(anchor="w", pady=5)
        vote_titles = [v.get("title", "") for v in self.data.get("votes", []) if v.get("title")]
        self._list_editor("議案", value.setdefault("bills", []),
                          [("kind", "区分", False), ("title", "議案名", False,
                            vote_titles, True), ("description", "説明", True),
                           ("qa_bulk", "質疑（問・答で開始）", True)],
                          lambda v: v.get("title") or "（議案名なし）")

    def _step_8(self):
        self._title("委員会報告")
        self._list_editor("報告", self.data.setdefault("committees", []),
                          [("committee", "委員会名", False), ("heading", "見出し", False), ("body", "本文", True)],
                          lambda v: v.get("committee") or v.get("heading") or "（名称なし）")

    def _step_9(self):
        self._title("一般質問")
        members = self.work.settings.members if self.work else []
        statuses = sources.reception_status(members, self.data.setdefault("questions", []))
        if statuses:
            ttk.Label(self.inner, text="受付状況: " + "／".join(
                f"{v['member']} {v['status']}" for v in statuses), wraplength=900,
                justify="left").pack(anchor="w", pady=5)
        self._list_editor("質問者", self.data.setdefault("questions", []),
                          [("member", "議員名", False,
                            members),
                           ("title", "題（横の大見出し）", False),
                           ("delivery", "届き方", False,
                            ("Word", "メール", "手書き", "その他")),
                           ("received_date", "受け取った日", False),
                           ("confirmed", "議員の確認", False, ("未", "済")),
                           ("qa_bulk", "質問（見出し、問、答、答弁者 で入力）", True)],
                          lambda v: f"{v.get('member', '')}　{v.get('title', '')}", max_items=10)
        row = ttk.Frame(self.inner)
        row.pack(fill="x", pady=5)
        ttk.Button(row, text="まとめて貼る", command=self.bulk_question).pack(side="left")
        ttk.Button(row, text="Word から読み込む", command=self.import_question_word).pack(side="left")
        ttk.Button(row, text="メール本文を貼る", command=self.import_question_email).pack(side="left", padx=5)
        ttk.Button(row, text="確認用に印刷（1人）",
                   command=lambda: self.print_question_confirmation(True)).pack(side="left")
        ttk.Button(row, text="確認用に印刷（全員）", command=self.print_question_confirmation).pack(side="left")
        ttk.Label(self.inner, text=("取り込み後は必ず、問と答の分け方が正しいか原稿と見比べてください。"
                                    "手書きは見ながら入力し、確認用に印刷して議員に見てもらいます。"
                                    "顔写真枠は自動で入ります。"),
                  wraplength=900).pack(anchor="w", pady=5)

    def _step_10(self):
        self._title("特集")
        value = self.data.setdefault("feature", {})
        self._entry("題", value.get("title", ""), lambda v: value.__setitem__("title", v))
        self._text("本文", value.get("body", ""), lambda v: value.__setitem__("body", v), 12)

    def _step_11(self):
        self._title("最終ページ")
        value = self.data.setdefault("last", {})
        for key, label, height in (("editorial", "編集後記", 5), ("free", "自由欄", 7),
                                   ("next_meeting", "次回定例会", 2), ("opinion", "意見・提言", 3)):
            self._text(label, value.get(key, ""), lambda v, k=key: value.__setitem__(k, v), height)
        self._entry("傍聴案内の見出し", value.get("hearing_title", "議会を傍聴してみませんか"),
                    lambda v: value.__setitem__("hearing_title", v))
        self._entry("傍聴の呼びかけ", value.get("invitation", "お気軽に傍聴に、お越し下さい。"),
                    lambda v: value.__setitem__("invitation", v))

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
            target = {layout.COVER: 3, layout.GYOSEI: 4, layout.YOSAN: 5,
                      layout.KESSAN: 5, layout.SHINGI: 7, layout.IINKAI: 8,
                      layout.IPPAN: 9, layout.TOKUSHU: 10, layout.LAST: 11}.get(section, 13)
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

    def import_votes(self) -> None:
        path = filedialog.askopenfilename(title="議案と賛否のExcelを選ぶ", parent=self.root,
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
                     "delivery": "その他", "received_date": "", "confirmed": "未"}
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
        dialog.geometry("760x620")
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="問と答の分け方が正しいか、原稿と見比べてください。",
                  foreground="#933").pack(anchor="w")
        preview = tk.Text(body, wrap="word", font=(self.font, 11))
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

    def import_question_word(self) -> None:
        member = self._choose_member()
        if not member:
            return
        path = filedialog.askopenfilename(title="Word 原稿を選ぶ", parent=self.root,
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
        dialog.geometry("760x600")
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="見出し、問、答を含む原稿を貼ってください。").pack(anchor="w")
        widget = tk.Text(body, wrap="word", font=(self.font, 11), undo=True)
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
        dialog.geometry("760x620")
        body = ttk.Frame(dialog, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="メール本文をそのまま貼ってください。候補は勝手に消しません。").pack(anchor="w")
        widget = tk.Text(body, wrap="word", font=(self.font, 11), undo=True)
        widget.pack(fill="both", expand=True, pady=6)

        def next_step():
            original = widget.get("1.0", "end-1c")
            candidates = sources.email_candidates(original)
            dialog.destroy()
            choice = tk.Toplevel(self.root)
            choice.title("外す候補と整えた結果")
            choice.geometry("820x660")
            frame = ttk.Frame(choice, padding=10)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="外す行だけにチェックしてください。チェックしない行は残ります。").pack(anchor="w")
            flags = []
            for candidate in candidates:
                var = tk.BooleanVar(value=False)
                flags.append((var, candidate["line"]))
                ttk.Checkbutton(frame, variable=var,
                                text=f"{candidate['line']}行目 {candidate['reason']}: {candidate['text'][:70]}").pack(anchor="w")
            preview = tk.Text(frame, height=18, wrap="word", font=(self.font, 11))
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
                if parsed["body"]:
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

    def open_issue(self, folder=None) -> None:
        folder = folder or filedialog.askdirectory(title="号フォルダを選ぶ", parent=self.root)
        if not folder:
            return
        try:
            self.work = edition.Edition.open(Path(folder))
            self.data = self.work.item_data()
            self.issue_label.configure(text=self.work.issue.title)
            self.show(1)
        except Exception as error:
            messagebox.showerror("開けません", str(error), parent=self.root)

    def add_photos(self) -> None:
        path = filedialog.askopenfilename(title="JPEGまたはPNGを選ぶ", parent=self.root,
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
            self.show(12)
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
        self.save(silent=True)
        dialog = tk.Toplevel(self.root)
        dialog.title("紙面を見る")
        dialog.geometry("760x690")
        top = ttk.Frame(dialog, padding=6)
        top.pack(fill="x")
        page_var = tk.IntVar(value=1)
        status = ttk.Label(top)
        status.pack(side="right")
        drag = {"part": None}
        paper = tk.Canvas(dialog, bg="#d9dde3", highlightthickness=0)
        paper.pack(fill="both", expand=True)

        def draw():
            number = page_var.get()
            result = self.work.compose(number)
            paper.delete("all")
            scale, ox, oy = 0.72, 150, 12
            paper.create_rectangle(ox, oy, ox + 595 * scale, oy + 842 * scale, fill="white", outline="#777")
            for placement in result.placements:
                actual = to_box(self.work.geometry, placement.rect)
                x1, y1 = ox + actual.x * scale, oy + actual.y * scale
                x2, y2 = x1 + actual.w * scale, y1 + actual.h * scale
                paper.create_rectangle(x1, y1, x2, y2,
                                       fill=COLORS.get(placement.part.kind, "#eeeeee"), outline="#888")
                paper.create_text((x1 + x2) / 2, (y1 + y2) / 2,
                                  text=placement.part.text[:18] or placement.part.kind,
                                  width=max(20, x2 - x1 - 4), font=(self.font, 8))
            status.configure(text=(f"{number}ページ　あふれ {result.overflow_lines}行"
                                   f"（約{result.overflow_lines * 12}字）／余り {result.free_lines}行"))
        ttk.Combobox(top, textvariable=page_var, values=[p["no"] for p in self.work.pages],
                     state="readonly", width=8).pack(side="left")
        ttk.Button(top, text="表示", command=draw).pack(side="left", padx=5)
        ttk.Button(top, text="元に戻す", command=lambda: (self.work.undo(), draw())).pack(side="left")
        ttk.Button(top, text="やり直す", command=lambda: (self.work.redo(), draw())).pack(side="left", padx=4)

        def grid_at(event):
            point_x, point_y = (event.x - 150) / 0.72, (event.y - 12) / 0.72
            g = self.work.geometry
            dan = round((point_y - g.margin_top_mm * 72 / 25.4) / (g.dan_h_pt + g.gap_pt))
            right = (g.page_w_mm - g.margin_right_mm) * 72 / 25.4
            line = int((right - point_x) / g.line_pitch_pt)
            return Rect(max(0, min(g.dans - 1, dan)),
                        max(0, min(g.lines_per_dan - 1, line)), 1, 1)

        def press(event):
            if self.step != 12:
                return
            point_x, point_y = (event.x - 150) / 0.72, (event.y - 12) / 0.72
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
            if self.step != 12:
                return
            try:
                target = grid_at(event)
                if drag["part"] is None:
                    if not getattr(self, "photo_var", None) or not self.photo_var.get():
                        raise ValueError("写真の手順で、置く写真を選んでください。")
                    actual, shifted = self.work.place_photo_near(
                        page_var.get(), self.photo_var.get(), target,
                        self.photo_size.get(), self.photo_caption.get())
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
        paper.bind("<ButtonPress-1>", press)
        paper.bind("<ButtonRelease-1>", release)
        draw()

    def export(self) -> None:
        if not self.work or not self.save():
            return
        try:
            paths = self.work.export()
            self.output_label.configure(text="出力先:\n" + "\n".join(str(path) for path in paths))
        except Exception as error:
            messagebox.showerror("出力できません", str(error), parent=self.root)


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


def _number(text) -> int:
    """「２０５」「第205号」「4月」のように書いても数字だけを読む。空なら 0。"""
    digits = "".join(ch for ch in str(text).translate(_ZEN_TO_HAN) if ch.isdigit())
    return int(digits) if digits else 0


_ZEN_TO_HAN = str.maketrans("０１２３４５６７８９", "0123456789")


if __name__ == "__main__":
    raise SystemExit(main())
