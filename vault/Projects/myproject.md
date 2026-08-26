---
type: project
status: 進行中
repo: akihitofujioka-bit/myproject
started: 2026-06-14
tags: [setup, obsidian, claude-code]
---

# myproject

## これは何
Claude Code のプロジェクト設定（セキュリティ・作業方針）と、Obsidian Vault を置いているリポジトリ。
作ったアプリの索引もここで管理する。

## 現在の状態
- Claude Code のセキュリティ設定済み（`.claude/settings.json`）
- 作業方針を `CLAUDE.md` に記載済み
- Obsidian Vault を `vault/` に設置（Mac + iPhone から利用）

## 場所
- リポジトリ: https://github.com/akihitofujioka-bit/myproject
- Vault: リポジトリのルートを Obsidian で開く（ノートは `vault/` 配下）

## やること
- [ ] GitHub の Fine-grained トークンを作る（Contents: Read and write）
- [ ] Mac でリポジトリを clone し、ルートを Obsidian の Vault として開く
- [ ] Mac に Obsidian Git を入れて自動同期を設定する
- [ ] iPhone に Obsidian Git を入れて clone する

## 決めたこと・ハマったこと
- **同期方式は Obsidian Git に一本化**（2026-08-26 決定）。iCloud ミラー方式は実体が2つになるため不採用。iPhone の clone が重くて破綻したときの退避先としてのみ残す。
- **Obsidian で開くのはリポジトリのルート、ノートは `vault/` 配下** — iPhone の Obsidian Git はリポジトリを Vault のルートに clone する仕様なので、Mac だけ `vault/` を Vault にすると `.obsidian` が二重にできて競合する。
- **iCloud の中で `git init` はしない** — `.git` の部分同期でリポジトリが壊れる事故が知られているため。
- `vault/.obsidian/workspace.json` は端末ごとに変わるので `.gitignore` 済み。コミットすると Mac と iPhone で毎回競合する。

## 関連
- [[00-Index]]
- 設定の経緯: `docs/security-setup.md`
- 同期の手順: `docs/obsidian-setup.md`
