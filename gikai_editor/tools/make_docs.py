#!/usr/bin/env python3
"""仕様書（ソースコード付き）を作る。

    python tools/make_docs.py

`仕様書.md` を作り直す。中身は次の2部構成。

  第1部　仕様 — 何をするアプリで、どう動いているか
  第2部　ソースコード — 全ファイルの中身

コードを直したらこれを実行し直せば、仕様書も追従する。
手で書き写さないので、書いてある内容と実物がずれない。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "仕様書.md"
FENCE = "`" * 3

# 収録するファイルと、その説明。並び順がそのまま目次になる。
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("起動まわり", [
        ("app.py", "起動用。二重起動の判定、保存先の用意、サーバの開始と停止。"),
        ("gikai/workspace.py", "保存先フォルダの決定。デスクトップの場所を OS ごとに調べる。"),
        ("gikai/runstate.py", "起動中かどうかの記録。黒い画面を閉じても動き続けるための目印。"),
        ("_pycheck.py", "Python が本当に動くかを確かめる小さな道具。バッチから呼ばれる。"),
    ]),
    ("原稿の取り込み", [
        ("gikai/importers.py", "docx / doc / txt / pdf / rtf の取り込み。文字コードの自動判別。"),
        ("gikai/doc97.py", "Word 旧形式(.doc)を追加ソフト無しで読む。OLE2 と FIB を自分で解く。"),
        ("gikai/textutil.py", "日本語の正規化・字数計算・文分割。縦書きの数字表記もここ。"),
    ]),
    ("校正と要約", [
        ("gikai/proofread.py", "校正エンジン。8種類の観点で原稿を見る。"),
        ("gikai/summarize.py", "冗長表現の圧縮と抽出型要約。文章の生成はしない。"),
    ]),
    ("写真", [
        ("gikai/photos.py", "向きの補正・枠に合わせた切り出し・印刷解像度の判定。"),
        ("gikai/autolayout.py", "写真の名前から、記事と紙面の枠を自動で割り当てる。"),
    ]),
    ("紙面を作る", [
        ("gikai/compose.py", "自動組版。5段縦書きの Word を組み立て、ページ数を見積もる。"),
        ("gikai/docxio.py", "前号の様式に差し込む方式。枠を見つけて中身だけ入れ替える。"),
        ("gikai/preview.py", "画面で見る下見用の紙面（HTML）。"),
    ]),
    ("全体のとりまとめ", [
        ("gikai/easy.py",
         "かんたん作成。区分ごとのフォルダの中身から、1号ぶんを組み立てる。"),
        ("gikai/shellopen.py",
         "フォルダやファイルを、パソコンの標準の方法で開く。"),
        ("gikai/sections.py",
         "議会だよりの構成（表紙→行政報告→…→最終ページ）。"
         "原稿がどの区分のものかの判定もここ。"),
        ("gikai/project.py", "1号ぶんの作業データ。記事・写真・設定の保存と読み出し。"),
        ("gikai/server.py", "ローカル専用サーバ。画面とのやりとりはすべてここを通る。"),
        ("gikai/__init__.py", "版数。"),
    ]),
    ("画面", [
        ("gikai/static/index.html", "画面の骨組み。6つの手順が1ページに入っている。"),
        ("gikai/static/style.css", "見た目。"),
        ("gikai/static/app.js", "画面の動き。通信先はこのパソコンの中だけ。"),
    ]),
    ("辞書データ（自治体に合わせて書き換えるところ）", [
        ("gikai/data/style_rules.json", "表記ルール。第203号の原稿と印刷版の差分から採録。"),
        ("gikai/data/confusions.json", "同音異義語と明確な誤字。"),
        ("gikai/data/ruby.json", "難読語とその読み。"),
        ("gikai/data/local_terms.json", "固有名詞（議員名・地名・課名など）。"),
    ]),
    ("Windows 用の起動ファイル", [
        ("_find_python.bat", "使える Python を探す。全バッチが共通で呼ぶ。"),
        ("起動.bat", "起動。立ち上がったら自分は閉じる。"),
        ("終了.bat", "終了。"),
        ("追加部品のインストール.bat", "同梱した部品を入れる。外部に接続しない。"),
        ("デスクトップにアイコンを作る.bat", "ショートカットの作成。"),
        ("start.sh", "macOS / Linux 用の起動。"),
    ]),
    ("その他", [
        ("CLAUDE.md", "コードをさわる人・AI 向けの約束ごと。踏んではいけない罠の一覧。"),
        ("requirements.txt", "追加部品の一覧。"),
        ("wheels/README.txt", "同梱した部品の説明と更新方法。"),
        ("tools/make_icon.py", "アイコンを作り直すとき。"),
        ("tools/make_docs.py",
         "この仕様書を作り直すとき。第1部の文章もこの中に入っているため、"
         "以下のコードには仕様の文言がそのまま現れる。"),
    ]),
    ("テスト", [
        ("tests/test_all.py", "全体のテスト。pytest が無くても直接実行できる。"),
    ]),
]

# API の窓口の説明。server.py から拾った並び順で表にする。
API_DESC = {
    "ping": "起動しているかの確認（バッチと二重起動の判定に使う）",
    "quit": "終了する",
    "workspace": "保存済みの号の一覧",
    "project/create": "新しい号を作る",
    "project/open": "保存済みの号を開く",
    "project": "いま開いている号の内容",
    "project/settings": "号の設定を変える",
    "template/upload": "様式（Word）を読み込む",
    "template/slots": "様式の枠の一覧",
    "template/image": "様式に入っている画像を返す",
    "template/images": "様式の画像の位置（ページ・順番）",
    "article/import": "原稿ファイルを取り込む",
    "article/paste": "貼り付けた文章を記事にする",
    "article/list": "記事の一覧",
    "article/save": "記事を保存する",
    "article/delete": "記事を削除する",
    "article/delete_many": "選んだ記事をまとめて削除する（元の原稿ファイルは残す）",
    "outline": "構成（表紙→行政報告→…）の順に並べた記事の一覧",
    "outline/sections": "構成そのものを変える（区分の追加・削除・並べ替え）",
    "outline/assign": "原稿の名前や見出しから、どの区分かを自動で振り分ける",
    "outline/move": "区分の中で記事を1つ上／下へ動かす",
    "easy/state": "かんたん作成の画面の状態（フォルダの中身・最大ページ数）",
    "easy/folders": "区分ごとの原稿フォルダを作る",
    "easy/max_pages": "最大ページ数を決める",
    "easy/rename": "原稿や写真の名前を変える（別の区分へ移すのもここ）",
    "easy/renumber": "1つの区分の原稿に、いまの並び順で 01_ 02_ … を振り直す",
    "easy/build": "フォルダの中身から1号ぶんを組み立てる（かんたん作成の本体）",
    "easy/pdf": "組み上がった Word を PDF にする（できあがりの確認用）",
    "open": "フォルダやファイルをパソコンの標準の方法で開く（号のフォルダの中だけ）",
    "article/proofread": "記事を校正する",
    "article/autofix": "自動で直せる指摘をまとめて直す",
    "article/fit": "枠に合わせて要約する",
    "article/shorten": "冗長表現を縮める",
    "article/titles": "見出し・リード文の候補を作る",
    "text/measure": "文字数・行数を数える",
    "text/proofread": "任意の文章を校正する",
    "photo/upload": "写真を取り込む",
    "photo/list": "写真の一覧",
    "photo/save": "写真の説明文・差し込み先を保存する",
    "photo/delete": "写真を削除する",
    "photo/autolayout": "写真の名前から記事と枠を自動で割り当てる",
    "photo/thumb": "写真の縮小画像",
    "photo/preview": "枠に合わせて切り出した結果",
    "layout/get": "紙面の決まりごとを読む",
    "layout/save": "紙面の決まりごとを保存する",
    "compose": "自動組版で紙面を組む",
    "layout/plan": "目標ページ数に対して何字詰めるかを計算する",
    "layout/fit": "目標ページ数に合わせてまとめて詰める",
    "export": "様式に差し込んで書き出す",
    "export/preview": "紙面プレビュー（下見用の HTML）",
    "download": "書き出したファイルを受け取る",
    "dict/get": "この号の固有名詞辞書を読む",
    "dict/save": "この号の固有名詞辞書を保存する",
}

LANG = {".py": "python", ".js": "javascript", ".css": "css", ".html": "html",
        ".json": "json", ".bat": "bat", ".sh": "sh", ".txt": "text", ".md": "markdown"}


def read_text(path: Path) -> str:
    """UTF-8 と CP932（バッチファイル）の両方に対応して読む。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def gather_facts() -> dict:
    """仕様書に載せる数字を、実物から数える。手書きしないのでずれない。"""
    sys.path.insert(0, str(ROOT))
    from gikai import __version__
    from gikai.compose import LayoutSpec
    from gikai.proofread import CHECKS, Dictionaries
    from gikai.summarize import SHORTEN_RULES

    dic = Dictionaries()
    style_counts = {g: len(b.get("rules", []))
                    for g, b in dic.style.items() if isinstance(b, dict)}

    endpoints = []
    for line in read_text(ROOT / "gikai" / "server.py").splitlines():
        line = line.strip()
        if line.startswith('if path == "'):
            endpoints.append(line.split('"')[1])

    files = [f for _, items in SECTIONS for f, _ in items]
    total_lines = sum(read_text(ROOT / f).count("\n") for f in files
                      if (ROOT / f).exists())

    tests = 0
    for line in read_text(ROOT / "tests" / "test_all.py").splitlines():
        if line.startswith("def test_"):
            tests += 1

    return {
        "version": __version__,
        "checks": CHECKS,
        "style_counts": style_counts,
        "confusions": len(dic.confusions["pairs"]),
        "typos": len(dic.confusions["typos"]["pairs"]),
        "ruby": len(dic.ruby["words"]),
        "nouns": len(dic.proper_nouns()),
        "shorten": len(SHORTEN_RULES),
        "endpoints": endpoints,
        "files": len(files),
        "lines": total_lines,
        "tests": tests,
        "metrics": LayoutSpec().metrics(),
        "spec": LayoutSpec(),
    }


def spec_part(f: dict) -> str:
    """第1部（仕様）。数字は gather_facts で数えた実物の値を使う。"""
    m = f["metrics"]
    s = f["spec"]
    checks = "\n".join(f"| {k} | {v} |" for k, v in f["checks"].items())
    style = "\n".join(
        f"| {g} | {n} 件 |" for g, n in f["style_counts"].items() if n)
    api = "\n".join(
        f"| `{e}` | {API_DESC.get(e, '')} |" for e in f["endpoints"])

    return f"""# 議会だより 原稿編集ツール 仕様書

版 {f['version']}／{date.today().isoformat()} 作成

各議員からばらばらの様式で届く原稿を、**校正・要約し、写真を配置して、
1ページ5段縦書きの紙面に組む**までを、インターネットにつながずに行う道具です。

この文書は2部構成です。

- **第1部 仕様** — 何をするアプリで、どう動いているか
- **第2部 ソースコード** — 全 {f['files']} ファイル・約 {f['lines']:,} 行の中身

> ソースコードは実物から自動で書き出しています（`python tools/make_docs.py`）。
> コードを直したら作り直してください。書いてある内容と実物がずれません。

---

# 第1部　仕様

## 1. このアプリについて

### 解決したい困りごと

議会だよりの編集では、次の作業が毎号くり返されます。

1. 議員からの原稿が、Word・テキスト・PDF・メール本文などばらばらの形で届く
2. 誤字脱字と表記ゆれを直す（「等」を「など」に開くなど、本誌の決まりがある）
3. 枠に入りきらない原稿を短くする
4. 写真を集めて、記事のそばに置き、大きさをそろえる
5. Word の紙面に流し込む

このツールは、**1・2・3・4を機械でできるところまで進めて、
人が内容の確認に集中できるようにする**ことを目的にしています。

### やらないこと

- **文章を書き直しません。** 要約は、原稿にあった文を選んで残す方式です
- **校正の判断を代行しません。** 指摘を出すところまでで、直すかどうかは人が決めます
- **外部に何も送りません。** 原稿・写真・議員名がこのパソコンから出ることはありません

## 2. 動作環境

| 項目 | 内容 |
|---|---|
| OS | Windows 10/11、macOS、Linux |
| 必須 | Python 3.10 以降 |
| 推奨 | Pillow（写真加工）、PyMuPDF（PDF 読み込み）— どちらも同梱 |
| 任意 | LibreOffice（PDF 書き出し、`.doc` 様式の変換） |
| 通信 | `127.0.0.1` のみ。外部への接続なし |

追加部品は `wheels` フォルダに同梱してあり、**インターネットにつながっていない
パソコンでも導入できます**（Windows 64ビット版 / Python 3.10〜3.14 向け）。

## 3. 全体の流れ

```
議員から届いた原稿           写真
  .docx .doc .txt .pdf        .jpg .png
        │                      │
        ▼                      ▼
  ① 取り込み ────────────  ファイル名で記事に結び付け
     文字コード自動判別          （autolayout）
     旧形式 .doc も対応
        │
        ▼
  ② 校正（proofread）
     誤字・表記ゆれ・固有名詞の誤記を指摘
        │
        ▼
  ③ 字数調整（summarize）
     冗長表現の圧縮 → 足りなければ抽出要約
        │
        ▼
  ④ 紙面に組む
     ┌── 自動組版（compose）── 5段縦書き固定、ページ数は分量しだい
     └── 差し込み（docxio） ── 前号の様式の枠に入れ替え
        │
        ▼
     Word ファイル（必要なら PDF）
```

## 4. ファイル構成

```
gikai_editor/
  app.py                        起動用
  起動.bat / 終了.bat            Windows 用
  _find_python.bat              使える Python を探す
  追加部品のインストール.bat       同梱部品の導入
  デスクトップにアイコンを作る.bat
  icon.ico / icon.png           アイコン
  wheels/                       同梱した追加部品
  gikai/
    textutil.py     日本語の正規化・字数計算
    importers.py    原稿の取り込み
    doc97.py        Word 旧形式の読み取り
    proofread.py    校正エンジン
    summarize.py    要約・字数調整
    photos.py       写真の加工
    autolayout.py   写真の自動割り付け
    compose.py      自動組版
    docxio.py       様式への差し込み
    preview.py      紙面プレビュー
    project.py      作業データ
    workspace.py    保存先フォルダ
    runstate.py     起動状態
    server.py       ローカル専用サーバ
    data/           辞書
    static/         画面
  tools/            アイコン・仕様書の生成
  tests/            テスト（{f['tests']} 件）
```

## 5. データの持ち方

作業データは1号ぶんが1フォルダにまとまります。**フォルダごとコピーすれば
別のパソコンに引き継げます。**

```
デスクトップ/議会だより/第204号/
  project.json      記事・写真・割付・設定（下記）
  template.docx     様式（差し込み方式のとき）
  manuscripts/      届いた原稿の原本（そのまま保存）
  photos/           写真の原本（そのまま保存）
  出力/             書き出した Word / PDF
  user_dict.json    この号だけの固有名詞辞書
```

**原本は書き換えません。** `manuscripts/` と `photos/` には届いたままの
ファイルが残るので、編集はいつでもやり直せます。

### project.json

| キー | 内容 |
|---|---|
| `schema` | データ形式の版 |
| `title` / `issue_no` / `issue_date` | 号の名前・号数・発行日 |
| `created` / `updated` | 作成日時・最終更新 |
| `template` | 様式ファイル名（差し込み方式のとき） |
| `articles` | 記事の配列（下記） |
| `photos` | 写真の配列（下記） |
| `layout` | 紙面の決まりごと（自動組版のとき） |
| `settings` | 校正の設定、組み方、目標ページ数 |

### 記事（articles の1件）

| 項目 | 内容 |
|---|---|
| `id` | 内部の識別子 |
| `title` / `author` / `lead` | 見出し・執筆者・リード文 |
| `source_file` | 元の原稿ファイル名（`manuscripts/` の中） |
| `raw` | 取り込んだままの本文（「取り込んだ原稿に戻す」で使う） |
| `body` | 編集後の本文。**これが紙面に出る** |
| `slot` / `title_slot` / `lead_slot` / `author_slot` | 差し込み先の枠 |
| `limit_chars` / `chars_per_line` / `lines` | 枠の字数・行数 |
| `photos` | この記事の写真（id の配列、並び順どおり） |
| `status` | 下書き／校正済み／割付済み／確定 |
| `ignored_issues` | 「以後指摘しない」にした校正ルール |

### 写真（photos の1件）

| 項目 | 内容 |
|---|---|
| `id` / `file` | 識別子・保存名 |
| `caption` / `credit` | 説明文・撮影者 |
| `slot` / `caption_slot` | 差し込み先（様式の画像名・説明文の枠） |
| `focus` | 切り出しの中心（既定は少し上寄り。人物写真を想定） |
| `info` | 元の大きさ、印刷可否の判定結果 |

### 紙面の決まりごと（layout）

| 項目 | 既定値 |
|---|---|
| 判型 | A4 縦（{s.page_width_mm:.0f} × {s.page_height_mm:.0f} mm） |
| 余白 | 上 {s.margin_top_mm:.0f} / 下 {s.margin_bottom_mm:.0f} / 左右 {s.margin_left_mm:.0f} mm |
| 段数 | **{s.columns} 段**（縦書き）／段間 {s.column_gap_mm:.0f} mm |
| 本文 | {s.body_font} {s.body_pt} pt ／ 行送り {s.line_spacing} 倍 |
| 見出し | {s.heading_font} {s.heading_pt} pt |
| 説明文 | {s.caption_pt} pt |
| 写真 | 段の高さの {s.photo_height_ratio} 倍 |

この既定値での字詰めは **1段 {m['chars_per_line']} 字 × {m['lines_per_column']} 行
（段の高さ {m['column_height_mm']} mm）／ 1ページ 約 {m['chars_per_page']} 字** です。

## 6. 画面とサーバのやりとり

画面はブラウザで動き、`127.0.0.1` の自前サーバと JSON でやりとりします。
**外部のホスト名でアクセスされた場合は 403 で拒否します。**

全 {len(f['endpoints'])} 個の窓口:

| 窓口 | 内容 |
|---|---|
{api}

## 7. 主要な処理の仕組み

### 7-1. 原稿の取り込み（importers.py / doc97.py）

| 形式 | 読み方 |
|---|---|
| `.docx` | ZIP を開いて XML を読む。本文・表・テキストボックスすべて |
| `.doc` | **自前で解読**（doc97.py）。追加ソフト不要 |
| `.txt` | UTF-8 / CP932 / EUC-JP を自動判別。化けを検出して選び直す |
| `.pdf` | PyMuPDF。無ければ pypdf（日本語は精度が落ちるため注意書きを出す） |
| `.rtf` | 書式を捨てて文字だけ |

**Word 旧形式の読み取り**は、複合文書（OLE2）を自分で解いてから、
FIB → CLX → ピーステーブルをたどって文字を取り出しています。
テキストボックスの中身も拾うので、見出しや写真の説明が落ちません。
フィールド（ページ番号など）は指示部分を捨てて結果だけ残します。

**取り込み時の整形**（設定で切り替え可）:

- 半角カナ → 全角、句読点・括弧を全角に統一、全角英数字 → 半角
- **数字を縦書きの慣行に合わせる** — 1桁は全角「４月」、2桁以上は半角「12日」
- 1行目が短く句点で終わっていなければ、見出しとみなして本文から切り出す

### 7-2. 校正（proofread.py）

{len(f['checks'])} 種類の観点で見ます。

| 記号 | 観点 |
|---|---|
{checks}

指摘は3段階（**要修正** / **確認** / **参考**）で色分けし、
機械的に直せるものだけ「まとめて修正」の対象にします。
**同音異義語とルビの提案は自動修正しません**（文脈で正解が変わるため）。

辞書の規模:

| 辞書 | 件数 |
|---|---|
{style}
| 同音異義語 | {f['confusions']} 組 |
| 明確な誤字 | {f['typos']} 件 |
| 難読語（ルビ提案） | {f['ruby']} 語 |
| 固有名詞 | {f['nouns']} 語 |

**表記ルールは推測ではありません。** 第203号の Word 原稿と印刷版を
1文字ずつ突き合わせ、実際に行われている書き換え（等→など、ひとつ→一つ、
買入れ→買い入れ、〜にて→〜で、様々→さまざま、子供→子ども）を採録しています。

**固有名詞の誤記検出**は2通りです。

1. 字形の似た漢字の取り違え（山崎↔山﨑、尾崎↔尾﨑、高↔髙 など）
2. 辞書の語と1文字だけ違う語（編集距離）

### 7-3. 要約・字数調整（summarize.py）

2段階で、**情報を落とさない方から順に**試します。

1. **冗長表現の圧縮**（{f['shorten']} 通りの言い換え）
   「対応することができる」→「対応できる」、「〜ということである」→「〜という」。
   これで枠に入れば**内容は一切落ちません**
2. **抽出型要約** — 1で足りないとき、重要度の低い文を落とす

重要度は、語の出現頻度（TF）と語の希少さ（IDF）から計算し、
冒頭の文と結論を示す語（決定・可決・課題・必要 など）を含む文を優遇します。
**各段落の先頭文は優先的に残します。**

> **文章を作り直しません。** 残った文はすべて原稿にあった文そのものなので
> 事実が変わることはありませんが、**文脈がつながらなくなることはあります。**
> そのため、反映前に必ず左右の比較画面を出します。

### 7-4. 写真の自動割り付け（autolayout.py）

**写真のファイル名を原稿と同じにしておくと、その記事に結び付きます。**

| | 名前 |
|---|---|
| 原稿 | `森下けい子_原稿.docx` |
| 写真 | `森下けい子_原稿.jpg` |
| 複数 | `森下けい子_原稿1.jpg` `森下けい子_原稿2.jpg`（番号順に並ぶ） |

比較の前に、全角半角・記号・空白の違いを取り除き、末尾の連番
（`_2` `②` `（3）` など）を切り離して並び順として扱います。
「写真」「原稿」のような区別に役立たない語も外します。

判定は確からしさを点数にし、55点未満は「分からなかった」として
一覧に出します。**自動でやったことは必ず全部見せて、手で直せるようにしています。**

差し込み方式では、記事が入る枠のページを見て、**同じページの空いている
写真枠**を選び、そのそばの説明文の枠も押さえます。

### 7-5. 自動組版（compose.py）

**紙面の決まりごとだけを固定し、中身は Word に組ませる**方式です。

Word の文書に次を指定します。

- `w:cols w:num="5"` — 1ページ5段
- `w:textDirection w:val="tbRl"` — 縦書き
- `w:docGrid` — 字送り・行送り

**段送りと改ページは Word 自身が行う**ので、原稿が増えればページが増え、
写真を入れればその分だけ本文が押し出されます。

**ページ数の見積もり**は、字数ではなく**行数**で数えます。

| 数えるもの | 理由 |
|---|---|
| 段落ごとの折り返し（切り上げ） | 段落の終わりは行の途中で終わる |
| 見出しの大きさ | 本文より大きい分だけ行を余分に使う |
| 写真の幅ぶんの行数 | 行が並ぶ方向に場所を取る |
| **写真の半分ぶんの空き** | 写真は段をまたげないので手前に空きができる |
| 記事の切れ目 7 行 | 段の変わり目の半端な空き |

実際に Word で組んだ結果と突き合わせて補正し、**記事1〜18本・写真0〜14枚の
10通りで、すべて実測のページ数と一致**しました。

**目標ページ数を指定**すると、記事ごとに何字詰めればよいかを算出します。
「まとめて詰める」は目標に届くまで最大4回くり返し、それでも入らなければ
「これ以上は縮まず、約◯ページまでになりました」と正直に伝えます。

### 7-6. 様式への差し込み（docxio.py）

前号の Word をそのまま様式として使い、**レイアウトには一切触れず、
文字と写真の中身だけを入れ替える**方式です。

様式を先頭から1回だけ走査して、文字の入る場所を「枠」として洗い出します。
テキストボックスは Word の互換用に同じ内容が2つ入っていることがあるため、
1つの枠として束ね、差し込み時は両方に書き込みます。

差し込み先の指定は2通り。

1. **枠番号** — 自動で採番された枠を画面で選ぶ
2. **差し込みマーカー** — 様式に `{{{{記事1_本文}}}}` と書いておく（**毎号使う様式にはこちらを推奨**）

書式は、その枠にもともとあった1つ目の文字の書式を引き継ぎます。

## 8. 安全性・プライバシー

| 項目 | 対策 |
|---|---|
| 外部送信 | **一切なし。** サーバは `127.0.0.1` のみで待ち受け |
| 外部からのアクセス | Host が localhost 以外なら 403 で拒否 |
| 画面の外部読み込み | 外部の CSS・フォント・画像を読み込まない |
| ファイルの取り出し | ダウンロードは出力フォルダの中だけに制限 |
| 原本 | 書き換えない。`manuscripts/` `photos/` にそのまま残る |
| 導入時の通信 | 追加部品は同梱。インターネット不要 |

ネットワークを切断した状態でも、すべての機能が動きます。

## 9. できないこと・注意点

| 項目 | 内容 |
|---|---|
| 要約の質 | 文を選んで残す方式。**文脈がつながらないことがある**ので必ず確認を |
| 校正の網羅性 | 辞書に無い誤字、文脈依存の誤りは検出できない。**人の校正の代わりにはならない** |
| PDF 原稿 | スキャンした画像だけの PDF は読めない（文字が入っていないため） |
| `.doc` の様式 | 差し込み方式で使うには `.docx` への変換が必要（原稿としてはそのまま読める） |
| 同時編集 | 1つの号を2人で同時に開くことはできない |
| ページ数 | 見積もりは目安。最終確認は Word で開いて行う |
| 同梱部品 | Windows 64ビット版 / Python 3.10〜3.14 向け。macOS・Linux は別途導入 |

## 10. 自治体に合わせて変えるところ

| 変えるもの | 場所 |
|---|---|
| 議員名・地名・課名 | 画面の「設定」、または `gikai/data/local_terms.json` |
| 表記ルール | `gikai/data/style_rules.json` |
| 難読語のルビ | `gikai/data/ruby.json` |
| 同音異義語 | `gikai/data/confusions.json` |
| 紙面の形（段数・文字の大きさ・余白） | 画面の「⑤ 紙面に組む」 |

表記ルールの書き方:

```json
{{ "find": "等", "to": "など", "severity": "warn",
  "note": "本誌は「等」を「など」に開く",
  "context_exclude": ["平等", "等級"] }}
```

- `severity` — `error`（要修正）/ `warn`（確認）/ `info`（参考）
- `context_exclude` — 前後にこの語があるときは指摘しない
- `to` に `／` を含めると、自動修正の対象から外れる（人が選ぶべき場合）

## 11. テスト

```
python tests/test_all.py
```

{f['tests']} 件。pytest が無くても直接実行できます。
不具合を直したときは**再発防止のテストを足してから**直しています。

主な検証:

- 表記ルール・誤字・固有名詞の検出（実物の第203号のデータで）
- Word 旧形式の読み取り（実物の18ページ文書で 14,000 字以上）
- 差し込みで段落書式が保たれること
- 写真が記事と同じページの枠に入ること
- 中身が変わっても紙面の決まりごとが変わらないこと
- 原稿が増えればページが増えること
- 起動用バッチの文字コード（CP932）と Python 判定

---

# 第2部　ソースコード

全 {f['files']} ファイル・約 {f['lines']:,} 行。
`python tools/make_docs.py` で実物から書き出しています。

"""


def code_part() -> str:
    parts: list[str] = ["## 目次\n"]
    for group, items in SECTIONS:
        parts.append(f"\n**{group}**\n")
        for name, desc in items:
            parts.append(f"- `{name}` — {desc}")
    parts.append("\n---\n")

    for group, items in SECTIONS:
        parts.append(f"\n## {group}\n")
        for name, desc in items:
            path = ROOT / name
            if not path.exists():
                continue
            text = read_text(path)
            lang = LANG.get(path.suffix, "text")
            lines = text.count("\n")
            parts.append(f"\n### `{name}`\n")
            parts.append(f"{desc}（{lines} 行）\n")
            parts.append(f"{FENCE}{lang}")
            parts.append(text.rstrip("\n"))
            parts.append(FENCE)
    return "\n".join(parts)


def main() -> None:
    facts = gather_facts()
    OUT.write_text(spec_part(facts) + code_part() + "\n", encoding="utf-8")
    size = OUT.stat().st_size
    print(f"作成しました: {OUT}")
    print(f"  {OUT.read_text(encoding='utf-8').count(chr(10)):,} 行 / {size:,} バイト")
    print(f"  収録: {facts['files']} ファイル / 約 {facts['lines']:,} 行のコード")


if __name__ == "__main__":
    main()
