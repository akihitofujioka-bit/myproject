"""Python が本当に動くかを確かめるための小さな道具。

バッチファイルから呼ばれ、引数で渡された場所に "ok" と書くだけ。
「コマンドは見つかるのに実行できない Python」を見分けるために使う。
（バッチの中に括弧を書かずに済ませたいので、別ファイルにしている）
"""

import sys

with open(sys.argv[1], "w", encoding="ascii") as f:
    f.write("ok")
