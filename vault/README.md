# Vault（Obsidian 保管庫）

このフォルダは **Obsidian の Vault（保管庫）** です。実体はただの Markdown フォルダなので、Obsidian・Git・Claude Code のどれからでも読み書きできます。プロジェクト管理（プロジェクト／タスク／議事録・デイリー）を Markdown で一元管理します。

## 使い方

### Obsidian で開く

1. Obsidian を起動 → 「別の保管庫を開く」→「フォルダを保管庫として開く」
2. このリポジトリ内の `vault/` フォルダを選択

`.obsidian/` にコア設定（テンプレート挿入先・デイリーノート先）を同梱してあるので、開いた時点でテンプレートとデイリーノートがそのまま使えます。

### 同期のしくみ（A案：リポジトリ内 Vault）

- この Vault は Git がそのままバージョン管理・同期・復元を担います。
- 別端末で使うときは `git pull`、書いたら `git add`／`commit`／`push`。
- クラウド同期サービス（iCloud/Drive/Obsidian Sync）は使わず、**Git を唯一の同期経路**にすると履歴が二重化せず安全です。

## フォルダ構成

```
vault/
├── README.md          … このファイル
├── projects/          … プロジェクトごとのノート（frontmatter で status/tags 管理）
├── tasks/             … タスク（チェックボックス）
├── daily/             … デイリーノート・議事録
├── templates/         … 各種テンプレート
└── .obsidian/         … Obsidian のコア設定（共有対象）
```

## frontmatter（メタデータ）の指針

各ノート先頭の YAML frontmatter で状態を管理します。Obsidian の検索・Dataview 系プラグインや Claude からの絞り込みに使えます。

```yaml
---
title: 例
type: project        # project / task / daily
status: active       # active / paused / done / archived
tags: [example]
created: 2026-07-10
updated: 2026-07-10
---
```

## Claude Code から扱うときのメモ

- ノートは `vault/` 配下の `.md`。Claude は直接読み書きできます。
- 破壊的な変更（ノート削除・大量置換）は、プロジェクト方針どおり日本語でメリット・デメリットを添えて確認してから実行します。
