import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../shared/scheduleview.js", import.meta.url), "utf8");
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);

const { groupForList, monthGrid, itemsOn, hideDuplicateExternal, isAlreadyRegistered } = context.window.ScheduleView;

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

  assert.deepEqual(Array.from(groups, (g) => g.label), ["明日", "今週", "それ以降", "終了した予定"]);
  // 12 時の時点で 10:00 開始（11:00 終わり）の今日の予定は終わっているので、最後の欄の先頭に回す
  assert.deepEqual(Array.from(groups[3].items, (x) => x.id), ["today", "past", "past7"]);
  assert.equal(groups.some((g) => g.items.some((x) => x.id === "past8")), false);
}

{
  const today = new Date(2026, 9, 5, 13, 30);
  const groups = groupForList([
    item("ended", "2026-10-05", "9:00〜10:00 開始"),
    item("ended2", "2026-10-05", "12:00〜13:30 開始"),
    item("running", "2026-10-05", "13:00〜14:00 開始"),
    item("later", "2026-10-05", "15:00 開始"),
    item("allday", "2026-10-05")
  ], today);
  assert.deepEqual(Array.from(groups.find((g) => g.label === "今日").items, (x) => x.id), ["running", "later", "allday"]);
  assert.deepEqual(Array.from(groups.find((g) => g.label === "終了した予定").items, (x) => x.id), ["ended2", "ended"]);
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

// iPhone のカレンダーの予定のうち、予定アプリの予定と同じものは出さない（表示の重なりを防ぐ）
{
  const appItems = [
    { id: "a1", kind: "予定", title: "星空委員会", dueOn: "2026-10-12", note: "13:30〜15:00 開始" },
    { id: "a2", kind: "予定", title: "若葉公園の下見", dueOn: "2026-10-13", note: "" }
  ];
  const external = [
    { id: "external-E1", eventId: "E1", title: "別の名前に変えた会議", dueOn: "2026-10-20", startTime: "10:00" },
    { id: "external-E2", eventId: "E2", title: "星空委員会", dueOn: "2026-10-12", startTime: "13:30" },
    { id: "external-E3", eventId: "E3", title: "星空委員会", dueOn: "2026-10-12", startTime: "18:00" },
    { id: "external-E4", eventId: "E4", title: "若葉公園の下見", dueOn: "2026-10-13", startTime: "" },
    { id: "external-E5", eventId: "E5", title: "虹色まつり", dueOn: "2026-10-14", startTime: "" }
  ];
  const shown = hideDuplicateExternal(appItems, external, { "meeting-a1": "E1" });
  assert.deepEqual(Array.from(shown, (x) => x.id), ["external-E3", "external-E5"]);
}

// 別々のカレンダーに入った同じ予定（祝日のカレンダーが 2 つある場合など）は 1 つだけ出す
{
  const external = [
    { id: "external-H1", eventId: "H1", title: "体育の日", dueOn: "2026-10-12", startTime: "" },
    { id: "external-H2", eventId: "H2", title: "体育の日", dueOn: "2026-10-12", startTime: "" },
    { id: "external-X1", eventId: "X1", title: "体育の日", dueOn: "2027-10-11", startTime: "" }
  ];
  const shown = hideDuplicateExternal([], external, {});
  assert.deepEqual(Array.from(shown, (x) => x.id), ["external-H1", "external-X1"]);
}

// 予定アプリからカレンダーへ書き込んだ予定は、カレンダーの予定番号で登録済みと判断する
{
  const event = { id: "CAL-A", title: "架空の青空会議", date: "2026-10-20", startTime: "10:00" };
  assert.equal(isAlreadyRegistered([], event, { "item-a": "CAL-A" }), true);
}

// カレンダーから取り込んだ予定は、保存した取り込み元の予定番号で登録済みと判断する
{
  const appItems = [
    { title: "架空の若葉会議", dueOn: "2026-10-21", startTime: "13:00", calEventId: "CAL-B" }
  ];
  const event = { id: "CAL-B", title: "変更後の件名", date: "2026-10-22", startTime: "15:00" };
  assert.equal(isAlreadyRegistered(appItems, event, {}), true);
}

// 予定番号が違っても、件名・日付・開始時刻が同じ予定は登録済みと判断する
{
  const appItems = [
    { title: "架空の虹色会議", dueOn: "2026-10-23", note: "09:30〜10:30 開始" }
  ];
  const event = { id: "CAL-C", title: "架空の虹色会議", date: "2026-10-23", startTime: "09:30" };
  assert.equal(isAlreadyRegistered(appItems, event, {}), true);
}

// どの条件にも当てはまらない予定は未登録と判断する
{
  const appItems = [
    { title: "架空の星空会議", dueOn: "2026-10-24", startTime: "11:00", calEventId: "CAL-D" }
  ];
  const event = { id: "CAL-E", title: "架空の月明かり会議", date: "2026-10-25", startTime: "14:00" };
  assert.equal(isAlreadyRegistered(appItems, event, { "item-d": "CAL-F" }), false);
}

console.log("schedule.test.mjs: OK");
