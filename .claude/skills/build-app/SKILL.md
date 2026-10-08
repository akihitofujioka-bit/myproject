---
name: build-app
description: 壱師アプリ（apps/ の Web アプリと mobile/ の iPhone・Apple Watch アプリ）や件など、アプリを作る・直す・機能を足すときの進め方。Claude と Codex の作業分担、ビルド、iPhone への転送、テスト、PR の取り込みまでの手順。ユーザーが「アプリに〜を追加して」「アプリを直して」「iPhone に入れて」「Watch に入れ直して」「アプリを統合して」と言ったときに使う。個人情報を含む作業は Codex に渡さない。外部へデータを送る機能は相談なしに足さない。
---

# アプリの作り方

壱師アプリは、`apps/` の Web アプリを `mobile/` の Capacitor（Web の画面を iPhone アプリにする仕組み）で包んでいる。
`apps/` や `mobile/` を変えたら、**利用者に Xcode の操作を頼まず、Claude がこの Mac から iPhone へ入れるところまで行う**（利用者の指示: 2026-09-18）。

## 大原則

1. **アプリは外部にデータを送らない**。通信を伴う機能を足す前に、必ず利用者に相談する（CLAUDE.md の「変えてはいけないこと」と同じ）
2. **作業は Claude と Codex で分担する**。Codex に向いた作業は Codex に任せ、Claude のトークンを節約する（利用者の指示: 2026-10-08）
3. **個人情報を含む作業は Codex に渡さない**。Codex は外部のサービスのため
4. **確かめていないものを「できた」と言わない**。Codex が書いたものも、Claude がテストとビルドで確かめてから報告する

## 作業分担（Claude と Codex）

| 担当 | 受け持つ作業 |
|---|---|
| **Claude** | 設計、利用者との相談、Codex への依頼文づくり、結果の確認、手直し、コミット・PR、iPhone への転送、報告 |
| **Codex** | 設計どおりにコードを書く作業、テストを書く作業、量の多い移植・書き換え、決まった形の繰り返し作業 |

- Claude がやったほうがよいもの: 1〜2 行の小さな修正、原因の分からない不具合の調査、設計の判断、サンドボックスの外で動かす操作（ビルド・転送・`gh`）
- 分担を始める前に、**担当の一覧表**（担当・対象ファイル・作業内容）を利用者に見せる
- 互いに関係しない作業は、Codex を複数同時に動かしてよい。完了・失敗はその都度報告する

### Codex への頼み方

1. 依頼文を `$TMPDIR` に書く。次の禁止事項を**必ず**入れる
   - 作業するフォルダの外（`~/Desktop`・`~/Documents`・`~/Obsidian` など、個人情報があり得る場所）を読まない
   - ネットに接続しない（`npm i`・`pip` などのインストールもしない）
   - `git commit`・`git push` をしない
   - テストや見本のデータには、架空の名前だけを使う
2. サンドボックスの外・バックグラウンドで実行する
   ```bash
   codex exec -s workspace-write -C <作業するフォルダ> -o /tmp/claude-501/codex-結果.md - < /tmp/claude-501/codex-依頼.md
   ```
   - 依頼文の場所は **フルパスで書く**。`$TMPDIR` はサンドボックスの中（`/tmp/claude-501`）と外（`/var/folders/…`）で指す場所が違う。サンドボックスの中で書いた依頼文を外から `$TMPDIR` で読もうとすると、見つからずにすぐ止まる（2026-10-08 に起きた）
   - 互いに別のファイルを変える作業なら、同時に動かしてよい。ただし `xcodebuild` は同時に動かすと壊れるので、Codex には実行させず Claude がまとめて行う
3. 結果を読み、`git diff` で変更を確かめる。テストとビルドを通してから、Claude がコミットする

## 更新の流れ（Mac で作業しているとき）

1. 作業ブランチで作業し、変更をコミットする（版表記にコミット番号が入るため。未コミットだと番号に `+` が付く）
2. **USB 接続の場合**: iPhone を USB で繋いでロックを解除してもらう
   **WiFi 接続の場合**: iPhone が Mac と同じ WiFi に接続していることを確認する
3. ビルド・インストール:
   ```bash
   cd mobile

   # USB 接続で実行
   npm run iphone

   # または WiFi 接続で実行（初回は USB 接続が必要な場合あり）
   WIFI=1 npm run iphone
   ```
   - `www` の組み立て → `cap sync` → 署名付き `xcodebuild` → `devicectl` で転送 → 起動、まで自動
   - **サンドボックスの中では失敗する**（Swift Package のキャッシュ書き込み、Mach ポート、キーチェーン）。そのコマンドに限りサンドボックスを外して実行する
   - iPhone がロック中だと起動だけ失敗するが、インストールは済んでいる
4. 報告には必ず **版** を書く。例: 「版 2026-09-18 09:34（8fd6240）」。アプリのトップ画面の一番下に同じ表記が出るので、利用者はこれで新しい版が入ったか確かめる

### 端末の見分け方

```bash
# 接続済みデバイスを一覧表示（Mac のターミナルで実行）
xcrun devicectl list devices
```

出力例:
```
00008150-000E058C0240401C  壱師                iPhone 15 Pro       physical
```

- 本物の iPhone は `physical` と出る行（端末名「壱師」、UDID `00008150-000E058C0240401C`）
  - USB 接続: `physical connected` と表示される
  - WiFi 接続: `physical network` と表示される
- 「iPhone 17 Pro」のように機種名だけの行は **シミュレータ**。Xcode の実行先がこれになっていると本物には入らない
- 複数台あるときは環境変数で指定する:
  ```bash
  IPHONE_UDID=00008150-000E058C0240401C npm run iphone
  IPHONE_UDID=00008150-000E058C0240401C WIFI=1 npm run iphone
  ```

### Apple Watch アプリ・再インストール用デスクトップアプリ

- Apple Watch へ入れ直すときは `cd mobile && npm run apple-watch`（WiFi は `WIFI=1`、複数台は `IPHONE_UDID=…`、Scheme 名が違うときは `WATCH_SCHEME=…`）
- ターミナルを使わない方法として、Electron 製のデスクトップアプリ `desktop/` がある（iPhone / Apple Watch / 両方 を選んで再インストール。ビルド・配置は `desktop/README.md`）
- Apple Watch が iPhone とペアリング済みで、ロック解除されていること
- `npm run apple-watch` の `IPHONE_UDID` には **Watch の番号**を入れる（名前に反して iPhone の番号ではない。iPhone の番号を渡すと「destination が見つからない」で止まる）。Watch の番号は `xcrun devicectl list devices` の Watch の行（例: `00008310-000B585E0E40E01E`）
- Watch は USB が無く、Mac とは必ず WiFi でつながる。Mac と端末が WiFi で互いに届かない環境では「Timed out while attempting to establish tunnel」で止まる（2026-10-09 に起きた）。そのときは、`npm run iphone`（USB）で iPhone に入れたあと、利用者に iPhone の「Watch」アプリ →「マイウォッチ」→ 日常アプリで入れてもらう（iPhone アプリの中に Watch アプリも入っている）
- Watch アプリのアイコンを変えても、上書きの更新では古いアイコンのまま出ることがある。Watch を再起動すると反映される

## Swift を変えたとき

- この Mac には Xcode があるので、`xcodebuild … -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` で **必ずコンパイルを通してから** 「できた」と言う
- Linux 側のセッション（Xcode なし）や Codex が書いた Swift は「未検証」と扱い、Mac 側で上の手順で確かめる

## テストの実行（Mac）

- ブラウザ不要のもの: `node apps/tests/<名前>.test.mjs`（`ean`／`ics`／`receipt`／`meeting`／`kakeibo`／`cards`／`build` など）
- Playwright を使うもの（`smoke.mjs`／`pwa`／`nativebridge`）: リポジトリに `node_modules` を作らず、一時領域に `npm i playwright` して `NODE_PATH` で渡す。ブラウザは `~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-mac/headless_shell` を `CHROMIUM_PATH` で指定する。Chromium の起動もサンドボックス内では失敗するので、その実行だけ外す
- `gikai_editor` のテストは `gikai_editor/仕様書.md` の日付行を書き換えることがある。実行後に差分が出ていたら `git checkout -- gikai_editor/仕様書.md` で戻す

## 取り込み（PR）

- 作業ブランチで作業し、`gh pr create` → `gh pr merge --merge` で `main` へ入れる。`gh` もサンドボックス内では証明書検証で失敗するので、その実行だけ外す
- マージ後は作業ブランチを `origin/main` に fast-forward して push し、次の作業を同じブランチで続ける
- ローカルだけにあるブランチ（例: 別セッションが作った `fix/…`）に取り込み忘れがないか、`git branch --no-merged origin/main` で時々確かめる

## やらないこと

- 通信を伴う機能を、利用者に相談せずに足さない
- 個人情報を含むファイル・作業を Codex に渡さない
- Codex に commit・push・ネット接続・作業フォルダの外の読み込みをさせない
- テストとビルドを通していないものを「できた」と報告しない
- リポジトリの公開設定や GitHub Pages の有効化は行わない（利用者の判断）
