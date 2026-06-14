# セキュリティ設定の進捗まとめ

最終更新: 2026-06-14

このリポジトリに対して行ったセキュリティ／運用設定の記録です。

## 1. 実施した設定

### `.claude/settings.json`（プロジェクト設定・git管理）

| 設定 | 内容 |
|---|---|
| `.env` 等の読み取り禁止（`permissions.deny`） | `.env` / `.env.*`、`secrets/`、`*.pem`・`*.key`、`id_rsa`、`.aws/`、`.ssh/` を Read 禁止 |
| セキュリティルール（`permissions.ask`） | `rm -rf`・`git push --force`・`curl`・`wget` は実行前に確認を求める |
| サンドボックス（`sandbox.enabled: true`） | bash を隔離実行。`filesystem.denyRead` で機密ファイルをコマンド経由でも遮断。`network` でローカルバインド禁止 |

### `CLAUDE.md`（プロジェクト方針・git管理）

- **確認・同意のルール**: 確認を求めるときは日本語で詳しく説明し、メリット・デメリットを併記する。
- **設定ファイルの編集ルール**: 既存の `CLAUDE.md` / `.claude/settings.json` は上書きせず追記・マージする（配列も既存要素を残す）。

## 2. git の状態

- すべての変更を `main` ブランチにマージ・push 済み。
- 作業ブランチ `claude/tender-euler-s5lac0`: ローカルは削除済み。リモート `origin/claude/tender-euler-s5lac0` は権限（HTTP 403）で削除できず残置（中身は `main` にマージ済みのため問題なし）。

## 3. 適用状況（検証結果）

### 現在のクラウドセッション（このデバイス）

| 設定 | 状態 | 根拠 |
|---|---|---|
| `.env` 読み取り禁止 | ✅ 有効 | 実際に `.env` を Read → ブロック確認 |
| セキュリティルール（ask） | ✅ 有効 | 同一 settings.json 由来 |
| CLAUDE.md の方針 | ✅ 有効 | 応答に反映 |
| `sandbox.enabled` | ⚠️ bwrap/socat 不在のため bwrap 層は未実働 | `which bwrap` 空、`Seccomp: 0` |
| 環境レベルの隔離 | ✅ 有効 | `IS_SANDBOX=yes`、`cloud_default` の使い捨て隔離コンテナで動作 |

### ローカルのターミナルで使う場合

- deny / ask / CLAUDE.md: プラットフォーム問わず有効。
- サンドボックス:
  - **macOS**: OS標準の Seatbelt で追加インストール不要・そのまま有効。
  - **Linux / WSL**: `bwrap`（bubblewrap）＋ `socat` を入れれば有効。無ければ警告して非サンドボックス実行。
    - Debian/Ubuntu: `sudo apt install bubblewrap socat`
    - Fedora/RHEL: `sudo dnf install bubblewrap socat`

## 4. 別デバイスでの適用手順

設定は「アカウント同期」ではなく「リポジトリ（git）に含まれるので pull すれば反映」される仕組み。

### 新規（初めて取り込む）

```bash
git clone https://github.com/akihitofujioka-bit/myproject.git
cd myproject
```

### 更新（既にある）

```bash
cd myproject
git checkout main
git pull origin main
```

### 仕上げ

- pull 後は **Claude Code を再起動**（または `/hooks` を一度開く）。起動中セッションには即時反映されない。
- `main` または `main` から派生したブランチで作業する。古いブランチは `git merge main` で取り込む。

## 5. 今後の検討事項（任意）

- `sandbox.failIfUnavailable: true` を付けると、サンドボックス非対応環境では Claude Code が起動時に停止（ハードゲート）。安全性は上がるが、bwrap の無い環境では起動不能になるため、複数デバイスの個人利用では非推奨。現状は付けていない。
- リモートの作業ブランチ `origin/claude/tender-euler-s5lac0` を消したい場合は GitHub の Web画面、または削除権限のある環境から `git push origin --delete claude/tender-euler-s5lac0`。
