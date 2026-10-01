# カレンダー直接書き込み・無音カメラの設計（2026-09-24 実装）

このドキュメントは、`claude/daily-life-app-ideas-67bori` ブランチで実装した3つの
ネイティブ機能（カレンダーへの直接書き込み／無音カメラ／撮り方の選択）を、
別セッションの AI が読んでもすぐ全体像をつかめるようにまとめたもの。

対象アプリ：`mobile/`（Capacitor で包んだ iPhone アプリ「日常アプリ」、Bundle ID
`jp.myproject.dailyapps`）。Web 側の実体は `apps/` にあり、`mobile/` はそれを
ネイティブの入れ物に包んでいるだけ（コードは共有）。

## 1. 何を解決したか

利用者（実機）からの指摘（2026-09-24）:

1. 会議をカレンダーに登録するとき「カレンダーに登録」を押すと共有シートが出て
   操作が分かりにくい
2. 同じ会議を登録し直すと、カレンダー側で予定が重複して増える
3. レシート・書類を撮るとき、VisionKit の書類カメラ（自動で四隅を切り出す）は
   日本向け iPhone だとシャッター音を消せない（写真撮影の仕組みを使う限り不可）

これに対応するため、次の3点を作った。

| 課題 | 対応 |
| --- | --- |
| 1, 2 | `CalendarWriterPlugin`（EventKit で直接書き込み、識別子で上書き） |
| 3 | `SilentCameraViewController`（映像の1コマを取り出す自前カメラ、音が鳴らない） |
| 3 の妥協点 | 撮り方を "無音" と "自動切り出し(書類カメラ)" の2択にして利用者に選ばせる（`camerapref.js`） |

## 2. 全体構成（Native プラグイン一覧）

`ViewController.swift`（`capacitorDidLoad`）で4つの Capacitor プラグインを登録している。
すべて iOS 標準の枠組み（EventKit / Vision / VisionKit / WatchConnectivity）だけを使い、
**外部への通信は一切行わない**（このアプリ全体の設計方針）。

```
ViewController.capacitorDidLoad()
  ├─ ReceiptScannerPlugin   … レシート/書類を撮って文字を読み取る、または写真に保存
  │     └─ 内部で SilentCameraViewController か VNDocumentCameraViewController を呼ぶ
  ├─ WatchBridgePlugin      … 今日の会議・期限・買い物リストを Apple Watch に渡す
  ├─ CalendarReaderPlugin   … iPhone カレンダーの予定を「読み取って」会議として取り込む
  └─ CalendarWriterPlugin   … 会議・期限を iPhone カレンダーへ「直接書き込む」（新規）
```

**読み取りと書き込みが別プラグインである理由**（`CalendarReaderPlugin.swift` 冒頭コメント）:
読み取った予定をそのまま書き戻すと同じ予定が重複して増えるため、経路をはっきり分けている。

### 2.1 CalendarReaderPlugin（既存・変更なし）
- `jsName: "CalendarReader"`
- メソッド: `isSupported` / `requestAccess` / `listCalendars` / `listEvents`
- 選んだカレンダーから、今日起点で指定日数分（既定60日）の予定を読み出して
  会議候補として返すだけ。書き込みはしない。

### 2.2 CalendarWriterPlugin（新規）
- `jsName: "CalendarWriter"`
- メソッド: `isSupported` / `requestAccess` / `saveEvents`
- 呼び出し元（JS）が渡す `events` の各要素に `key`（呼び出し側の識別用文字列）と
  `eventId`（前回保存時に返ってきた EventKit の識別子）を持たせる。
  `eventId` があればその予定を**上書き**し、無ければ新規作成する。
  → これが「登録し直しても増えない」仕組みの核。
- 通知（アラーム）は毎回いったん全部外してから付け直す（重複防止）。
- 認可は「前に入れた予定を書き換える」ために `requestFullAccessToEvents`
  （読み取り相当の権限）を要求する。`CalendarReaderPlugin` と同じ権限区分なので、
  利用者への確認ダイアログは実質1回で済む。
- 書き込み先はこのアプリが作った予定だけ。ほかの予定は触らない。

### 2.3 ReceiptScannerPlugin（既存・大幅変更）
- `jsName: "ReceiptScanner"`
- メソッド: `scan`（文字認識して返す）/ `scanToPhotos`（写真アプリに保存）/ `isSupported`
- 呼び出し時に JS が `camera: "silent" | "document"` を指定する（既定 `silent`）。
  - `"silent"` → `SilentCameraViewController` を全画面表示。音は鳴らないが、
    書類の四隅を自動で切り出さない（利用者が枠に収めて撮る）。
  - `"document"` → 既存の `VNDocumentCameraViewController`（VisionKit）。
    四隅の自動切り出し・歪み補正ができるが、シャッター音は消せない。
- 文字認識はどちらの撮り方でも Vision（`VNRecognizeTextRequest`, 言語 `ja-JP`/`en-US`）。
  返すのは「行ごとの文字＋画像内の位置（0〜1 の割合）」までで、
  合計・日付・店名などの意味づけは JS 側（`apps/shared/receipt.js`）が行う。
  → 理由: 店ごとにレシートの様式が違い、抽出ルールを直す機会が多いため、
     ネイティブを作り直さず JS だけで調整できるようにしている。
- 表示先の画面が見つからない／別画面が既に開いている場合はエラーを返すよう
  ガードを追加（以前は `present` の成否を確認しておらず、失敗時に画面が
  何も出ないまま固まって見える不具合があった）。

### 2.4 SilentCameraViewController（新規、UIViewController）
`ReceiptScannerPlugin` から呼ばれる、シャッター音を鳴らさないための自前カメラ画面。

**なぜ自前で作るか**: `AVCapturePhotoOutput`（写真を撮る仕組み）を使う限り、
日本向け iPhone はシャッター音を消せない。そこで `AVCaptureVideoDataOutput`
（プレビュー映像の1コマ）を取り出す方式にした。これは「写真を撮る」動作を
一切使わないため、音が鳴らない。

- `AVCaptureSession` + `AVCaptureVideoDataOutput` でプレビューを流しっぱなしにし、
  「撮る」ボタンが押されたら次に届いた1フレーム（`CMSampleBuffer`）を
  `UIImage` に変換して呼び出し元へ返す（`onFinish` クロージャ）。
  ボタン処理はキャプチャ用のシリアルキュー（`wantsCapture` フラグ）で行い、
  フレーム到着のたびに毎回フラグを見るだけの軽い処理にしている。
- 画質は `.photo` プリセット優先（使えない機種は `.hd1920x1080` に自動で落とす）。
- 撮影した画像はこの画面から呼び出し元に渡すだけで、外部送信は一切しない。

## 3. JS 側（Web 共通コード）との対応

Native プラグインは薄いブリッジ（`apps/shared/*.js`）を介して各アプリ（家計簿・
会議・書類トラッカーなど）から呼ばれる。ブラウザ実行時やプラグインが無い環境では
`available()` が `false` を返し、呼び出し側が代替経路（`.ics` ファイル共有など）に
自動で切り替わる設計。

```
apps/<各アプリ>
   │ 呼ぶ
   ▼
apps/shared/calendarwrite.js   ← CalendarWriterPlugin の薄いラッパー
apps/shared/camerapref.js      ← 撮り方（silent/document）の設定 UI と永続化
apps/shared/receipt.js         ← ReceiptScanner が返す「行と位置」から金額等を抽出
apps/shared/watch.js           ← WatchBridge 用（今回変更なし）
```

### 3.1 `apps/shared/calendarwrite.js`
- `CalendarWrite.save(events)` … `events` 配列を `CalendarWriterPlugin.saveEvents` に渡す。
- 呼び出し前に `isSupported()` → 未許可なら `requestAccess()` を1回だけ試す。
- 戻り値 `{ ok, reason, ids: { key: eventId }, failed }`。
  呼び出し側（各アプリ）はこの `ids` を localStorage 等に保存しておき、
  次回の保存時に同じ `key` の `eventId` を渡すことで上書きを実現する
  （＝重複防止の実体は JS 側が識別子を覚えておくこと）。
- `ok:false` のときは呼び出し側が従来の `.ics` 経由に切り替える想定
  （このファイル自体はフォールバック処理を持たず、可否を返すだけ）。

### 3.2 `apps/shared/camerapref.js`
- 設定は `localStorage` の `camera.v1` に `"silent"` または `"document"` を保存。
- `mount(container, onChange)` で「撮り方」を選ぶチップ状のボタンUIをどのアプリにも
  同じ見た目で挿入できる。選択結果を `get()` で読み、`ReceiptScanner.scan({ camera })`
  のように渡す想定。

## 4. 権限（Info.plist）

`NSCalendarsUsageDescription` / `NSCalendarsFullAccessUsageDescription` の文言を、
読み取り専用の説明から「会議や書類の期限をカレンダーに登録し、カレンダーの予定を
会議として取り込むために使用します」に更新（書き込みが増えたため）。
「書き込むのは、このアプリから登録した予定だけ」である点は明記を維持。

## 5. ビルド時のハマりどころ（2026-09-24 に発生・解消済み）

`CalendarWriterPlugin.swift` と `SilentCameraViewController.swift` は
ファイルとしては追加されていたが、**Xcode プロジェクトファイル
（`mobile/ios/App/App.xcodeproj/project.pbxproj`）への登録が漏れていた**ため、
`ViewController.swift` から参照できず `xcodebuild` がコンパイルエラーになった。

pbxproj は次の4箇所に「同じファイルへの参照」を書く必要がある（漏れると
ファイルシステムにあってもビルド対象に入らない）。

1. `PBXBuildFile` セクション（`... in Sources ...`）
2. `PBXFileReference` セクション（ファイル本体の登録）
3. 所属する `PBXGroup`（Xcode の Project Navigator 上のグループ、`App` グループ）
4. `PBXSourcesBuildPhase` の `files`（実際にコンパイル対象にするリスト）

新規 Swift ファイルを別セッション（Xcode の GUI を使わない環境）で追加した場合、
この pbxproj への登録が漏れやすい。**Swift ファイルを追加したら、pbxproj に
4箇所とも入っているかを `grep -n "<ファイル名>" project.pbxproj` で確認する**のが
早い（コミット `9de937b` で修正済み）。

## 6. 関連ファイル一覧

| ファイル | 役割 |
| --- | --- |
| `mobile/ios/App/App/ViewController.swift` | プラグイン登録の入口 |
| `mobile/ios/App/App/CalendarReaderPlugin.swift` | カレンダー読み取り |
| `mobile/ios/App/App/CalendarWriterPlugin.swift` | カレンダー直接書き込み（新規） |
| `mobile/ios/App/App/ReceiptScannerPlugin.swift` | 撮影〜文字認識、撮り方2種の切替 |
| `mobile/ios/App/App/SilentCameraViewController.swift` | 無音カメラ本体（新規） |
| `mobile/ios/App/App/WatchBridgePlugin.swift` | Apple Watch への同期（今回変更なし） |
| `mobile/ios/App/App/Info.plist` | カレンダー権限文言 |
| `apps/shared/calendarwrite.js` | CalendarWriterPlugin の JS 側ラッパー |
| `apps/shared/camerapref.js` | 撮り方の設定 UI・永続化 |
| `apps/shared/receipt.js` | レシートの行データから金額等を抽出（今回変更なし） |
| `mobile/README.md` | 「アプリ内で定義しているプラグイン」節に一覧あり |

## 7. 未検証・今後の注意

- Apple Watch 連携（`WatchBridgePlugin`／`docs/apple-watch-app.md`）は元々
  「ビルド未検証」表記のまま。今回の変更でも触っていない。
- `SilentCameraViewController` は四隅の自動切り出しをしないため、書類が
  枠からはみ出すと文字認識の精度が落ちる可能性がある（利用者への案内文で
  「枠に収めて」と明示することで対応）。
- カレンダー書き込みの `eventId` は JS 側（localStorage）が唯一の保存場所。
  端末を機種変更する、あるいはアプリを再インストールして localStorage が
  消えると、次回保存時に「前回の予定」を見失い、同じ会議が重複して
  新規作成される可能性がある（許容している設計上のトレードオフ）。

## 8. 2026-10-01 の追加（取り込み・無音カメラの改善・手帳の読み取り）

- このブランチ（`claude/daily-life-app-ideas-67bori`）の4コミットは `main` に入っていなかった。
  `feat/planner-scan` に取り込み、Mac で `xcodebuild`（iOS 向け・署名なし）が通ることを確かめた
- `SilentCameraViewController` を改善した（複数レンズのカメラでマクロへ自動切替、ピント待ち、
  4コマから最もくっきりしたものを選ぶ、紙の四隅を探して傾き補正、ライト、タップでピント、点滅と振動）
- `ReceiptScannerPlugin.scan` に `purpose`（`receipt` / `planner` / `any`）を足した。
  案内文と、文字認識の `minimumTextHeight`（手帳・振り分け前は 0.006）を切り替える
- 手帳の読み取りは JS 側（`apps/shared/planner.js`）。詳しくは `apps/README.md` の「手帳のページを読み取って…」
- 書類トラッカーの `writeToCalendar` が終日の予定（`allDay`）を扱えるようにした。`CalendarWriterPlugin` は
  `startTime` が空なら終日として入れる（既存の動き）。`.ics` 経由でも `DTSTART;VALUE=DATE` で終日になる
