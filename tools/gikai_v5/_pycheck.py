"""Python が本当に動くかを確かめるための小さな道具（gikai_editor から複製）。

バッチファイルから呼ばれ、引数で渡された場所に "ok" と書くだけ。
「コマンドは見つかるのに実行できない Python」を見分けるために使う。
このツールは画面に tkinter を使うので、tkinter が読めない Python も「動かない」とみなす。
"""

import sys

import tkinter  # noqa: F401  画面の部品が無い Python は使えない

with open(sys.argv[1], "w", encoding="ascii") as f:
    f.write("ok")
