# キャラクター写真の追加機能（アルバム連携・Watch の背景） 実装計画

> **進め方:** スキル `build-app` の分担に従う。Task 1・2 は互いに別のファイルなので Codex を同時に動かす。Task 3 は Task 1・2 の部品を使うので、その後に頼む。Task 4 は Claude。

**Goal:** 写真アプリのアルバムとつないだ枠が自動で写真を取り込み、トップの写真が Watch の壱師アプリの背景にも出る。

**Architecture:** Swift の部品 `PhotoAlbumPlugin`（アルバムの一覧・写真の番号・写真の取り出し）と、`WatchBridgePlugin.setBackground`（Watch へ写真を送る）を足す。JS 側は `character.js` に差分と同期、`character-settings.js` にアルバムの選択を足し、トップ画面が同期と Watch への送信を呼ぶ。

**Tech Stack:** Swift（Capacitor プラグイン、PhotoKit、WatchConnectivity、SwiftUI on watchOS）、素の JavaScript、Node のテスト

**Spec:** `docs/superpowers/specs/2026-10-08-character-album-watch-design.md`（前提: `2026-10-08-character-photo-design.md`）

## Global Constraints

- アプリから外部へデータを送らない。iCloud からの取り寄せ（`isNetworkAccessAllowed = true`）だけは利用者が許可済み
- JS の名前: プラグインは `PhotoAlbum`、`WatchBridge`。Watch の送信は `WatchSync.setBackground(blob | null)`
- `status` は `"ok"`・`"limited"`・`"denied"` の3つ
- 写真の大きさ: 取り込みは長い辺 1080、Watch へは長い辺 400。JPEG 品質 0.85
- Watch の膜は黒、不透明度 0.55
- 枠の記録に足す項目: `album: null | { id, title }`、`albumIds: []`、`manualPhotos: []`
- アルバムの増減では `startDate` を変えない。アルバムを選んだとき・やめたときは今日にする
- 既存の書き方に合わせる（JS は `"use strict"`・`var`・即時関数、Swift は既存プラグインの形。コメントは日本語）
- Codex には `build-app` スキルの禁止事項を伝える

## Review Focus

- **「選んだ写真だけ」の許可**（`limited`）→ 取り込み済みの写真を使い続け、登録欄に案内を出す。Task 3 のテストで `status` ごとの案内文を押さえる
- **アルバムが消された・名前が変わった** → `id` で探すので名前の変更は問題なし。消えたら「見つかりません」と出し、取り込み済みを使う。Task 1 で `assetIds` が `status: "ok", ids: []` ではなく reject を返すこと
- **iCloud から取り寄せられない写真** → その1枚だけ飛ばし、`albumIds` に入れない。Task 3 の同期のテストで押さえる
- **Watch が無い／Watch アプリ未導入** → 送らずに `ok: false`。画面は止めない。Task 2
- **トップを開くたびに Watch へ送り直す** → 印が同じなら送らない。Task 3 のテストで押さえる

---

### Task 1: アルバムの Swift の部品

**担当:** Codex

**Files:**
- Create: `mobile/ios/App/App/PhotoAlbumPlugin.swift`
- Modify: `mobile/ios/App/App/ViewController.swift`（`registerPluginInstance(PhotoAlbumPlugin())` を足す）
- Modify: `mobile/ios/App/App/Info.plist`（`NSPhotoLibraryUsageDescription`、文言は設計書のとおり）

**Interfaces:**
- Produces（JS から `Capacitor.Plugins.PhotoAlbum`）:
  - `isSupported() -> { supported: true }`
  - `listAlbums() -> { status, albums: [{ id: String, title: String, count: Int }] }`
  - `assetIds({ albumId }) -> { status, ids: [String] }`。アルバムが見つからなければ reject（メッセージ `"album-not-found"`）
  - `loadPhoto({ id, maxSide }) -> { data: String }`（base64 の JPEG）。取り出せなければ reject

- [ ] **Step 1:** `ReceiptScannerPlugin.swift` の形にならって書く。許可は `PHPhotoLibrary.requestAuthorization(for: .readWrite)`、`.limited` は `"limited"`、`.denied`/`.restricted` は `"denied"`。対象は `PHAssetCollectionType.album` の利用者のアルバムだけ、写真（`mediaType == .image`）だけを数える。`loadPhoto` は `PHImageManager.requestImage`（`isNetworkAccessAllowed = true`、`deliveryMode = .highQualityFormat`、`resizeMode = .exact`、縦横比を保って長い辺 `maxSide`）
- [ ] **Step 2: ビルドを通す**

Run: `cd mobile/ios/App && xcodebuild -project App.xcodeproj -scheme App -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build -quiet`
Expected: `BUILD SUCCEEDED`（Codex の環境で動かないときは Claude が行う）

- [ ] **Step 3:** Claude が確認・ビルドしてコミット（`feat: 写真アプリのアルバムを読む部品を追加`）

---

### Task 2: Watch の背景（Swift と watch.js）

**担当:** Codex

**Files:**
- Modify: `mobile/ios/App/App/WatchBridgePlugin.swift`（メソッド `setBackground`）
- Modify: `apps/shared/watch.js`（`WatchSync.setBackground`）
- Modify: `mobile/ios/App/WatchAppSources/WatchStore.swift`、`mobile/ios/App/WatchAppSources/ContentView.swift`

**Interfaces:**
- Produces:
  - `WatchBridge.setBackground({ data } | { clear: true }) -> { ok: Bool, reason: String }`（`reason` は既存の `send` と同じ値: `not-supported`・`not-activated`・`no-watch`・`app-not-installed`）
  - `WatchSync.setBackground(blob: Blob | null) -> Promise<{ ok, reason }>`。プラグインが無い（ブラウザ）ときは `{ ok: false, reason: "not-supported" }`
  - Watch 側: `WatchStore.background: UIImage?`

- [ ] **Step 1: iPhone 側。** `data` は一時フォルダの `watch-background.jpg` に書き、`outstandingFileTransfers` のうち `metadata["kind"] == "background"` のものを `cancel()` してから `transferFile(url, metadata: ["kind": "background"])`。`clear` は `transferUserInfo(["kind": "background-clear"])`
- [ ] **Step 2: watch.js。** 既存の `sync` の呼び方にならう。Blob は `FileReader` で base64（`data:` の前置きを除く）にして渡す
- [ ] **Step 3: Watch 側。** `session(_:didReceive file: WCSessionFile)` で `kind == "background"` を `Application Support/background.jpg` に置き換え保存して `background` に読み込む（メインスレッドで代入）。`session(_:didReceiveUserInfo:)` で `background-clear` ならファイルを消して `nil`。`init` で保存済みを読む。`ContentView` の `List` に `.scrollContentBackground(.hidden)` と `.background { 写真 scaledToFill + Color.black.opacity(0.55) }`、写真が無ければ今のまま
- [ ] **Step 4: ビルドを通す**

Run: `cd mobile/ios/App && xcodebuild -project App.xcodeproj -scheme App -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build -quiet`、Watch も `xcodebuild -list` で Scheme を確かめて同様に
Expected: 両方 `BUILD SUCCEEDED`

- [ ] **Step 5:** Claude が確認・ビルドしてコミット（`feat: Watch の壱師アプリの背景にトップの写真を出す`）

---

### Task 3: 差分・同期・登録欄・Watch への送信（JS）

**担当:** Codex（Task 1・2 のコミット後）

**Files:**
- Modify: `apps/shared/character.js`、`apps/shared/character-settings.js`、`apps/index.html`
- Test: `apps/tests/character.test.mjs`

**Interfaces:**
- Consumes: Task 1 の `PhotoAlbum.*`、Task 2 の `WatchSync.setBackground`
- Produces（`window.Character` に追加）:
  - `albumDiff(oldIds: string[], newIds: string[]) -> { keep: string[], add: string[], order: string[] }`
  - `syncAlbum(slot: string, plugin) -> Promise<{ status: "ok"|"limited"|"denied"|"not-found", added: number, failed: number }>`
  - `albumNotice(status: string, title: string) -> string`（`ok` なら `""`）
  - `watchMark(record, today: Date) -> string`（`"<日付の番号>:<写真の番号>:<枚数>"`。写真 0 枚なら `"clear"`）

- [ ] **Step 1: 失敗するテストを足す**

```js
const D = C.albumDiff(["a", "b", "c"], ["b", "c", "d"]);
ok(D.keep.join() === "b,c" && D.add.join() === "d" && D.order.join() === "b,c,d", "albumDiff: 増えた d だけ add、消えた a は除く");
ok(C.albumDiff(["a", "b"], ["b", "a"]).add.length === 0, "albumDiff: 並び替えだけなら add は空");
ok(C.albumDiff([], []).order.length === 0, "albumDiff: 空どうし");
const m = C.normalize({ album: "壊れた値", albumIds: 1, manualPhotos: null }, "top");
ok(m.album === null && Array.isArray(m.albumIds) && Array.isArray(m.manualPhotos), "normalize: アルバムの項目を埋める");
ok(C.albumNotice("ok", "キャラ") === "", "albumNotice: ok は空");
ok(/すべての写真/.test(C.albumNotice("limited", "キャラ")) && /すべての写真/.test(C.albumNotice("denied", "キャラ")), "albumNotice: 許可の案内");
ok(/キャラ.*見つかりません/.test(C.albumNotice("not-found", "キャラ")), "albumNotice: アルバムが無い");
// syncAlbum: 偽のプラグインと保存先で、取り出せない写真を飛ばすこと・startDate を変えないこと
```

`syncAlbum` のテストは、`Character` の `load`/`save` を差し替えられるよう `Character._store = { load, save }` を内部で使う形にしてよい（テストからだけ差し替える）。偽のプラグインは `assetIds` が `["x", "y"]`、`loadPhoto` が `y` だけ reject。期待: `added === 1`、`failed === 1`、保存された `albumIds` が `["x"]`、`startDate` が元のまま。`watchMark` は写真 0 枚で `"clear"`、同じ日なら同じ文字列

- [ ] **Step 2:** `node apps/tests/character.test.mjs` が失敗することを確かめる
- [ ] **Step 3: character.js を足す。** `syncAlbum` は `assetIds` の reject を `not-found` とする。`add` の写真を `loadPhoto({ id, maxSide: 1080 })` で1枚ずつ取り込み（base64 → Blob）、`order` の並びで `photos`/`albumIds` を組み直す。取り込めなかったものは両方から外す
- [ ] **Step 4: character-settings.js を足す。** 設計書の「登録欄」のとおり（ボタンは `window.Capacitor && Capacitor.Plugins && Capacitor.Plugins.PhotoAlbum` があるときだけ）。アルバムを選んだら `manualPhotos` に今の `photos` を退避、`startDate` を今日にして同期。やめたら `photos = manualPhotos`、`album = null`、`albumIds = []`、`startDate` を今日に
- [ ] **Step 5: apps/index.html。** トップを開いたとき、アルバムとつないだ枠を `syncAlbum` で順に同期してから `updateCharacterDisplay()`。`updateCharacterDisplay` の中で、`watchMark` が `localStorage["character.watchSent"]` と違えば、`top` の今日の写真を長い辺 400 に縮めて `WatchSync.setBackground` へ（`clear` なら `null`）、`ok` のときだけ印を控える
- [ ] **Step 6:** `for t in apps/tests/*.test.mjs; do node "$t" || echo "FAILED: $t"; done` で、Playwright を使う `kakeibo`・`pwa` 以外に `FAILED` が無いこと
- [ ] **Step 7:** Claude が確認してコミット（`feat: キャラクター写真をアルバムとつなげ、Watch へ送る`）

---

### Task 4: 確認・転送・取り込み

**担当:** Claude

- [ ] Playwright のテスト（`smoke`・`pwa`・`kakeibo`・`nativebridge`）が `main` と同じ結果（`smoke` は元からの 2 件だけ失敗）
- [ ] 計画 1 のブラウザ確認スクリプトがまだ通る（アルバムのボタンはブラウザでは出ない）
- [ ] `npm run iphone`、`npm run apple-watch` で転送し、版を報告する
- [ ] 実物: アルバムを選ぶ → 写真が入る → 写真アプリでアルバムに足す → トップを開き直すと増える → Watch の背景に出る
- [ ] 利用者の確認後に PR を作って取り込む
