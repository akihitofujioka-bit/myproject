/*
 * apps/shared/todos.js（通知からTODO候補を見つけ、書類トラッカーへ足す）のテスト。
 *
 *   node apps/tests/todos.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/todos.js"), "utf8"))(g);
const T = g.Todos;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

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
ok(d.items[1].kind === "TODO" && d.items[1].note === "予定: 架空の委員会（10/22）" && d.items[1].scheduleId === "s1", "TODOの形");
ok(d.memos.length === 1 && d.calIds.a === "b", "他の項目を消さない");
const emptySchedule = T.add(s, [{ title: "架空の単独作業", dueOn: "", scheduleId: "", scheduleTitle: "", scheduleDate: "" }]);
const afterEmptySchedule = JSON.parse(s.getItem("docs-tracker.v1"));
ok(emptySchedule.ok && afterEmptySchedule.items.at(-1).note === "", "予定の件名も日付もないTODOには空の予定行を付けない");
const bad = mem(); bad.setItem("docs-tracker.v1", "{壊れた");
ok(T.add(bad, [{ title: "x", dueOn: "", scheduleId: "", scheduleTitle: "", scheduleDate: "" }]).ok === false && bad.getItem("docs-tracker.v1") === "{壊れた", "壊れたデータは上書きしない");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
