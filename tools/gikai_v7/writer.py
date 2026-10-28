"""事務局原稿を書く窓と、印付き文章への相互変換。"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter as tk
from typing import Dict, List, Optional, Tuple

import ingest


BUTTONS = ("大見出し", "中見出し", "問", "答", "本文", "写真")
PREFIXES = {
    "大見出し": "【大見出し】",
    "中見出し": "【見出し】",
    "問": "問　",
    "答": "答　",
    "本文": "",
}


def insert_mark(text: str, cursor: int, kind: str, photo_line: str = "") -> Tuple[str, int]:
    """カーソルのある行頭へ、選んだ部品の印を入れる。"""
    if kind not in BUTTONS:
        raise ValueError("原稿の印が正しくありません: " + kind)
    start = text.rfind("\n", 0, max(0, cursor)) + 1
    mark = photo_line if kind == "写真" else PREFIXES[kind]
    return text[:start] + mark + text[start:], cursor + len(mark)


def marked_text(parts: List[ingest.Part], section: str,
                overrides: Optional[Dict[int, dict]] = None) -> str:
    """取り込んだ部品を、種類が変わらない印付き文章へ戻す。"""
    overrides = overrides or {}
    lines = []
    photo_no = 0
    skip = set()
    for index, original in enumerate(parts):
        if index in skip:
            continue
        part = original
        changed = overrides.get(index, {})
        if changed.get("kind"):
            part = ingest.Part(changed["kind"], part.text, True, "人が直した", part.image,
                               vertical=part.vertical)
        vertical = part.vertical if changed.get("vertical") is None else changed["vertical"]
        if part.kind == "大見出し":
            lines.append(("【大見出し】" if vertical else "【大見出し・横】") + part.text)
        elif part.kind == "中見出し":
            lines.append(("【見出し】" if vertical else "【横見出し】") + part.text)
        elif part.kind == "質問":
            lines.append(part.text if part.text.startswith("問　") else "問　" + part.text)
        elif part.kind == "答弁":
            lines.append(part.text if part.text.startswith("答　") else "答　" + part.text)
        elif part.kind == "議案":
            lines.append(part.text if part.text.startswith("◎") else "◎" + part.text)
        elif part.kind == "写真":
            photo_no += 1
            if part.reason == "印刷所が入れる顔写真の空欄":
                lines.append("【顔写真枠】")
                continue
            default = "顔" if section == "一般質問" and photo_no == 1 else "中"
            size = changed.get("size") or part.photo_size or default
            caption = ""
            if index + 1 < len(parts) and parts[index + 1].kind == "写真説明":
                caption = parts[index + 1].text.lstrip("▲△").strip()
                skip.add(index + 1)
            lines.append(f"【写真】{Path(part.image or '').name}｜{size}｜{caption}")
        elif part.kind == "空き行":
            lines.append(f"【空き行:{part.text}】")
        elif part.kind == "次段":
            lines.append("【次段】")
        else:
            lines.append(part.text)
    return "\n".join(lines)


class CommonSheetEditor:
    """一つのシートから複数ページへ原稿を割り当てる窓。"""

    def __init__(self, app) -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("共通シート")
        self.window.geometry("760x740")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        ttk.Label(self.window, text=(
            "【ページ:番号】で区切り、原稿を貼り付けます。対象にするページだけ記入してください。\n"
            "【大見出し】／【大見出し・横】、【見出し】／【横見出し】、"
            "問　、答　、【本文】を使えます。\n"
            "【空き行:2】は2行分の空白、【次段】は次の段へ送ります。"
            "本文中の【分割】で部品を分けます。"),
            wraplength=730, justify="left").pack(fill="x", padx=10, pady=10)
        bar = ttk.Frame(self.window)
        bar.pack(fill="x", padx=10)
        ttk.Button(bar, text="配置を確認", command=self.preview).pack(side="left")
        ttk.Button(bar, text="原稿を取り込む", command=self.import_sheet).pack(side="left", padx=8)
        self.status = ttk.Label(self.window, text="")
        self.status.pack(fill="x", padx=10, pady=7)
        frame = ttk.Frame(self.window)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.text = tk.Text(frame, wrap="word", undo=True,
                            font=(app.default_family, 12))
        scroll = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        old = app.edition.latest_common_sheet()
        if old:
            self.text.insert("1.0", old)
        else:
            candidates = [page for page in app.edition.pages if "form" not in page]
            selected = next((page for page in candidates if page["no"] == app.page_no),
                            candidates[0] if candidates else None)
            if selected:
                self.text.insert("1.0", f"【ページ:{selected['no']}】\n")

    def _value(self) -> str:
        return self.text.get("1.0", "end-1c")

    def preview(self) -> None:
        try:
            _blocks, summary = self.app.edition.common_sheet_preview(self._value())
        except (ValueError, OSError) as error:
            messagebox.showerror("共通シート", str(error), parent=self.window)
            return
        lines = [f"{no}ページ：{parts}部品、あふれ{overflow}行、余り{free}行"
                 for no, parts, overflow, free, _warnings in summary]
        self.status.configure(text=f"{len(summary)}ページを確認しました")
        messagebox.showinfo("配置の確認", "\n".join(lines), parent=self.window)

    def import_sheet(self) -> None:
        try:
            blocks, summary = self.app.edition.common_sheet_preview(self._value())
        except (ValueError, OSError) as error:
            messagebox.showerror("共通シート", str(error), parent=self.window)
            return
        replacing = [number for number in blocks
                     if self.app.edition.pages[number - 1].get("source")]
        if replacing:
            numbers = "、".join(map(str, replacing))
            detail = (f"{numbers}ページには既に原稿があります。\n\n"
                      "共通シートから新しいページ別原稿を作り、紙面への割当を変更します。"
                      "元の原稿ファイルは残り、履歴から割当を戻せます。"
                      "既存の部品ごとの位置・余白指定は初期化されます。\n\n"
                      "この内容で取り込みますか？")
            if not messagebox.askyesno("原稿の割当変更", detail, parent=self.window):
                return
        try:
            numbers = self.app.edition.import_common_sheet(self._value())
        except (ValueError, OSError) as error:
            messagebox.showerror("取り込めませんでした", str(error), parent=self.window)
            return
        self.app._refresh_pages()
        self.app._draw()
        overflow = [str(no) for no, _parts, lines, _free, _warnings in summary if lines]
        suffix = f"。あふれ: {', '.join(overflow)}ページ" if overflow else ""
        self.status.configure(text=f"{len(numbers)}ページを取り込みました{suffix}")

    def close(self) -> None:
        self.app.common_sheet_editor = None
        self.window.destroy()


class WriterEditor:
    """印ボタンと即時の紙面見本を備えた事務局原稿の別窓。"""

    def __init__(self, app, page_no: int) -> None:
        self.app = app
        self.page_no = page_no
        self.pending = None
        self.window = tk.Toplevel(app.root)
        self.window.title(app.edition.pages[page_no - 1]["label"] + "を書く")
        # 紙面の見本（本体の真ん中）を隠さないよう、本体の左端に重ねて細めに開く。
        # 左のページ一覧は書いている間は使わないので隠れてよい
        app.root.update_idletasks()
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
        height = max(500, min(800, app.root.winfo_height() - 40))
        self.window.geometry(f"480x{height}+{x}+{y + 20}")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(self.window, padding=8)
        toolbar.pack(fill="x")
        for label in BUTTONS:
            ttk.Button(toolbar, text=label,
                       command=lambda value=label: self._insert(value)).pack(side="left", padx=2)
        # 窓を細めに開くので、保存は印のボタンと別の段に置く（同じ段だと右端で見切れる）
        save_bar = ttk.Frame(self.window, padding=(8, 0))
        save_bar.pack(fill="x")
        ttk.Button(save_bar, text="保存して紙面に入れる", command=self.save).pack(side="right", padx=2)
        self.fit = ttk.Label(self.window, text="", padding=(10, 0))
        self.fit.pack(fill="x")
        self.text = tk.Text(self.window, wrap="word", undo=True,
                            font=(app.default_family, 12), padx=8, pady=8)
        self.text.pack(fill="both", expand=True, padx=8, pady=8)
        self.text.insert("1.0", app.edition.writer_text(page_no))
        self.text.edit_reset()
        self.text.bind("<KeyRelease>", self._changed)
        ttk.Label(self.window,
                  text="印のボタンは今の行の先頭へ入ります。Ctrl+Z／Ctrl+Yで入力を元に戻す／やり直すことができます。",
                  padding=(10, 0, 10, 8)).pack(fill="x")
        self._preview()

    def _value(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _changed(self, _event=None) -> None:
        if self.pending:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(350, self._preview)

    def _insert(self, kind: str) -> None:
        if kind == "写真":
            path = filedialog.askopenfilename(parent=self.window, title="写真を選ぶ",
                                              filetypes=[("画像", "*.png *.jpg *.jpeg")])
            if not path:
                return
            size = simpledialog.askstring("写真の大きさ", "大・中・小・顔のいずれか",
                                          initialvalue="中", parent=self.window) or "中"
            if size not in ("特大", "大", "中", "小", "顔"):
                messagebox.showinfo("写真の大きさ", "大・中・小・顔から選んでください。",
                                    parent=self.window)
                return
            caption = simpledialog.askstring("写真の説明", "短い説明",
                                             parent=self.window) or ""
            try:
                name = self.app.edition.keep_writer_photo(Path(path))
            except OSError as error:
                messagebox.showerror("写真を写せませんでした", str(error), parent=self.window)
                return
            mark = f"【写真】{name}｜{size}｜{caption}"
        else:
            mark = ""
        value = self._value()
        cursor = len(self.text.get("1.0", "insert"))
        changed, position = insert_mark(value, cursor, kind, mark)
        self.text.delete("1.0", "end")
        self.text.insert("1.0", changed)
        self.text.mark_set("insert", f"1.0+{position}c")
        self.text.focus_set()
        self._changed()

    def _preview(self) -> None:
        self.pending = None
        try:
            result, parts = self.app.edition.preview_writer(self.page_no, self._value())
        except (OSError, ValueError) as error:
            self.fit.configure(text="見本を作れません: " + str(error))
            return
        text = (f"あふれ {result.overflow_lines} 行" if result.overflow_lines
                else f"余り {result.free_lines} 行")
        self.fit.configure(text=text)
        self.app._draw(result, parts)

    def save(self) -> None:
        try:
            self.app.edition.save_writer(self.page_no, self._value())
        except (OSError, ValueError) as error:
            messagebox.showerror("保存できませんでした", str(error), parent=self.window)
            return
        self.app.selected_part = None
        self.app._draw()
        self.app.status.configure(text="事務局原稿を保存しました。")

    def close(self) -> None:
        if self.pending:
            self.window.after_cancel(self.pending)
        self.app.writer_editor = None
        self.window.destroy()
        self.app._draw()
