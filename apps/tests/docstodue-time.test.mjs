/*
 * 書類・TODOの任意の期限時刻を、ブラウザを使わず Node だけで確認する。
 *
 *   node apps/tests/docstodue-time.test.mjs
 *
 * テストデータはすべて架空のもの。
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = fs.readFileSync(path.join(ROOT, "apps/docs-tracker/index.html"), "utf8");

const between = (start, end) => {
  const from = html.indexOf(start);
  const to = html.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `${start} のテスト対象を取得できる`);
  return html.slice(from, to);
};

const context = {
  window: {},
  console,
  STATUSES: ["未着手", "対応中", "提出済", "完了"],
  OPEN_STATUSES: ["未着手", "対応中", "提出済"],
  PRIORITY_ORDER: { "高": 0, "中": 1, "低": 2 }
};
vm.createContext(context);
vm.runInContext(`
  function uid() { return "test-id"; }
  ${between("function normalize(data)", "function save()")}
  ${between("function daysUntil(dateStr)", "function dueLevel(item)")}
  ${between("function dueText(item)", "function esc(s)")}
  ${between("function todoByDue(a, b)", "function todoRow(it)")}
  ${between("function noticeLine(item)", "function registerToCalendar(items, options)")}
`, context);

const normalized = context.normalize({ items: [
  { id: "a", title: "架空の午前作業", kind: "TODO", dueOn: "2026-11-12", dueTime: "09:30", status: "未着手" },
  { id: "b", title: "架空の時刻なし作業", kind: "TODO", dueOn: "2026-11-12", status: "未着手" },
  { id: "c", title: "架空の不正時刻作業", kind: "TODO", dueOn: "2026-11-12", dueTime: "9:30", status: "未着手" },
  { id: "d", title: "架空の日付なし作業", kind: "TODO", dueOn: "", dueTime: "15:00", status: "未着手" },
  { id: "e", title: "架空の書類", kind: "申請", dueOn: "2026-11-12", dueTime: "12:00", status: "未着手" }
] });
assert.equal(normalized.items[0].dueTime, "09:30", "正しい時刻を保持する");
assert.equal(normalized.items[1].dueTime, "", "古いTODOは時刻なしで読める");
assert.equal(normalized.items[2].dueTime, "", "形式が違う時刻を空にする");
assert.equal(normalized.items[3].dueTime, "", "期限日がないと時刻を空にする");
assert.equal("dueTime" in normalized.items[4], false, "TODO以外には期限時刻を足さない");

const display = context.dueText(normalized.items[0]);
assert.match(display, /^2026-11-12 09:30（/, "TODOの期限日後ろに時刻を表示する");
assert.doesNotMatch(context.dueText(normalized.items[4]), /12:00/, "書類には時刻を表示しない");

const sameDay = [
  { title: "時刻なし", dueOn: "2026-11-12", dueTime: "", createdAt: "2026-01-01" },
  { title: "午後", dueOn: "2026-11-12", dueTime: "15:00", createdAt: "2026-01-02" },
  { title: "午前", dueOn: "2026-11-12", dueTime: "09:00", createdAt: "2026-01-03" }
].sort(context.todoByDue);
assert.deepEqual(sameDay.map(item => item.title), ["午前", "午後", "時刻なし"], "同じ日は時刻順、時刻なしの順に並べる");

const calendarEvent = context.toCalendarEvent({
  id: "a", title: "架空の午前作業", kind: "TODO", dueOn: "2026-11-12", dueTime: "09:30",
  status: "未着手", note: "", dest: "", icsSeq: 0
});
assert.equal(calendarEvent.title, "【TODO】架空の午前作業（09:30まで）", "TODOのカレンダー件名に時刻を足す");
assert.equal(calendarEvent.time, "09:00", "カレンダー予定の既存時刻は変えない");

assert.match(html, /id="todo-due-time" name="dueTime" type="time"/, "TODOフォームに時刻入力がある");
assert.match(html, /dueTime:\s*dueOn\s*\?\s*document\.getElementById\("todo-due-time"\)\.value\s*:\s*""/, "期限日なしでは時刻を保存しない");

console.log("docstodue-time: すべて通過");
