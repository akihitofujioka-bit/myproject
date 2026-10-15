# 端末内 AI と履歴（計画 2-4）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 予定アプリに「AI」（秘書・壁打ち・ブレスト）と「履歴」（会話・書類・手書きメモ）のタブを足す。AI は端末内だけ。

**Architecture:** 会話・履歴は Web 側（IndexedDB `ichishi-history`）で持ち、Swift の `OnDeviceAI` プラグインは毎回 1 問 1 答だけ。日付・期間・空き時間・下書きの確かめは AI を使わない `secretary.js` で行う。

**Tech Stack:** 素の JavaScript（`apps/shared/*.js`、`window.Xxx` に公開する即時関数）、Node のテスト（`node apps/tests/*.test.mjs`）、Playwright、Swift（Capacitor プラグイン、FoundationModels、Vision、PhotosUI）。

**Spec:** `docs/superpowers/specs/2026-10-13-ondevice-ai-design.md`

## Global Constraints

- 外部への通信を一切足さない。AI は `FoundationModels`（端末内）だけ
- アプリの対応 OS（`IPHONEOS_DEPLOYMENT_TARGET = 16.0`）は変えない。AI の部分だけ `@available(iOS 26.0, *)`
- 予定データ（localStorage `schedule.v1`）と書類・やること（`docs-tracker.v1`）の形は変えない。読めないデータは上書きしない
- 履歴は IndexedDB `ichishi-history`（版 1）、ストア `entries`（keyPath `id`、索引 `updatedAt`・`kind`）
- 数値: 会話は直近 **6 往復**、資料は先頭 **3,000 字**、予定一覧は **60 件**、期間の既定は **今日から 14 日間**、空きは **8:30〜17:15**、題名は **30 字**。上限超過時のやり直しは **1 回だけ**（直近 **2 往復**・資料 **1,500 字**）
- 新しい npm パッケージを入れない。テストの見本・名前は架空のものだけ
- 画面の文言・コメントは日本語。既存の書き方（`window.Xxx = {...}`、`esc()`、`toast()`）に合わせる
- 新しい `apps/shared/*.js` は `apps/schedule/index.html` の `<script>` と `apps/schedule/sw.js` のキャッシュ一覧の両方に足す
- Codex に渡す依頼文には「myproject の外（Desktop・Documents・Obsidian など）を読まない・ネット禁止・commit 禁止・架空の名前だけ」を書く

## Review Focus

- **AI が JSON の前後に説明文や ```json の囲みを付けて返す** → 囲みの中の最初の `{…}` を取り出して読む（Task 2 のテストに追加）
- **会話の途中でアプリを閉じた・別の会話を開いた** → 送った質問は AI の答えが来る前に履歴へ保存され、答えは送ったときの会話 ID に追記される（Task 5 のテストに追加）
- **選んだ資料が後から消された** → 会話は残り、資料名は「削除された資料」と表示（Task 5 のテストに追加）
- **年末に「来月」「1月5日」と聞く** → 年をまたいで翌年になる（Task 2 のテストに追加）
- **答えの文字に `<script>` や `<b>` が入る** → 吹き出しはすべて `esc()` を通し、HTML として解釈しない（Task 5 のテストに追加）

---

### Task 1: 履歴の保存（`history.js`）

**Files:**
- Create: `apps/shared/history.js`
- Test: `apps/tests/history.test.mjs`

**Interfaces:**
- Produces: `window.History`（`History` は既存のブラウザ API と名前がぶつかるため **`window.AIHistory`** とする）
  - `AIHistory.open(indexedDB?) -> Promise<db>`（省略時は `window.indexedDB`。使えなければ reject `Error("unavailable")`）
  - `AIHistory.add(entry) -> Promise<entry>`: `id`・`createdAt`・`updatedAt` を埋めて保存。`entry` は設計書の表の項目
  - `AIHistory.update(id, patch) -> Promise<entry>`: 上書きして `updatedAt` を更新
  - `AIHistory.appendMessage(id, {role, text}) -> Promise<entry>`: `messages` に `at` 付きで足す
  - `AIHistory.get(id) -> Promise<entry|null>`
  - `AIHistory.list({kind?, query?}) -> Promise<entry[]>`: `updatedAt` の新しい順
  - `AIHistory.remove(id)`・`AIHistory.clear() -> Promise<void>`
  - `AIHistory.normalize(text) -> string`: 検索用。NFKC、カタカナ→ひらがな、小文字化
  - `AIHistory.titleFrom(text) -> string`: 最初の空でない行の先頭 30 字

- [ ] **Step 1: 失敗するテストを書く**（テスト内に小さな IndexedDB のにせもの: `open`・`transaction`・`objectStore` の `put/get/delete/clear/getAll` と `onsuccess` だけ）
  - `normalize("ＡＢＣ　カイギ") === normalize("abc かいぎ")`
  - `add({kind:"document", title:"架空の通知", body:"第1委員会室で開催"})` の戻り値に `id`・`createdAt` がある
  - `list({query:"ダイイチ"})` は 0 件、`list({query:"第１ 委員会"})` は 1 件（複数語はすべて含む）
  - 会話は `messages[].text` も検索対象
  - `list({kind:"chat"})` は会話だけ。並びは `updatedAt` の新しい順
  - `appendMessage` で `messages.length` が 1 増え、`updatedAt` が新しくなる
  - `remove` 後は `get` が `null`、`clear` 後は `list()` が空
  - `titleFrom("\n\n架空の議案について説明します。" + "あ".repeat(40))` が 30 字
- [ ] **Step 2:** `node apps/tests/history.test.mjs` → FAIL（`AIHistory` が無い）
- [ ] **Step 3:** `apps/shared/history.js` を書く。検索は `getAll` してから JS で絞る（件数は数百件想定）
- [ ] **Step 4:** `node apps/tests/history.test.mjs` → すべて PASS
- [ ] **Step 5: コミット** `feat: 履歴を端末内の IndexedDB に保存・検索・削除できる部品を足す`

### Task 2: AI 秘書の規則（`secretary.js`）

**Files:**
- Create: `apps/shared/secretary.js`
- Test: `apps/tests/secretary.test.mjs`

**Interfaces:**
- Produces: `window.Secretary`
  - `range(question, today) -> {from:"YYYY-MM-DD", to:"YYYY-MM-DD", found:boolean}`（`today` は `"YYYY-MM-DD"`。週は月曜始まり）
  - `lines(range, {items, calendarEvents, todos}) -> {text:string, count:number, cut:boolean}`
    - `items`: 予定アプリの `state.items`（`title, dueOn, dest, note, calEventId`、時刻は既存の `timeOf`/`endTimeOfItem` と同じ規則でメモ欄から取る。関数は `index.html` から引数で渡す: `lines(range, data, {timeOf, endTimeOf})`）
    - `calendarEvents`: `CalendarRead` の予定（`title, start, end, allDay, location, id`）。`calEventId` が一致する壱師の予定があれば 1 件にまとめる
    - `todos`: 書類・やることの期限付き項目（`title, dueOn`）→ `M/D(曜) 期限 件名（やること）`
    - 1 行の形: `10/20(火) 10:00-12:00 議会運営委員会 @第1委員会室`。日付・開始時刻順、60 件で切る
  - `wantsFree(question) -> boolean`（「空き」「空いて」）
  - `freeSlots(range, busy) -> string`（`busy`: `[{date, start, end, allDay}]`。各日 8:30〜17:15 の空き。例 `10/20(火) 空き 8:30-10:00, 12:00-17:15`、終日なら `10/21(水) 終日の予定あり`）
  - `wantsDraft(question) -> boolean`（「入れて」「登録」「追加」「やること」「忘れないように」「予定にして」）
  - `draftInstructions(today) -> string`（JSON だけを返させる指示。形は設計書のとおり）
  - `checkDraft(aiText, question, today) -> {ok:boolean, draft?:{kind, title, date, start, end, place, memo}}`

- [ ] **Step 1: 失敗するテストを書く**（今日 = `2026-10-13`(火)）
  - `range("今日の予定は？")` → `2026-10-13〜2026-10-13`、`明日` → 14、`あさって` → 15
  - `今週` → `10-12〜10-18`、`来週` → `10-19〜10-25`、`今月` → `10-01〜10-31`、`来月` → `11-01〜11-30`
  - `10月20日` → 20〜20、`20日` → 20〜20、`火曜` → `10-13`、`来週火曜` → `10-20`
  - 言葉なし → `10-13〜10-26`・`found:false`
  - 年またぎ（今日 `2026-12-20`）: `来月` → `2027-01-01〜2027-01-31`、`1月5日` → `2027-01-05`
  - `lines`: calEventId が同じ予定とカレンダー予定が 1 行、61 件で `cut:true`・`count:60`
  - `freeSlots`: 10:00-12:00 と 11:00-13:00 が重なる日 → `空き 8:30-10:00, 13:00-17:15`。終日 → `終日の予定あり`。8:30 前・17:15 後の予定は空きを削らない
  - `checkDraft('```json\n{"kind":"event","title":"架空の打合せ","date":"2026-10-21","start":"10:00"}\n```', "来週火曜10時に架空の打合せを入れて", "2026-10-13")` → `ok`・`date:"2026-10-20"`（規則が勝つ）
  - 読めない文字 → `ok:false`。`date:"2026-02-30"`・`start:"25:00"` → 空欄。`title` 空 → 質問の先頭 30 字。`kind` が不明 → `event`
- [ ] **Step 2:** `node apps/tests/secretary.test.mjs` → FAIL
- [ ] **Step 3:** `apps/shared/secretary.js` を書く。`todos.js` の `validDate`/`closestDate` の考え方（年の無い月日は今日以降で最初の日）に合わせる
- [ ] **Step 4:** → すべて PASS
- [ ] **Step 5: コミット** `feat: AI 秘書に渡す期間・予定一覧・空き時間・下書きの確かめを決まった規則で作る`

### Task 3: 会話の組み立て（`aichat.js`）

**Files:**
- Create: `apps/shared/aichat.js`
- Test: `apps/tests/aichat.test.mjs`

**Interfaces:**
- Consumes: `OnDeviceAI.respond({instructions, prompt}) -> Promise<{text}>`（Task 4。テストではにせもの）
- Produces: `window.AIChat`
  - `MODES = {secretary:"秘書", sparring:"壁打ち", brainstorm:"ブレスト"}`
  - `instructions(mode, {today, context, source}) -> string`: 設計書の指示文（秘書は「今日は YYYY-MM-DD（曜日）」と `context` を含む。`source` があれば「資料: 題名\n本文」を付ける）
  - `recent(messages, turns) -> messages`（直近 `turns` 往復＝`turns*2` 件）
  - `clip(text, limit) -> {text, cut:boolean}`
  - `sourceNotice(cut) -> string`: `cut` なら `"資料が長いため先頭 3,000 字だけ渡しています"`
  - `ask(ai, {mode, today, context, source, messages, question}) -> Promise<{text, retried:boolean}>`
    - 1 回目: 直近 6 往復・資料 3,000 字。`tooLong` で reject されたら直近 2 往復・資料 1,500 字で 1 回だけやり直す
    - prompt は過去のやりとりを `利用者: …` / `秘書|相手: …` の行で並べ、最後に今回の質問
  - `errorMessage(code) -> string`: 設計書「うまくいかないとき」の文言（`unsupported`/`oldOS`/`disabled`/`notReady`/`tooLong`/`refused`/`failed`）

- [ ] **Step 1: 失敗するテストを書く**
  - `recent` に 20 件 → 12 件、末尾が同じ
  - `clip("あ".repeat(3001), 3000)` → 3,000 字・`cut:true`
  - `instructions("sparring", …)` に「問いを 1 つ返す」、`brainstorm` に「8〜10 個」、`secretary` に「分かりません」と「2026-10-13（火）」
  - にせ AI が 1 回目 `tooLong` → 2 回目成功: `retried:true`、2 回目の prompt の過去行は 4 件以下、資料は 1,500 字以下
  - にせ AI が 2 回とも `tooLong` → reject の `code === "tooLong"`、呼び出し回数 2
  - にせ AI が `refused` → やり直さず reject（呼び出し 1 回）
- [ ] **Step 2:** `node apps/tests/aichat.test.mjs` → FAIL
- [ ] **Step 3:** `apps/shared/aichat.js` を書く
- [ ] **Step 4:** → すべて PASS
- [ ] **Step 5: コミット** `feat: 秘書・壁打ち・ブレストの指示文と、量を絞った会話の組み立てを足す`

### Task 4: Swift の橋渡し（`OnDeviceAI`・写真の文字認識）

**Files:**
- Create: `mobile/ios/App/App/OnDeviceAIPlugin.swift`、`apps/shared/ondeviceai.js`
- Modify: `mobile/ios/App/App/ViewController.swift`（`registerPluginInstance(OnDeviceAIPlugin())`）、`mobile/ios/App/App.xcodeproj/project.pbxproj`（新ファイルをターゲットに追加）、`mobile/ios/App/App/DocumentReaderPlugin.swift`（`pickImage` を足す）、`apps/shared/documentreader.js`（`pickImage()`）
- Test: `apps/tests/nativebridge.test.mjs` に追記

**Interfaces:**
- Produces:
  - Swift `OnDeviceAI.status() -> {available, reason}`、`OnDeviceAI.respond({instructions, prompt}) -> {text}`、失敗は `call.reject(文言, code)`（`code`: `tooLong`/`refused`/`unavailable`/`failed`）
    - `SystemLanguageModel.default.availability` の `.unavailable(.deviceNotEligible)` → `unsupported`、`.appleIntelligenceNotEnabled` → `disabled`、`.modelNotReady` → `notReady`、iOS 26 未満 → `oldOS`
    - `LanguageModelSession.GenerationError.exceededContextWindowSize` → `tooLong`、`.guardrailViolation`・`.refusal` → `refused`
  - JS `window.OnDeviceAI.status() -> Promise<{available, reason}>`（ネイティブでなければ `{available:false, reason:"unsupported"}`）、`window.OnDeviceAI.respond(args) -> Promise<{text}>`（reject の `error.code` を保つ）
  - Swift `DocumentReader.pickImage() -> {cancelled, name, text, ocr:true}`: `PHPickerViewController`（画像 1 枚）→ Vision `VNRecognizeTextRequest`（`ja-JP`、`.accurate`）。既存の PDF の文字認識と同じ書き方
  - JS `DocumentReader.pickImage() -> Promise<{cancelled, name, text}>`

- [ ] **Step 1: 失敗するテストを書く**（`nativebridge.test.mjs` の既存の書き方で）
  - Capacitor が無いとき `OnDeviceAI.status()` → `{available:false, reason:"unsupported"}`
  - にせ Capacitor の `nativePromise("OnDeviceAI","respond",…)` が `{code:"tooLong"}` で reject → `respond` の reject の `code === "tooLong"`
  - にせ Capacitor で `DocumentReader.pickImage()` が `nativePromise("DocumentReader","pickImage",{})` を呼ぶ
- [ ] **Step 2:** `node apps/tests/nativebridge.test.mjs` → 追加分が FAIL
- [ ] **Step 3:** JS 2 つと Swift 2 つを書き、プラグインを登録する。通信のコード（`URLSession` など）を書かない
- [ ] **Step 4:** `node apps/tests/nativebridge.test.mjs` → PASS
- [ ] **Step 5（Claude）:** `cd mobile && npm run sync` のあと `xcodebuild -project ios/App/App.xcodeproj -scheme App -sdk iphoneos -configuration Debug build CODE_SIGNING_ALLOWED=NO` → `BUILD SUCCEEDED`
- [ ] **Step 6: コミット** `feat: 端末内 AI と写真の文字認識を Web 画面から呼べるようにする`

### Task 5: 履歴のタブ・手書きメモ・書類の自動保存

**Files:**
- Modify: `apps/schedule/index.html`（切り替えに「AI」「履歴」、`<main id="aiView">`（中身は Task 6）と `<main id="historyView">`、`<script>` 4 つ）、`apps/schedule/sw.js`（4 ファイル）
- Test: `apps/tests/schedulehistory.test.mjs`（Playwright。`schedulereader.test.mjs` の `addInitScript` で Capacitor をにせものにする書き方）

**Interfaces:**
- Consumes: `AIHistory`（Task 1）、`ReceiptScan.scan({purpose:"planner"})` の `lines[].text`、`DocumentReader.pickImage()`（Task 4）
- Produces（`index.html` 内の関数。Task 6 が使う）:
  - `setView("ai"|"history")`（既存の `setView` を広げる）
  - `openHistory(id)`、`chooseSource(callback)`（書類・手書きメモの一覧から 1 件選ぶ画面を出し `callback(entry)`）
  - `currentDocumentHistoryId`（直近の読み取りの履歴 ID。登録時に `eventTitles` を足す）

- [ ] **Step 1: 失敗するテストを書く**
  - 「履歴」を押すと検索欄・絞り込み（すべて/会話/書類/手書きメモ）・「✍️ 手書きメモを撮る」「写真から」が出る
  - にせ `DocumentReader.takeShared` で架空の通知を読む → 履歴に「書類」1 件。確認画面で登録 → その項目の `eventTitles` に件名
  - 「写真から」→ にせ `pickImage` の文字が編集欄に入る → 直して「保存」→ 手書きメモ 1 件。題名が空なら本文 1 行目
  - 検索「ダイイチ」0 件／「第１」1 件、絞り込み「会話」で書類が消える
  - 1 件削除・すべて削除は確認（`confirm`）で「キャンセル」なら消えない
  - 書類を開くと「この資料で壁打ち」「この資料でブレスト」ボタン
  - IndexedDB を壊したとき（`indexedDB.open` が失敗）「履歴を保存できません」と出て、一覧タブは動く
  - 本文に `<b>架空</b>` → 太字にならず文字のまま
- [ ] **Step 2:** テスト → FAIL
- [ ] **Step 3:** 画面を書く。書類の自動保存は `showDocumentResult` と `applyMeetingScan` で取り出した文字を `AIHistory.add({kind:"document", title: ファイル名 || titleFrom(text), body:text})`。会議の登録処理（`meetingItems` を使う登録）の保存後に `eventTitles` を `update`
- [ ] **Step 4:** テストと既存の `schedule*.test.mjs`・`build.test.mjs`・`pwa.test.mjs` → PASS
- [ ] **Step 5: コミット** `feat: 予定アプリに履歴のタブを足し、読み取った書類と手書きメモを残せるようにする`

### Task 6: AI のタブ（秘書・壁打ち・ブレスト・下書き）

**Files:**
- Modify: `apps/schedule/index.html`
- Test: `apps/tests/scheduleai.test.mjs`（Playwright。`OnDeviceAI` をにせものにし、質問ごとに決まった答えを返す）

**Interfaces:**
- Consumes: `Secretary`（Task 2）、`AIChat`（Task 3）、`OnDeviceAI`（Task 4）、`AIHistory`・`setView`・`openHistory`・`chooseSource`（Task 1・5）、既存の `startEditing` の値の入れ方（`f-title`・`f-date`・`f-start`・`f-end`・`f-place`・`f-note`）、`Todos.add(localStorage, [{title, dueOn}])`、`SpeechMemo`
- Produces: `openDraftForm(draft)`（登録画面を新規として開き値を入れる。既存の `startEditing` は編集用なので使わず、同じ欄に入れる新しい関数）

- [ ] **Step 1: 失敗するテストを書く**
  - `status` が `{available:false, reason:"disabled"}` → AI タブに「設定 → Apple Intelligence と Siri でオンにしてください」だけ。`unsupported`・`oldOS` もそれぞれの文言
  - 秘書で「来週の予定は？」→ にせ AI に渡った `instructions` に架空の予定 `10/20(火) 10:00-12:00 架空の委員会` を含み、答えの吹き出しと「端末内 AI の答えです。日時は予定一覧で確かめてください」
  - 「来週火曜10時に架空の打合せを入れて」→「予定の登録画面で開く」→ 一覧タブの登録画面に `2026-10-20`・`10:00`・件名
  - 「金曜までに架空の資料を出す、やることに追加して」→「やることとして開く」→ 件名・期限を直せる小さな確認欄 →「書類・やることに入れる」で `docs-tracker.v1` に 1 件（既存の項目とメモは残る）
  - JSON にならない答え →「下書きを作れませんでした。登録画面を空で開きますか？」
  - 壁打ちで「📎 資料を選ぶ」→ 4,000 字の架空の書類 → 「資料が長いため先頭 3,000 字だけ渡しています」、渡った `instructions` の資料部分が 3,000 字
  - 最初の送信で履歴に会話 1 件（題名＝質問の先頭 30 字・`mode`・`sourceId`）。にせ AI の答えを遅らせ、その間に「新しい会話」を押しても、答えは元の会話に追記される
  - 資料を消したあと会話を開く →「削除された資料」
  - 「続きから話す」で同じ会話に追記される
  - にせ AI が `refused` →「答えを作れませんでした。言い方を変えてみてください」、入力欄の文字と会話は消えない
  - 答えに `<script>alert(1)</script>` → 文字として表示、`alert` は呼ばれない
- [ ] **Step 2:** テスト → FAIL
- [ ] **Step 3:** 画面を書く。秘書の流れ: `Secretary.range` → `lines`（予定・`CalendarRead` で読んだ予定・`docs-tracker.v1` の期限付き項目）→ `wantsFree` なら `freeSlots` を添える → `wantsDraft` なら `draftInstructions` で別に 1 回聞き `checkDraft` → `AIChat.ask`。音声は `SpeechMemo` の既存の使い方に合わせる
- [ ] **Step 4:** 新旧すべてのテスト → PASS（`for f in apps/tests/*.test.mjs; do node "$f" || echo "NG $f"; done`）
- [ ] **Step 5: コミット** `feat: 予定アプリに端末内 AI の秘書・壁打ち・ブレストを足し、予定とやることの下書きを作れるようにする`

### Task 7（Claude）: iPhone への転送と実機確認

- [ ] **Step 1:** `cd mobile && npm run iphone`（WiFi で届かなければポケット WiFi の再起動、だめなら USB）。トップ画面下の版表記「版 日時（コミット番号）」を控える
- [ ] **Step 2:** 利用者に実機で確かめてもらう項目を送る
  - AI タブの状態表示（Apple Intelligence のオン・オフ）
  - 秘書: 「今日の予定は？」「来週の空きは？」「来週火曜10時に打合せを入れて」「金曜までに資料提出をやることに追加して」
  - 壁打ち・ブレスト（資料あり・なし）、長い資料での表示
  - 手書きメモ（撮る・写真から）と直して保存
  - 書類の読み取り後に履歴へ入ること、検索・削除
  - 機内モードでも AI が答えること
- [ ] **Step 3:** 指摘を直したら PR を作る（`superpowers:finishing-a-development-branch`）
