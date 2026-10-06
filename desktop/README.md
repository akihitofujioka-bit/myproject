# 壱師アプリ再インストール ツール

macOS で iPhone / Apple Watch の壱師アプリを再インストールするための Electron アプリです。

## セットアップ

```bash
cd desktop
npm install
```

## 開発

```bash
npm run dev
```

## ビルド・パッケージ化

### ビルド手順

```bash
npm run build
```

このコマンドで macOS 用アプリがビルドされ、`dist/` ディレクトリに出力されます。

### Applications フォルダへの配置

ビルド完了後：

1. `dist/壱師アプリ再インストール.app` を Applications フォルダにドラッグ＆ドロップ
2. または `mv dist/壱師アプリ再インストール.app ~/Applications/`

## 使い方

1. アプリをダブルクリックで起動
2. 対象（iPhone / Apple Watch）と、USB または WiFi 接続を選択
3. 「再インストール開始」ボタンをクリック
4. インストール完了を待つ

### 接続方式

- **USB 接続**: iPhone と Apple Watch を USB で Mac に接続
- **WiFi 接続**: iPhone と Apple Watch が Mac と同じ WiFi に接続

## トラブルシューティング

### エラーが出た場合

1. Apple Watch が iPhone とペアリング済みか確認
2. Apple Watch がロック解除されているか確認
3. ターミナルで手動実行:
   ```bash
   cd /Users/[ユーザー名]/myproject/mobile
   npm run iphone        # iPhone
   npm run apple-watch   # Apple Watch
   # または WiFi 接続
   WIFI=1 npm run apple-watch
   ```

## 開発者向け

- `src/main.js` — Electron メインプロセス（npm コマンド実行）
- `renderer/` — UI（HTML/CSS/JS）
- `public/` — アプリアイコン（未実装）
