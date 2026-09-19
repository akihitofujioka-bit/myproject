/*
 * apps/shared/calendarread.js（カレンダーの予定を会議の形に直す）のテスト。ブラウザ不要。
 * ネイティブ呼び出し（isSupported/requestAccess/listCalendars/listEvents）は
 * 実機でしか確認できないため、ここでは純粋な変換関数 toMeeting() だけを見る。
 *
 *   node apps/tests/calendarread.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/calendarread.js"), "utf8"))(g);
const C = g.CalendarRead;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

console.log("== toMeeting ==");
{
  const m = C.toMeeting({ id: "abc", title: "○○委員会", date: "2026-10-15", startTime: "13:30", endTime: "15:00", place: "本庁舎3階" });
  ok(m.title === "○○委員会", "会議名を写す");
  ok(m.date === "2026-10-15", "日付を写す");
  ok(m.startTime === "13:30" && m.endTime === "15:00", "開始・終了時刻を写す");
  ok(m.place === "本庁舎3階", "場所を写す");
  ok(m.social.has === false && m.social.fee === null, "懇親会の有無はカレンダーに無いため false で始まる");
  ok(m.source === "calendar", "出典が calendar になる");
}
{
  const m = C.toMeeting({});
  ok(m.title === "" && m.date === "" && m.startTime === "" && m.endTime === "" && m.place === "", "空の予定でも例外にならず空文字になる");
}
{
  const m = C.toMeeting(null);
  ok(m.title === "" && m.source === "calendar", "null が渡っても例外にならない");
}

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
