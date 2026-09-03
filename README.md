# myproject

## 日報・週報ドラフト生成（`/report`）

GitHub（コミット・PR・Issue）、Google カレンダー、PLAUD の文字起こしから対象期間の活動を集め、
日報・週報のドラフトを `reports/` に生成する Claude Code スキル。

```
/report 日報
/report 週報
/report 日報 2026-08-25
```

- スキル定義: `.claude/skills/report/SKILL.md`
- 設定: `.claude/skills/report/config.example.json` を `report.config.json` にコピーして編集
- 生成物はドラフトのみ。メール送信・チャット投稿は行わない
- `reports/daily/`・`reports/weekly/` は業務情報を含むため git 管理対象外

## 朝のブリーフ（`/brief`）

Google カレンダーの予定、期限の近い書類、要対応のメール、前日の日報の持ち越しを集めて、
今日1日の段取りを1枚にまとめた**朝のブリーフ**を `reports/brief/` に生成する Claude Code スキル。

```
/brief
/brief 2026-09-04
```

- スキル定義: `.claude/skills/brief/SKILL.md`
- 設定: `.claude/skills/brief/config.example.json` を `brief.config.json` にコピーして編集
- 読み取り専用。メールの既読化・返信、予定の変更は行わない
- `reports/brief/` は業務情報を含むため git 管理対象外

## 日常アプリ（`apps/`）

ブラウザだけで動く単一HTMLのアプリ。サーバー不要で、ファイルを開けばそのまま使える。

| アプリ | 用途 | 開くファイル |
| --- | --- | --- |
| 冷蔵庫の在庫・賞味期限管理 | 食材の期限管理と食品ロスの記録 | `apps/fridge/index.html` |
| 書類・回覧の期限トラッカー | 提出期限のある書類・回覧・申請の管理 | `apps/docs-tracker/index.html` |

- データは開いたブラウザの中（localStorage）にのみ保存され、外部には送信しない
- 端末を移すときは「JSONで保存」→ 移行先で「JSONから読み込み」
- 書類トラッカーの書き出しを `data/deadlines.json` に置くと `/brief` が締切として拾う
- 詳しい注意事項は `apps/README.md` を参照
