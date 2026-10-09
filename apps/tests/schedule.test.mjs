import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../shared/scheduleview.js", import.meta.url), "utf8");
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);

const { groupForList, monthGrid, itemsOn } = context.window.ScheduleView;

function item(id, dueOn, note = "") {
  return { id, title: `架空の予定${id}`, dueOn, note };
}

{
  const today = new Date(2026, 9, 5, 12); // 月曜日
  const groups = groupForList([
    item("today", "2026-10-05", "10:00 開始"),
    item("tomorrow", "2026-10-06"),
    item("week", "2026-10-11"),
    item("later", "2026-10-12"),
    item("past", "2026-10-04"),
    item("past7", "2026-09-28"),
    item("past8", "2026-09-27")
  ], today);

  assert.deepEqual(Array.from(groups, (g) => g.label), ["今日", "明日", "今週", "それ以降", "過ぎた予定"]);
  assert.deepEqual(Array.from(groups[4].items, (x) => x.id), ["past", "past7"]);
  assert.equal(groups.some((g) => g.items.some((x) => x.id === "past8")), false);
}

{
  const sunday = new Date(2026, 9, 11, 12);
  const groups = groupForList([
    item("today", "2026-10-11"),
    item("tomorrow", "2026-10-12"),
    item("tuesday", "2026-10-13")
  ], sunday);
  assert.equal(groups.some((g) => g.label === "今週"), false);
  assert.deepEqual(Array.from(groups.find((g) => g.label === "それ以降").items, (x) => x.id), ["tuesday"]);
}

{
  const grid = monthGrid(2026, 9);
  assert.equal(grid.length, 6);
  assert.equal(grid.every((week) => week.length === 7), true);
  assert.deepEqual(
    [grid[0][0].getFullYear(), grid[0][0].getMonth(), grid[0][0].getDate()],
    [2026, 8, 28]
  );
  assert.equal(grid[0][3].getDate(), 1);
  assert.equal(grid[0][3].getDay(), 4);
}

{
  const grid = monthGrid(2026, 11);
  assert.equal(grid[5].some((d) => d.getFullYear() === 2027 && d.getMonth() === 0), true);
}

{
  const sorted = itemsOn([
    item("none", "2026-10-05"),
    item("late", "2026-10-05", "14:30 開始"),
    item("other", "2026-10-06", "08:00 開始"),
    { ...item("early", "2026-10-05"), startTime: "09:00" }
  ], "2026-10-05");
  assert.deepEqual(Array.from(sorted, (x) => x.id), ["early", "late", "none"]);
}

console.log("schedule.test.mjs: OK");
