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
- Vault: `vault/`（Obsidian ではこのフォルダを開く）

## やること
- [ ] Mac で `vault/` を Obsidian の Vault として開く
- [ ] Obsidian Git プラグインを入れて自動同期を設定する
- [ ] iPhone 側の同期方法を決める（Obsidian Git / iCloud ミラー）

## 決めたこと・ハマったこと
- **Vault はリポジトリ直下ではなく `vault/` に置く** — `.obsidian/` や `.git` が混ざるのを避けるため。
- **iCloud の中で `git init` はしない** — `.git` の部分同期でリポジトリが壊れる事故が知られているため。
- `vault/.obsidian/workspace.json` は端末ごとに変わるので `.gitignore` 済み。コミットすると Mac と iPhone で毎回競合する。

## 関連
- [[00-Index]]
- 設定の経緯: `docs/security-setup.md`
- 同期の手順: `docs/obsidian-setup.md`
