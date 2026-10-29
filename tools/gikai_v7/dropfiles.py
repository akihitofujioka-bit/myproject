"""Windows で、エクスプローラーからファイルを画面へドロップして受け取る。

追加の部品は使わず、Python に付いている ctypes で Windows の仕組み（WM_DROPFILES）を
呼ぶ。Windows 以外や、仕組みを使えなかったときは何もせず False を返す（ボタンからの
取り込みはそのまま使える）。
"""

from __future__ import annotations

import sys
from typing import Callable, List

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def enable(widget, callback: Callable[[List[str]], None]) -> bool:
    """widget（ふつうは画面全体）へのドロップを受け付ける。使えたら True。"""
    if sys.platform != "win32":
        return False
    try:
        return _enable_windows(widget, callback)
    except Exception:
        return False


def _enable_windows(widget, callback) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    lresult = ctypes.c_ssize_t
    wndproc = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        set_long = user32.SetWindowLongPtrW
    else:
        set_long = user32.SetWindowLongW
    set_long.restype = ctypes.c_void_p
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = lresult
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                       ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    # Tk の窓は、中身の窓（winfo_id）と、その外側の枠の窓の二重になっている。
    # どちらの上に落としても受け取れるよう、両方に受け付けの印と受け取り口を付ける。
    hwnd = widget.winfo_id()
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    targets = [hwnd]
    outer = user32.GetParent(hwnd)
    if outer:
        targets.append(outer)
    kept = []
    for target in targets:
        hook = _hook(ctypes, user32, shell32, set_long, wndproc, target, widget, callback)
        if hook is not None:
            kept.append(hook)
    if not kept:
        return False
    # 呼び出し先が消えないよう、画面の部品に持たせておく。
    widget._gikai_drop = kept
    return True


def _hook(ctypes, user32, shell32, set_long, wndproc, hwnd, widget, callback):
    """1 つの窓に、ドロップの受け付けと受け取り口（窓の処理の差し替え）を付ける。"""
    previous = [None]

    def handle(window, message, wparam, lparam):
        if message == WM_DROPFILES:
            paths = []
            try:
                count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for index in range(count):
                    length = shell32.DragQueryFileW(wparam, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                    paths.append(buffer.value)
            finally:
                shell32.DragFinish(wparam)
            # Windows の処理の途中で画面を作り替えないよう、一息おいてから渡す。
            widget.after(10, lambda: callback(paths))
            return 0
        return user32.CallWindowProcW(previous[0], window, message, wparam, lparam)

    procedure = wndproc(handle)
    shell32.DragAcceptFiles(hwnd, True)
    previous[0] = set_long(hwnd, GWLP_WNDPROC, ctypes.cast(procedure, ctypes.c_void_p))
    if not previous[0]:
        shell32.DragAcceptFiles(hwnd, False)
        return None
    return (procedure, previous)
