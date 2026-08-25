"""フォルダやファイルを、パソコンの標準の方法で開く。

「原稿を入れるフォルダはどこ？」と探させないための道具。
画面のボタンから、そのフォルダをエクスプローラーで開く。

外部へは一切出ない。開くのはこのパソコンの中のものだけで、
呼び出し側（`server.py`）が号のフォルダの中かどうかを必ず確かめる。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(target: Path | str) -> tuple[bool, str]:
    """開く。戻り値は (開けたか, 利用者に見せる言葉)。"""
    p = Path(target)
    if not p.exists():
        return False, f"{p.name} が見つかりませんでした。"
    try:
        if sys.platform == "win32":
            os.startfile(str(p))          # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return False, (f"{p.name} を開けませんでした（{e}）。\n"
                       f"エクスプローラーで次の場所を開いてください:\n{p}")
    return True, f"{p.name} を開きました。"
