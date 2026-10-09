# キャラクター写真 実装計画

> **進め方:** スキル `build-app` の分担に従う。Task 1〜3 は Codex が書き、Claude が確認・コミットする。Task 4 は Claude が行う。各手順はチェックボックス（`- [ ]`）で進み具合を記録する。

**Goal:** 機能ごとに登録したキャラクター写真を、トップ画面（背景とアイコン）と各機能の画面（背景）に表示し、選んだ間隔で自動的に切り替える。

**Architecture:** 共通の部品 `apps/shared/character.js` が、保存（IndexedDB）、今日の写真の決定、背景の表示を受け持つ。登録画面は `apps/shared/character-settings.js` に分け、トップ画面だけが読み込む。各機能のページは `character.js` を読み込み、`Character.applyBackground("<枠の名前>")` を1行呼ぶだけにする。

**Tech Stack:** 素の JavaScript（即時関数で `window` に公開する既存の書き方）、IndexedDB、`<canvas>`、Node のテスト（`apps/tests/*.test.mjs` の書き方）

**Spec:** `docs/superpowers/specs/2026-10-08-character-photo-design.md`

## Global Constraints

- 写真は端末の中（IndexedDB）だけに保存する。通信を伴う処理は足さない
- 枠の名前は `top`・`fridge`・`docs-tracker`・`stock`・`kakeibo`・`cards` の 6 つ
- IndexedDB はデータベース `character`（版 1）、オブジェクトストア `slots`（キーは `slot`）
- 1 枠の形: `{ slot, interval: "day"|"week"|"month", veil: "light"|"normal"|"strong", startDate: "YYYY-MM-DD", photos: [Blob] }`。最初の値は `interval: "day"`、`veil: "normal"`
- 膜の不透明度: `light`=0.55、`normal`=0.7、`strong`=0.85。知らない値は 0.7
- 写真は長い辺 1080 ピクセル以下、JPEG 品質 0.85 に縮めて保存する
- 週の区切りは月曜日、月の区切りは 1 日。日付は端末の地域の時刻
- iPhone のホーム画面のアイコン・Apple Watch・ウィジェットは変えない
- 既存の書き方に合わせる: `"use strict"`、`var`、即時関数 `(function (global) { ... })(window)`、コメントは日本語
- Codex への依頼文には、`build-app` スキルの禁止事項（作業フォルダの外を読まない、ネット禁止、commit 禁止、架空の名前だけ）を入れる

## Review Focus

- **古い記録や壊れた記録**（`startDate` が無い、`photos` が配列でない）→ 画面を止めず、写真が無いときと同じ表示にする。Task 1 の `normalize` のテストで押さえる
- **写真をすべて消した枠** → アイコンは元の画像、背景は元の色に戻る。Task 3 の確認手順で押さえる
- **保存に失敗したとき**（容量不足など）→ 「保存できませんでした」と知らせ、登録画面は使える状態のまま。Task 2 で `save` の失敗を受け止める
- **時計を戻した日付**（今日が `startDate` より前）→ 0 番を出す。Task 1 のテストで押さえる
- **写真の上の文字が読みにくい** → カードやボタンは白い地のまま。Task 3 の iPhone での確認で押さえる

---

### Task 1: 共通の部品 `character.js`（今日の写真の決定・保存・背景の表示）

**担当:** Codex

**Files:**
- Create: `apps/shared/character.js`
- Test: `apps/tests/character.test.mjs`

**Interfaces:**
- Produces（`window.Character` に公開）:
  - `SLOTS: string[]` … 6 つの枠の名前
  - `pickIndex(count: number, interval: string, startDate: string, today: Date) -> number` … 写真 0 枚なら `-1`
  - `veilAlpha(veil: string) -> number`
  - `normalize(record: any, slot: string) -> Record` … 欠けた項目を最初の値で埋める。`photos` が配列でなければ `[]`、`startDate` が無ければ今日
  - `todayString(date: Date) -> "YYYY-MM-DD"`（端末の地域の日付）
  - `load(slot: string) -> Promise<Record>`（記録が無いときも `normalize` 済みの空の枠を返す）
  - `save(record: Record) -> Promise<void>`（失敗したら reject）
  - `resize(file: Blob) -> Promise<Blob>`
  - `currentPhotoURL(slot: string) -> Promise<string|null>`
  - `applyBackground(slot: string) -> Promise<void>`

- [ ] **Step 1: 失敗するテストを書く**（書き方は `apps/tests/scanrouter.test.mjs` に合わせ、`new Function("window", 中身)(g)` で読み込む）

```js
const C = g.Character;
const d = (s) => new Date(s + "T09:00:00");
// 数え始めの日は 0 番
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-08")) === 0, "day: 当日は 0");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-09")) === 1, "day: 翌日は 1");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-11")) === 0, "day: 3 日後は一周して 0");
// 2026-10-08 は木曜日。同じ週の日曜日までは 0、月曜日に 1
ok(C.pickIndex(3, "week", "2026-10-08", d("2026-10-11")) === 0, "week: 日曜日までは 0");
ok(C.pickIndex(3, "week", "2026-10-08", d("2026-10-12")) === 1, "week: 月曜日に 1");
ok(C.pickIndex(3, "month", "2026-10-08", d("2026-10-31")) === 0, "month: 月末までは 0");
ok(C.pickIndex(3, "month", "2026-10-08", d("2026-11-01")) === 1, "month: 1 日に 1");
ok(C.pickIndex(3, "month", "2026-10-08", d("2027-01-01")) === 0, "month: 年またぎ（3 か月後）");
ok(C.pickIndex(1, "day", "2026-10-08", d("2026-12-25")) === 0, "1 枚ならいつも 0");
ok(C.pickIndex(0, "day", "2026-10-08", d("2026-10-08")) === -1, "0 枚なら -1");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-01")) === 0, "時計を戻したら 0");
ok(C.veilAlpha("light") === 0.55 && C.veilAlpha("normal") === 0.7 && C.veilAlpha("strong") === 0.85, "膜の 3 段階");
ok(C.veilAlpha("xxx") === 0.7, "知らない値は normal");
const n = C.normalize({ photos: "壊れた値" }, "fridge");
ok(n.slot === "fridge" && n.interval === "day" && n.veil === "normal" && Array.isArray(n.photos) && n.photos.length === 0, "壊れた記録を最初の値で埋める");
ok(/^\d{4}-\d{2}-\d{2}$/.test(n.startDate), "startDate が無ければ今日");
ok(C.todayString(new Date(2026, 0, 5)) === "2026-01-05", "地域の日付で YYYY-MM-DD");
ok(C.SLOTS.join(",") === "top,fridge,docs-tracker,stock,kakeibo,cards", "6 つの枠");
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `node apps/tests/character.test.mjs`
Expected: `character.js` が無いため失敗する

- [ ] **Step 3: `apps/shared/character.js` を書く**

- `pickIndex` の数え方（設計書のとおり）:
  - day: `startDate` から `today` までの日数（地域の日付どうしの差。夏時間の影響を受けないよう `Date.UTC(年, 月, 日)` で比べる）
  - week: `startDate` を含む週の月曜日から `today` までの日数 ÷ 7 の整数部分
  - month: `(today の年 − 開始の年) × 12 + (today の月 − 開始の月)`
  - 数が負なら 0 番。それ以外は `数 % count`
- `applyBackground(slot)`: 写真があれば、`<body>` の最初に `<div id="charBg">` を入れる（`position:fixed; inset:0; z-index:-1; background: center / cover no-repeat url(...)`）。その上に `rgba(255,255,255, veilAlpha)` の膜を重ねる。`<html>` に `has-char-bg` を付け、`html.has-char-bg body { background: transparent; }` のスタイルを1度だけ差し込む。写真が無いとき、または読み込みに失敗したときは何もしない
- `resize`: `createImageBitmap` か `<img>` で読み込み、長い辺 1080 以下に縮めて `canvas.toBlob(..., "image/jpeg", 0.85)`。もともと小さい写真は縮めない

- [ ] **Step 4: テストが通ることを確かめる**

Run: `node apps/tests/character.test.mjs`
Expected: すべて `PASS`、最後に失敗 0

- [ ] **Step 5: Claude が確認してコミットする**

```bash
git add apps/shared/character.js apps/tests/character.test.mjs
git commit -m "feat: キャラクター写真の共通部品を追加"
```

---

### Task 2: トップ画面の登録欄 `character-settings.js`

**担当:** Codex

**Files:**
- Create: `apps/shared/character-settings.js`
- Modify: `apps/index.html`（`scanCard` の後に、いつも見える登録欄 `<section class="card" id="characterCard">` を足し、2 つのスクリプトを読み込む）

**Interfaces:**
- Consumes: Task 1 の `Character.SLOTS`・`load`・`save`・`resize`・`todayString`
- Produces: `window.CharacterSettings.mount(container: HTMLElement, opts: { onChange: (slot: string) => void, toast: (msg: string) => void }) -> void`

- [ ] **Step 1: `CharacterSettings.mount` を書く**

- 枠ごとの見出し名: `top`=トップ、`fridge`=冷蔵庫、`docs-tracker`=書類、`stock`=備蓄、`kakeibo`=家計簿、`cards`=ポイントカード
- 各枠に並べるもの: 写真の小さな見本の一覧（各写真に「上へ」「下へ」「削除」）、「写真を追加」（`<input type="file" accept="image/*" multiple>`）、切り替え間隔（毎日／毎週／毎月）、膜の濃さ（薄い／普通／濃い）
- 写真の追加・並べ替え・削除・間隔の変更のときは、`startDate` を `Character.todayString(new Date())` に更新して保存する。膜の濃さの変更では更新しない
- 削除は `confirm("この写真を削除しますか？")` で確かめてから行う
- 保存に失敗したら `opts.toast("保存できませんでした")` を出し、画面は元の状態を表示し直す
- 保存に成功したら `opts.onChange(slot)` を呼ぶ

- [ ] **Step 2: `apps/index.html` に組み込む**

- `<script src="shared/character.js">` と `<script src="shared/character-settings.js">` を、既存の `shared/` の読み込みの並びに足す
- `CharacterSettings.mount(document.getElementById("characterCard"), { onChange, toast })` を呼ぶ。`onChange` では Task 3 の表示を更新する関数を呼ぶ（Task 3 で中身を足す。この時点では空の関数でよい）

- [ ] **Step 3: 既存のテストが通ることを確かめる**

Run: `for t in apps/tests/*.test.mjs; do node "$t" || echo "FAILED: $t"; done`
Expected: `FAILED` が1つも出ない

- [ ] **Step 4: Claude が確認してコミットする**

```bash
git add apps/shared/character-settings.js apps/index.html
git commit -m "feat: トップ画面にキャラクター写真の登録欄を追加"
```

---

### Task 3: トップ画面と 5 機能の画面に表示する

**担当:** Codex

**Files:**
- Modify: `apps/index.html`（各アイコンの `<img>` に `data-char-slot="<枠の名前>"` を付け、背景とアイコンを更新する関数を足す）
- Modify: `apps/fridge/index.html`、`apps/docs-tracker/index.html`、`apps/stock/index.html`、`apps/kakeibo/index.html`、`apps/cards/index.html`
- Modify: 同じ 5 機能の `sw.js`（`ASSETS` に `"../shared/character.js"` を足す）

**Interfaces:**
- Consumes: Task 1 の `Character.applyBackground`・`currentPhotoURL`、Task 2 の `onChange`

- [ ] **Step 1: トップ画面**

- 画面を開いたときと `onChange` のときに、`Character.applyBackground("top")` を呼ぶ。また、`[data-char-slot]` の各 `<img>` を `currentPhotoURL(slot)` の写真に差し替える（`object-fit: cover`。枠の形は今のまま）
- 写真が無い枠は、元の `src`（`data-default-src` に控えておく）に戻す。写真が 0 枚になったときの背景の片付けは `applyBackground` が行う（Task 1 で実装済み）

- [ ] **Step 2: 5 機能の画面**

- 各 `index.html` で `<script src="../shared/character.js"></script>` を読み込み、`Character.applyBackground("<枠の名前>")` を呼ぶ（枠の名前はフォルダ名と同じ）
- カード・ボタン・一覧が、今と同じ白い地（`var(--surface)`）のままであることを確かめる。背景が透けている部分があれば、その要素に `background: var(--surface)` を足す

- [ ] **Step 3: 5 機能の `sw.js` に `../shared/character.js` を足す**

- [ ] **Step 4: テストが通ることを確かめる**

Run: `for t in apps/tests/*.test.mjs; do node "$t" || echo "FAILED: $t"; done`
Expected: `FAILED` が1つも出ない（`build.test.mjs` が保存一覧を確かめている場合も通ること）

- [ ] **Step 5: Claude が確認してコミットする**

```bash
git add apps/index.html apps/*/index.html apps/*/sw.js
git commit -m "feat: トップ画面と各機能の画面にキャラクター写真を表示"
```

---

### Task 4: 画面の確認・iPhone への転送・取り込み

**担当:** Claude

- [ ] **Step 1: Playwright の smoke を通す**（手順は `build-app` スキルの「テストの実行」。サンドボックスの外で動かす）

Expected: 失敗 0

- [ ] **Step 2: iPhone に入れる**

Run: `cd mobile && npm run iphone`（サンドボックスの外）
Expected: インストールが成功する。報告に版（例: 「版 2026-10-08 15:00（abc1234）」）を書く

- [ ] **Step 3: 実物で確かめる**（利用者と一緒に）

- トップ画面の登録欄で、写真を 2 枚追加する → トップ画面の背景が 1 枚目になる
- 冷蔵庫の枠に写真を追加する → トップ画面の冷蔵庫のアイコンと、冷蔵庫の画面の背景がその写真になる
- 膜の濃さを 3 段階で切り替え、文字が読めることを確かめる
- 写真をすべて削除する → アイコンと背景が元に戻る

- [ ] **Step 4: PR を作って取り込む**

Run: `gh pr create` → `gh pr merge --merge`（サンドボックスの外）
Expected: `main` に取り込まれる
