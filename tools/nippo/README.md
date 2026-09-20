# 日報ツール（tools/nippo）

フォルダに **手書きメモの写真・テキスト・Word・Excel・写真・音声** を入れておき、ボタンひとつで
**日報 → 週報 → 月報** の下書き（Markdown）を作る Python ツール。

- OCR（手書き・写真・PDF）は macOS 標準の Vision、音声の文字起こしはローカルの Whisper を使う。
  **すべてこの Mac の中で処理し、外部には何も送らない**（個人情報を含むメモでも安心して使える設計）
- 要約は LLM を使わず、語句の一致で「会議・打ち合わせ／その他の業務／明日の予定／課題・相談事項」に振り分ける。
  文章の言い換えはしないので、**出力は下書き**として手で整えて使う
- 書式は `/report` スキルの日報（`reports/daily/`）に合わせてある。出力先は別（既定 `~/日報/`）なので混ざらない

## 使い方

1. `tools/nippo/日報ツール.command` をダブルクリック（またはターミナルで `python3 tools/nippo/nippo.py`）
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
| Word 旧形式ほか | .doc .rtf .odt | macOS 標準の `textutil` |
| Excel | .xlsx .xlsm | openpyxl（全シート。1 行目は見出し扱い） |
| Excel 旧形式 | .xls | 未対応（.xlsx で保存し直す） |
| 画像・手書き | .jpg .png .heic .tif など | Vision で OCR（日本語・英語）。確度が低いと注意書きが付く |
| PDF | .pdf | 文字層があればそれを使い、なければページごとに OCR |
| 音声・動画 | .m4a .mp3 .wav .aiff .mov .mp4 など | Whisper（既定 `medium`）。**音声の長さと同程度の時間がかかる** |

## 設定（config.json）

- `workspace` … 作業フォルダ（既定 `~/日報`）。環境変数 `NIPPO_WORKSPACE` があればそちらを優先
- `whisper.model` … `base`（速いが粗い）〜 `large-v3`（遅いが正確）。`whisper.initialPrompt` に固有名詞を並べると誤変換が減る
- `classify` … 節に振り分ける語句。職場の言い回しに合わせて足す
- `privacy.excludeTopics` … 含む行を転記しない話題（既定: 人事・評価・給与・報酬・契約条件）
- `overwrite` … `ask`（確認）／`replace`／`skip`
- `openWith` … 生成した報告書を開くアプリ（既定 `TextEdit`）。`Obsidian` や `Visual Studio Code` に変えられる。空なら `.md` の既定アプリ

## 必要なもの

- macOS（Vision・textutil・sips を使う）、`/usr/bin/python3`
- `python-docx`・`openpyxl`・`openai-whisper`（入っていなければ `pip3 install python-docx openpyxl openai-whisper`）
- `ffmpeg`（音声用。`~/bin` か Homebrew）
- `swiftc`（Xcode か Command Line Tools）。OCR 補助プログラムを初回だけ自動で組み立て、`tools/nippo/.build/` に置く

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
