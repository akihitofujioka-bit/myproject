/*
 * apps/shared/suggest.js（予定の重複・移動時間不足・曜日の食い違いを見つける）のテスト。ブラウザ不要。
 *
 *   node apps/tests/suggest.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/suggest.js"), "utf8"))(g);
const S = g.Suggest;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

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
ok(S.check([{ ...b, start: "9:30", end: "10:30" }], [a]).length === 1, "1 桁の時刻も読む");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
