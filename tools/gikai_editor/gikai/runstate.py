"""起動中かどうかの記録。

黒い画面（コマンドプロンプト）を閉じても動き続ける作りにしたため、
「いま動いているか」「どのアドレスで動いているか」を記録しておく必要がある。
一時フォルダに小さな JSON を置いて、それを目印にする。

この目印は起動用バッチファイルも見ている（立ち上がったかどうかの判定）。
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

APP_ID = "gikai_editor"
STATE_FILE = Path(tempfile.gettempdir()) / "gikai_editor_run.json"


def write(url: str, port: int, workspace: str) -> None:
    """起動したことを記録する。"""
    data = {
        "app": APP_ID,
        "url": url,
        "port": port,
        "pid": os.getpid(),
        "workspace": workspace,
    }
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def read() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def clear() -> None:
    try:
        STATE_FILE.unlink()
    except OSError:
        pass


def _ping(url: str, timeout: float = 1.5) -> dict | None:
    """そのアドレスでこのツールが応答するか確かめる。"""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/ping", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None
    return data if data.get("app") == APP_ID else None


def find_running() -> dict | None:
    """すでに起動しているならその情報を返す。

    記録が残っていても応答が無ければ（前回異常終了したなど）、
    古い記録として消してから None を返す。
    """
    state = read()
    if not state or not state.get("url"):
        return None
    alive = _ping(state["url"])
    if alive is None:
        clear()
        return None
    state.update(alive)
    return state


def request_quit(url: str, timeout: float = 3.0) -> bool:
    """動いているツールに終了をお願いする。"""
    req = urllib.request.Request(
        url.rstrip("/") + "/api/quit",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
    except (urllib.error.URLError, OSError):
        return False
    return True
