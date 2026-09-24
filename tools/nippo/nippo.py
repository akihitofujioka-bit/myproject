#!/usr/bin/env python3
"""日報ツール — 素材フォルダに入れたメモ・Word・Excel・写真・音声から、日報・週報・月報の下書きを作る。

    python3 tools/nippo/nippo.py              # ボタン画面を開く
    python3 tools/nippo/nippo.py daily        # 今日の日報（コマンド実行）
    python3 tools/nippo/nippo.py daily 2026-09-19
    python3 tools/nippo/nippo.py weekly 2026-09-19    # その日を含む週（月〜日）の週報
    python3 tools/nippo/nippo.py monthly 2026-09      # その月の月報
    python3 tools/nippo/nippo.py list 2026-09-19      # その日の素材を一覧するだけ
    python3 tools/nippo/nippo.py extract <ファイル>    # 1 ファイルの文字取り出しを試す

フォルダ構成（config.json の workspace、既定 ~/日報）:
    素材/   ここにファイルを入れる（サブフォルダ可。日付は名前・撮影日時・作成日時から判定）
    日報/   YYYY-MM-DD.md
    週報/   YYYY-Www.md
    月報/   YYYY-MM.md
    .cache/ 文字取り出しの結果（同じファイルを二度処理しないため）

OCR・文字起こし・分類はすべてこの Mac の中だけで行い、外部には何も送らない。
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import extractors  # noqa: E402
import reporter  # noqa: E402
from reporter import Material  # noqa: E402

CONFIG_PATH = HERE / "config.json"
Log = Callable[[str], None]


# ---------------------------------------------------------------- 設定とフォルダ

def load_config() -> Dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


class Workspace:
    def __init__(self, config: Dict):
        # 環境変数 NIPPO_WORKSPACE があれば config より優先（試験や別フォルダでの利用）
        root = Path(os.environ.get("NIPPO_WORKSPACE") or config.get("workspace", "~/日報")).expanduser()
        f = config.get("folders", {})
        self.root = root
        self.inbox = root / f.get("inbox", "素材")
        self.daily = root / f.get("daily", "日報")
        self.weekly = root / f.get("weekly", "週報")
        self.monthly = root / f.get("monthly", "月報")
        self.cache = root / f.get("cache", ".cache")

    def ensure(self):
        for p in (self.inbox, self.daily, self.weekly, self.monthly, self.cache):
            p.mkdir(parents=True, exist_ok=True)

    def daily_path(self, d: date) -> Path:
        return self.daily / (d.isoformat() + ".md")

    def weekly_path(self, d: date) -> Path:
        iso = d.isocalendar()
        return self.weekly / ("%d-W%02d.md" % (iso[0], iso[1]))

    def monthly_path(self, d: date) -> Path:
        return self.monthly / ("%04d-%02d.md" % (d.year, d.month))


# ---------------------------------------------------------------- 素材の収集

def scan_inbox(ws: Workspace) -> List["tuple[Path, datetime, str]"]:
    """素材フォルダを走査し、(ファイル, 日時, 根拠) を返す。文字の取り出しはまだしない。"""
    found = []
    for p in sorted(ws.inbox.rglob("*")):
        if not extractors.is_material(p):
            continue
        dt, basis = extractors.detect_datetime(p, ws.inbox)
        found.append((p, dt, basis))
    return found


def materials_between(ws: Workspace, first: date, last: date) -> Dict[date, List["tuple[Path, datetime, str]"]]:
    by_day: Dict[date, list] = {}
    for p, dt, basis in scan_inbox(ws):
        if first <= dt.date() <= last:
            by_day.setdefault(dt.date(), []).append((p, dt, basis))
    return by_day


def extract_all(entries, ws: Workspace, config: Dict, log: Log) -> List[Material]:
    mats = []
    for i, (p, dt, basis) in enumerate(entries, 1):
        log("[%d/%d] %s（%s）" % (i, len(entries), p.name, extractors.KIND_LABEL.get(extractors.kind_of(p), "?")))
        info = extractors.extract(p, ws.cache, config, log)
        mats.append(Material(p, dt, basis, info))
    return mats


# ---------------------------------------------------------------- 生成

Ask = Callable[[Path], bool]


def _may_write(path: Path, config: Dict, ask: Ask, log: Log) -> bool:
    if not path.exists():
        return True
    mode = config.get("overwrite", "ask")
    if mode == "replace":
        log("既存の %s を置き換えます" % path.name)
        return True
    if mode == "skip":
        log("既に %s があるため作り直しません（config の overwrite）" % path.name)
        return False
    if ask(path):
        return True
    log("既存の %s を残しました" % path.name)
    return False


def make_daily(day: date, ws: Workspace, config: Dict, log: Log, ask: Ask) -> Optional[Path]:
    ws.ensure()
    out = ws.daily_path(day)
    if not _may_write(out, config, ask, log):
        return out
    entries = materials_between(ws, day, day).get(day, [])
    log("%s の素材: %d 件" % (reporter.jp_date(day), len(entries)))
    mats = extract_all(entries, ws, config, log)
    out.write_text(reporter.build_daily(day, mats, config), encoding="utf-8")
    log("日報を書き出しました: %s" % out)
    return out


def _gather_dailies(first: date, last: date, ws: Workspace, config: Dict, log: Log):
    """期間内の日報を集める。素材はあるのに日報がない日は、先に日報を作る。"""
    by_day = materials_between(ws, first, last)
    kinds_by_day: Dict[date, Counter] = {}
    for d, entries in by_day.items():
        kinds_by_day[d] = Counter(extractors.kind_of(p) for p, _, _ in entries)
        if not ws.daily_path(d).exists():
            log("%s の日報がないので先に作ります" % reporter.jp_date(d))
            mats = extract_all(entries, ws, config, log)
            ws.daily_path(d).write_text(reporter.build_daily(d, mats, config), encoding="utf-8")
    dailies: "OrderedDict[date, Dict[str, List[str]]]" = OrderedDict()
    d = first
    while d <= last:
        p = ws.daily_path(d)
        if p.exists():
            dailies[d] = reporter.parse_report(p.read_text(encoding="utf-8"))
        d += timedelta(days=1)
    return dailies, kinds_by_day


def make_weekly(day: date, ws: Workspace, config: Dict, log: Log, ask: Ask) -> Optional[Path]:
    ws.ensure()
    out = ws.weekly_path(day)
    if not _may_write(out, config, ask, log):
        return out
    first, last = reporter.week_range(day)
    log("週報の期間: %s 〜 %s" % (first, last))
    dailies, kinds = _gather_dailies(first, last, ws, config, log)
    out.write_text(reporter.build_weekly(day, dailies, kinds, config), encoding="utf-8")
    log("週報を書き出しました: %s（日報 %d 日分）" % (out, len(dailies)))
    return out


def make_monthly(day: date, ws: Workspace, config: Dict, log: Log, ask: Ask) -> Optional[Path]:
    ws.ensure()
    out = ws.monthly_path(day)
    if not _may_write(out, config, ask, log):
        return out
    first, last = reporter.month_range(day)
    log("月報の期間: %s 〜 %s" % (first, last))
    dailies, kinds = _gather_dailies(first, last, ws, config, log)
    out.write_text(reporter.build_monthly(day, dailies, kinds, config), encoding="utf-8")
    log("月報を書き出しました: %s（日報 %d 日分）" % (out, len(dailies)))
    return out


def list_materials(first: date, last: date, ws: Workspace, log: Log):
    by_day = materials_between(ws, first, last)
    if not by_day:
        log("%s 〜 %s の素材はありません（%s）" % (first, last, ws.inbox))
        return
    for d in sorted(by_day):
        log("■ %s" % reporter.jp_date(d))
        for p, dt, basis in sorted(by_day[d], key=lambda e: e[1]):
            log("   %s %s（%s、根拠: %s）" % (dt.strftime("%H:%M"), p.relative_to(ws.inbox),
                                         extractors.KIND_LABEL.get(extractors.kind_of(p), "?"), basis))


def open_in_finder(path: Path, app: Optional[str] = None):
    """フォルダやファイルを OS 標準の方法で開く。

    app を指定するとそのアプリで開く（.md に既定のアプリが無いことがあるため）。
    Windows では既定のアプリで開く（アプリ名の指定は効かない）。
    """
    if sys.platform == "win32":
        try:
            os.startfile(str(path))          # type: ignore[attr-defined]
        except OSError:
            subprocess.Popen(["explorer", str(path)])
        return
    if sys.platform == "darwin":
        cmd = ["open"] + (["-a", app] if app and path.is_file() else []) + [str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.Popen(cmd)


# ---------------------------------------------------------------- 日付の読み取り

def parse_day(text: str, default: Optional[date] = None) -> date:
    text = (text or "").strip()
    if not text:
        return default or date.today()
    m = re.match(r"^(\d{4})[-/年.](\d{1,2})(?:[-/月.](\d{1,2})日?)?$", text)
    if not m:
        raise ValueError("日付は 2026-09-21 か 2026-09 の形で書いてください: %r" % text)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))


# ---------------------------------------------------------------- ボタン画面

def run_gui(config: Dict):
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    ws = Workspace(config)
    ws.ensure()

    root = tk.Tk()
    root.title("日報ツール")
    root.geometry("720x560")
    root.minsize(600, 420)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="素材フォルダ: %s" % ws.inbox).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Button(frame, text="素材フォルダを開く", command=lambda: open_in_finder(ws.inbox)).grid(row=0, column=3, sticky="e")
    ttk.Label(frame, text="ここに手書きメモの写真・テキスト・Word・Excel・音声を入れて、下のボタンを押します。"
                          "日付はファイル名（例: 2026-09-21_メモ.jpg）→ 撮影・録音日時 → ファイル作成日時の順で判定します。",
              wraplength=680, foreground="#555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))

    ttk.Label(frame, text="日付").grid(row=2, column=0, sticky="w")
    day_var = tk.StringVar(value=date.today().isoformat())
    ttk.Entry(frame, textvariable=day_var, width=14).grid(row=2, column=1, sticky="w")
    ttk.Button(frame, text="今日", command=lambda: day_var.set(date.today().isoformat())).grid(row=2, column=2, sticky="w")
    ttk.Label(frame, text="週報はこの日を含む週（月〜日）、月報はこの日を含む月", foreground="#555").grid(row=2, column=3, sticky="w")

    btns = ttk.Frame(frame)
    btns.grid(row=3, column=0, columnspan=4, sticky="w", pady=10)
    log_box = scrolledtext.ScrolledText(frame, height=18, wrap="word")
    log_box.grid(row=4, column=0, columnspan=4, sticky="nsew")
    frame.rowconfigure(4, weight=1)
    frame.columnconfigure(3, weight=1)
    status = tk.StringVar(value="待機中")
    ttk.Label(frame, textvariable=status).grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

    q: "queue.Queue[tuple]" = queue.Queue()
    working = {"busy": False}
    buttons: List[ttk.Button] = []

    def log(msg: str):
        q.put(("log", msg))

    def ask(path: Path) -> bool:
        # 作業スレッドから呼ばれるので、画面スレッドに問い合わせて答えを待つ
        ev = threading.Event()
        answer = {"ok": False}

        def show():
            answer["ok"] = messagebox.askyesno(
                "上書きの確認",
                "%s は既にあります。\n\n作り直すと、手で直した内容は消えます。\n作り直しますか？" % path.name)
            ev.set()
        root.after(0, show)
        ev.wait()
        return answer["ok"]

    def run(label: str, fn):
        if working["busy"]:
            return
        try:
            day = parse_day(day_var.get())
        except ValueError as e:
            messagebox.showerror("日付の形式", str(e))
            return
        working["busy"] = True
        for b in buttons:
            b.state(["disabled"])
        status.set("%s を作成中… 音声の文字起こしは時間がかかります" % label)
        log_box.delete("1.0", "end")

        def worker():
            try:
                out = fn(day, ws, config, log, ask)
                q.put(("done", out))
            except Exception as e:  # noqa: BLE001
                q.put(("error", "%s: %s" % (type(e).__name__, e)))
        threading.Thread(target=worker, daemon=True).start()

    def do_list():
        if working["busy"]:
            return
        try:
            day = parse_day(day_var.get())
        except ValueError as e:
            messagebox.showerror("日付の形式", str(e))
            return
        log_box.delete("1.0", "end")
        list_materials(day, day, ws, lambda m: log_box.insert("end", m + "\n"))

    for text, fn in (("日報を作る", make_daily), ("週報を作る", make_weekly), ("月報を作る", make_monthly)):
        b = ttk.Button(btns, text=text, command=lambda t=text, f=fn: run(t, f))
        b.pack(side="left", padx=(0, 8))
        buttons.append(b)
    b = ttk.Button(btns, text="この日の素材を確認", command=do_list)
    b.pack(side="left", padx=(0, 8))
    buttons.append(b)
    ttk.Button(btns, text="出力フォルダを開く", command=lambda: open_in_finder(ws.root)).pack(side="left")

    def poll():
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    log_box.insert("end", payload + "\n")
                    log_box.see("end")
                elif kind == "done":
                    working["busy"] = False
                    for b in buttons:
                        b.state(["!disabled"])
                    status.set("完了: %s" % payload)
                    if payload and config.get("openAfterGenerate", True):
                        open_in_finder(payload, config.get("openWith") or None)
                elif kind == "error":
                    working["busy"] = False
                    for b in buttons:
                        b.state(["!disabled"])
                    status.set("失敗しました")
                    log_box.insert("end", "エラー: " + payload + "\n")
                    log_box.see("end")
        except queue.Empty:
            pass
        root.after(100, poll)

    poll()
    root.mainloop()


# ---------------------------------------------------------------- コマンド実行

def main(argv: List[str]) -> int:
    config = load_config()
    if not argv:
        run_gui(config)
        return 0

    cmd, args = argv[0], argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    ws = Workspace(config)
    log = print

    def ask(path: Path) -> bool:
        if force:
            return True
        print("既に %s があります。作り直すには --force を付けてください" % path)
        return False

    if cmd == "extract":
        if not args:
            print("使い方: nippo.py extract <ファイル>")
            return 2
        p = Path(args[0]).expanduser().resolve()
        info = extractors.extract(p, ws.cache, config, log)
        print(json.dumps({k: v for k, v in info.items() if k != "text"}, ensure_ascii=False, indent=1))
        print(info.get("text", ""))
        return 1 if info.get("error") else 0

    day = parse_day(args[0] if args else "")
    if cmd == "daily":
        out = make_daily(day, ws, config, log, ask)
    elif cmd == "weekly":
        out = make_weekly(day, ws, config, log, ask)
    elif cmd == "monthly":
        out = make_monthly(day, ws, config, log, ask)
    elif cmd == "list":
        list_materials(day, day, ws, log)
        return 0
    else:
        print(__doc__)
        return 2
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
