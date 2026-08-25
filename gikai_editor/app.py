#!/usr/bin/env python3
"""議会だより 原稿編集ツール — 起動用。

    python app.py                    画面を開く
    python app.py --no-browser       サーバだけ起動
    python app.py --workspace PATH   保存先フォルダを指定
    python app.py --quit             動いているツールを終了させる

保存先の既定はデスクトップの「議会だより」フォルダ。
無い場合は自動で作成する。

黒い画面（コマンドプロンプト）を閉じても動き続ける。
終わるときは、画面右上の「終了」ボタンか `python app.py --quit`。

外部への通信は行わない。127.0.0.1（このパソコンの中）だけで動く。
"""

from __future__ import annotations

import argparse
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from gikai import runstate  # noqa: E402
from gikai.server import serve  # noqa: E402
from gikai.workspace import default_workspace, ensure_workspace  # noqa: E402

ERROR_LOG = HERE / "起動エラー.log"


def _log_error(exc: BaseException) -> None:
    """画面が出ない起動のしかたでも原因が分かるよう、記録を残す。"""
    try:
        with open(ERROR_LOG, "w", encoding="utf-8") as f:
            f.write("議会だより 原稿編集ツール の起動に失敗しました。\n")
            f.write("この内容を担当者にお伝えください。\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except OSError:
        pass


def _quit_running() -> int:
    running = runstate.find_running()
    if not running:
        print("ツールは動いていません。")
        return 0
    if runstate.request_quit(running["url"]):
        runstate.clear()
        print("終了しました。")
        return 0
    print("終了できませんでした。タスクマネージャーから python を終了してください。")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="議会だより 原稿編集ツール")
    ap.add_argument("--workspace", "-w", default=None,
                    help=f"保存先フォルダ（既定: {default_workspace()}）")
    ap.add_argument("--port", "-p", type=int, default=0, help="ポート番号")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    ap.add_argument("--quit", action="store_true", help="動いているツールを終了させる")
    args = ap.parse_args()

    if args.quit:
        return _quit_running()

    # すでに動いていれば、二重に立ち上げず画面を開くだけにする
    running = runstate.find_running()
    if running:
        print("すでに起動しています。ブラウザで画面を開きます。")
        print(f"  画面   : {running['url']}")
        print(f"  保存先 : {running.get('workspace', '')}")
        if not args.no_browser:
            webbrowser.open(running["url"])
        return 0

    ws, note = ensure_workspace(args.workspace)

    httpd = serve(ws, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    print("=" * 62)
    print("  議会だより 原稿編集ツール")
    print("=" * 62)
    print(f"  画面      : {url}")
    print(f"  保存先    : {ws}")
    print("  通信範囲  : このパソコンの中だけ（外部には接続しません）")
    if note:
        print("")
        print(f"  {note}")
    print("")
    print("  終わるときは、画面右上の「終了」ボタンを押してください。")
    print("  （この画面を閉じてもツールは動き続けます）")
    print("=" * 62)

    ERROR_LOG.unlink(missing_ok=True)
    runstate.write(url, httpd.server_address[1], str(ws))

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        httpd.server_close()
        runstate.clear()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as e:  # 画面が出ない起動でも原因を残す
        _log_error(e)
        raise
