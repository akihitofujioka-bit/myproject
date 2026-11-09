/*
 * トップ画面の「次の予定」欄（shared/nextup.js）の選び方の確認。
 *
 *   node apps/tests/nextup.test.mjs
 *
 * ブラウザを使わず Node だけで動く。データは架空のもの。
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = fs.readFileSync(path.join(ROOT, "apps/shared/nextup.js"), "utf8");
const window = {};
vm.runInNewContext(source, { window });
const { pick, indexAt, detail, INTERVAL } = window.NextUp;
// vm の中で作った配列は prototype が違うため、比べる前にこちらの配列へ移す
const titles = (list) => [...list].map((m) => m.title);
const noon = 12 * 60 + 15;

// 明日の終日の会議2件
assert.deepEqual(titles(pick({ meetings: [
  { id: "a", title: "終日X", days: 1, time: "" },
  { id: "b", title: "終日Y", days: 1 }
] }, noon)), ["終日X", "終日Y"]);

// 今日の会議は始まったものを外し、時刻の早い順・終日は後ろ
assert.deepEqual(titles(pick({ meetings: [
  { id: "a", title: "始まった会議", days: 0, time: "12:00〜13:00" },
  { id: "c", title: "終日の会議", days: 0, time: "" },
  { id: "d", title: "15時の会議", days: 0, time: "15:00" },
  { id: "b", title: "13時の会議", days: 0, time: "13:00" },
  { id: "e", title: "明日の会議", days: 1, time: "10:00" }
] }, noon)), ["13時の会議", "15時の会議", "終日の会議"]);

// いちばん近い日より前に書類の期限があるときは空（ウィジェットはその期限を出すため）
assert.equal(pick({
  meetings: [{ id: "a", title: "X", days: 1 }, { id: "b", title: "Y", days: 1 }],
  deadlines: [{ id: "d", title: "書類", days: 0 }]
}, noon).length, 0);

// 同じ日の期限はそのまま会議を出す
assert.equal(pick({
  meetings: [{ id: "a", title: "X", days: 1 }, { id: "b", title: "Y", days: 1 }],
  deadlines: [{ id: "d", title: "書類", days: 1 }]
}, noon).length, 2);

// 会議が無い・壊れた一覧でも止まらない
assert.equal(pick({}, noon).length, 0);
assert.equal(pick(null, noon).length, 0);

// 10秒ごとに次の件へ進み、最後の次は先頭に戻る
assert.equal(INTERVAL, 10000);
assert.equal(indexAt(3, 0), 0);
assert.equal(indexAt(3, 10000), 1);
assert.equal(indexAt(3, 29999), 2);
assert.equal(indexAt(3, 30000), 0);

assert.equal(detail({ days: 1, time: "" }, 0, 2), "明日 終日　1/2");
assert.equal(detail({ days: 0, time: "13:00〜14:00" }, 1, 3), "今日 13:00〜14:00　2/3");

console.log("nextup: すべて通過");
