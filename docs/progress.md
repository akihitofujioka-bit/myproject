# 進捗・再開ガイド（議会だより編集部）

> このファイルは「ここまでの経緯」と「次に何をするか」を1枚にまとめたもの。
> 作業を中断・再開するときは、まずこのファイルを読めば全体像がつかめる。
> 最終更新: 2026-06-30

---

## 1. これは何のプロジェクトか（一言で）

議員から提出された記事（**手書き原稿・Word・Excel**）を、アプリ内で同じ「記事データ」に
**正規化**し、決められたレイアウトに流し込んで**議会だより**を作り、**Word / PDF** で出力する
**Electron デスクトップアプリ**。

主な機能（計画）:
1. 提出記事の取り込み・正規化（ワンクッション）
2. 記事本文の編集（縦書き対応）
3. 写真・画像の簡単な編集（切り抜き・回転・明るさ）
4. 議員の掲載順の決定（ドラッグ＆ドロップ）
5. レイアウトテンプレートへの自動流し込み
6. Word / PDF 出力

---

## 2. 決まっていること（確定方針）

| # | 論点 | 決定 |
| --- | --- | --- |
| 形態 | アプリの種類 | **Electron デスクトップアプリ**（Win/Mac、オフライン・ローカル完結） |
| 出力 | 出力形式 | **PDF=完成版** / **Word=出力後に微修正できる近似編集版**（R-1） |
| R-2 | 縦書き | **縦書き必須**（PoCで .docx/プレビュー/PDF とも成立を確認） |
| R-3 | 提出様式 | **統一は強制しない**。手書き・Word混在を前提に**アプリ内で正規化**。推奨様式は任意配布（§15） |
| R-3b | 手書き | **スキャン画像を見ながら手入力で書き起こし**（自動OCR/クラウド送信は使わない） |
| R-5 | 入力形式 | **幅広く対応**（.docx/.xlsx/.doc/PDF/テキスト/手書きスキャン） |
| R-6 | 配布 | **手動配布**（インストーラを各PCへ） |
| R-4 | 既存号提供 | ⏳ **後日、参考として提供予定**（到着後に標準テンプレートを具体化） |

> 設計の核: **「データ（中身）」と「レイアウト（見た目）」を分離**し、
> 取り込みは**正規化ワークベンチ**でどんな形式も同じ記事データに整える。

---

## 3. 今どこまで進んだか

| フェーズ | 状態 | 成果物 |
| --- | --- | --- |
| 設計・仕様書 | ✅ v0.5 | `docs/design-spec.md` |
| **P0 PoC（要素検証）** | ✅ 完了 | `poc/` 一式、`docs/poc-p0-results.md` |
| **P1 基盤** | ✅ 完了 | `src/`（main/preload/renderer/shared）、`test/` |
| P2 取り込み・正規化 | ⬜ 未着手（次はここ推奨） | — |
| P3 議員・掲載順 | ⬜ | — |
| P4 記事編集 | ⬜ | — |
| P5 画像編集 | ⬜ | — |
| P6 レイアウト | ⬜ | — |
| P7 出力（PDF/Word） | ⬜ | — |
| P8 仕上げ（自動保存/複製/インストーラ） | ⬜ | — |

### P0 で検証済み（実コードで成立を確認）

- 縦書き .docx 出力 … `docx` ライブラリ、`page.textDirection = tbRl`（`poc/src/01-vertical-docx.mjs`）
- 縦書きプレビュー＋PDF … `writing-mode: vertical-rl` を Chromium で描画→PDF（=Electronと同じ描画）
- Word 取り込み … `mammoth` ＋スタイルマッピングでタイトル/氏名/本文を判別
- 正規化ワークベンチの操作感 … 左:スキャン / 右:書き起こしフォーム

### P1 で実装済み

- Electron + React + TS + Vite + electron-builder のアプリ骨格
- 共通データモデル（`src/shared/types.ts`、仕様書 §6）
- プロジェクトの新規/保存/読込（フォルダ形式 `project.json` + `assets/`）
- ホーム画面（号の基本情報編集・状態表示）
- 検証: 型チェック○ / ビルド○ / 単体テスト 7件○

---

## 4. リポジトリ構成（現在）

```
myproject/
├─ README.md
├─ package.json / electron.vite.config.ts / tsconfig*.json / electron-builder.yml
├─ src/
│   ├─ main/         Electron メイン（index.ts / projectStore.ts / ipc/project.ts）
│   ├─ preload/      contextBridge（index.ts）
│   ├─ renderer/     React UI（App.tsx / pages/HomePage.tsx / styles.css ほか）
│   └─ shared/       types.ts / project.ts / ipc.ts（main・renderer共通）
├─ test/             project.test.ts（中核ロジックの単体テスト）
├─ poc/              P0 の検証コード（本体とは独立）
└─ docs/
    ├─ design-spec.md      設計・仕様書（最新 v0.5）
    ├─ poc-p0-results.md   P0 結果レポート
    ├─ dev-setup.md        実行・ビルド手順
    ├─ progress.md         ← このファイル
    └─ poc-assets/         スクリーンショット
```

開発ブランチ: `claude/council-newsletter-layout-1shkqc`（push 済み、PR 未作成）

---

## 5. 動かし方（おさらい）

```bash
npm install          # 初回はネット接続必要（Electronバイナリ取得）
npm run dev          # 開発起動
npm run build        # ビルド
npm run typecheck    # 型チェック
npm run test:core    # 中核ロジックのテスト
```

> 制限ネットワークで依存だけ入れる場合: `ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm install`（起動は不可）。
> PoC の再現は `cd poc && npm install && npm run poc:all`。

---

## 6. 次にやること（P2: 取り込み・正規化ワークベンチ）

**目的**: どの形式の提出物も「記事データ（タイトル/本文/写真/キャプション）」に整えて一覧に並べる。

着手の取っ掛かり:

1. **取り込み IPC を追加** — `src/main/ipc/import.ts`（新規）。
   - Word: `mammoth`（PoC `poc/src/02-import-word.mjs` のスタイルマッピングを移植）。
   - Excel: `SheetJS`。
   - 画像/PDF(スキャン): ファイルを `assets/` へコピーし `ImageAsset` 化。
   - preload `window.api` に `import` 系を追加（`src/shared/ipc.ts` の契約を拡張）。
2. **正規化ワークベンチ画面** — `src/renderer/pages/ImportWorkbench.tsx`（新規）。
   - 左: スキャン画像プレビュー、右: 記事フォーム（PoC `poc/src/03-workbench.html` の構成を React 化）。
   - Word/Excel は自動抽出結果を初期値として流し込み、手書きは空フォーム＋スキャン参照。
   - 文字数カウント（`countArticleChars` を使用）。
3. **記事をプロジェクトに追加** — `Article` を `project.articles` に push し保存。

実装の足場（すでにある）:
- 記事の型: `Article`（`src/shared/types.ts`）。`source` に取り込み元種別、`sourceScanImageId` に手書き参照。
- 文字数: `countArticleChars()`（`src/shared/project.ts`）。
- 追加に必要なライブラリ: `mammoth`, `xlsx`（本体 `package.json` へ追加。PoC では検証済み）。

完了条件: **提出物（Word/手書きスキャン）を取り込み、正規化して記事一覧に並び、保存→再オープンで残る。**

---

## 7. 未決・要確認（実装の合間に詰める）

- **日本語フォントの同梱方針**（縦書きメトリクス／ライセンス）。実機の標準フォント or 同梱。
- **Word 出力の複数段組・写真位置**の再現度（P0は単段で確認。P7で詰める）。
- **R-4 既存号**の提供待ち → 受領後に標準テンプレート（§15・レイアウト枠）を具体化。
- PR をどの単位で作るか（フェーズごと／まとめて）。現状 PR 未作成。

---

## 8. 関連ドキュメントへのリンク

- 設計・仕様書: [design-spec.md](design-spec.md)
- P0 PoC 結果: [poc-p0-results.md](poc-p0-results.md)
- 開発セットアップ: [dev-setup.md](dev-setup.md)
