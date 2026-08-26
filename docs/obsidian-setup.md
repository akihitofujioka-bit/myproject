# Obsidian Vault のセットアップ手順（Mac + iPhone / Obsidian Git 方式）

最終更新: 2026-08-26

このリポジトリを Obsidian の Vault として使い、GitHub 経由で Mac と iPhone を同期する構成の手順。

## 構成

```
        GitHub (akihitofujioka-bit/myproject)
          ↑ push / pull          ↑ push / pull
   Mac の Obsidian          iPhone の Obsidian
   （Obsidian Git）          （Obsidian Git）
          ↑
   Claude Code のクラウドセッションも同じリポジトリを読む
```

**Vault = リポジトリのルート**、**ノートの置き場 = `vault/`** とする。
iPhone 版の Obsidian Git はリポジトリを Vault のルートに clone する仕様のため、Mac 側もルートに揃えている
（Mac だけ `vault/` を Vault にすると `.obsidian` が二重にできて競合する）。

Vault をリポジトリに入れることで、**新しい Claude Code セッションでも過去の記録を読める**ようになる。

## 1. GitHub の Personal Access Token を作る

iPhone・Mac の Obsidian Git が GitHub に push するために必要。

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. 設定内容:
   - Token name: `obsidian-git`
   - Expiration: 90 日〜1年（**期限が切れたら再発行が必要**）
   - Repository access: **Only select repositories** → `myproject` を選ぶ
   - Repository permissions → **Contents: Read and write**（Metadata は自動で Read-only が付く）
3. 生成されたトークン（`github_pat_...`）を控える。**この画面を離れると二度と表示されない。**

> トークンはパスワードと同じ。ノートやリポジトリには絶対に書かないこと。

## 2. Mac 側のセットアップ

### 2-1. クローン

iCloud Drive の**外**に置くこと（`.git` が iCloud の同期で壊れる事故が知られているため）。

```bash
mkdir -p ~/dev && cd ~/dev
git clone https://github.com/akihitofujioka-bit/myproject.git
```

### 2-2. Vault として開く

1. Obsidian →「フォルダを Vault として開く」→ **`~/dev/myproject`**（リポジトリのルート）
2. 「信頼して制限モードを解除」を選ぶ

### 2-3. コアプラグイン

- 設定 → コアプラグイン → **テンプレート** をオン → フォルダを `vault/Templates` に
- 設定 → コアプラグイン → **デイリーノート** をオン → 新規ファイルの場所を `vault/Daily`、テンプレートを `vault/Templates/daily` に
- 設定 → ファイルとリンク → **除外するファイル** に `docs` を追加（検索候補からコード用のドキュメントを外す。任意）

### 2-4. Obsidian Git

1. 設定 → コミュニティプラグイン → 制限モードを解除 → 参照 → **「Git」（作者: Vinzent）** をインストールして有効化
2. 設定:
   - Vault backup interval: `10`（分）
   - Auto pull interval: `10`（分）
   - Commit message: `vault: {{date}}`

Mac は `git clone` 済みなので認証は macOS のキーチェーン任せでよい。push で認証を求められたら、パスワード欄に手順1のトークンを入れる。

## 3. iPhone 側のセットアップ

1. Obsidian を開く →「新しい Vault を作成」→ 名前は `myproject`、保存先は **「iPhone 内」**（iCloud は選ばない）
2. 設定 → コミュニティプラグイン → 制限モードを解除 → 参照 → **「Git」** をインストールして有効化
3. Git プラグインの設定 → 認証情報:
   - Username: GitHub のユーザー名（`akihitofujioka-bit`）
   - Password/Token: 手順1で作ったトークン
   - Author name / email も入れておく
4. コマンドパレット（画面下のツールバー、または右上のメニュー）→ **`Git: Clone an existing remote repo`**
   - URL: `https://github.com/akihitofujioka-bit/myproject.git`
   - 保存先を聞かれたら **Vault のルート** を選ぶ
5. clone が終わったら Obsidian を再起動する（ファイル一覧が反映されないことがあるため）

### iPhone での使い方

- 書いたあと、コマンドパレット → `Git: Commit-and-sync` で push
- 自動同期を使う場合は Mac と同じく backup interval を設定する。ただし**モバイルはアプリを開いている間しか動かない**ので、書き終わったら手動で1回同期するのが確実

## 4. 運用ルール

- 何かアプリ／プロジェクトを作ったら `vault/00-Index.md` の表に1行足す
- セッションの終わりに Claude Code で `/log` を実行すると、作業記録が `vault/Logs/` に残り索引も更新される
- **Mac と iPhone の両方で編集する前に、必ず先に pull する**（`Git: Pull`）。同じファイルを両方で編集するとコンフリクトになる

## 5. 注意点

- **iCloud の中で `git init` しない** — `.git` が部分同期されリポジトリが破損する事例がある
- **画像を貼りすぎない** — リポジトリが肥大化し、iPhone の同期が目に見えて重くなる
- **秘密情報をノートに書かない** — GitHub にそのまま入る。API キー・パスワード・トークンは書かないこと
- **トークンの期限切れ** — 突然 push が失敗したらまずこれを疑う。GitHub で再発行してプラグイン設定を更新する

## 6. うまくいかないとき

| 症状 | 対処 |
|---|---|
| iPhone で clone が途中で止まる | Vault のサイズが大きいのが原因。画像を減らす。それでも駄目なら iCloud ミラー方式（Vault を iCloud に置き、Mac でリポジトリへ同期）に切り替える |
| push が 403 で失敗する | トークンの権限（Contents: Read and write）と有効期限を確認 |
| コンフリクトが出た | Mac 側で解決するのが楽。iPhone では該当ファイルの内容を控えてから `Git: Discard` して pull し直す |
