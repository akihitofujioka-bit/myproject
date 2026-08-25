"""保存先フォルダの決定。

既定の保存先は「デスクトップ ＼ 議会だより」。
デスクトップの場所は OS や設定によって違うため、次の順に調べる。

  Windows : レジストリの Shell Folders（OneDrive にリダイレクトされていても正しく取れる）
            → USERPROFILE\\Desktop
  macOS   : ~/Desktop
  Linux   : ~/.config/user-dirs.dirs の XDG_DESKTOP_DIR → ~/Desktop → ~/デスクトップ

デスクトップが見つからない場合や、作成できない場合は
ホームフォルダの下に切り替える（起動できなくなるのを避けるため）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

WORKSPACE_NAME = "議会だより"


def _windows_desktop() -> Path | None:
    """Windows のデスクトップ。OneDrive へのリダイレクトにも対応する。"""
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    for key_path in (
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
        except OSError:
            continue
        if not value:
            continue
        # %USERPROFILE%\Desktop のような環境変数を展開する
        expanded = Path(os.path.expandvars(value))
        if expanded.is_dir():
            return expanded
    return None


def _linux_desktop() -> Path | None:
    """XDG のユーザーディレクトリ設定を読む。"""
    conf = Path.home() / ".config" / "user-dirs.dirs"
    if conf.exists():
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        m = re.search(r'^\s*XDG_DESKTOP_DIR\s*=\s*"(.*)"\s*$', text, re.MULTILINE)
        if m:
            raw = m.group(1).replace("$HOME", str(Path.home()))
            p = Path(os.path.expandvars(raw)).expanduser()
            if p.is_dir():
                return p
    return None


def desktop_dir() -> Path | None:
    """デスクトップのフォルダ。見つからなければ None。"""
    if sys.platform == "win32":
        found = _windows_desktop()
        if found:
            return found
    elif sys.platform == "linux":
        found = _linux_desktop()
        if found:
            return found

    for name in ("Desktop", "デスクトップ"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return None


def default_workspace() -> Path:
    """既定の保存先「デスクトップ＼議会だより」。

    フォルダはまだ無くてもよい（``ensure_workspace`` が作る）。
    デスクトップが見つからない場合はホームフォルダの下を返す。
    """
    desktop = desktop_dir()
    base = desktop if desktop is not None else Path.home()
    return base / WORKSPACE_NAME


def ensure_workspace(path: Path | str | None = None) -> tuple[Path, str]:
    """保存先フォルダを用意する。無ければ作る。

    戻り値は (実際に使うフォルダ, 利用者への説明). 説明は空文字なら
    特に伝えることがないという意味。

    指定された場所に作れなかった場合（権限が無い、ドライブが無いなど）は、
    ホームフォルダの下に切り替える。**起動できなくなるより、
    場所が変わってでも動くほうがよい**という判断。
    """
    target = Path(path).expanduser() if path else default_workspace()
    existed = target.is_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        if existed:
            return target, ""
        return target, f"保存先フォルダを作成しました: {target}"
    except OSError as e:
        fallback = Path.home() / WORKSPACE_NAME
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            # ホームにも作れないなら、現在のフォルダを使うほかない
            fallback = Path.cwd() / WORKSPACE_NAME
            fallback.mkdir(parents=True, exist_ok=True)
        return fallback, (
            f"保存先 {target} を作成できなかったため（{e.strerror or e}）、"
            f"{fallback} を使います。"
        )
