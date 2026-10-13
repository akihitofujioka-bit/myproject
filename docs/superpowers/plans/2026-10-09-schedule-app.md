# 予定アプリの新設と備蓄の削除 実装計画

> **進め方:** スキル `build-app` の分担に従う。Task 1・2・3 は互いに別のファイルなので Codex を同時に動かす。Task 4 は 1〜3 の後。Task 5 は Claude。各手順はチェックボックスで進み具合を記録する。

**目的:** 備蓄をなくし、書類トラッカーから会議・予定を「予定」アプリへ分け、一覧とカレンダーで iPhone のカレンダーの予定と一緒に見られるようにする。

**作りの考え方:** 予定は localStorage の `schedule.v1` に置く。引っ越しは `apps/shared/schedulemove.js`、一覧とカレンダーの組み立て（日付の計算）は `apps/shared/scheduleview.js` に分け、どちらもブラウザ不要でテストする。画面は `apps/schedule/index.html`。会議・手帳の機能は書類トラッカーから移す。

**使う技術:** 素の JavaScript（即時関数で `window` に公開する既存の書き方）、localStorage、Node のテスト、Capacitor の既存プラグイン（`CalendarReader`・`CalendarWriter`）

**設計書:** `docs/superpowers/specs/2026-10-09-schedule-app-design.md`

## 全体で守ること

- 外部へデータを送らない。iPhone のカレンダーの予定は見るだけ（変えない・消さない）
- 保存の鍵: 予定 `schedule.v1`（`{ version: 1, items: [] }`）、書類 `docs-tracker.v1`（変えない）、控え `docs-tracker.v1.backup-2026-10`、表示の選択 `schedule.view`（`"list"` または `"calendar"`）
- 予定の項目は書類トラッカーの会議・予定の形をそのまま使う（`kind` は `"会議"` または `"予定"`）
- フォルダ名 `docs-tracker` と Deep Link `myproject://docs?id=...` は変えない
- キャラクター写真の枠: `top`・`fridge`・`docs-tracker`・`schedule`・`kakeibo`・`cards`（`stock` を外し `schedule` を足す。見出しは「予定」）
- カレンダーは月曜始まり。iPhone のカレンダーは今日から 60 日先まで、アプリ版でだけ読む
- 既存の書き方に合わせる（`"use strict"`・`var`・即時関数、日本語のコメント）
- Codex には `build-app` スキルの禁止事項を伝える。**ファイルの削除は Codex にさせない**（Claude が利用者の承諾を得て行う）

## 特に確かめること（想定外の場面）

- **引っ越しの途中で保存に失敗**（容量不足など）→ `docs-tracker.v1` は元のまま。Task 2 のテストで押さえる
- **引っ越しが 2 回走る**（トップと予定アプリを続けて開く）→ 2 回目は何もしない。Task 2 のテストで押さえる
- **書類トラッカーの古い画面を開いたままの状態で引っ越し**→ 書類トラッカーは開くたびに読み直すので、会議が二重に戻らないこと。Task 4 で、書類トラッカーが保存時に `kind` が会議・予定の項目を書き戻さないようにする
- **カレンダーの読み取りを許可していない**→ 予定アプリの予定だけを出し、画面は止めない。Task 3
- **月末・年末のカレンダー**（31 日の月、12 月→1 月）→ マス目と移動が正しい。Task 3 のテストで押さえる

---

### Task 1: 備蓄を外す（2-1）

**担当:** Codex

**対象ファイル:**
- 変更: `apps/index.html`（備蓄のアイコンを外す。トップを開いたとき localStorage の `stock.v1` を1回だけ消す）
- 変更: `mobile/scripts/build-www.mjs`（`stock` を外す）
- 変更: `apps/shared/watch.js`（`stockShopping` を外し、買い物は `fridgeShopping` だけ）
- 変更: `apps/shared/inbox.js`（送り先 `stock` を外す）
- 変更: `apps/kakeibo/index.html`（「備蓄へ送る」ボタン `sendStock` と関連の処理を外す）
- 変更: `apps/shared/character.js`・`apps/shared/character-settings.js`（枠 `stock` → `schedule`、見出し「予定」。保存済みの `stock` 枠は `Character` の初回の読み込みで消す）
- 変更: `apps/tests/*`（備蓄に触れているテストを直す）、`apps/README.md`
- **`apps/stock/` は消さない**（Claude が後で消す）

- [ ] **手順 1:** 上の変更をする。`character.test.mjs` の `SLOTS` の期待値を `"top,fridge,docs-tracker,schedule,kakeibo,cards"` に直す
- [ ] **手順 2:** `rg -n "stock" apps mobile/scripts --glob '!apps/stock/**'` で、残りが意図したもの（`stock.v1` を消す処理など）だけであること
- [ ] **手順 3:** `for t in apps/tests/*.test.mjs; do node "$t" || echo "FAILED: $t"; done` で、Playwright を使うもの以外が通る
- [ ] **手順 4:** Claude が確認し、利用者の承諾を得て `apps/stock/` を消し、コミット（`feat: 使っていない備蓄・消耗品をなくし、買い物リストを冷蔵庫だけにする`）

---

### Task 2: 引っ越しの処理

**担当:** Codex

**対象ファイル:**
- 新規: `apps/shared/schedulemove.js`
- テスト: `apps/tests/schedulemove.test.mjs`

**ほかの作業との受け渡し:**
- 作るもの: `window.ScheduleMove.run(storage) -> { moved: number, skipped: boolean, error: string }`
  - `storage` は `getItem`/`setItem` を持つもの（ふだんは `localStorage`。テストでは偽物）
  - `schedule.v1` が既にあれば `{ moved: 0, skipped: true }`
  - 手順と失敗時の扱いは設計書の「引っ越し」のとおり。書き込みの順は ①控え ②`schedule.v1` ③`docs-tracker.v1`。②か③で失敗したら、②で書いた `schedule.v1` を元に戻し（消し）、`error` に理由を入れる

- [ ] **手順 1: 失敗するテストを書く**（偽の storage で）
  - 会議・予定だけが `schedule.v1` に移り、書類・回覧・申請は `docs-tracker.v1` に残る
  - 控え `docs-tracker.v1.backup-2026-10` が元の中身と同じ
  - 2 回目は `skipped: true` で何も変えない
  - `docs-tracker.v1` が無い・壊れているとき: `schedule.v1` を空で作り、`docs-tracker.v1` には触れない
  - ③の `setItem` が例外を出すとき: `docs-tracker.v1` は元のまま、`schedule.v1` は無いまま、`error` が空でない
- [ ] **手順 2:** `node apps/tests/schedulemove.test.mjs` が失敗することを確かめる
- [ ] **手順 3:** `schedulemove.js` を書く
- [ ] **手順 4:** テストが通る
- [ ] **手順 5:** Claude が確認してコミット（`feat: 書類トラッカーの会議・予定を予定アプリへ引っ越す処理を追加`）

---

### Task 3: 予定アプリの画面

**担当:** Codex

**対象ファイル:**
- 新規: `apps/shared/scheduleview.js`（日付の計算だけ。画面に触れない）
- 新規: `apps/schedule/index.html`、`apps/schedule/sw.js`、`apps/schedule/manifest.webmanifest`、`apps/schedule/icon-180.png`・`icon-192.png`・`icon-512.png`（`apps/docs-tracker/` のものを写す）
- テスト: `apps/tests/schedule.test.mjs`

**ほかの作業との受け渡し:**
- 使うもの: Task 2 の `ScheduleMove.run(localStorage)`（画面を開いたとき最初に呼ぶ）、既存の `CalendarRead`・`CalendarWrite`・`ics.js`・`character.js`・`deeplink.js`・`watch.js`
- 作るもの（`window.ScheduleView`）:
  - `groupForList(items, today: Date) -> [{ label: "今日"|"明日"|"今週"|"それ以降"|"過ぎた予定", items }]`（空の見出しは返さない。「今週」は明後日〜その週の日曜。「過ぎた予定」は直近 7 日まで、新しい順）
  - `monthGrid(year, month /* 0-11 */) -> Date[][]`（月曜始まり、6 週 × 7 日の固定）
  - `itemsOn(items, ymd: "YYYY-MM-DD") -> items`（時刻の順）

- [ ] **手順 1: 失敗するテストを書く**
  - `groupForList`: 今日・明日・今週・それ以降・過ぎた予定（8 日前は出ない）の分け方。日曜日が今日のとき「今週」は空
  - `monthGrid(2026, 9)`（2026 年 10 月）: 先頭が 2026-09-28（月）、10 月 1 日が木曜の列。`monthGrid(2026, 11)` の最後の週に 2027 年 1 月の日が入る
  - `itemsOn`: 時刻の早い順、時刻なしは最後
- [ ] **手順 2:** テストが失敗することを確かめる
- [ ] **手順 3:** `scheduleview.js` を書く
- [ ] **手順 4: 画面を書く。** 書類トラッカー（`apps/docs-tracker/index.html`）から、会議・予定に関わる部分を写して作る: 予定の一覧・登録・編集・削除、会議の読み取り確認欄、手帳の読み取りの登録、カレンダーへの書き込み、ics の書き出し、`pendingScan` の受け取り。見た目（CSS）と書き方は書類トラッカーに合わせる。設計書の「画面」のとおり、上部に「一覧」「カレンダー」の切り替え（`schedule.view` に保存）。iPhone のカレンダーの予定は `CalendarRead` で今日から 60 日先まで読み、左端に色の帯（`border-left: 4px solid` の別の色）を付けて並べ、押しても編集しない。読めないとき・ブラウザでは出さない。`Character.applyBackground("schedule")` を呼ぶ。**このタスクでは書類トラッカーは変えない**
- [ ] **手順 5:** `node apps/tests/schedule.test.mjs` と既存のテストが通る
- [ ] **手順 6:** Claude が確認してコミット（`feat: 一覧とカレンダーで見られる予定アプリを追加`）

---

### Task 4: 書類・回覧トラッカーへの整理と、つなぎ替え

**担当:** Codex（Task 1〜3 のコミット後）

**対象ファイル:**
- 変更: `apps/docs-tracker/index.html`（名前を「書類・回覧トラッカー」に。種別から「会議」「予定」を外す。会議の読み取り確認欄・手帳の登録・会議のカレンダー書き込みを外す。保存時に `kind` が会議・予定の項目を書き戻さない。開いたとき `ScheduleMove.run(localStorage)` を呼ぶ）
- 変更: `apps/index.html`（予定のアイコンを書類のすぐ下に足す。書類のアイコンの名前と説明を直す。開いたとき `ScheduleMove.run(localStorage)` を呼ぶ）
- 変更: `apps/shared/scanrouter.js`（`DEST.meeting`・`DEST.planner` を `"schedule/index.html"` に）
- 変更: `apps/shared/watch.js`（会議・予定は `schedule.v1` から、期限は `docs-tracker.v1` から）
- 変更: `apps/shared/calendarread.js`（コメントと形を予定アプリに合わせる）
- 変更: `mobile/scripts/build-www.mjs`（`schedule` を足す）
- 変更: `apps/docs-tracker/sw.js`（キャッシュの版を上げる）
- 変更: `apps/tests/*`（`watch`・`scanrouter`・`ics`・`smoke`・`pwa`・`build` を新しい形に）、`apps/README.md`

- [ ] **手順 1:** 上の変更をする
- [ ] **手順 2:** `for t in apps/tests/*.test.mjs; do node "$t" || echo "FAILED: $t"; done` で、Playwright を使うもの以外が通る
- [ ] **手順 3:** Claude が確認してコミット（`feat: 書類トラッカーを書類・回覧だけにし、会議・手帳・撮るを予定アプリへつなぐ`）

---

### Task 5: 確認・転送・取り込み

**担当:** Claude

- [ ] Playwright のテスト（`smoke`・`pwa`・`kakeibo`・`nativebridge`）が、元からある `smoke` の 2 件以外は通る
- [ ] ブラウザで: 書類トラッカーに会議と書類を入れた状態から予定アプリを開く → 会議だけ移る、一覧とカレンダーの切り替え、月の移動
- [ ] `npm run iphone`（USB）で転送し、版を報告。Watch は iPhone の Watch アプリから
- [ ] 実物: 引っ越し、カレンダーの予定の表示、「撮る」で会議・手帳が予定アプリに入る、Watch の会議と期限
- [ ] 利用者の確認後に PR を作って取り込む
