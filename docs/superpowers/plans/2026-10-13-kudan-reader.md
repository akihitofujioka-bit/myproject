# 件の読み取り機能の移植（計画 2-3）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 件の 4 機能（Word・Excel・PDF の読み込み、連絡先、提案、やること候補）を壱師に移し、「書類・やること」に自由メモ（文字・端末内の音声）を足す。

**Architecture:** 予定の判断はすべて Web 側の小さな部品（`apps/shared/*.js`、通信なし、ブラウザなしでテストできる）で行う。iPhone 側（Swift）はファイルから「文字の行」と「表」を取り出す DocumentReader と、端末内だけで音声を文字にする SpeechMemo の 2 つだけを受け持つ。画面は今の予定アプリの確認欄（`#meetingConfirm`）と書類トラッカーに足す。

**設計書からの細かい変更:** 設計書では「複数件のときは手帳の読み取りと同じ画面」としたが、今の会議の確認欄（`#meetingConfirm`）がすでに 1 件ごとのチェックとまとめての登録に対応しているため、1 件も複数件もこの欄を使う（見た目と操作は設計書どおり）。

**Tech Stack:** 素の JavaScript（ES5 風の `(function (global) { … })`）、Capacitor 8、Swift（PDFKit・Vision・Speech・Compression）、Node のテスト（`node:assert` か自前の `ok()`）、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-13-kudan-reader-design.md`

## Global Constraints

- 端末の外にデータを送らない。`fetch`・`XMLHttpRequest`・外部 URL への読み込みを足さない
- 音声認識は `requiresOnDeviceRecognition = true` を必ず付ける。端末内で使えなければ「この端末では使えません」と出し、サーバーでの認識に切り替えない。録音データは保存しない
- 読み込んだファイルは保存しない。共有で届いたファイルのコピーは読み終えたら消す
- 取り出した予定・やることは、必ず人が確認画面で確かめてから登録する
- アプリ名は「書類・やること」（`short_name` も「書類・やること」）。フォルダ名 `docs-tracker` と保存の鍵 `docs-tracker.v1`・`schedule.v1` は変えない
- 今の保存データを壊さない: `memos`・`dismissedHints`・`scheduleId` が無いデータもそのまま読め、保存し直しても他の項目が消えない
- 画面の文言・コメントは日本語。テストと見本のデータは架空の名前・番号だけ（電話は `03-0000-0000` のような番号、メールは `@example.jp`）
- 移動時間不足のしきい値は 15 分。「気づいたこと」の範囲は今日から 30 日
- やること候補の語: 「持参」「資料」「提出」「締切」「締め切り」「期限」「用意」「準備」「持ち物」「必要」
- Xcode プロジェクトは objectVersion 60（同期グループではない）。新しい Swift ファイルは `project.pbxproj` に手で足す（`CalendarReaderPlugin.swift` の 4 か所と同じ形）
- 新しい `apps/shared/*.js` を使うページは、`<script src>` と、そのアプリの `sw.js` の読み込み一覧の両方に足す
- Codex に頼むときは「作業フォルダの外を読まない・ネット禁止・commit 禁止・架空の名前だけ」を依頼文に書く。`xcodebuild` と iPhone への転送は Claude が行う

## Review Focus

1. **保存し直しで新しい項目が消える** — 書類トラッカーの `load()` は `{ v, calIds, items }` だけを返し、予定アプリの `load()` も `{ version, items, calIds }` だけを返す。`memos`・`dismissedHints` を足し忘れると、何か 1 件保存しただけでメモや消した指摘が消える。Task 5・Task 8 のテストで「メモ／消した指摘を入れた状態で別の項目を保存しても残る」を確かめる
2. **別アプリからの書き込みで書類のデータを壊す** — 予定アプリから `docs-tracker.v1` にやることを足すとき、読めないデータ（壊れた JSON）を空で上書きしない。Task 3 のテストで「壊れた JSON のときは書かずに `{ ok: false }`」を確かめる
3. **年の無い日付が去年になる・1 月の予定表が今年になる** — 「1/15」を 12 月に読むと翌年にする。Task 4 のテストで、今日 2026-12-10 に「1/15」→ `2027-01-15` を確かめる
4. **終日の予定や時刻の無い予定で、重複の誤検出が出る** — Task 2 のテストで、時刻の無い予定どうしは重複にしないことを確かめる
5. **同じファイルを 2 回共有すると、前のファイルが残る・2 回読まれる** — `takeShared()` は取り出したら消す。Task 10 のテストで、偽の DocumentReader の `takeShared()` を 2 回呼んで 2 回目が `null` になることを確かめる

---

## ファイルの構成

| ファイル | 種類 | 役割 |
|---|---|---|
| `apps/shared/contacts.js` | 新規 | 電話・メール・URL の取り出し、メモの 1 行、押せるリンクの HTML |
| `apps/shared/suggest.js` | 新規 | 重複・移動時間不足・曜日の食い違い |
| `apps/shared/todos.js` | 新規 | やること候補の検出と `docs-tracker.v1` への追加 |
| `apps/shared/scheduletable.js` | 新規 | 表から予定を複数取り出す |
| `apps/shared/documentreader.js` | 新規 | DocumentReader（Swift）の呼び出し口、結果から予定の一覧を作る、共有ファイルの案内 |
| `apps/shared/speechmemo.js` | 新規 | SpeechMemo（Swift）の呼び出し口 |
| `apps/shared/scanrouter.js` | 変更 | 受け渡しの種類に `memo` を足す |
| `apps/docs-tracker/index.html` | 変更 | 名前、種別「やること」、`memos` の保存、メモのタブ、音声ボタン |
| `apps/schedule/index.html` | 変更 | ファイルから読む、注意・連絡先・やること候補、気づいたこと、メモのリンク、`dismissedHints` |
| `apps/index.html`・`apps/README.md`・`apps/docs-tracker/manifest.webmanifest` | 変更 | 名前を「書類・やること」に |
| `mobile/ios/App/App/DocumentText/DocumentText.swift` | 新規 | docx・xlsx・pdf から行と表を取り出す（UIKit に依存しない） |
| `mobile/ios/App/App/DocumentText/ZipReader.swift` | 新規 | 件の `ZipReader.swift` を移す |
| `mobile/ios/App/App/DocumentReaderPlugin.swift` | 新規 | ファイル選択、共有の受け取り、スキャン PDF の文字認識 |
| `mobile/ios/App/App/SpeechMemoPlugin.swift` | 新規 | 端末内の音声認識 |
| `mobile/ios/App/App/ViewController.swift`・`SceneDelegate.swift`・`Info.plist`・`App.xcodeproj/project.pbxproj` | 変更 | 登録、共有で届いたファイルの受け取り、書類の種類と許可の文 |
| `mobile/ios/DocumentTextCheck/main.swift` | 新規 | Mac 上で DocumentText を見本ファイルで確かめる小さな実行ファイル |
| `apps/tests/tools/make-doc-fixtures.mjs` | 新規 | 見本の docx・xlsx・pdf を作る |
| `apps/tests/fixtures/doc-*.docx|xlsx|pdf` | 新規 | 見本（架空の内容） |
| `apps/tests/contacts|suggest|todos|scheduletable.test.mjs` | 新規 | 部品のテスト（ブラウザ不要） |
| `apps/tests/docstodo.test.mjs`・`apps/tests/schedulereader.test.mjs` | 新規 | 画面のテスト（Playwright） |

---

### Task 1: 連絡先の取り出し（`contacts.js`）

**Files:**
- Create: `apps/shared/contacts.js`
- Test: `apps/tests/contacts.test.mjs`

**Interfaces:**
- Produces: `window.Contacts.find(text: string) -> { phones: string[], emails: string[], urls: string[] }`
- Produces: `window.Contacts.noteLine(found) -> string`（何も無ければ `""`）
- Produces: `window.Contacts.linkify(text: string) -> string`（HTML。`& < > "` をエスケープしたうえで、電話を `<a href="tel:数字だけ">`、メールを `<a href="mailto:…">` にする。改行は `<br>`）

- [ ] **Step 1: 失敗するテストを書く**（`meeting.test.mjs` と同じく `new Function("window", src)(g)` で読み込む）

```js
const f = C.find("問い合わせ先 総務課 電話 ０３－００００－００００（内線 123）\nmail: kakuu@example.jp 詳細 https://example.jp/a\n再掲 03-0000-0000");
ok(JSON.stringify(f.phones) === JSON.stringify(["03-0000-0000", "内線 123"]), "全角を直し、重複を除き、出た順");
ok(JSON.stringify(f.emails) === JSON.stringify(["kakuu@example.jp"]), "メール");
ok(JSON.stringify(f.urls) === JSON.stringify(["https://example.jp/a"]), "URL");
ok(C.find("090-0000-0000 と 0300000000").phones.length === 2, "携帯と区切り無し");
ok(C.find("令和8年10月22日 13:30").phones.length === 0, "日付・時刻を電話と取り違えない");
ok(C.noteLine(f) === "問い合わせ: 電話 03-0000-0000 / 内線 123 / メール kakuu@example.jp", "メモの 1 行（URL は入れない）");
ok(C.noteLine(C.find("なし")) === "", "無ければ空");
ok(C.linkify("電話 03-0000-0000 <b>") === '電話 <a href="tel:0300000000">03-0000-0000</a> &lt;b&gt;', "電話のリンクとエスケープ");
ok(C.linkify("a@example.jp\nb").includes('<a href="mailto:a@example.jp">a@example.jp</a><br>b'), "メールのリンクと改行");
```

- [ ] **Step 2: 実行して失敗を確かめる** — `node apps/tests/contacts.test.mjs` → `contacts.js` が無いので失敗
- [ ] **Step 3: `contacts.js` を書く** — 先に全角の数字・ハイフン（`－ ‐ ー`）を半角に直す。電話は `0\d{1,4}-\d{1,4}-\d{3,4}` と区切り無しの `0\d{9,10}`（前後が数字でないこと）と `内線\s*\d{2,5}`（表記は「内線 123」にそろえる）
- [ ] **Step 4: 実行して通ることを確かめる** — 同じコマンド → 最後に `すべて成功`（他のテストと同じ締めの表示）
- [ ] **Step 5: コミット** — `git add apps/shared/contacts.js apps/tests/contacts.test.mjs && git commit -m "feat: 通知から電話・メールを取り出す部品を足す"`

### Task 2: 提案（`suggest.js`）

**Files:**
- Create: `apps/shared/suggest.js`
- Test: `apps/tests/suggest.test.mjs`

**Interfaces:**
- 予定の形（呼び出し側が作る）: `{ id: string, title: string, date: "YYYY-MM-DD", start: "HH:MM"|"", end: "HH:MM"|"", place: string, rawText?: string }`。`start` が空なら終日・時刻なしとみなす。`end` が空なら `start` の 60 分後とみなす
- 指摘の形: `{ type: "overlap"|"travel"|"weekday", key: string, itemId: string, otherId: string, message: string }`
- Produces: `window.Suggest.check(newItems, existingItems) -> Hint[]`（確認画面用。新しい予定ごとに、既存の予定・他の新しい予定との重複／移動時間不足と、`rawText` の曜日の食い違いを返す）
- Produces: `window.Suggest.upcoming(items, today: "YYYY-MM-DD", days = 30) -> Hint[]`（一覧用。期間内の予定どうしの重複・移動時間不足。曜日は見ない）
- Produces: `window.Suggest.TRAVEL_MINUTES === 15`
- 鍵の作り方: `type + ":" + [a.id + "@" + a.date + "T" + a.start, b.id + "@" + b.date + "T" + b.start].sort().join("|")`（曜日は `"weekday:" + id + "@" + date`）。日時が変われば鍵も変わる

- [ ] **Step 1: 失敗するテストを書く**

```js
const a = { id: "a", title: "架空の委員会", date: "2026-10-22", start: "10:00", end: "11:00", place: "第1会議室" };
const b = { id: "b", title: "架空の打合せ", date: "2026-10-22", start: "10:30", end: "", place: "第1会議室" };
const c = { id: "c", title: "架空の視察", date: "2026-10-22", start: "11:10", end: "12:00", place: "架空市民会館" };
const h = S.check([b], [a]);
ok(h.length === 1 && h[0].type === "overlap" && h[0].message === "10:00 の「架空の委員会」と重なります", "重複");
const t = S.check([c], [a]);
ok(t.length === 1 && t[0].type === "travel" && t[0].message === "前の予定（架空の委員会、第1会議室）から 10 分しかありません", "移動時間不足");
ok(S.check([{ ...c, start: "11:15" }], [a]).length === 0, "15 分ちょうどなら出さない");
ok(S.check([{ ...c, place: "第1会議室" }], [a]).length === 0, "同じ場所なら移動時間は見ない");
ok(S.check([{ ...a, id: "x", start: "", end: "" }], [{ ...b, start: "", end: "" }]).length === 0, "時刻なしどうしは重複にしない");
const w = S.check([{ id: "w", title: "架空の会", date: "2026-10-15", start: "", end: "", place: "", rawText: "日時 10月15日（水）午後" }], []);
ok(w.length === 1 && w[0].type === "weekday" && w[0].message === "10/15 は木曜ですが、通知には水曜とあります", "曜日の食い違い（2026-10-15 は木曜）");
ok(S.check([{ id: "w2", title: "架空", date: "2026-10-15", start: "", end: "", place: "", rawText: "10/15(木)" }], []).length === 0, "合っていれば出さない");
const u = S.upcoming([a, b, { ...b, id: "old", date: "2026-10-01" }, { ...b, id: "far", date: "2026-12-01" }], "2026-10-13");
ok(u.length === 1 && u[0].key === "overlap:a@2026-10-22T10:00|b@2026-10-22T10:30", "一覧は 30 日の中だけ・鍵の形");
ok(S.upcoming([a, { ...b, start: "10:45" }], "2026-10-13")[0].key !== u[0].key, "時刻が変われば鍵も変わる");
```

- [ ] **Step 2: 実行して失敗を確かめる** — `node apps/tests/suggest.test.mjs`
- [ ] **Step 3: `suggest.js` を書く** — 同じ日の予定を開始順に並べて比べる。移動時間は「前の予定の終了〜次の開始」が 0 以上 15 未満で、場所が両方あり、違うとき。曜日は `rawText` から `M月D日(曜)` と `M/D(曜)`（全角括弧も）を探し、`date` の月日と同じものだけ比べる
- [ ] **Step 4: 実行して通ることを確かめる**
- [ ] **Step 5: コミット** — `feat: 予定の重複・移動時間不足・曜日の食い違いを見つける部品を足す`

### Task 3: やること候補と書類トラッカーへの追加（`todos.js`）

**Files:**
- Create: `apps/shared/todos.js`
- Test: `apps/tests/todos.test.mjs`

**Interfaces:**
- Produces: `window.Todos.KEYWORDS`（Global Constraints の 10 語）
- Produces: `window.Todos.candidates(text: string, eventDate: "YYYY-MM-DD"|"", today: "YYYY-MM-DD") -> [{ title: string, dueOn: "YYYY-MM-DD"|"" }]` — 句点・改行で区切った文のうち語を含むものを候補に。`title` は前後の空白と「・」「※」を除き 40 字まで。期限は `M/D` か `M月D日` の後に（曜日の括弧を挟んで）「まで」が続くものを、`today` 以降で一番近い年にする。無ければ `eventDate`
- Produces: `window.Todos.add(storage, list: [{ title, dueOn, scheduleId, scheduleTitle, scheduleDate }]) -> { ok: boolean, added: number }` — `storage.getItem("docs-tracker.v1")` を読み、`items` に `{ id, title, kind: "やること", dest: "", dueOn, status: "未着手", priority: "中", note: "予定: " + scheduleTitle + "（M/D）", createdAt, doneAt: "", icsSeq: 0, planKey: "", scheduleId }` を足して書き戻す。他の鍵（`memos`・`calIds` など）はそのまま残す。データが無ければ `{ v: 1, items: [], calIds: {} }` から始める。JSON が壊れていれば書かずに `{ ok: false, added: 0 }`

- [ ] **Step 1: 失敗するテストを書く**

```js
const list = T.candidates("1 日時 10月22日（木）\n2 当日は資料を持参してください。\n3 出欠を10/20（火）までに提出", "2026-10-22", "2026-10-13");
ok(list.length === 2, "2 件（1 つの通知から複数出す）");
ok(list[0].title === "2 当日は資料を持参してください" && list[0].dueOn === "2026-10-22", "期限が無ければ予定の日");
ok(list[1].title === "3 出欠を10/20（火）までに提出" && list[1].dueOn === "2026-10-20", "「まで」の日を期限に");
ok(T.candidates("1/15までに提出", "", "2026-12-10")[0].dueOn === "2027-01-15", "年をまたぐ");
ok(T.candidates("日時 10月22日", "2026-10-22", "2026-10-13").length === 0, "語が無ければ空");
const mem = () => { const m = {}; return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, m }; };
const s = mem(); s.setItem("docs-tracker.v1", JSON.stringify({ v: 1, items: [{ id: "x", title: "架空の申請書", kind: "申請" }], calIds: { a: "b" }, memos: [{ id: "m1", text: "架空のメモ" }] }));
const r = T.add(s, [{ title: "資料を持参", dueOn: "2026-10-22", scheduleId: "s1", scheduleTitle: "架空の委員会", scheduleDate: "2026-10-22" }]);
const d = JSON.parse(s.getItem("docs-tracker.v1"));
ok(r.ok && r.added === 1 && d.items.length === 2, "足すだけ");
ok(d.items[1].kind === "やること" && d.items[1].note === "予定: 架空の委員会（10/22）" && d.items[1].scheduleId === "s1", "やることの形");
ok(d.memos.length === 1 && d.calIds.a === "b", "他の項目を消さない");
const bad = mem(); bad.setItem("docs-tracker.v1", "{壊れた");
ok(T.add(bad, [{ title: "x", dueOn: "", scheduleId: "", scheduleTitle: "", scheduleDate: "" }]).ok === false && bad.getItem("docs-tracker.v1") === "{壊れた", "壊れたデータは上書きしない");
```

- [ ] **Step 2: 実行して失敗を確かめる** — `node apps/tests/todos.test.mjs`
- [ ] **Step 3: `todos.js` を書く**（`inbox.js` の「読めないときは書かない・足すだけ」に合わせる）
- [ ] **Step 4: 実行して通ることを確かめる**
- [ ] **Step 5: コミット** — `feat: 通知からやること候補を見つけ、書類トラッカーへ足す部品を足す`

### Task 4: 表からの予定の取り出し（`scheduletable.js`）

**Files:**
- Create: `apps/shared/scheduletable.js`
- Test: `apps/tests/scheduletable.test.mjs`

**Interfaces:**
- 入力の表: `tables: string[][][]`（表 → 行 → セルの文字）。DocumentReader（Task 9）が作る形と同じ
- Produces: `window.ScheduleTable.isSchedule(tables) -> boolean`（どれかの表に日付が読める行が 2 行以上）
- Produces: `window.ScheduleTable.parse(tables, today: "YYYY-MM-DD") -> Meeting[]` — `Meeting` は `Meeting.parse` と同じ形 `{ title, date, dateConfidence: null, startTime, endTime, place, social: { has: false, fee: null }, rows: [その行のセルを " " でつないだ文字], source: "file" }`
- 見出しの語: 日付＝「日付」「月日」「日」「開催日」、時刻＝「時間」「時刻」「開始」、件名＝「行事」「件名」「内容」「会議名」「名称」、場所＝「場所」「会場」。見出しが無ければ、日付の読めるセルが一番多い列を日付、残りの一番長い文字の列を件名にする
- 読める日付: `YYYY-MM-DD`、`YYYY/M/D`、`M/D`、`M月D日`（曜日の括弧つきも）。年が無ければ `today` 以降で一番近い年。時刻は `H:MM`（`〜` で終了も）と `H時MM分`／`H時`

- [ ] **Step 1: 失敗するテストを書く**

```js
const t1 = [[["月日", "曜", "行事", "時間", "会場"], ["10月22日", "木", "架空の定例会", "10:00〜12:00", "議場"], ["10/28", "水", "架空の研修", "13時30分", "第1会議室"], ["", "", "（備考）", "", ""]]];
ok(TB.isSchedule(t1) === true, "日付の行が 2 行で予定表");
const m = TB.parse(t1, "2026-10-13");
ok(m.length === 2 && m[0].title === "架空の定例会" && m[0].date === "2026-10-22" && m[0].startTime === "10:00" && m[0].endTime === "12:00" && m[0].place === "議場", "1 行目");
ok(m[1].date === "2026-10-28" && m[1].startTime === "13:30" && m[1].source === "file", "2 行目");
ok(TB.parse([[["2026-01-15", "架空の新年会"], ["2026-01-20", "架空の会議"]]], "2026-10-13")[0].title === "架空の新年会", "見出しなし・Excel の日付");
ok(TB.parse([[["日付", "内容"], ["1/15", "架空の会"], ["1/16", "架空の会2"]]], "2026-12-10")[0].date === "2027-01-15", "年をまたぐ");
ok(TB.isSchedule([[["日時", "10月22日 10:00"], ["場所", "議場"]]]) === false, "開催通知の 2 列の表は予定表ではない");
```

- [ ] **Step 2: 実行して失敗を確かめる** — `node apps/tests/scheduletable.test.mjs`
- [ ] **Step 3: `scheduletable.js` を書く**（日付の読み取りは `meeting.js` の `Meeting.normalize` を使ってよいが、`meeting.js` が無くても動くよう自前で全角→半角をする）

  最後のテストのため、2 列の表で 1 列目が見出しの語（「日時」「場所」など）の並びのときは予定表とみなさない。
- [ ] **Step 4: 実行して通ることを確かめる**
- [ ] **Step 5: コミット** — `feat: 行事予定表から予定を複数取り出す部品を足す`

### Task 5: 「書類・やること」への名前変更と種別「やること」

**Files:**
- Modify: `apps/docs-tracker/index.html`（`<title>`・見出し・説明、種別の `<select id="f-kind">`、`load()`／`normalize`（440〜466 行あたり）、`save()`）
- Modify: `apps/docs-tracker/manifest.webmanifest`、`apps/index.html:93-94`、`apps/README.md`（表の行と本文の「書類・回覧トラッカー」）
- Test: `apps/tests/docstodo.test.mjs`（新規、Playwright。`schedulecalendar.test.mjs` と同じ起動の仕方）

**Interfaces:**
- Produces: `docs-tracker.v1` の形 `{ v: 1, items: [...], calIds: {...}, memos: Memo[] }`。項目に `scheduleId: string`（無ければ `""`）。`Memo = { id, text, createdAt, updatedAt, movedTo: ("schedule"|"todo")[] }`
- 名前: 題名・見出し「書類・やること」、説明「提出期限のある書類・回覧・申請と、やることを管理します。」、manifest の `name`・`short_name` とも「書類・やること」

- [ ] **Step 1: 失敗するテストを書く**（`docstodo.test.mjs`）
  - 題名が「書類・やること」、トップ画面（`apps/index.html`）のアプリ名も「書類・やること」
  - 種別の選択肢に「やること」がある
  - `localStorage` に `memos: [{ id: "m1", text: "架空のメモ", createdAt: "2026-10-13T00:00:00Z", updatedAt: "2026-10-13T00:00:00Z", movedTo: [] }]` と `scheduleId: "s1"` 付きの項目を入れて開き、新しい書類を 1 件登録したあと、`memos` が 1 件残り、`scheduleId` も残る（Review Focus 1）
  - 種別「やること」の項目が一覧に出て、件数（未処理）に数えられる
- [ ] **Step 2: 実行して失敗を確かめる** — `NODE_PATH=… CHROMIUM_PATH=… node apps/tests/docstodo.test.mjs`
- [ ] **Step 3: 直す** — `load()` で `memos` を（配列でなければ `[]`、各要素の欠けた値を埋めて）読み、`save()` で書く。項目の正規化に `scheduleId: it.scheduleId || ""` を足す。名前を 4 つのファイルで変える
- [ ] **Step 4: 実行して通ることを確かめる**。あわせて `node apps/tests/watch.test.mjs`・`pwa.test.mjs` が通ること（Watch の期限一覧に種別「やること」も出るのは今の仕組みのまま）
- [ ] **Step 5: コミット** — `feat: 書類・回覧トラッカーを「書類・やること」にし、種別「やること」を足す`

### Task 6: メモのタブ（文字）と、予定・やることへの移動

**Files:**
- Modify: `apps/docs-tracker/index.html`（切り替え「書類・やること｜メモ」、メモの入力欄・一覧、`meeting.js`・`todos.js`・`scanrouter.js` の読み込み）、`apps/docs-tracker/sw.js`
- Modify: `apps/shared/scanrouter.js`（`DEST` に `memo: "schedule/index.html"`）、`apps/tests/scanrouter.test.mjs`
- Modify: `apps/schedule/index.html`（`takeHandoff("memo")` を受け取る）
- Test: `apps/tests/docstodo.test.mjs` に足す

**Interfaces:**
- Consumes: `Meeting.findDate(text)`（`null` でなければ日付あり）、`Todos.candidates`（Task 3）、`ScanRouter.handoff("memo", lines: string[])`
- 予定アプリ側: `ScanRouter.takeHandoff("memo")` で `string[]` を受け取り、`Meeting.parse(lines, {})` の結果に `source: "memo"` を付けて `renderMeetings` に渡す（`Receipt.rowsFromLines` は通さない。メモは文字の行なので）。`meetingNote` の出どころの行は `source === "memo"` のとき「（メモから登録）」
- 「やることにする」: 書類の入力欄に、件名＝メモの 1 行目（40 字まで）、種別＝やること、期限＝`Todos.candidates(text, "", today)` の最初の `dueOn`（無ければ空）、メモ＝本文を入れ、入力欄へ移る。登録されたらそのメモの `movedTo` に `"todo"` を足す
- 「予定に入れる」: `ScanRouter.handoff("memo", text.split("\n"))` の後、`schedule/index.html` へのリンクを利用者が押して移る（`deeplink.js` と同じ理由で、プログラムからは移動しない）。押した時点で `movedTo` に `"schedule"` を足す

- [ ] **Step 1: 失敗するテストを書く**
  - メモのタブで「10月22日 14時から 架空の打合せ 第2会議室」と書いて保存 → 一覧の先頭に出て、「予定に入れる」「やることにする」が出る
  - 日付も「まで」も無いメモ（「架空の思いつき」）にはボタンが出ない
  - 「予定に入れる」を押すと `sessionStorage.pendingScan` が `type: "memo"` になり、予定アプリを開くと確認欄に 1 件、日付 `2026-10-22`（年は今日から決まる値を比べる）が出る
  - 「やることにする」で入力欄が埋まり、登録するとメモに「やることにした」の印が出る
  - メモの編集・削除（削除は確認つき）
  - `scanrouter.test.mjs`: `destinationFor("memo") === "schedule/index.html"`
- [ ] **Step 2: 実行して失敗を確かめる**
- [ ] **Step 3: 作る**
- [ ] **Step 4: 実行して通ることを確かめる**（`docstodo`・`scanrouter`・`schedule`・`pwa`）
- [ ] **Step 5: コミット** — `feat: 書類・やることにメモのタブを足し、予定・やることへ移せるようにする`

### Task 7: 確認画面の注意・連絡先・やること候補

**Files:**
- Modify: `apps/schedule/index.html`（`renderMeetings`・`collectMeetings`・`meetingItems`・`meetingNote`・`registerMeetingMode`、`contacts.js`・`suggest.js`・`todos.js` の読み込み）、`apps/schedule/sw.js`
- Test: `apps/tests/schedulereader.test.mjs`（新規、Playwright）

**Interfaces:**
- Consumes: `Contacts.find/noteLine`（Task 1）、`Suggest.check`（Task 2）、`Todos.candidates/add`（Task 3）
- 予定 → 提案の形への変換 `toSuggestItem(item)`: `{ id: item.id, title: item.title, date: item.dueOn, start: timeOf(item), end: endTimeOfItem(item), place: item.dest, rawText: "" }`。確認画面の予定は `{ id: "scan-" + index, title, date, start: startTime, end: endTime, place, rawText: meeting.rows.join("\n") }`。既存は `allItems()`（壱師の予定＋カレンダーの予定）
- 各 `.scan-result` の下に、見つかったものだけ:
  - `<ul class="scan-hints">`（⚠️ と `message`）
  - `<label class="check"><input type="checkbox" class="m-contact" checked> ☎️ <span>` + `noteLine` + `</span></label>`。チェックが付いていれば、`meetingNote` の最後の行（出どころ）の前にその 1 行を入れる
  - やること候補ごとに `<label class="check"><input type="checkbox" class="m-todo" data-title=… data-due=… checked> ✅ 件名（期限 M/D）</label>`
- 登録（`registerMeetingMode` の app と calendar の両方）で、チェックの付いたやることを `Todos.add(localStorage, …)` へ。`scheduleId` は登録した予定の `id`。成功したら知らせの文に「やること N 件を書類・やることに入れました」を足す。`ok: false` なら「やることを入れられませんでした（書類・やることのデータが読めません）」

- [ ] **Step 1: 失敗するテストを書く** — 偽のカレンダー（`schedulecalendar.test.mjs` と同じ作り）に 2026-10-22 10:00〜11:00「架空の委員会」を置き、予定アプリで `applyMeetingScan` の代わりに `renderMeetings([...])` を `page.evaluate` で呼ぶ（`rows` に「当日は資料を持参」「出欠を10/20までに提出」「電話 03-0000-0000」「10月22日（水）」を含める）
  - 注意に「10:00 の「架空の委員会」と重なります」と「10/22 は木曜ですが、通知には水曜とあります」が出る
  - 連絡先の行に「問い合わせ: 電話 03-0000-0000」が出る
  - やること候補が 2 件、チェック付きで出る
  - 1 件の候補のチェックを外して「アプリに登録」→ 予定のメモに「問い合わせ: 電話 03-0000-0000」が入り、`docs-tracker.v1` に種別「やること」が 1 件だけ増える
- [ ] **Step 2: 実行して失敗を確かめる** — `node apps/tests/schedulereader.test.mjs`（`NODE_PATH`・`CHROMIUM_PATH` 付き）
- [ ] **Step 3: 作る**
- [ ] **Step 4: 実行して通ることを確かめる**（`schedulereader`・`schedule`・`schedulecalendar`・`meeting`・`pwa`）
- [ ] **Step 5: コミット** — `feat: 読み取りの確認画面に、注意・連絡先・やること候補を出す`

### Task 8: 予定一覧の「気づいたこと」とメモのリンク

**Files:**
- Modify: `apps/schedule/index.html`（一覧の上に `<section class="card" id="hintsCard" hidden>`、`load()`／`save()` に `dismissedHints`、予定の詳細のメモ表示）
- Test: `apps/tests/schedulereader.test.mjs` に足す

**Interfaces:**
- Consumes: `Suggest.upcoming(allItems().map(toSuggestItem), today)`（Task 2・7）、`Contacts.linkify`（Task 1）
- `schedule.v1` の形に `dismissedHints: string[]`（無ければ `[]`）
- 「気づいたこと」は `render()` のたびに作り直し、`dismissedHints` に鍵があるものは出さない。1 件も無ければ `hidden`。各行に「この指摘を消す」（`data-key`）
- 予定の詳細でメモを出している箇所を `Contacts.linkify(cleanNote(item))` にする（今 `esc()` している所の置き換え）

- [ ] **Step 1: 失敗するテストを書く**
  - 壱師の予定 2 件（今日から 5 日後の 10:00〜11:00 と 10:30〜）→「気づいたこと」に 1 件
  - 「この指摘を消す」で消え、開き直しても出ない。別の予定を 1 件登録して保存しても `dismissedHints` が残る（Review Focus 1）
  - 片方の時刻を 10:45 に変えると再び出る
  - 31 日後の重なりは出ない
  - メモに `03-0000-0000` のある予定の詳細に `a[href="tel:0300000000"]` がある
- [ ] **Step 2: 実行して失敗を確かめる**
- [ ] **Step 3: 作る**
- [ ] **Step 4: 実行して通ることを確かめる**（`schedulereader`・`schedule`・`schedulecalendar`・`schedulemove`）
- [ ] **Step 5: コミット** — `feat: 予定一覧に「気づいたこと」を出し、メモの電話・メールを押せるようにする`

### Task 9: ファイルから文字と表を取り出す（Swift、Mac で確かめる）

**Files:**
- Create: `apps/tests/tools/make-doc-fixtures.mjs`、`apps/tests/fixtures/doc-meeting.docx`・`doc-table.docx`・`doc-table.xlsx`・`doc-text.pdf`・`doc-scan.pdf`
- Create: `mobile/ios/App/App/DocumentText/ZipReader.swift`（`~/ScheduleReaderApp/ScheduleReader/Services/DocumentService/ZipReader.swift` を移す）、`mobile/ios/App/App/DocumentText/DocumentText.swift`
- Create: `mobile/ios/DocumentTextCheck/main.swift`
- Modify: `mobile/ios/App/App.xcodeproj/project.pbxproj`（新しい 2 ファイルを App ターゲットに）

**Interfaces:**
- Produces（Swift、`import Foundation`・`PDFKit`・`Compression` だけ。UIKit を使わない）:
  - `struct DocumentContent { let kind: String; let lines: [String]; let tables: [[[String]]]; var needsOCR: Bool }`
  - `enum DocumentText { static func read(url: URL) throws -> DocumentContent }` — 拡張子で振り分け。`kind` は `"docx"|"xlsx"|"pdf"`
  - `enum DocumentTextError: LocalizedError { case unsupported, broken, locked, empty }`。`errorDescription` はそれぞれ「この形式は読めません（.docx・.xlsx・.pdf だけ読めます）」「ファイルが壊れているため読めませんでした」「パスワードが付いているため読めませんでした」「文字が見つかりませんでした」
  - docx: `word/document.xml` の `w:p` ごとに 1 行（表の中の段落も行に入れる）。`w:tbl` → `w:tr` → `w:tc` の文字を表に
  - xlsx: `xl/sharedStrings.xml` と `xl/worksheets/sheet*.xml`。シートごとに 1 表。空の行は飛ばす。セルの位置（`r="C3"`）に合わせて空のセルを埋める。日付の書式のセル（`s` 属性の書式が日付。`xl/styles.xml` の `numFmtId` 14〜22 か、独自書式に `y`・`m`・`d` を含むもの）のシリアル値は `YYYY-MM-DD` にする。`lines` は各行のセルを " " でつないだもの
  - pdf: `PDFDocument(url:)` が `nil` なら `broken`、`isLocked` なら `locked`。各ページの `string` を行に分ける。全ページで空白以外の文字が無ければ `needsOCR = true`（`lines` は空、エラーにしない）
  - `.doc`・`.xls` など他の拡張子は `unsupported`
- 見本の中身（架空）: 会議通知 docx「架空市 第3回 架空検討委員会の開催について／日時 令和8年10月22日（木）午後1時30分から／場所 架空市役所 第1会議室／当日は資料を持参してください。／出欠を10月20日（火）までに提出してください。／問い合わせ 架空課 電話 03-0000-0000」。予定表 docx・xlsx は Task 4 のテストの `t1` と同じ 3 行（xlsx の日付列は Excel の日付セル）。`doc-text.pdf` は会議通知と同じ文を HTML から Playwright の `page.pdf()` で、`doc-scan.pdf` は同じ文の画面写真を `<img>` だけの HTML にして `page.pdf()` で作る（文字の層が無い PDF）

- [ ] **Step 1: 見本を作る** — `make-doc-fixtures.mjs` は Node の `zlib.deflateRawSync` で最小の ZIP（docx・xlsx）を自前で書き、PDF は Playwright で作る。実行: `NODE_PATH=… CHROMIUM_PATH=… node apps/tests/tools/make-doc-fixtures.mjs` → 5 ファイルができる
- [ ] **Step 2: 失敗する確認を書く** — `main.swift` は 5 つの見本と存在しない拡張子（`doc-x.doc` を一時的に作る）を読み、次を確かめて `PASS`／`FAIL` を出し、1 つでも失敗なら終了コード 1
  - `doc-meeting.docx`: `lines` に「場所 架空市役所 第1会議室」がある
  - `doc-table.docx`・`doc-table.xlsx`: `tables[0].count == 4`、`tables[0][1] == ["10月22日","木","架空の定例会","10:00〜12:00","議場"]`（xlsx は日付列が `"2026-10-22"`）
  - `doc-text.pdf`: `needsOCR == false` で、`lines.joined()` に「架空検討委員会」がある
  - `doc-scan.pdf`: `needsOCR == true`
  - `.doc`: `DocumentTextError.unsupported`
- [ ] **Step 3: 実行して失敗を確かめる** — `swiftc -o $TMPDIR/doccheck mobile/ios/App/App/DocumentText/*.swift mobile/ios/DocumentTextCheck/main.swift && $TMPDIR/doccheck apps/tests/fixtures` → `DocumentText.swift` が無いのでコンパイルが止まる
- [ ] **Step 4: `DocumentText.swift` を書き、`ZipReader.swift` を移す**（件の `DocumentTextExtractor` の docx・xlsx・PDF 部分を、上の形に合わせて直す。UIKit の部分は持ってこない）
- [ ] **Step 5: 実行して通ることを確かめる** — Step 3 のコマンド → すべて `PASS`
- [ ] **Step 6: App に足してコンパイルする** — `project.pbxproj` に 2 ファイル（`DocumentText` グループ）を足し、`xcodebuild -project mobile/ios/App/App.xcodeproj -scheme App -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` → `** BUILD SUCCEEDED **`（サンドボックスの外で）
- [ ] **Step 7: コミット** — `feat: Word・Excel・PDF から文字と表を取り出す部品を足す（iPhone 側）`

### Task 10: DocumentReader（ファイル選択・共有の受け取り）と「ファイルから読む」

**Files:**
- Create: `mobile/ios/App/App/DocumentReaderPlugin.swift`、`apps/shared/documentreader.js`
- Modify: `mobile/ios/App/App/ViewController.swift`（登録とログの文）、`SceneDelegate.swift`（ファイルの URL を受け取る）、`Info.plist`（`CFBundleDocumentTypes`）、`project.pbxproj`
- Modify: `apps/schedule/index.html`（`#scanCard` に「📁 ファイルから読む」、`?shared=1` で開かれたとき・起動時の受け取り）、`deeplink.js` を読み込んでいる 8 ページに `documentreader.js` を足し、各 `sw.js` も
- Test: `apps/tests/schedulereader.test.mjs` に足す（偽の `Capacitor.Plugins.DocumentReader`）

**Interfaces:**
- Swift プラグイン名 `DocumentReader`（`jsName`）。メソッド:
  - `pick()` → `UIDocumentPickerViewController(forOpeningContentTypes: [.pdf, UTType("org.openxmlformats.wordprocessingml.document")!, UTType("org.openxmlformats.spreadsheetml.sheet")!], asCopy: true)`。取り消しは `{ cancelled: true }`。選ばれたら読んで結果を返し、コピーを消す
  - `hasShared()` → `{ has: Bool, name: String }`
  - `takeShared()` → 結果か `{}`（無いとき）。取り出したら覚えていた URL を消し、ファイルも消す
  - 結果の形: `{ name, kind, lines: [String], tables: [[[String]]], ocr: Bool }`。`needsOCR` のときは、各ページを `page.thumbnail(of:for:)` で 2 倍の画像にし、`VNRecognizeTextRequest`（`recognitionLanguages = ["ja-JP"]`、`.accurate`）で読んだ行を `lines` に入れ、`ocr: true`
  - 失敗は `call.reject(エラーの日本語の文)`
- `SceneDelegate`: `scene(_:openURLContexts:)` と `scene(_:willConnectTo:options:)` の `connectionOptions.urlContexts` で、`url.isFileURL` のものは `DocumentReaderPlugin.receive(url:)`（一時フォルダへ移し、静的な変数に覚える）に渡し、それ以外は今まで通り `SceneDelegateProxy` へ
- `Info.plist`: `CFBundleDocumentTypes` に 1 項目（`CFBundleTypeName`「書類」、`CFBundleTypeRole` `Viewer`、`LSHandlerRank` `Alternate`、`LSItemContentTypes` に上の 3 種類）。`LSSupportsOpeningDocumentsInPlace` は `false`
- JS `window.DocumentReader`:
  - `available() -> boolean`（ネイティブで、`Plugins.DocumentReader` があるとき）
  - `pick() -> Promise<Result|{cancelled:true}>`、`takeShared() -> Promise<Result|null>`、`hasShared() -> Promise<{has,name}>`
  - `toMeetings(result, today) -> { meetings: Meeting[], text: string }` — `ScheduleTable.isSchedule(result.tables)` なら `ScheduleTable.parse`、そうでなければ `Meeting.parse(result.lines, {})` に `source: "file"` を付ける。`text` は `lines.join("\n")`
  - `watchShared(schedulePath: string)` — ページを開いたときと `resume` のときに `hasShared()` を見て、予定アプリ以外のページでは「共有された「name」を予定アプリで読む」帯と「開く」ボタン（`schedulePath + "?shared=1"` へのリンク）を出す
- 予定アプリ:
  - 「📁 ファイルから読む」は `DocumentReader.available()` のときだけ出す
  - 結果の予定が 1 件以上なら `renderMeetings(meetings)`。見出しを「ファイルから読み取った予定（確認して登録）」に変える（会議の通知・メモのときは今の見出し）。`ocr` なら「スキャンした PDF なので、読み違いがないか特によく確かめてください」を添える
  - 0 件なら、`text` を `<pre>` で見せ、「手入力」ボタンを出す
  - エラーなら知らせに「このファイルは読めませんでした（理由）」
  - 起動時（`?shared=1` のときも、そうでないときも）に `takeShared()` を 1 回呼ぶ

- [ ] **Step 1: 失敗するテストを書く**（偽のプラグインを `addInitScript` で置く。`Capacitor.isNativePlatform = () => true`）
  - 予定表の結果（Task 4 の `t1`）を `pick()` が返す → 確認欄に 2 件、見出し「ファイルから読み取った予定（確認して登録）」
  - 会議通知の `lines`（Task 9 の見本と同じ文）→ 1 件、日付 `2026-10-22`、やること候補 2 件、連絡先あり
  - `ocr: true` → 注意の文が出る
  - `lines` も `tables` も空 → 取り出した文字の欄と「手入力」
  - `pick()` が `reject("ファイルが壊れているため読めませんでした")` → その文が知らせに出る
  - `takeShared()` を 2 回呼ぶと、2 回目は `null`（偽のプラグイン側で 1 回だけ返す作り。予定アプリが起動時に 1 回だけ呼んで 1 回だけ確認欄に出すこと）（Review Focus 5）
  - トップ画面で `hasShared()` が `{ has: true, name: "架空.pdf" }` → 帯が出て、リンク先が `schedule/index.html?shared=1`
- [ ] **Step 2: 実行して失敗を確かめる**
- [ ] **Step 3: Web 側を作る**（`documentreader.js` と予定アプリ・各ページ）→ Step 1 のテストが通る
- [ ] **Step 4: Swift 側を作り、コンパイルする** — `DocumentReaderPlugin.swift`・`SceneDelegate`・`ViewController`・`Info.plist`・`project.pbxproj`。`xcodebuild … CODE_SIGNING_ALLOWED=NO build` → `** BUILD SUCCEEDED **`
- [ ] **Step 5: 全テストを通す** — `apps/tests/*.test.mjs` すべて（Playwright のものは `NODE_PATH`・`CHROMIUM_PATH` 付き）
- [ ] **Step 6: コミット** — `feat: 予定アプリで Word・Excel・PDF を読み、共有メニューからも受け取れるようにする`

### Task 11: 音声メモ（端末内のみ）

**Files:**
- Create: `mobile/ios/App/App/SpeechMemoPlugin.swift`、`apps/shared/speechmemo.js`
- Modify: `ViewController.swift`、`Info.plist`（`NSMicrophoneUsageDescription`・`NSSpeechRecognitionUsageDescription`）、`project.pbxproj`、`apps/docs-tracker/index.html`（メモのタブに「🎤 話してメモ」）、`apps/docs-tracker/sw.js`
- Test: `apps/tests/docstodo.test.mjs` に足す（偽の `Capacitor.Plugins.SpeechMemo`）

**Interfaces:**
- Swift プラグイン名 `SpeechMemo`。メソッド:
  - `isSupported()` → `{ supported: Bool }`（`SFSpeechRecognizer(locale: ja-JP)` があり、`supportsOnDeviceRecognition` が真のとき `true`）
  - `start()` → マイクと音声認識の許可を求め、`SFSpeechAudioBufferRecognitionRequest` に `requiresOnDeviceRecognition = true` と `shouldReportPartialResults = true` を付けて始める。途中の文字は `notifyListeners("partial", ["text": …])`。端末内が使えなければ `reject("この端末では使えません")`、許可が無ければ `reject("マイクか音声認識が許可されていません（設定 → 壱師）")`
  - `stop()` → 止めて `{ text }`（最後の文字）。音声のバッファはどこにも保存しない
- `Info.plist` の文: マイク「話した内容をメモにするために使います。音声は端末の外に送りません」、音声認識「話した内容を、この iPhone の中だけで文字にします」
- JS `window.SpeechMemo`: `available() -> Promise<boolean>`（`isSupported` の `supported`）、`start(onPartial: (text) => void) -> Promise<void>`、`stop() -> Promise<string>`
- 画面: `available()` が `false` ならボタンを出さない。押すと「● 聞いています…（もう一度押すと止まる）」になり、途中の文字を入力欄に出す。止めたら入力欄に文字が残り、利用者が「保存」を押す（自動では保存しない）。失敗の文は知らせに出す

- [ ] **Step 1: 失敗するテストを書く**
  - 偽の `SpeechMemo`（`isSupported` → `{ supported: true }`、`start` 後に `partial` で「10/22 架空の」、`stop` で「10/22 架空の打合せ」）→ ボタンを押す → 入力欄が「10/22 架空の」→ もう一度押す →「10/22 架空の打合せ」。まだメモの一覧には増えていない
  - `isSupported` → `{ supported: false }` ならボタンが無い
  - ブラウザ（Capacitor なし）ならボタンが無い
  - `start` が `reject("この端末では使えません")` → その文が知らせに出る
- [ ] **Step 2: 実行して失敗を確かめる**
- [ ] **Step 3: Web 側を作る** → テストが通る
- [ ] **Step 4: Swift 側を作り、コンパイルする** — `xcodebuild … CODE_SIGNING_ALLOWED=NO build` → `** BUILD SUCCEEDED **`。`grep -n "requiresOnDeviceRecognition = true" mobile/ios/App/App/SpeechMemoPlugin.swift` が 1 行出ること
- [ ] **Step 5: 全テストを通す**
- [ ] **Step 6: コミット** — `feat: 書類・やることのメモを、端末内の音声認識で入力できるようにする`

### Task 12: iPhone 実機での確認と PR

- [ ] **Step 1: iPhone へ入れる** — `cd mobile && IPHONE_UDID=00008150-000E058C0240401C WIFI=1 npm run iphone`（届かなければ USB で `npm run iphone`）。版の表記を控える
- [ ] **Step 2: 利用者に確かめてもらう**（Claude は手順を示し、結果を聞く）
  - 「ファイル」App から見本（`apps/tests/fixtures/doc-*.docx|xlsx|pdf` を AirDrop か iCloud Drive で iPhone に置く）を読む
  - メール添付（見本を自分あてに送ったもの）を共有メニュー →「壱師」で読む。壱師が開いて帯が出て、予定アプリで確認欄に出る
  - スキャン PDF が読める
  - 機内モードで「🎤 話してメモ」が動く
  - メモから予定・やることへ移せる
  - 予定から入れたやることが Watch の期限に出る
- [ ] **Step 3: 直すところがあれば直し、テストとビルドを通して入れ直す**
- [ ] **Step 4: PR** — `gh pr create`（本文に変更点・テスト結果・版、末尾に `🤖 Generated with [Claude Code](https://claude.com/claude-code)`）→ 利用者の了承後に `gh pr merge --merge`
