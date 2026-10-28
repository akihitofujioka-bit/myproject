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
        ttk.Button(bottom, text="戻る", command=self.back).pack(side="right")
        ttk.Button(bottom, text="次へ", command=self.next).pack(side="right", padx=6)

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
                    widget = ttk.Combobox(body, values=choices, state="readonly")
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
        self._entry("号数", value.get("number", ""), lambda v: value.__setitem__("number", int(v or 0)))
        self._entry("発行月", value.get("month", 4), lambda v: value.__setitem__("month", int(v or 0)))
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
        self._title("審議したこと")
        value = self.data.setdefault("shingi", {"counts": [], "bills": []})
        self._entry("定例会名", value.get("meeting", ""), lambda v: value.__setitem__("meeting", v))
        self._entry("会期", value.get("period", ""), lambda v: value.__setitem__("period", v))
        self._list_editor("議案の種類と件数", value.setdefault("counts", []),
                          [("kind", "種類", False), ("count", "件数", False)],
                          lambda v: f"{v.get('kind', '')} {v.get('count', '')}件")
        self._list_editor("議案", value.setdefault("bills", []),
                          [("kind", "区分", False), ("title", "議案名", False),
                           ("description", "説明", True), ("qa_bulk", "質疑（問・答で開始）", True)],
                          lambda v: v.get("title") or "（議案名なし）")

    def _step_7(self):
        self._title("賛否表")
        votes = self.data.setdefault("votes", [])
        members = self.work.settings.members if self.work else []
        chair = self.work.settings.chair if self.work else ""
        votes[:] = items.build_votes(votes, members, chair)
        self._list_editor("議案・発議案", votes,
                          [("kind", "区分", False), ("title", "件名", False), ("result", "議決結果", False)],
                          lambda v: f"{v.get('kind', '')} {v.get('title', '')}")
        for number, row in enumerate(votes, 1):
            box = ttk.LabelFrame(self.inner, text=f"{number}. {row.get('title', '件名なし')} の賛否", padding=7)
            box.pack(fill="x", pady=4)
            for name in members:
                line = ttk.Frame(box)
                line.pack(side="left", padx=(0, 8))
                ttk.Label(line, text=name).pack()
                var = tk.StringVar(value=row.setdefault("marks", {}).get(name, "議長" if name == chair else "○"))
                ttk.Combobox(line, textvariable=var, values=MARKS, state="readonly", width=7).pack()
                self.getters.append(lambda v=var, r=row, n=name: r["marks"].__setitem__(n, v.get()))

    def _step_8(self):
        self._title("委員会報告")
        self._list_editor("報告", self.data.setdefault("committees", []),
                          [("committee", "委員会名", False), ("heading", "見出し", False), ("body", "本文", True)],
                          lambda v: v.get("committee") or v.get("heading") or "（名称なし）")

    def _step_9(self):
        self._title("一般質問")
        self._list_editor("質問者", self.data.setdefault("questions", []),
                          [("member", "議員名", False,
                            self.work.settings.members if self.work else []),
                           ("title", "題（横の大見出し）", False),
                           ("qa_bulk", "質問（見出し、問、答、答弁者 で入力）", True)],
                          lambda v: f"{v.get('member', '')}　{v.get('title', '')}", max_items=10)
        ttk.Label(self.inner, text="文章は保存時に最大4件の質問へ分けます。顔写真枠は自動で入ります。",
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
        ttk.Button(self.inner, text="写真を追加", command=self.add_photos).pack(anchor="w", pady=5)
        names = [value["name"] for value in self.work.photo_files()]
        self.photo_var = tk.StringVar(value=names[0] if names else "")
        self.photo_page = tk.StringVar(value="1")
        ttk.Label(self.inner, text="写真").pack(anchor="w")
        ttk.Combobox(self.inner, textvariable=self.photo_var, values=names, state="readonly").pack(fill="x")
        ttk.Label(self.inner, text="置くページ番号").pack(anchor="w", pady=(8, 0))
        ttk.Combobox(self.inner, textvariable=self.photo_page,
                     values=[str(p["no"]) for p in self.work.pages], state="readonly").pack(fill="x")
        ttk.Button(self.inner, text="このページへ自動配置", command=self.place_photo).pack(anchor="e", pady=8)

    def _step_13(self):
        self._title("全ページの確認")
        messages = self.work.check() if self.work else ["号を作るか開いてください。"]
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
                      layout.KESSAN: 5, layout.SHINGI: 6, layout.IINKAI: 8,
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
            if not issue.get("number") or not issue.get("date"):
                return "号数または発行日が空です。表紙と出力名に必要です。"
        if self.step == 2 and self.work and not self.work.settings.members:
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
        paths = filedialog.askopenfilenames(title="JPEGまたはPNGを選ぶ", parent=self.root,
                                            filetypes=(("写真", "*.jpg *.jpeg *.png"),))
        if paths:
            try:
                self.work.add_photos(paths)
                self.show(12)
            except Exception as error:
                messagebox.showerror("写真を追加できません", str(error), parent=self.root)

    def place_photo(self) -> None:
        try:
            page = int(self.photo_page.get())
            placed = False
            for dan in range(self.work.geometry.dans):
                for line in range(0, self.work.geometry.lines_per_dan, 3):
                    if self.work.place_photo(page, self.photo_var.get(), Rect(dan, line, 1, 1)):
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                raise ValueError("写真を置ける空きがありません。別のページを選んでください。")
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


if __name__ == "__main__":
    raise SystemExit(main())
