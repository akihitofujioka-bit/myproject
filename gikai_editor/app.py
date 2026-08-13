#!/usr/bin/env python3
"""議会だより 原稿編集ツール — 起動用。

    python app.py                    画面を開く
    python app.py --no-browser       サーバだけ起動
    python app.py --workspace PATH   保存先フォルダを指定

外部への通信は行わない。127.0.0.1（このパソコンの中）だけで動く。
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gikai.server import serve  # noqa: E402

DEFAULT_WORKSPACE = Path.home() / "議会だより"


def main() -> int:
    ap = argparse.ArgumentParser(description="議会だより 原稿編集ツール")
    ap.add_argument("--workspace", "-w", default=str(DEFAULT_WORKSPACE),
                    help=f"保存先フォルダ（既定: {DEFAULT_WORKSPACE}）")
    ap.add_argument("--port", "-p", type=int, default=0, help="ポート番号")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser()
    ws.mkdir(parents=True, exist_ok=True)

    httpd = serve(ws, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    print("=" * 62)
    print("  議会だより 原稿編集ツール")
    print("=" * 62)
    print(f"  画面      : {url}")
    print(f"  保存先    : {ws}")
    print("  通信範囲  : このパソコンの中だけ（外部には接続しません）")
    print("")
    print("  終了するには、この画面で Ctrl+C を押してください。")
    print("=" * 62)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
