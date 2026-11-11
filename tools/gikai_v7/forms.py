"""V6 の固定ページ入力欄。"""
from __future__ import annotations
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path
import ingest
import layout
import templates
FONT_SIZE = 11
FONT = ("TkDefaultFont", 11)
SMALL_FONT = ("TkDefaultFont", 9)

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
        # 紙面と右欄を隠さないよう、原稿を書く窓と同じ位置・幅で開く。
        app.root.update_idletasks()
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
        height = max(500, min(800, app.root.winfo_height() - 40))
        self.window.geometry(f"480x{height}+{x}+{y + 20}")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas)
        self.body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        body_window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_window, width=event.width))
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
        ttk.Label(self.body, text=detail, font=SMALL_FONT, wraplength=430).pack(anchor="w")

    def _text_field(self, field) -> None:
        self._label(field)
        value = str(self.form.get(field.name, "") or "")
        if field.multiline:
            widget = tk.Text(self.body, height=5, width=48, font=FONT, wrap="word")
            widget.insert("1.0", value)
            widget.bind("<KeyRelease>", lambda _e, name=field.name, item=widget:
                        self._changed(name, item.get("1.0", "end-1c")))
        else:
            variable = tk.StringVar(value=value)
            widget = ttk.Entry(self.body, textvariable=variable, width=50, font=FONT)
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
        widget = tk.Text(self.body, height=4, width=48, font=FONT)
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


