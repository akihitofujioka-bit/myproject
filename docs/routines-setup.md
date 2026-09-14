# 日報・週報の自動生成をセットアップする

`/report` スキルを定期実行するための手順。**claude.ai の Routines 画面から設定する必要がある。**

## なぜ画面から作る必要があるのか

Claude Code のセッション内から Routine を作ることもできるが、その方法で作った Routine には
**コネクタ（PLAUD・Google カレンダー・Google Drive）が引き継がれない。**

2026-08-28 に実際に検証した結果：

- Routine 作成時に「this trigger stores no MCP connectors」という警告が出る
- `connectors` パラメータはこの組織では利用できない
- テスト実行したところ、「Drive にファイルを1つ作る」だけの指示でも何も作られなかった

コネクタが無いと PLAUD もカレンダーも読めず、空の日報しか出ない。
**claude.ai の Routines 画面で作れば、使用するコネクタを選択できる。**

## セットアップ手順

1. claude.ai を開き、Routines（定期実行）の画面へ行く
2. 新規 Routine を作成する
3. 下の3本をそれぞれ登録する。**各 Routine で PLAUD / Google カレンダー / Google Drive の3つを有効にすること**
4. 実行環境（environment）は、このリポジトリが入っているものを選ぶ

登録後、1本を手動実行して Google Drive の「日報・週報」フォルダにファイルができるか確認する。
できなければコネクタの選択漏れなので、Routine の設定を見直す。

---

## Routine 1: 日報ドラフト（18時・速報）

- **スケジュール**: 平日 18:00（JST）
- **通知**: ON
- **コネクタ**: PLAUD / Google カレンダー / Google Drive

```
本日（実行日・Asia/Tokyo基準）の日報ドラフトを作成してください。

手順はリポジトリ /home/user/myproject の `.claude/skills/report/SKILL.md` に書かれています。必ず最初にそれを読み、記載どおりに実行してください。設定は同リポジトリ直下の `report.config.json` です。参照資料は `.claude/skills/report/references/` にあります。

要点:
- まず `TZ=Asia/Tokyo date` で現在の日時を確認する。対象期間は本日（JST）
- PLAUD・Googleカレンダー・GitHub から収集する。MCPツール名はセッションごとに変わるので、ToolSearch でキーワード検索して探すこと
- PLAUD は録音日（start_at、UTC→JST変換）で判定し、前後1日を含めて広めに取得すること
- `reports/daily/YYYY-MM-DD.md` に保存する
- あわせて Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）に「日報 YYYY-MM-DD（曜）」というタイトルで保存する。contentMimeType は text/markdown

これは18時時点の速報版です。PLAUD への同期が済んでいない録音は拾えないことがあります。文字起こしが無い会議は「（文字起こし未実施）」と明記し、末尾の「確認してほしい点」でその旨を伝えてください。翌朝8時に確定版へ差し替える運用になっています。

本日が休日で活動が何もない場合は、ファイルを作らずに終了して構いません。コネクタに接続できない場合は、そのソースを飛ばして他のソースだけで作成し、末尾に取得できなかった旨を明記してください。

メール送信・チャット投稿・ドキュメント共有は一切しないでください。成果物はローカルのMarkdownとDriveのドキュメントのみです。
```

## Routine 2: 日報ドラフト（翌朝8時・確定）

- **スケジュール**: 平日翌朝 8:00（JST）※火〜土の朝
- **通知**: OFF（静かに差し替えるため）
- **コネクタ**: PLAUD / Google カレンダー / Google Drive

```
前日（実行日の前日・Asia/Tokyo基準）の日報ドラフトを作り直してください。前夜18時に作った速報版を、その後アップロード・文字起こしされた録音を含めて確定版に差し替えるのが目的です。

手順はリポジトリ /home/user/myproject の `.claude/skills/report/SKILL.md` に書かれています。必ず最初にそれを読み、記載どおりに実行してください。設定は同リポジトリ直下の `report.config.json` です。

要点:
- まず `TZ=Asia/Tokyo date` で現在の日時を確認する。対象期間は前日（JST）
- MCPツール名はセッションごとに変わるので、ToolSearch でキーワード検索して探すこと
- PLAUD は録音日（start_at、UTC→JST変換）で判定し、前後1日を含めて広めに取得する。前日の会議が当日アップロードされているケースを必ず拾うこと
- `reports/daily/YYYY-MM-DD.md` を前日分の内容で更新する
- Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）を search_files で検索し、「日報 YYYY-MM-DD（曜）」が既にあれば、内容に変化があるときだけ古いファイルを trash して新しい内容で作り直す。変化がなければ何もしない
- Drive にまだ無ければ新規作成する

前日が休日で活動が何もない場合、また速報版から内容が一切変わらない場合は、何も変更せずに終了して構いません。

メール送信・チャット投稿・ドキュメント共有は一切しないでください。
```

## Routine 3: 週報ドラフト（月曜8時・前週分）

- **スケジュール**: 毎週月曜 8:00（JST）
- **通知**: ON
- **コネクタ**: PLAUD / Google カレンダー / Google Drive

```
前週（月曜〜金曜、Asia/Tokyo基準）の週報ドラフトを作成してください。

手順はリポジトリ /home/user/myproject の `.claude/skills/report/SKILL.md` に書かれています。必ず最初にそれを読み、記載どおりに実行してください。設定は同リポジトリ直下の `report.config.json` です。

要点:
- まず `TZ=Asia/Tokyo date` で現在の日時を確認する。対象期間は直前の月曜〜金曜（JST）
- MCPツール名はセッションごとに変わるので、ToolSearch でキーワード検索して探すこと
- PLAUD は録音日（start_at、UTC→JST変換）で判定し、期間の前後1日を含めて広めに取得すること
- 週報は日報の連結ではない。テーマ単位でまとめ、「今週何が前に進んだか」「詰まっているものは何か」が読み取れる形にする
- `reports/weekly/YYYY-Www.md`（ISO週番号）に保存する
- あわせて Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）に「週報 YYYY-MM-DD 〜 YYYY-MM-DD」というタイトルで保存する。contentMimeType は text/markdown
- カレンダーに登録がなく録音だけ存在する会議もあるため、PLAUD 側を必ず突き合わせること

メール送信・チャット投稿・ドキュメント共有は一切しないでください。
```

---

## 作成ボタンが押せないとき

claude.ai の Routines 画面で作成ボタンが有効にならない場合、次の順に確認する。

1. **実行環境（リポジトリ）が未選択** — 最も多い原因。`myproject` が入っている環境を選ぶ
2. **スケジュールが未確定** — 頻度だけでなく時刻まで指定する
3. **Routine の名前が空**
4. **プロンプトが長すぎる** — 下の短縮版を使う

### 短縮版プロンプト

指示の中身は `SKILL.md` 側にあるため、プロンプトは短くても動く。

**日報（18時・速報）**

```
本日（Asia/Tokyo基準）の日報ドラフトを作成してください。

/home/user/myproject の .claude/skills/report/SKILL.md を読み、その手順どおりに実行してください。設定は report.config.json です。

対象は本日。reports/daily/ に保存し、あわせて Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）に「日報 YYYY-MM-DD（曜）」で保存してください。

送信・投稿は一切しないでください。
```

**日報（翌朝8時・確定）**

```
前日（Asia/Tokyo基準）の日報ドラフトを作り直してください。前夜18時の速報版を、その後届いた録音を含めて差し替えるのが目的です。

/home/user/myproject の .claude/skills/report/SKILL.md を読み、その手順どおりに実行してください。設定は report.config.json です。

対象は前日。reports/daily/ を更新し、Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）に同名のファイルがあれば、内容が変わったときだけ差し替えてください。

送信・投稿は一切しないでください。
```

**週報（月曜8時・前週分）**

```
前週（月曜〜金曜、Asia/Tokyo基準）の週報ドラフトを作成してください。

/home/user/myproject の .claude/skills/report/SKILL.md を読み、その手順どおりに実行してください。設定は report.config.json です。

reports/weekly/ に保存し、あわせて Google Drive のフォルダ（folderId: 1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV）に「週報 YYYY-MM-DD 〜 YYYY-MM-DD」で保存してください。日報の連結ではなくテーマ単位でまとめること。

送信・投稿は一切しないでください。
```

上記をすべて確認しても押せない場合、組織の設定で Routine の作成自体が制限されている可能性がある。その場合は手動運用（セッションで「日報作って」と依頼する）に切り替える。

---

## 停止済みの Routine について

セッション内から作成した同名の Routine 3本が、無効化された状態で残っている。

| 名前 | ID |
|---|---|
| 日報ドラフト（18時・速報） | `trig_01X6WXsC41xehEqZWUNAhMQY` |
| 日報ドラフト（翌朝8時・確定） | `trig_01Qy4WHsRM6K45QMggBYD2FT` |
| 週報ドラフト（月曜8時・前週分） | `trig_01Q3TEukfUh5wsqMUynXuM93` |

コネクタが無く動作しないため、画面から作り直したあとは削除してよい。

## 保存先

Google Drive のフォルダ「日報・週報」
folderId: `1hMd8_qucMKNL_RzNmuFjYVxgAoAhzYKV`
