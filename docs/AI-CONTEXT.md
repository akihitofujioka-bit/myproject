# 議会だより編集部 — AI 向け引き継ぎコンテキスト

> 目的: このファイル 1 つで、リポジトリを見なくても
> 「何を作っているか / どう決めたか / 今どこまで / 次に何をするか」を
> AI（別セッションの Claude 等）が正確に把握し、作業を再開できるようにする。
> 最終更新: 2026-06-30 / 対応リポジトリ状態: 設計 v0.7・P3 完了時点

---

## 0. TL;DR（30秒で把握）

- **作っているもの**: 「議会だより」（地方議会の広報紙）を作成する **Electron デスクトップアプリ**。名称 **議会だより編集部**。
- **中心的な課題**: 議員の提出物が **手書き原稿・Word・Excel でバラバラ**。統一できない。
- **解法の核**: 提出物を直接レイアウトせず、アプリ内の **「取り込み・正規化ワークベンチ」** で
  いったん同じ「記事データ」に整える（＝ワンクッション）。以後の工程は形式を意識しない。
- **出力**: **PDF＝完成版** / **Word＝出力後に微修正できる近似版**。
- **紙面**: **縦書き必須**。
- **進捗**: 設計 ✅ / P0 ✅ / P1 ✅ / P2 取り込み・正規化 ✅ / P3 議員・掲載順 ✅ / 次は **P4 記事編集**。
- **ブランチ**: `claude/council-newsletter-layout-1shkqc`（push 済み、PR 未作成）。

---

## 1. プロダクト概要

議員から提出された記事（Word・Excel・手書き原稿）を、決められたレイアウトに流し込んで
議会だよりを作る。担当は議会事務局の広報担当者（DTP不慣れ、Word/Excelは使える、1〜数名）。

### 求められた機能（ユーザーの原文要望より）
1. 提出記事（Word・Excel等）を決められたレイアウトに落とし込む
2. 提出記事の編集
3. 写真等画像の簡単な編集
4. 議員の記載順の決定

### 設計上の最優先方針
- 「DTPソフトを使えない人でも迷わず1冊作れる」こと。
- **データ（中身）とレイアウト（見た目）を分離**する。並べ替え・差し替えで紙面が崩れない。
- **オフライン・ローカル完結**（原稿・議員情報・写真を外部送信しない）。

---

## 2. 確定した意思決定（重要。これらは合意済み）

| ID | 論点 | 決定内容 | 補足 |
| --- | --- | --- | --- |
| 形態 | アプリ種別 | **Electron デスクトップアプリ**（Windows/Mac） | インストール型・オフライン |
| R-1 | 出力の再現度 | **PDF=完成版、Word=近似編集版** | Wordは完全一致を求めない |
| R-2 | 縦書き | **縦書き必須** | PoCで成立確認済み |
| R-3 | 提出様式 | **統一しない**。アプリ内で正規化して吸収 | 推奨様式(§15)は任意配布に格下げ |
| R-3b | 手書き原稿 | **スキャン画像を見ながら手入力で書き起こし** | 自動OCR/クラウド送信は使わない（オフライン原則） |
| R-5 | 入力形式 | **幅広く対応**：.docx / .xlsx / .doc / PDF / テキスト / 手書きスキャン | .docx/.xlsx が中心 |
| R-6 | 配布 | **手動配布**（インストーラを各PCへ） | 更新も手動 |
| R-4 | 既存号の提供 | ⏳ **後日、参考として提供予定** | 到着後に標準テンプレを具体化 |
| 名称 | プロダクト名 | **議会だより編集部** | npm slug と appId のみ英字（council-newsletter） |

---

## 3. 技術スタック

| 領域 | 採用 | 備考 |
| --- | --- | --- |
| アプリ基盤 | Electron | Win/Mac、ローカルファイル操作・配布に適す |
| UI | React + TypeScript | 画面が多く状態管理が要るため |
| ビルド | electron-vite（Vite）+ electron-builder | 開発HMR・インストーラ作成 |
| Word読込 | mammoth.js | .docx→HTML/テキスト。スタイル名で項目判別（PoC実証済み） |
| Excel読込 | SheetJS (xlsx) | 表データ（P2で導入予定） |
| 本文エディタ | Tiptap（予定・P4） | 見出し/太字/ルビ等 |
| 画像編集 | Cropper.js + Canvas（予定・P5） | 切り抜き/回転/明るさ |
| レイアウト描画 | HTML/CSS（`writing-mode: vertical-rl`）+ paged.js | 縦書き・段組・ページ送り |
| PDF出力 | Electron `webContents.printToPDF` | プレビューと一致（PoCではPlaywright/Chromiumで実証） |
| Word出力 | `docx`（npm） | 縦書き=セクションの `page.textDirection = tbRl`（PoC実証済み） |
| ローカル保存 | プロジェクトフォルダ（JSON+画像） | 中身が見え、受け渡し容易 |

---

## 4. アーキテクチャ

Electron 標準の 2 プロセス構成。

```
Renderer（React UI）  ── IPC ──▶  Main（Node.js）  ──▶  ローカルFS（プロジェクトフォルダ）
  画面・編集・プレビュー           ファイル読書き・変換・出力
```

セキュリティ（実装済み）:
- `contextIsolation: true` / `nodeIntegration: false`。
- renderer は **preload 経由の `window.api` だけ**を使い、fs 等に直接触れない。
- renderer 配信は **独自スキーム `app://`**（`file://` だと CSP `'self'` と Vite の `crossorigin` で
  モジュールスクリプトが実行されず真っ白になる問題を回避）。CSP は本番のみレスポンスヘッダで付与。

---

## 5. データモデル（実装済み。`src/shared/types.ts`）

プロジェクト＝1号分。JSONで永続化。要点のみ:

```
Project
├─ schemaVersion (=1)   ← 互換性チェック。非対応はロード時にエラー
├─ id, meta{ issueNumber, publishDate, municipality, pageSize }
├─ councilMembers[]  { id, name, nameKana, faction, seatNumber, term, role, portraitImageId, order }
├─ articles[]        { id, memberId, sectionId, title, subtitle, body[],
│                       images[], source, sourceFile, sourceScanImageId, charCount }
├─ images[]          { id, relativePath, edits{crop,rotate,flip,brightness,...},
│                       caption, dpiWarning }   ← 非破壊編集
├─ layout{ pages[] { frameAssignments[] } }
├─ templates[]       { id, name, pageSize, writingMode(vertical/horizontal),
│                       margins, columns, fonts, frames[] }
├─ activeTemplateId
└─ createdAt, updatedAt
```

- `Article.source` = `handwritten | word | excel | pdf | text | manual`（取り込み元＝来歴）。
- `Article.sourceScanImageId` = 手書き時の参照スキャン画像。
- 既定テンプレートは **縦書き・A4・3段**。

---

## 6. 現在の進捗（フェーズ）

| フェーズ | 状態 | 完了条件 / 実績 |
| --- | --- | --- |
| 設計・仕様書 | ✅ v0.5 | `docs/design-spec.md` |
| **P0 PoC** | ✅ | 縦書き.docx / 縦書きプレビュー+PDF / Word取込 / ワークベンチUI を実コードで検証 |
| **P1 基盤** | ✅ | アプリ骨格＋プロジェクト新規/保存/読込。型チェック○・ビルド○・単体テスト7件○ |
| **P2 取り込み・正規化** | ✅ | Word/Excel/テキスト/手書きスキャンを取り込み、同一Articleへ正規化。保存→再オープンで残る（テスト19件○） |
| **P3 議員・掲載順** | ✅ | 名簿(Excel)取込（実データ10名）・編集・並べ替え（議席/党派/五十音＋▲▼手動）。テスト26件○ |
| P4 記事編集 | ⬜ 次はここ | リッチ編集・文字数・ルビ |
| P4 記事編集 | ⬜ | リッチ編集・文字数・ルビ |
| P5 画像編集 | ⬜ | 切り抜き/回転/明るさ（非破壊） |
| P6 レイアウト | ⬜ | テンプレ流し込み・プレビュー・あふれ警告 |
| P7 出力 | ⬜ | PDF / Word 出力 |
| P8 仕上げ | ⬜ | 自動保存・複製・インストーラ |

### P0/P2 で技術的に実証済みの要点（重要な既知の解）
- 縦書き .docx: `docx` の `page.textDirection = PageTextDirectionType.TOP_TO_BOTTOM_RIGHT_TO_LEFT`（"tbRl"）。
  生成物の `word/document.xml` の `<w:sectPr>` に `<w:textDirection w:val="tbRl"/>` が入ることを確認。画像埋め込みも可。
- 縦書き表示: CSS `writing-mode: vertical-rl`。**`text-orientation` は既定の `mixed` が正解**
  （`upright` は字間が崩れて重なる、という失敗を経験済み）。縦書きメトリクスを持つ日本語フォント同梱が前提。
- Word取込: `mammoth.convertToHtml` の `styleMap` でスタイル名→項目（title/author/body）判別が成立。
- **xlsx の二形態ハザード**: Vite は ESM(`xlsx.mjs`, 名前空間に関数・default無し)、tsx/CJS は default に実体。
  → `import * as ns from 'xlsx'; const XLSX = ns.default ?? ns;` で両対応（`src/main/importers/excel.ts`）。
  同様の CJS ライブラリは名前付き import が壊れ得るので注意。

---

## 7. リポジトリ構成（P1 時点）

```
myproject/
├─ package.json / electron.vite.config.ts / tsconfig{,.node,.web}.json / electron-builder.yml
├─ src/
│   ├─ main/       index.ts(ウィンドウ/app:///IPC登録), projectStore.ts, assetStore.ts,
│   │              ipc/{project,import}.ts, importers/{word,excel,text,normalize,roster}.ts
│   ├─ preload/    index.ts（contextBridgeで window.api={project,import} 公開）
│   ├─ renderer/   index.html, main.tsx, App.tsx(タブ:ホーム/取り込み/議員), styles.css,
│   │              pages/{HomePage,ImportWorkbench,MembersPage}.tsx
│   └─ shared/     types.ts（モデル/ArticleDraft/MemberDraft）, project.ts（articleFromDraft/memberFromDraft/sortMembersByPreset等）, ipc.ts
├─ test/           project / normalize / import.e2e / roster .test.ts（計26件）
├─ poc/            P0検証コード（本体と独立。01=縦書きdocx, 02=Word取込, 03=HTML試作, 04=描画/PDF）
└─ docs/
    ├─ design-spec.md      設計・仕様書（最新 v0.5、変更履歴あり）
    ├─ poc-p0-results.md   P0結果レポート（スクショ・再現手順）
    ├─ dev-setup.md        実行・ビルド手順
    ├─ progress.md         進捗・再開ガイド（人間向け）
    ├─ AI-CONTEXT.md       ← このファイル（AI向け）
    └─ poc-assets/         スクリーンショット（縦書き紙面/ワークベンチ/P1ホーム）
```

主要コマンド:
```
npm install            # 初回はネット必要（Electronバイナリ）。制限環境は ELECTRON_SKIP_BINARY_DOWNLOAD=1
npm run dev            # 開発起動
npm run build          # main/preload/renderer ビルド
npm run typecheck      # 型チェック（node/web）
npm run test:core      # 中核ロジックのテスト
npm run dist           # インストーラ作成
```

---

## 8. 次にやること（P4: 記事編集）

目的: **記事本文をリッチに編集（見出し/太字/箇条書き/表/ルビ）し、文字数チェックを可能に**（F-EDIT-1〜6）。

手順（推奨）:
1. 本文エディタ導入: `Tiptap`(ProseMirror系)。まず見出し/段落/太字/箇条書き/表。
2. ルビ(ふりがな)対応（F-EDIT-2、議会だよりで需要大）。
3. 文字数・体裁チェック（`countArticleChars()` 活用、枠上限の超過/不足を警告）。

判断ポイント: `Article.body` は現状 `string[]`（段落配列）。リッチ化に合わせ
リッチテキスト構造(JSON)へ移行するか、段落配列を維持するか（**データ移行に注意**）。

完了条件: 本文を編集し保存→再オープンで残る。文字数超過が視覚的に分かる。

> P3（議員・掲載順）は完了。実装は `src/main/importers/roster.ts`（「氏名」列でヘッダ検出→列特定→正規化）、
> `src/renderer/pages/MembersPage.tsx`、並べ替えは `sortMembersByPreset()`（seat/faction/kana/manual）。
> 名簿の個人情報(住所/電話/生年月日)は既定で取り込まない。ふりがなはアプリで手入力。

---

## 9. 未決・要注意（実装の合間に詰める）

- **日本語フォント同梱方針**（縦書きメトリクス／ライセンス）。実機標準フォント or 同梱。
- **Word出力の複数段組・写真位置**の再現度（P0は単段で確認、P7で詰める）。
- **R-4 既存号**の提供待ち → 受領後に標準テンプレート（§15・レイアウト枠 `frames[]`）を具体化。
- **PR運用**: 現状PR未作成。フェーズ単位でまとめるか要相談。
- 制限ネットワークでは **Electronバイナリのダウンロードが失敗**しGUI起動不可（ロジック検証は可）。実機で起動確認する。

---

## 10. 会話の経緯（意思決定の流れ・要約）

1. ユーザー要望: 議員提出記事(Word/Excel等)をレイアウトに落とし込む／記事編集／画像簡易編集／議員掲載順決定。
2. 形態=Electron、出力=Word+PDF、まず設計仕様書から、を選択。→ 仕様書 v0.1 作成。
3. R-1 OK / R-2 縦書き必須 / R-3 「統一は困難、手書き・Word混在」 / R-5 対応したい / R-6 手動配布。
   → ユーザーが「テンプレに落とすワンクッションが必要か？」と提起。
4. 回答: **必須**。提出様式統一を諦め、アプリ内「正規化ワークベンチ」で吸収する設計へ転換（v0.3）。
   手書きは手入力書き起こし（OCR不使用）に決定。
5. P0(PoC)実施 → 縦書き.docx / 縦書きプレビュー+PDF / Word取込 / ワークベンチUI すべて成立（v0.4）。
6. P1(基盤)実装 → アプリ骨格＋保存読込、型チェック/ビルド/テスト通過（v0.5）。
   実装中に file:// の真っ白問題を発見し app:// 方式で解消。
7. 進捗を `docs/progress.md` に集約。
8. プロダクト名を **議会だより編集部** に変更。
9. AI向けコンテキスト（本ファイル）を作成し、Googleドライブにも保存。
10. **P2(取り込み・正規化)実装** → Word/Excel/テキスト/手書きスキャンの取り込みとワークベンチ、テスト19件通過（v0.6）。
    実装中に xlsx の二形態ハザードを踏み `default ?? namespace` で解消。
11. **P3(議員・掲載順)実装** → ユーザー提供の名簿Excel(日高村議会10名)を取り込む roster importer、議員管理画面、
    掲載順プリセット＋手動並べ替え。テスト26件通過（v0.7）。名簿の個人情報はコミットしない方針。

---

## 付記
- この文書と同内容の人間向け要約は `docs/progress.md`。詳細仕様は `docs/design-spec.md`。
- 再開時の合言葉: 「**P2 から続けて**」→ §8 の手順に沿って着手する。
