# 日報ツール（tools/nippo）

フォルダに **手書きメモの写真・テキスト・Word・Excel・写真・音声** を入れておき、ボタンひとつで
**日報 → 週報 → 月報** の下書き（Markdown）を作る Python ツール。

- **macOS と Windows 10/11 のどちらでも動く。** OCR はそれぞれの OS に最初から入っているものを使う
  （macOS は Vision、Windows は Windows.Media.Ocr）。音声の文字起こし（Whisper）は macOS のみ
- **すべてこのパソコンの中で処理し、外部には何も送らない**（個人情報を含むメモでも安心して使える設計）
- 要約は LLM を使わず、語句の一致で「会議・打ち合わせ／その他の業務／明日の予定／課題・相談事項」に振り分ける。
  文章の言い換えはしないので、**出力は下書き**として手で整えて使う
- 書式は `/report` スキルの日報（`reports/daily/`）に合わせてある。出力先は別（既定 `~/日報/`）なので混ざらない

## 使い方

1. 起動する
   - macOS … `日報ツール.command` をダブルクリック（または `python3 tools/nippo/nippo.py`）
   - Windows … `日報ツール.bat` をダブルクリック
2. 画面の「素材フォルダを開く」で `~/日報/素材/` を開き、ファイルを入れる
   - 日付は **ファイル名 → 親フォルダ名 → 写真の撮影日時・録音の作成日時 → ファイル作成日時** の順に判定
   - 例: `2026-09-21_打合せメモ.jpg`、`20260921_進捗.xlsx`、`素材/2026-09-21/録音.m4a`
   - 「この日の素材を確認」で、どのファイルが何日と判定されたか見られる
3. 日付を入れて **日報を作る**／**週報を作る**（その日を含む月〜日）／**月報を作る**（その日を含む月）
4. `~/日報/日報/2026-09-21.md` などが開くので、内容を直して使う
   - 週報・月報は各日の日報を束ねて作るので、**日報を手直ししてから作り直すと反映される**
   - 素材はあるのに日報がない日は、週報・月報を作るときに自動で日報も作る

### コマンドで使う

```
python3 tools/nippo/nippo.py daily 2026-09-21
python3 tools/nippo/nippo.py weekly 2026-09-21
python3 tools/nippo/nippo.py monthly 2026-09
python3 tools/nippo/nippo.py list 2026-09-21        # 素材の一覧と日付判定だけ
python3 tools/nippo/nippo.py extract <ファイル>      # 1 ファイルの文字取り出しを試す
python3 tools/nippo/test_reporter.py                # 組み立て部分の確認
```

既にある報告書は作り直さない。作り直すときは `--force`（画面では確認ダイアログが出る）。

## 対応する形式

| 種類 | 拡張子 | 読み方 |
|---|---|---|
| テキスト | .txt .md .csv .tsv .json .log | そのまま（文字コードは UTF-8 / Shift_JIS / EUC を自動判定） |
| Word | .docx | python-docx（段落と表） |
| Word 旧形式 | .doc | macOS: `textutil` ／ Windows: `doc97`（追加ソフト不要） |
| Word その他 | .rtf .odt | macOS のみ（Windows では .docx にして入れる） |
| Excel | .xlsx .xlsm | openpyxl（全シート。1 行目は見出し扱い） |
| Excel 旧形式 | .xls | 未対応（.xlsx で保存し直す） |
| 画像・手書き | .jpg .png .heic .tif など | macOS: Vision ／ Windows: 標準 OCR。確度が低いと注意書きが付く |
| PDF | .pdf | 文字層があればそれを使い、なければページごとに OCR |
| 音声・動画 | .m4a .mp3 .wav .aiff .mov .mp4 など | **macOS のみ** Whisper（既定 `medium`）。音声の長さと同程度の時間がかかる。Windows では文字起こし済みの .txt を入れる |

## 設定（config.json）

- `workspace` … 作業フォルダ（既定 `~/日報`）。環境変数 `NIPPO_WORKSPACE` があればそちらを優先
- `whisper.model` … `base`（速いが粗い）〜 `large-v3`（遅いが正確）。`whisper.initialPrompt` に固有名詞を並べると誤変換が減る
- `classify` … 節に振り分ける語句。職場の言い回しに合わせて足す
- `privacy.excludeTopics` … 含む行を転記しない話題（既定: 人事・評価・給与・報酬・契約条件）
- `overwrite` … `ask`（確認）／`replace`／`skip`
- `openWith` … 生成した報告書を開くアプリ（既定 `TextEdit`）。`Obsidian` や `Visual Studio Code` に変えられる。空なら `.md` の既定アプリ

## 必要なもの

### macOS

- `/usr/bin/python3`
- `python-docx`・`openpyxl`・`openai-whisper`（`pip3 install python-docx openpyxl openai-whisper`）
- `ffmpeg`（音声用。`~/bin` か Homebrew）
- `swiftc`（Xcode か Command Line Tools）。OCR 補助プログラムを初回だけ自動で組み立て、`tools/nippo/.build/` に置く

### Windows 10 / 11 — いちばん簡単な入れ方

**配布用の zip には、必要な部品（Python 3.11・64 ビット Windows 用）が `wheels` フォルダに入っています。**
インターネットにつながっていなくても入れられます。

1. Python 3.11 を入れる（インストール時に「Add Python to PATH」にチェック）
2. **`部品のインストール.bat` をダブルクリック**（`wheels` フォルダの中だけを見ます）
3. **`日報ツール.bat` をダブルクリック**

`wheels` フォルダがあるだけでは動きません。**2 を実行して、はじめて使えるようになります。**
うまくいくと最後に「終わりました」と出ます。

画像・PDF の文字読み取り（OCR）は Windows に最初から入っているものを使うので、追加は要りません。
Python が 3.11 以外のときは `wheels` の中身が合わないので、下の手順で作り直してください。

### Windows 10 / 11 — 中で何を使っているか

- **Python 3.9 以降**（python.org。インストール時に「Add Python to PATH」にチェック）
- `pip install python-docx openpyxl pillow pymupdf`
  - `pillow` … 写真の撮影日時を読む
  - `pymupdf` … PDF を読む（文字層が無ければページを画像にして OCR にかける）
- **OCR は追加インストール不要**（Windows に最初から入っているものを使う）
- `.doc` を読むために `tools/gikai_simple/doc97.py` を使う。
  nippo だけを配る場合は、`doc97.py` を `nippo` フォルダにコピーして一緒に渡す
- 音声の文字起こしは使えない。ほかの方法で文字起こしした `.txt` を素材フォルダに入れる

> ネットにつながらないパソコンへ入れるときは、つながるパソコンで
> `pip download -d wheels python-docx openpyxl pillow pymupdf` として作った `wheels` フォルダを
> USB で持ち込み、`pip install --no-index --find-links=wheels python-docx openpyxl pillow pymupdf` で入れる。

## 仕組み

```
素材/ ─ 走査 ─ 日付判定 ─ 文字取り出し（.cache に保存、同じファイルは二度処理しない）
                                 └ reporter.build_daily → 日報/YYYY-MM-DD.md
日報/ ─ parse_report ─ build_weekly  → 週報/YYYY-Www.md
日報/ ─ parse_report ─ build_monthly → 月報/YYYY-MM.md
```

- `nippo.py` … 画面・コマンド・フォルダ管理
- `extractors.py` … 形式ごとの文字取り出しとキャッシュ
- `reporter.py` … 行の整形・分類・Markdown の組み立て
- `ocr_helper.swift` … Vision で OCR する補助プログラム
