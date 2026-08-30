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
- `reports/daily/`・`reports/weekly/`・`reports/verbatim/` は業務情報を含むため git 管理対象外

## 逐語録（全文議事録）

議会の委員会など、要約では足りず全文が要る会議向け。2台のデバイスで録った同じ会議を
1本の逐語録にまとめる（片方が冒頭を録り逃していても、カバー範囲の広い方を主にして補完する）。

```
逐語録を作って   /   2026-08-27の常任委員会の全文を起こして
```

- 手順: `.claude/skills/report/references/verbatim.md`
- 整列・欠落検出・話者対応の候補出し: `.claude/skills/report/scripts/merge_transcripts.py`
- 出力: `reports/verbatim/YYYY-MM-DD-<会議名>.md`
- 音声認識の誤字は**直さず印を付ける**。巻末に要確認箇所と、録音間で食い違った語の一覧が付く
