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
| 設計・仕様書 | ✅ v0.9 | `docs/design-spec.md` |
| **P0 PoC（要素検証）** | ✅ 完了 | `poc/` 一式、`docs/poc-p0-results.md` |
| **P1 基盤** | ✅ 完了 | `src/`（main/preload/renderer/shared）、`test/` |
| **P2 取り込み・正規化** | ✅ 完了 | `src/main/importers/`、`src/renderer/pages/ImportWorkbench.tsx` |
| **P3 議員・掲載順** | ✅ 完了 | `src/main/importers/roster.ts`、`src/renderer/pages/MembersPage.tsx` |
| **P4 記事編集** | ✅ 完了 | `src/shared/richtext.ts`、`src/renderer/components/RichEditor.tsx`、`pages/ArticleEditPage.tsx` |
| **P5 画像編集** | ✅ 完了 | `src/shared/imageedit.ts`、`src/renderer/components/ImageEditor.tsx`、`pages/ImagesPage.tsx` |
| P6 レイアウト | ⬜ 次はここ | — |
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

### P2 で実装済み

- 取り込み: Word(`mammoth`) / Excel(`xlsx`) / テキスト / 手書きスキャン(画像・PDF)。
  `src/main/importers/`（word/excel/text/normalize）、`src/main/assetStore.ts`、`src/main/ipc/import.ts`。
- 正規化ワークベンチ画面 `src/renderer/pages/ImportWorkbench.tsx`（記事一覧＋正規化フォーム＋スキャン参照）。
- どの形式も同じ `Article` に整えて `project.articles` に追加。手書きはスキャンを `assets/` に複製し `ImageAsset` 化。
- 検証: 型チェック○ / ビルド○ / 単体テスト **19件**○（取り込み→正規化→保存→再オープンの実I/O込み実証）。
- 実装メモ: `xlsx` は Vite(ESM)と tsx(CJS)で export 形が異なる二形態のため、
  `import * as` して `default ?? namespace` で両対応させた（`src/main/importers/excel.ts`）。

### P3 で実装済み

- 議員名簿(Excel)取り込み `src/main/importers/roster.ts`（「氏名」列でヘッダ検出→列位置特定→議員行を正規化）。
  実提供の日高村議会 名簿=10名を正しく抽出（議席/氏名/党派/期別/役職。複数役職は／区切り）。
- 議員管理画面 `src/renderer/pages/MembersPage.tsx`（名簿取込・編集・追加・削除、掲載順プリセット＋▲▼手動並べ替え）。
- `CouncilMember` に `term`(期別)・`role`(役職名) を追加。`sortMembersByPreset`（seat/faction/kana/manual）を実装。
- ワークベンチの議員ドロップダウンが名簿を参照 → 記事に議員を割り当て可能。
- 個人情報（住所/電話/生年月日）は既定で取り込まない。ふりがなは名簿に無いのでアプリで手入力。
- 検証: 型チェック○ / ビルド○ / 単体テスト **26件**○。
- 注意: 実名簿は個人情報を含むためリポジトリにコミットしない（テストは擬似データ）。

### P4 で実装済み

- 本文リッチエディタ `src/renderer/components/RichEditor.tsx`（contentEditable + execCommand。
  対象が Electron の Chromium 単一環境なので安定）。太字/見出し(h3)/本文(p)/箇条書き/**ルビ**。
- 記事編集画面 `src/renderer/pages/ArticleEditPage.tsx`（記事一覧＋タイトル/小見出し/本文編集、
  文字数と **枠の上限(charLimit)** による**あふれ警告**）。App に「記事編集」タブ追加。
- **データモデル移行**: `Article.body: string[]` → `bodyHtml: string`（最小HTML: p/h3/ul>li/strong/ruby）。
  `charLimit: number|null` を追加。本文HTMLの純粋ヘルパー `src/shared/richtext.ts`
  （`paragraphsToHtml`/`htmlToPlainText`/`countCharsFromHtml`。ルビの読みは文字数に数えない）。
- 取り込み(ArticleDraft)は段落配列のまま。`articleFromDraft` で HTML 化。
- 検証: 型チェック○ / ビルド○ / 単体テスト **31件**○。

### P5 で実装済み

- 画像 非破壊編集: 切り抜き（正規化矩形をドラッグ指定）・90°回転・左右/上下反転・明るさ/コントラスト/彩度。
  調整値は `ImageAsset.edits` に保存し、元画像は保持。仕上がりプレビュー・解像度警告・キャプション。
- CSS変換の純粋ヘルパー `src/shared/imageedit.ts`（`cssFilterFor`/`cssTransformFor`/`clampCrop`/
  `cropBackgroundStyle`/`effectiveLongEdge`/`isLowResolution`）。切り抜きは background-image で再現（回転/フィルタと合成）。
- `src/renderer/components/ImageEditor.tsx`、`pages/ImagesPage.tsx`（記事→写真→編集）。App に「画像編集」タブ。
- 写真取り込み IPC `import:image`（`window.api.import.addImage`。assets へ複製）。
- 検証: 型チェック○ / ビルド○ / 単体テスト **36件**○。
- メモ: `url()` の data URL は括弧混入に備え `url("...")` と引用（SVGサンプルで発覚。実写真=base64は無問題）。

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

## 6. 次にやること（P6: レイアウト）

**目的**: テンプレートの枠に記事・写真を流し込み、縦書き紙面をプレビューする（F-LAY-1〜7）。

着手の取っ掛かり:

1. **テンプレート/枠の定義** — `Template.frames[]`（既に型あり: 位置・サイズ・用途）を編集/選択。
   紙面サイズ・段組・余白・フォント・縦書き（`writingMode`）はテンプレートで持つ。
2. **枠への割り当て** — `Layout.pages[].frameAssignments[]` に記事/画像を割り当て。あふれ（オーバーフロー）警告。
3. **プレビュー** — PoC の縦書きHTML/CSS（`writing-mode: vertical-rl`、`poc/src/03-vertical-preview.html`）を
   React 化。記事本文は `bodyHtml`、写真は `ImageAsset.edits` を適用（`cssFilterFor`/`cssTransformFor`/`cropBackgroundStyle`）。
4. 掲載順（`CouncilMember.order`）を反映して記事を並べる。

実装の足場（すでにある）:
- `Template` / `FrameDef` / `Layout` / `LayoutPage` / `FrameAssignment`（`src/shared/types.ts`）。既定テンプレは縦書き・A4・3段。
- 縦書き描画の知見: PoC（`poc/`）。画像適用ヘルパー: `src/shared/imageedit.ts`。
- R-4（既存号）が届けば標準テンプレの枠を具体化できる（未着なら汎用テンプレで進める）。

完了条件: **1ページを自動レイアウトし、縦書きプレビューで確認。あふれ警告が出る。保存→再オープンで残る。**

> P5（画像編集）は完了済み。実装は `src/shared/imageedit.ts`・`src/renderer/components/ImageEditor.tsx`・`pages/ImagesPage.tsx`。
> 判断ポイント: 画像編集の適用は「表示時に edits を適用」で統一（切り抜きは background-image、色/回転は filter/transform）。出力(P7)でも同方式で焼き込む。

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
