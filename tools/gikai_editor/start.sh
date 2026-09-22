#!/bin/sh
# 議会だより 原稿編集ツール（macOS / Linux 用）
cd "$(dirname "$0")" || exit 1
exec python3 app.py "$@"
