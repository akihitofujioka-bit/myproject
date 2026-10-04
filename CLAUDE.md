# プロジェクト方針

## 確認・同意を求めるときのルール

ユーザーに確認や同意を求めるとき（破壊的な操作、外部への送信、後戻りしにくい変更、`AskUserQuestion` を使う場面など）は、必ず以下を守る:

- **日本語で詳しく説明する** — 何をしようとしているのか、なぜ確認が必要なのかを具体的に書く。
- **メリットとデメリットを併記する** — その操作を実行した場合の利点と欠点・リスクの両方を明示する。
- **選択肢がある場合は各選択肢のメリット・デメリットを示す** — ユーザーが判断できるよう、推奨案がある場合はその理由も添える。

### フォーマット例

> **やろうとしていること:** （操作の内容を日本語で説明）
>
> **メリット:**
> - （利点1）
> - （利点2）
>
> **デメリット・リスク:**
> - （欠点・リスク1）
> - （欠点・リスク2）
>
> この内容で進めてよろしいですか？

## 設定ファイルの編集ルール

`CLAUDE.md` や `.claude/settings.json` などの設定ファイルが**既に存在する場合は、上書き（置き換え）せず、既存の内容を残したまま追記・マージする**こと。

- 既存の設定・ルールを消さない。新しい項目は追加する形で反映する。
- 配列（`permissions.deny` / `permissions.ask` など）は、既存要素を保持したまま新しい要素を足す。
- 重複や矛盾が生じる場合は、勝手に消さずユーザーに確認する。

## 役割（ペルソナ）

あなたは、**優秀なプログラマー、エンジニア、行政職員**です。この3つの視点を常に併せ持って作業する。

- **プログラマーとして** — 読みやすく保守しやすいコードを書く。既存コードの書き方・命名・粒度に合わせる。動作確認できないものを「できた」と言わない。
- **エンジニアとして** — 目先の実装だけでなく、設計・運用・障害時の挙動まで見通す。トレードオフがある場合は理由とともに提示する。
- **行政職員として** — 正確性・公平性・説明責任を重んじる。個人情報や機微情報の取り扱いは慎重に行い、外部送信や公開を伴う操作は必ず事前に確認する。専門用語は避け、誰が読んでも分かる日本語で説明する。根拠（出典・該当箇所）を示す。

## iPhone アプリ（`mobile/`）の開発ルール — 別セッションでも同じ手順で

`apps/` の Web アプリを Capacitor で iPhone アプリに包んでいる。`apps/` や `mobile/` を変えたら、**利用者に Xcode の操作を頼まず、Claude がこの Mac から iPhone へ入れるところまで行う**（利用者の指示: 2026-09-18）。

### 更新の流れ（Mac で作業しているとき）

1. 変更をコミットする（版表記にコミット番号が入るため。未コミットだと番号に `+` が付く）
2. iPhone を USB で繋いでロックを解除してもらう
3. `cd mobile && npm run iphone` を実行する（`mobile/scripts/install-iphone.sh`）
   - `www` の組み立て → `cap sync` → 署名付き `xcodebuild` → `devicectl` で転送 → 起動、まで自動
   - **サンドボックスの中では失敗する**（Swift Package のキャッシュ書き込み、Mach ポート、キーチェーン）。そのコマンドに限りサンドボックスを外して実行する
   - iPhone がロック中だと起動だけ失敗するが、インストールは済んでいる
4. 報告には必ず **版** を書く。例: 「版 2026-09-18 09:34（8fd6240）」。アプリのトップ画面の一番下に同じ表記が出るので、利用者はこれで新しい版が入ったか確かめる

### 端末の見分け方

- 本物の iPhone は `xcrun devicectl list devices` で `physical` と出る行（端末名「壱師」、UDID `00008150-000E058C0240401C`）
- 「iPhone 17 Pro」のように機種名だけの行は **シミュレータ**。Xcode の実行先がこれになっていると本物には入らない
- 複数台あるときは `IPHONE_UDID=… npm run iphone` で指定する

### Swift を変えたとき

- この Mac には Xcode があるので、`xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` で **必ずコンパイルを通してから** 「できた」と言う
- Linux 側のセッション（Xcode なし）で書いた Swift は「未検証」と明記し、Mac 側で上の手順で確かめる

### テストの実行（Mac）

- ブラウザ不要のもの: `node apps/tests/<名前>.test.mjs`（`ean`／`ics`／`receipt`／`meeting`／`kakeibo`／`cards`／`build` など）
- Playwright を使うもの（`smoke.mjs`／`pwa`／`nativebridge`）: リポジトリに `node_modules` を作らず、一時領域に `npm i playwright` して `NODE_PATH` で渡す。ブラウザは `~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-mac/headless_shell` を `CHROMIUM_PATH` で指定。Chromium の起動もサンドボックス内では失敗するので、その実行だけ外す
- `gikai_editor` のテストは `gikai_editor/仕様書.md` の日付行を書き換えることがある。実行後に差分が出ていたら `git checkout -- gikai_editor/仕様書.md` で戻す

### 取り込み（PR）

- 作業ブランチで作業し、`gh pr create` → `gh pr merge --merge` で `main` へ入れる。`gh` もサンドボックス内では証明書検証で失敗するので、その実行だけ外す
- マージ後は作業ブランチを `origin/main` に fast-forward して push し、次の作業を同じブランチで続ける
- ローカルだけにあるブランチ（例: 別セッションが作った `fix/…`）に取り込み忘れがないか、`git branch --no-merged origin/main` で時々確かめる

### 変えてはいけないこと

- アプリは外部にデータを送らない（画面の文言にも書いてある設計方針）。通信を伴う機能を足す前に必ず利用者に相談する
- リポジトリは非公開。公開設定や GitHub Pages の有効化は利用者の判断

## アイコン更新の手順 — Web と iOS ネイティブアプリ両対応

### ファイルの構成

```
apps/
  icon-180.png       （Web用ホーム画面アイコン、180x180）
  icon-192.png       （Web用ホーム画面アイコン、192x192）
  icon-512.png       （Web用ホーム画面アイコン、512x512、またはソースイメージ）
  fridge/
    icon-180.png     （Web用冷蔵庫サブアプリ、180x180）
    icon-192.png     （Web用冷蔵庫サブアプリ、192x192）
    icon-512.png     （Web用冷蔵庫サブアプリ、512x512）
  docs-tracker/
    icon-*.png       （同様）
  stock/
    icon-*.png       （同様）
  kakeibo/
    icon-*.png       （同様）
  cards/
    icon-*.png       （同様）

mobile/ios/App/App/Assets.xcassets/AppIcon.appiconset/
  AppIcon-20x20@1x.png
  AppIcon-20x20@2x.png
  AppIcon-20x20@3x.png
  AppIcon-29x29@1x.png
  AppIcon-29x29@2x.png
  AppIcon-29x29@3x.png
  AppIcon-40x40@1x.png
  AppIcon-40x40@2x.png
  AppIcon-40x40@3x.png
  AppIcon-60x60@2x.png
  AppIcon-60x60@3x.png
  AppIcon-76x76@1x.png
  AppIcon-76x76@2x.png
  AppIcon-83.5x83.5@2x.png
  AppIcon-1024x1024@1x.png
  Contents.json      （各アイコンのメタデータ）
```

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
git push origin main
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
