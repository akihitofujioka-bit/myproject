# gikai_editor — 開発時の約束ごと

議会だより（自治体の議会広報紙）を作るためのオフライン専用ツール。
このファイルはコードをさわる人・AI 向け。使い方は `README.md`、
全体像と全ソースは `仕様書.md` にある。

> 上位の `../CLAUDE.md`（確認の取り方・設定ファイルの扱い）も併せて守ること。

---

## 1. 誰のための道具か

**高知県日高村議会事務局の職員**が、2か月に1回の発行作業で使う。
プログラミングの知識は前提にできない。ここから次が決まる。

- **画面・メッセージ・エラー文はすべて日本語。** 専門用語を避け、
  「何が起きたか」と「次に何をすればよいか」を書く
- **コメントと docstring も日本語。** 何をしているかより **なぜそうしたか** を書く
- 失敗しても行き止まりにしない。代わりの手段を必ず示す

## 2. 絶対に壊してはいけない前提

### 2-1. 完全オフライン

役場の端末は外部に接続できない。

- **ネットワークへ出るコードを足さない。** サーバは `127.0.0.1` のみで待ち受け、
  Host が localhost 以外なら 403 で拒否する（`server.py` の `_guard_origin`）
- 画面から外部の CSS・フォント・画像・CDN を読み込まない
- **`pip install` が要る依存を増やさない。** 追加部品は `wheels/` に同梱済みで、
  導入も `--no-index` 指定。新しい依存を足すなら wheel も同梱すること
- 標準ライブラリで済むものは標準ライブラリで書く（`docxio.py` `doc97.py`
  `compose.py` `server.py` はすべて標準ライブラリのみ）

### 2-2. 原稿を勝手に書き換えない

議員から預かった原稿を扱っている。

- 取り込んだ原本は `manuscripts/` `photos/` にそのまま残す。**上書きしない**
- 要約・一括修正は、**反映前に必ず比較画面を出す**。黙って本文を差し替えない
- `Article.raw` は取り込み直後の本文。「取り込んだ原稿に戻す」の戻り先なので消さない
- **文章を生成しない。** 要約は原稿にあった文を選んで残す抽出型
  （`summarize.py`）。言語モデルは使わない — オフライン要件と、
  事実が変わらないことの担保のため

### 2-3. 自動処理は必ず結果を見せる

写真の自動割り付け・区分の自動振り分け・ページ数調整・一括修正は、
**やったことを全件返して画面に出す**。判定できなかったものも隠さず出し、
手で直せるようにする（`sections.py` の `guess_section` は判定の理由も返す。
これは画面に出すためのもので、消さないこと）。

一括削除も同じ考え方で、**何が消えるのかを一覧で見せてから実行する**。
記事を消しても `manuscripts/` `photos/` の原本は消さない（2-2 のとおり）。

## 3. さわる前に知っておくこと（過去に踏んだ罠）

いずれも実際に不具合を出した箇所。テストで再発を防いでいるので、
テストが落ちたら「テストを直す」のではなく **原因を疑うこと**。

| 罠 | 内容 | 守っているテスト |
|---|---|---|
| **バッチの文字コード** | `.bat` は CP932 + CRLF で保存する。UTF-8 だと日本語版 Windows で文字化けする | `test_batch_files_are_cp932` |
| **ZIP のファイル名** | 日本語名を含む ZIP は Python の `zipfile` で作る。Info-ZIP の `zip` は UTF-8 フラグを立てず Windows で化ける | — |
| **CSS の `display`** | `hidden` 属性を使う要素に無条件の `display` を書かない。ブラウザ標準の `[hidden]{display:none}` は詳細度が最低で、`.steps{display:flex}` 程度の指定にも負ける。2回踏んだので `[hidden]{display:none !important}` を1つ置いてある。**これを消さない** | `test_modal_is_hidden_by_default` / `test_hidden_elements_are_really_hidden` |
| **Python の探し方** | `where` で「あるか」だけ見ない。**実際に走らせて確かめる**（`_find_python.bat` → `_pycheck.py`）。壊れた Python が PATH に残っている端末がある | `test_python_detection_is_verified_not_assumed` |
| **バッチの括弧** | `for` / `if` ブロック内で、括弧を含む文字列を変数展開しない。cmd がブロックを途中で閉じる。`call :label` 方式にする | 同上 |
| **sectPr の要素順** | OOXML はスキーマ順が決まっている。`w:cols` → `w:textDirection` → `w:docGrid` の順（逆にすると Word が読めない） | `test_compose_produces_vertical_five_columns` |
| **テキストボックスの二重化** | `.docx` のテキストボックスは `mc:Choice` と `mc:Fallback` に同じ内容が入る。**両方に書き込む**（片方だけだと Word と LibreOffice で表示が食い違う） | `test_docx_slot_detect_and_fill` |
| **区分の並び** | 構成の並びは「紙面の順」そのもの。③の一覧・自動組版の両方がこの順に従う。片方だけ並べ替えない | `test_outline_lists_sections_in_order_with_unassigned_last` / `test_compose_lays_out_sections_in_order` |
| **pypdf と日本語** | pypdf は日本語 PDF で文字化けする。PyMuPDF を優先し、pypdf を使ったときは画面に注意書きを出す | — |

## 4. どこを直せばよいか

| やりたいこと | さわる場所 |
|---|---|
| 校正ルールを足す・変える | `gikai/data/*.json`（**コードではなくデータ**。ここは自治体ごとの調整面なので、判定ロジックを増やす前にデータで済まないか考える） |
| 原稿の形式を増やす | `gikai/importers.py` の `read_any` |
| 紙面の見た目を変える | `gikai/compose.py`（自動組版）／ `gikai/docxio.py`（差し込み） |
| 画面を変える | `gikai/static/`（`index.html` / `style.css` / `app.js`） |
| 窓口（API）を足す | `gikai/server.py` の `handle_api`。**追加したら `tools/make_docs.py` の `API_DESC` にも説明を足す** |
| 保存する項目を足す | `gikai/project.py` の `Article` / `Photo` dataclass（既存プロジェクトを壊さないよう既定値を付ける） |
| 紙面の構成（台割）を変える | `gikai/sections.py` の `DEFAULT_SECTIONS`（**区分の並び＝紙面の並び＝③の編集順＝自動組版の順**。3か所が同じ順で動くので、ここだけ直せばよい） |
| 画面の中の「使い方」を直す | `gikai/help.py`（**文章はここ1か所だけ**。`app.js` は並べるだけなので、文言を直すならここ。画面のボタン名を変えたら `UI_LABELS` も直す） |
| かんたん作成の作りを変える | `gikai/easy.py`（**フォルダの中身がそのまま紙面**、という一点だけで動いている。ここに条件分岐を足す前に、その規則で説明できないか考える） |

### 画面は2つある。かんたん作成が既定

- **かんたん作成** — 最大ページ数を決める → 区分ごとのフォルダに原稿と写真を
  入れる → ボタン1つ → プレビュー → 書き出し。事務局の通常運用はこちら
- **くわしく編集** — いままでの①〜⑥。1本ずつ校正したいときだけ

**かんたん作成に設定項目を足さない。** 「いろいろ設定がありすぎる」という
声から生まれた画面なので、増やすなら「くわしく編集」側に置くこと。

届く写真はカメラの名前（`IMG_2451.jpg`）のままなので、名前だけでは
どの原稿のものか決められない。**そこは人にしか分からない**ので、
`photo_plan()` / `assign_photos()` で「写真を見て選ぶ」形にしてある。
このとき、**名前がすでに合っているものは初めから選んでおく**こと。
全部選ばせると手間が減らず、作った意味がなくなる
（`test_photo_plan_flags_only_the_ones_that_need_a_person`）。

名前を変えたら `easy._retag()` で `Article.origin` / `Photo.origin` も付け替える。
これを忘れると、次の作り直しで「消えた」「新しく入った」と見なされ、
**写真との結びつきが切れる**（`test_rename_keeps_the_photo_link`）。
番号の振り直しは、いったん仮の名前へ逃がしてから付け直すこと。
02→01 のように詰めると既存の 01 とぶつかる
（`test_renumber_does_not_collide_when_shifting`）。

`easy.build()` は毎回フォルダから組み直す（同じフォルダからは同じ紙面ができる）。
画面で直した本文は消えるので、`hand_edited` が立っている記事があるときだけ
確認を出す。この往復の作りを崩さないこと
（`test_easy_build_is_repeatable`）。

### 出力方式は2つある。どちらも壊さないこと

- **自動組版**（`compose.py`）— 1ページ5段・縦書きは固定、ページ数は分量しだい。既定
- **差し込み**（`docxio.py`）— 前号の様式の枠に文字と写真を入れ替える

写真は記事の本文の**中に**挟む（`_weave_photos`）。末尾にまとめると、
長い記事では写真が何段も離れ、次のページに出てしまう
（`test_easy_photos_are_placed_inside_their_article`）。

### 使い方は道具の中に置く

役場の端末で `README.md` を探して開く運用は現実的でない。
**画面を変えたら `gikai/help.py` も直すこと。**
説明だけ残って画面に無い、が起きないよう、使い方が名前を出しているボタンは
実在するかを見ている（`test_help_only_names_buttons_that_exist`）。
号を作る前でも読めるようにしておくこと — まさにその時に読みたいものなので、
`.card.ez.off` でまとめて止めない。

## 5. 開発の作法

```bash
python tests/test_all.py        # テスト（pytest が無くても動く）
python app.py --no-browser      # 起動
python tools/make_docs.py       # 仕様書.md を作り直す
python tools/make_icon.py       # アイコンを作り直す
```

- **pytest に依存しない。** `python tests/test_all.py` で直接動く形を保つ
  （役場の端末に pytest は入らない）
- **不具合を直すときは、先に再発防止のテストを書く。**
  そのテストが「修正前のコードで落ちる」ことを確かめてから直す
- コードを変えたら `python tools/make_docs.py` で仕様書も作り直す
  （数字は実物から数えているので、手で直さない）
- 既存プロジェクト（`project.json`）を読めなくする変更をしない

## 6. この環境で確認できること

Linux コンテナ上でも、次は実際に動かして確かめられる。**推測で済ませない。**

| 確かめたいこと | 方法 |
|---|---|
| 画面の動き | Playwright + Chromium（`/opt/pw-browsers/chromium-1194/chrome-linux/chrome`） |
| Word の組み上がり | `soffice --headless --convert-to pdf` → PyMuPDF でページ数・見た目を確認 |
| 日本語の表示 | `fonts-noto-cjk` 導入済み |

**確かめられないもの**（実機での確認を依頼すること）:

- `.bat` の実行（cmd.exe が無い）
- Word 本体での表示（LibreOffice とは差が出る）
- Windows の Word COM 変換、PowerShell でのショートカット作成

### ページ数の見積もりを変えるとき

`compose.py` の行数の数え方は、**LibreOffice で実際に組んだ結果と
突き合わせて補正してある**（記事1〜18本・写真0〜14枚の10通りで実測と一致）。
レイアウトに関わる変更をしたら、同じやり方で測り直すこと。
補正値（記事の切れ目 7 行、写真の段またぎ ½、見出しの段送り ½）を
根拠なく動かさない。

見出しには `keepNext` / `keepLines` を付けてある。行送りを本文の高さに
**固定**しているため、これを外すと大きい見出しが隣の行に重なって印刷される
（`test_compose_headings_are_not_split_across_columns`）。

## 7. 書き方の約束

- 変数名・関数名は英語、コメントと docstring は日本語
- 1行は 95 文字くらいまで
- 例外は握りつぶさない。利用者に見せるメッセージに変えて返す
- 画面のメッセージに「エラーが発生しました」だけを書かない。
  **何が起きて、どうすればよいか**を書く
- コミットメッセージは日本語。**何を直したかより、なぜそうしたか**を書く
