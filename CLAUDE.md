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
2. **USB 接続の場合**: iPhone を USB で繋いでロックを解除してもらう
   **WiFi 接続の場合**: iPhone が Mac と同じ WiFi に接続していることを確認
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

- 本物の iPhone は `physical` と出る行（端末名「壱師」、UDIP `00008150-000E058C0240401C`）
  - USB 接続: `physical connected` と表示される
  - WiFi 接続: `physical network` と表示される
- 「iPhone 17 Pro」のように機種名だけの行は **シミュレータ**。Xcode の実行先がこれになっていると本物には入らない
- 複数台あるときは環境変数で指定:
  ```bash
  IPHONE_UDID=00008150-000E058C0240401C npm run iphone
  IPHONE_UDID=00008150-000E058C0240401C WIFI=1 npm run iphone
  ```

### Apple Watch アプリ・再インストール用デスクトップアプリ

- Apple Watch へ入れ直すときは `cd mobile && npm run apple-watch`（WiFi は `WIFI=1`、複数台は `IPHONE_UDID=…`、Scheme 名が違うときは `WATCH_SCHEME=…`）
- ターミナルを使わない方法として、Electron 製のデスクトップアプリ `desktop/` がある（iPhone / Apple Watch / 両方 を選んで再インストール。ビルド・配置は `desktop/README.md`）
- Apple Watch が iPhone とペアリング済みで、ロック解除されていること

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

## 日常アプリの構成

冷蔵庫・書類トラッカー・備蓄・家計簿・ポイントカードの 5 アプリを `apps/` に置き、`mobile/` の Capacitor で iPhone アプリに包んでいる。
各アプリの役割・データの持ち方・ファイル構造は `apps/README.md` とコードを見る。守る点は次の 2 つ。

- データは端末内の IndexedDB だけ。外部サーバーへ送らない
- 書類トラッカーの QR は Deep Link（`myproject://docs?id=...`）で開く

## アイコン更新

Web 用（`apps/**/icon-*.png`）と iOS 用（`AppIcon.appiconset` の 15 サイズ）を作り直す手順は、スキル `update-icons` を使う。

## モデルと effort の選び方

仕事ごとのモデルと effort(頑張り度)は `モデルとeffortの使い分け.md` を見る。うまくいかない時は、先に effort を1段上げる。
