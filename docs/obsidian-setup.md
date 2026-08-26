# Obsidian Vault のセットアップ手順（Mac + iPhone）

最終更新: 2026-08-26

このリポジトリの `vault/` を Obsidian の Vault として使い、GitHub 経由で同期する構成の手順。

## 構成

```
GitHub (akihitofujioka-bit/myproject)
   ↑ push / pull
Mac の作業フォルダ  ──→ Obsidian が vault/ を開く
   ↑
   └─ Claude Code のクラウドセッションも同じリポジトリを読む
```

Vault をリポジトリに入れることで、**新しい Claude Code セッションでも過去の記録を読める**ようになる。

## 1. Mac 側のセットアップ

### 1-1. リポジトリをクローンする

iCloud Drive の**外**に置くこと（`.git` が iCloud の同期で壊れる事故が知られているため）。

```bash
mkdir -p ~/dev && cd ~/dev
git clone https://github.com/akihitofujioka-bit/myproject.git
```

### 1-2. Obsidian で Vault を開く

1. Obsidian を起動 → 「フォルダを Vault として開く」
2. `~/dev/myproject/vault` を選択（**リポジトリのルートではなく `vault/`**）
3. 「信頼して制限モードを解除」を選ぶ（プラグインを使うため）

### 1-3. コアプラグインの設定

- 設定 → コアプラグイン → **テンプレート** をオン → 設定でフォルダを `Templates` に
- 設定 → コアプラグイン → **デイリーノート** をオン → 新規ファイルの場所を `Daily`、テンプレートを `Templates/daily` に

### 1-4. Obsidian Git（自動で push / pull）

1. 設定 → コミュニティプラグイン → 制限モードを解除 → 参照 → 「Obsidian Git」をインストールして有効化
2. 設定で以下を指定:
   - Vault backup interval: `10`（分。0 で自動バックアップ無効）
   - Auto pull interval: `10`
   - Commit message: `vault: {{date}}`
3. コマンドパレット（⌘P）から `Obsidian Git: Commit-and-sync` で手動同期もできる

> Obsidian Git は Vault フォルダの1つ上にある `.git` を自動で見つけるため、`vault/` を開いていてもリポジトリ全体を対象に動作する。

## 2. iPhone 側のセットアップ

方式は2つ。**A を先に試し、重い・失敗するようなら B に切り替える**のがおすすめ。

### A. Obsidian Git（モバイル版）を使う — 一元管理

1. iPhone の Obsidian で新規 Vault を作成（iCloud ではなく「iPhone 内」でよい）
2. コミュニティプラグイン → Obsidian Git をインストール
3. GitHub の Personal Access Token（`repo` 権限、Fine-grained なら当該リポジトリの Contents: Read and write）を作成し、プラグイン設定の認証情報に入力
4. リポジトリ URL を指定して clone

- **メリット**: Mac と完全に同じものを見る。履歴も1本。ミラー不要。
- **デメリット**: モバイル版の git は重く、Vault が大きくなると失敗しやすい。コンフリクトの解決が iPhone 上では苦しい。トークンを端末に保存する必要がある。

### B. iCloud ミラー — iPhone を楽にする

`vault/` を iCloud Drive にも置き、Mac 側でリポジトリへ同期する。

- **メリット**: iPhone は同期を意識しなくてよい（Obsidian の標準動作のまま）。
- **デメリット**: 実体が2つになり、Mac で同期操作を挟む手間が増える。両方を同時に編集すると競合する。

## 3. 運用ルール

- 何かアプリ／プロジェクトを作ったら `vault/00-Index.md` の表に1行足す
- セッションの終わりに Claude Code で `/log` を実行すると、作業記録が `vault/Logs/` に残り索引も更新される
- `vault/.obsidian/workspace.json` は端末ごとに変わるため `.gitignore` 済み（コミットすると毎回競合する）

## 4. 注意点

- **iCloud の中で `git init` しない** — `.git` が部分同期されリポジトリが破損する事例がある
- **画像を貼りすぎない** — リポジトリが肥大化し、モバイル同期が重くなる
- **秘密情報をノートに書かない** — GitHub にそのまま入る。API キーやパスワードは書かないこと
