# 開発セットアップ / 実行手順

議会だより作成支援（Electron デスクトップアプリ）の開発・実行手順。

## 前提

- Node.js 20 以上（推奨: 22）
- 初回はインターネット接続（Electron バイナリのダウンロードのため）

## セットアップ

```bash
npm install
```

> 注: 制限ネットワークで Electron バイナリの取得に失敗する場合、依存だけ入れるには
> `ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm install`（この場合アプリ起動はできない）。

## よく使うコマンド

| コマンド | 内容 |
| --- | --- |
| `npm run dev` | 開発起動（electron-vite。HMR 付き） |
| `npm run build` | main / preload / renderer をビルド（`out/`） |
| `npm run typecheck` | 型チェック（main 側 / renderer 側の両方） |
| `npm run test:core` | プロジェクト保存/読込など中核ロジックの単体テスト |
| `npm run dist` | ビルド＋インストーラ作成（`release/`。電子配布用） |

## ディレクトリ構成（P1 時点）

```
src/
├─ main/                 Electron メイン（Node 側）
│   ├─ index.ts          ウィンドウ生成・app:// プロトコル・IPC登録
│   ├─ projectStore.ts   プロジェクトフォルダの読み書き（fs）
│   └─ ipc/project.ts    新規/開く/保存 の IPC ハンドラ
├─ preload/
│   └─ index.ts          contextBridge で window.api を限定公開
├─ renderer/             React UI
│   ├─ index.html / main.tsx / App.tsx / styles.css
│   └─ pages/HomePage.tsx
└─ shared/               main/renderer 共通
    ├─ types.ts          データモデル（設計仕様書 §6）
    ├─ project.ts        生成・直列化・検証（純粋関数。テスト対象）
    └─ ipc.ts            IPC 契約・window.api 型
test/
└─ project.test.ts       中核ロジックの単体テスト
```

## 設計メモ（P1 で決めた実装上のポイント）

- **セキュリティ**: `contextIsolation: true` / `nodeIntegration: false`。
  renderer は preload 経由の `window.api` だけを使い、fs などには直接触れない（仕様書 §8）。
- **renderer の配信は独自スキーム `app://`**: `file://` だと CSP `'self'` や
  Vite が付与する `crossorigin` と相性が悪くモジュールスクリプトが実行されないことがあるため、
  標準オリジンを持つ `app://` で配信する。CSP は本番のみメインプロセスのレスポンスヘッダで付与する
  （dev の HMR を壊さないため index.html にメタ CSP は置かない）。
- **プロジェクトはフォルダ形式**（仕様書 F-PRJ-2）:
  `<選んだフォルダ>/project.json` ＋ `assets/`（画像。後フェーズで使用）。
  形式は `schemaVersion` で管理し、非対応バージョンは読み込み時にエラーにする。

## 動作確認状況（P1）

- ✅ `npm run typecheck` 通過（main / renderer）
- ✅ `npm run build` 成功（main / preload / renderer の3バンドル生成）
- ✅ `npm run test:core` 7件パス（空プロジェクトの作成→保存(直列化)→再オープン(復元)の往復ほか）
- ⏳ GUI 起動（`npm run dev`）は Electron バイナリが必要。実機（Win/Mac）で確認する。
