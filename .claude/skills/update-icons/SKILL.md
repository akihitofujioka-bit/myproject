---
name: update-icons
description: 壱師アプリ（日常アプリ）のホーム画面アイコンを差し替える。Web 用（apps/icon-*.png とサブアプリ）と iOS 用（AppIcon.appiconset の 15 サイズ）を作り直す。ユーザーが「アイコンを変えて」「アイコンを更新」と言ったときに使う。
---

# アイコン更新

Web 用の `icon-180/192/512.png`（`apps/` と各サブアプリ `fridge/`・`docs-tracker/`・`stock/`・`kakeibo/`・`cards/`）と、
iOS 用 `mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/`（`AppIcon-<サイズ>.png` 15 個と `Contents.json`）を更新する。
どこまで変えるか（ホーム画面だけか、サブアプリもか）は、先にユーザーへ確かめる。

### アイコン画像を更新するコマンド（Claude Cloud Session）

**ホーム画面アイコンを更新:**

```bash
# 1. 新しい画像ファイルをコピー（例：/path/to/new-icon.webp）
cp /path/to/new-icon.webp /home/user/myproject/apps/icon-512.png

# 2. 正方形にリサイズして各サイズを生成
cd /home/user/myproject/apps
convert icon-512.png -trim +repage -resize 512x512! -background none icon-512.png
convert icon-512.png -resize 180x180 icon-180.png
convert icon-512.png -resize 192x192 icon-192.png

# 3. iOS ホーム画面アイコンセットも更新
cd /home/user/myproject/mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset
SOURCE="/home/user/myproject/apps/icon-512.png"
convert "$SOURCE" -resize 20x20 AppIcon-20x20@1x.png
convert "$SOURCE" -resize 40x40 AppIcon-20x20@2x.png
convert "$SOURCE" -resize 60x60 AppIcon-20x20@3x.png
convert "$SOURCE" -resize 29x29 AppIcon-29x29@1x.png
convert "$SOURCE" -resize 58x58 AppIcon-29x29@2x.png
convert "$SOURCE" -resize 87x87 AppIcon-29x29@3x.png
convert "$SOURCE" -resize 40x40 AppIcon-40x40@1x.png
convert "$SOURCE" -resize 80x80 AppIcon-40x40@2x.png
convert "$SOURCE" -resize 120x120 AppIcon-40x40@3x.png
convert "$SOURCE" -resize 120x120 AppIcon-60x60@2x.png
convert "$SOURCE" -resize 180x180 AppIcon-60x60@3x.png
convert "$SOURCE" -resize 76x76 AppIcon-76x76@1x.png
convert "$SOURCE" -resize 152x152 AppIcon-76x76@2x.png
convert "$SOURCE" -resize 167x167 AppIcon-83.5x83.5@2x.png
convert "$SOURCE" -resize 1024x1024 AppIcon-1024x1024@1x.png
```

**サブアプリ（例：冷蔵庫）アイコンを更新:**

```bash
# 1. 新しい画像をコピー
cp /path/to/new-icon.webp /home/user/myproject/apps/fridge/icon-512.png

# 2. 各サイズを生成
cd /home/user/myproject/apps/fridge
convert icon-512.png -trim +repage -resize 512x512! -background none icon-512.png
convert icon-512.png -resize 180x180 icon-180.png
convert icon-512.png -resize 192x192 icon-192.png
```

**コミット・push（クラウド環境）:**

```bash
cd /home/user/myproject
git add apps/ mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/
git commit -m "アイコンを更新：[変更内容を説明]"
git push origin <作業ブランチ>   # main へは gh pr create → gh pr merge --merge で入れる（CLAUDE.md の「取り込み（PR）」）
```

### ビルド・デプロイ（Mac のターミナル）

```bash
cd /Users/ichishi/myproject
git pull

cd mobile
rm -rf .build
npm run iphone
```

### トラブルシューティング

**アイコンが反映されない:**
- キャッシュをクリア: `rm -rf .build ~/Library/Developer/Xcode/DerivedData/*`
- iPhone のアプリを削除してから再インストール
- Safari キャッシュをクリア（Web版の場合）

**ビルドエラー「AppIcon did not have any applicable content」:**
- iOS アイコンセットに 15 個のサイズがすべて揃っているか確認
- Contents.json が正しい形式か確認（JSON フォーマッタで検証）
- `git checkout` で古い状態に戻して再度生成
