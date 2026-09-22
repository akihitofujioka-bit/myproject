このフォルダについて
====================

議会だより 原稿編集ツール が使う「追加部品」を、あらかじめ入れてあります。
インターネットにつながらないパソコンでも導入できるようにするためです。

  pillow-*-win_amd64.whl   写真の切り出し・向きの補正・解像度の判定に使います。
                           Python のバージョンごとに 1 つずつ入っています。
                           使うのは 1 つだけで、残りは自動的に無視されます。

  pymupdf-*-win_amd64.whl  PDF で届いた原稿を読むために使います。
                           1 つで Python 3.10 以降に対応します。

  pypdf-*-py3-none-any.whl PyMuPDF が使えないときの予備です。
                           どのバージョンの Python でもそのまま動きますが、
                           日本語の PDF では文字が正しく取り出せないことが
                           あります。ふだんは PyMuPDF が使われます。

対応している環境
----------------
  Windows 64ビット版 / Python 3.10・3.11・3.12・3.13・3.14

  ※ macOS や Linux では、この中のファイルは使えません。
    その場合は次のようにインターネット経由で入れてください。
        pip install Pillow pymupdf pypdf

入れ方
------
  「追加部品のインストール.bat」をダブルクリックしてください。
  このフォルダの中だけを見に行くので、インターネットには接続しません。

新しくしたいとき（インターネットのあるパソコンで）
--------------------------------------------------
  pip download Pillow --dest wheels --only-binary=:all: ^
      --platform win_amd64 --python-version 3.13 --no-deps
  pip download pymupdf --dest wheels --only-binary=:all: ^
      --platform win_amd64 --python-version 3.13 --no-deps
  pip download pypdf --dest wheels --only-binary=:all: --no-deps
