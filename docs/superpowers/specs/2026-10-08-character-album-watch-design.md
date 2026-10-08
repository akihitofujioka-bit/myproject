# キャラクター写真の追加機能（アルバム連携・Watch の背景）設計書

作成 2026-10-08。`2026-10-08-character-photo-design.md`（計画 1）に足す機能。計画 1 の決まりはそのまま守る。

## 目的

1. 写真アプリのアルバムとつなげ、アルバムに写真を足すだけで壱師に反映されるようにする
2. 壱師のトップ画面の写真（`top` 枠）を、Apple Watch の壱師アプリの背景にも出す

## 決まったこと（利用者との確認 2026-10-08）

- 写真の取り込み元は **写真アプリのアルバム**（ファイルアプリのフォルダではない）。6 枠それぞれに別のアルバムを選べる
- 今の「写真を1枚ずつ追加する」方法も残す
- Watch は **壱師アプリの背景** に出す（文字盤のコンプリケーションには出さない）
- アルバムの写真が iPhone に保存されていないとき、iOS が利用者自身の iCloud から取り寄せることを **許す**（利用者の承諾 2026-10-08）。アプリから外部へデータを送ることはしない

## 1. アルバムとつなげる

### Swift の部品 `PhotoAlbumPlugin`（新規 `mobile/ios/App/App/PhotoAlbumPlugin.swift`）

既存の `ReceiptScannerPlugin` と同じ作り（`CAPPlugin, CAPBridgedPlugin`、`ViewController.swift` で登録）。JS 側の名前は `PhotoAlbum`。

| メソッド | 受け取るもの | 返すもの |
|---|---|---|
| `isSupported` | なし | `{ supported: true }` |
| `listAlbums` | なし | `{ status, albums: [{ id, title, count }] }` |
| `assetIds` | `{ albumId }` | `{ status, ids: [String] }`（アルバムの並び順） |
| `loadPhoto` | `{ id, maxSide }` | `{ data }`（JPEG 品質 0.85 を base64 にしたもの） |

- `status` は `"ok"`・`"limited"`（「選んだ写真だけ」の許可）・`"denied"`（許可なし）のどれか。`ok` 以外のとき、`albums`・`ids` は空
- 許可は、初めて `listAlbums` を呼んだときに `PHPhotoLibrary.requestAuthorization(for: .readWrite)` で求める
- 対象のアルバムは、利用者が作ったアルバム（`PHAssetCollectionType.album`）だけ。写真だけを数え、動画は除く
- `loadPhoto` は `PHImageManager` で長い辺 `maxSide` に縮めて取り出す。`isNetworkAccessAllowed = true`（iCloud からの取り寄せを許す）、`deliveryMode = .highQualityFormat`。取り出せなかったら reject する
- `Info.plist` に `NSPhotoLibraryUsageDescription` を足す。文言は「キャラクター写真に使うアルバムを読み込みます。写真はこの端末の中だけで使い、外部へは送りません。」

### 枠の記録に足す項目

```js
{
  ...計画 1 の項目,
  album: null | { id: "…", title: "キャラ冷蔵庫" },
  albumIds: [String]   // 取り込み済みの写真の番号。photos と同じ並び
}
```

- `album` が `null` のときは、計画 1 と同じ（手で足した写真を使う）
- `album` があるときは、`photos` と `albumIds` をアルバムの中身で置き換えて使う。手で足した写真は、別の項目 `manualPhotos` に退避しておき、つなげるのをやめたら `photos` に戻す
- `normalize` は、`album` が無ければ `null`、`albumIds`・`manualPhotos` が配列でなければ `[]` にする

### 取り込み（同期）

- **いつ**: トップ画面を開いたとき（`updateCharacterDisplay` の前）に、アルバムとつないだ枠を順に同期する。各機能の画面は同期せず、取り込み済みの写真を使う
- **差分の計算**は、新しい関数 `Character.albumDiff(oldIds, newIds)` で行う。返すもの: `{ keep: [番号], add: [番号], order: newIds }`。`newIds` に無いものは除き、`oldIds` に無いものだけ `add` に入れる
- `add` の写真だけを `loadPhoto({ id, maxSide: 1080 })` で1枚ずつ取り込み、`newIds` の並びに組み直して保存する
- アルバムの写真が増えても減っても、`startDate` は変えない（切り替えの順番が急に1枚目に戻らないようにするため）
- 1枚取り込めなかったときは、その写真を飛ばし、次の同期でまた試す（`albumIds` に入れない）
- `status` が `ok` でないとき、またはアルバムが見つからないときは、取り込み済みの写真をそのまま使い、登録欄に案内を出す
  - `limited`: 「設定アプリ → プライバシー → 写真 で『すべての写真』を許可してください」
  - `denied`: 同じ案内
  - アルバムが無い: 「アルバム『◯◯』が見つかりません。選び直してください」

### 登録欄

- 各枠に「アルバムとつなげる」ボタンを足す。押すとアルバムの一覧（名前と枚数）を出し、選ぶとすぐ同期する
- つないでいる枠では、「写真を追加」と「上へ／下へ／削除」を隠し、「アルバム『◯◯』とつないでいます（◯枚）」と「つなげるのをやめる」を出す
- `window.Capacitor` があり、`PhotoAlbum` が使えるときだけボタンを出す（ブラウザでは出さない）
- アルバムを選んだとき、つなげるのをやめたときは、`startDate` を今日にする（計画 1 と同じく、そのときに1枚目が出る）

## 2. Watch の背景

### iPhone 側

- `WatchBridgePlugin` にメソッド `setBackground` を足す。受け取るもの: `{ data: base64 の JPEG }` または `{ clear: true }`
  - `data` のとき: 一時ファイルに書き、`WCSession.default.transferFile(url, metadata: ["kind": "background"])` で送る。前回送ったものがまだ送信待ちなら取り消してから送る
  - `clear` のとき: `WCSession.default.transferUserInfo(["kind": "background-clear"])` を送る
  - Watch が無い・アプリが入っていないときは、`ok: false` と理由を返す（`sync` と同じ形）
- JS 側（`apps/shared/watch.js`）に `WatchSync.setBackground(blob | null)` を足す
- トップ画面の `updateCharacterDisplay` で、`top` 枠の今日の写真を長い辺 400 ピクセルに縮め、Watch に送る
  - 送ったものの印（`日付の番号:写真の番号:写真の枚数` の文字列）を `localStorage` の `character.watchSent` に控え、前回と同じなら送らない
  - `top` 枠の写真が 0 枚になったら `clear` を送る（前回が既に `clear` なら送らない）

### Watch 側

- `WatchStore` に `@Published var background: UIImage?` を足す
  - `session(_:didReceive file:)` で `kind == "background"` のファイルを、アプリのフォルダ（`Application Support/background.jpg`）に移して読み込む
  - `session(_:didReceiveUserInfo:)` で `kind == "background-clear"` のときは、そのファイルを消して `nil` にする
  - 起動時は、保存済みの `background.jpg` があれば読み込む
- `ContentView` の `List` に `.scrollContentBackground(.hidden)` を付け、後ろに写真を `scaledToFill` で敷き、その上に黒の半透明（不透明度 0.55）を重ねる。写真が無いときは今のまま

## 3. テスト

- `apps/tests/character.test.mjs` に足す:
  - `albumDiff`: 増えた写真だけ `add`、消えた写真は除く、並び替えだけなら `add` は空、空どうし
  - `normalize`: `album`・`albumIds`・`manualPhotos` の欠けや壊れた値を埋める
- Swift: iPhone アプリと Watch アプリの両方を `xcodebuild … CODE_SIGNING_ALLOWED=NO build` で通す
- 既存のテスト（`apps/tests/*.test.mjs`、Playwright の `smoke`・`pwa`・`kakeibo`・`nativebridge`）が今と同じ結果であること
- 実物: アルバムを作って写真を入れ、壱師でつなぐ → 写真を足す → トップを開き直すと増える。Watch の壱師アプリの背景にトップの写真が出る

## 4. 作業分担

| 担当 | 対象ファイル | 作業 |
|---|---|---|
| Codex | `PhotoAlbumPlugin.swift`、`ViewController.swift`、`Info.plist` | アルバムの Swift の部品 |
| Codex | `apps/shared/character.js`、`character-settings.js`、`apps/index.html`、`apps/tests/character.test.mjs` | 差分・同期・登録欄 |
| Codex | `WatchBridgePlugin.swift`、`apps/shared/watch.js`、`WatchStore.swift`、`ContentView.swift` | Watch の背景 |
| Claude | 全体 | 依頼文づくり、確認、ビルド、iPhone・Watch への転送、コミット |

## やらないこと

- 文字盤のコンプリケーションには写真を出さない
- アプリから外部へデータを送らない（iCloud からの取り寄せは iOS の写真の仕組みによる受け取りで、利用者が許可済み）
- 件の機能の移植（計画 2）は扱わない
