/*
 * apps/shared/scheduletable.js（表から予定を取り出す）のテスト。ブラウザ不要。
 *
 *   node apps/tests/scheduletable.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/scheduletable.js"), "utf8"))(g);
const TB = g.ScheduleTable;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

const t1 = [[["月日", "曜", "行事", "時間", "会場"], ["10月22日", "木", "架空の定例会", "10:00〜12:00", "議場"], ["10/28", "水", "架空の研修", "13時30分", "第1会議室"], ["", "", "（備考）", "", ""]]];
ok(TB.isSchedule(t1) === true, "日付の行が 2 行で予定表");
const m = TB.parse(t1, "2026-10-13");
ok(m.length === 2 && m[0].title === "架空の定例会" && m[0].date === "2026-10-22" && m[0].startTime === "10:00" && m[0].endTime === "12:00" && m[0].place === "議場", "1 行目");
ok(m[1].date === "2026-10-28" && m[1].startTime === "13:30" && m[1].source === "file", "2 行目");
ok(TB.parse([[["2026-01-15", "架空の新年会"], ["2026-01-20", "架空の会議"]]], "2026-10-13")[0].title === "架空の新年会", "見出しなし・Excel の日付");
ok(TB.parse([[["日付", "内容"], ["1/15", "架空の会"], ["1/16", "架空の会2"]]], "2026-12-10")[0].date === "2027-01-15", "年をまたぐ");
ok(TB.isSchedule([[["日時", "10月22日 10:00"], ["場所", "議場"]]]) === false, "開催通知の 2 列の表は予定表ではない");

ok(TB.parse([[["2026-01-15", "架空の新年会"], ["2026-01-20", "架空の会議"]]], "2026-10-13")[0].startTime === "", "時刻が無ければ空の文字");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
