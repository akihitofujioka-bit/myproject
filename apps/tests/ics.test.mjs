/*
 * apps/shared/ics.js（カレンダー用の .ics 生成）の単体テスト。ブラウザ不要。
 *
 *   node apps/tests/ics.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const fake = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/ics.js"), "utf8"))(fake);
const ICS = fake.ICS;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

// 折り返された行を元に戻す（CRLF + 半角空白 が継続を表す）
const unfold = (text) => text.replace(/\r\n /g, "");
const linesOf = (text) => unfold(text).split("\r\n").filter(Boolean);

const sample = [{
  uid: "doc-1@docs-tracker",
  title: "職員研修 受講報告書",
  date: "2026-09-10",
  description: "様式は庁内ポータルの様式集から取得",
  location: "総務課",
  sequence: 2,
}];

console.log("== 基本の形 ==");
const text = ICS.build(sample, { calendarName: "書類の期限" });
ok(text.startsWith("BEGIN:VCALENDAR\r\n"), "VCALENDAR で始まる");
ok(text.endsWith("END:VCALENDAR\r\n"), "VCALENDAR で終わる");
ok(!/[^\r]\n/.test(text), "改行がすべて CRLF");
const L = linesOf(text);
for (const required of ["VERSION:2.0", "CALSCALE:GREGORIAN", "BEGIN:VEVENT", "END:VEVENT", "UID:doc-1@docs-tracker", "SEQUENCE:2", "SUMMARY:職員研修 受講報告書", "LOCATION:総務課"]) {
  ok(L.includes(required), "必要な行がある: " + required);
}
ok(L.some((l) => /^DTSTAMP:\d{8}T\d{6}Z$/.test(l)), "DTSTAMP が UTC 形式");
ok(L.includes("DTSTART:20260910T090000"), "期限日の09:00に予定を作る");
ok(L.includes("DTEND:20260910T093000"), "既定の長さは30分");

console.log("== 通知（アラーム）==");
ok(L.filter((l) => l === "BEGIN:VALARM").length === 2, "既定で通知は2つ");
ok(L.includes("TRIGGER:-P1D"), "前日に通知");
ok(L.includes("TRIGGER:PT0S"), "当日の開始時刻に通知");
const custom = linesOf(ICS.build([{ ...sample[0], alarms: [180, 60, 30] }]));
ok(custom.includes("TRIGGER:-PT3H"), "3時間前を時間で表す");
ok(custom.includes("TRIGGER:-PT30M"), "30分前を分で表す");
ok(linesOf(ICS.build([{ ...sample[0], alarms: [] }])).every((l) => l !== "BEGIN:VALARM"), "通知なしも指定できる");

console.log("== 日をまたぐ場合 ==");
const midnight = linesOf(ICS.build([{ ...sample[0], time: "23:50", durationMinutes: 30 }]));
ok(midnight.includes("DTSTART:20260910T235000"), "23:50 開始");
ok(midnight.includes("DTEND:20260911T002000"), "終了が翌日になる");

console.log("== 特殊文字の退避 ==");
ok(ICS.escapeText("a;b") === "a\\;b", "; を退避する");
ok(ICS.escapeText("a,b") === "a\\,b", ", を退避する");
ok(ICS.escapeText("a\\b") === "a\\\\b", "バックスラッシュを退避する");
ok(ICS.escapeText("a\nb") === "a\\nb", "改行を退避する");
const tricky = linesOf(ICS.build([{ ...sample[0], title: "備品発注伺い（A;B,C）" }]));
ok(tricky.includes("SUMMARY:備品発注伺い（A\\;B\\,C）"), "件名の中の記号が退避される");

console.log("== 行の折り返し ==");
const longTitle = "〇〇事業に係る実績報告書および関係書類一式の提出について（令和8年度分・企画課経由）";
const folded = ICS.build([{ ...sample[0], title: longTitle }]);
const overLimit = folded.split("\r\n").filter((l) => Buffer.byteLength(l, "utf8") > 75);
ok(overLimit.length === 0, "75オクテットを超える行がない");
ok(linesOf(folded).includes("SUMMARY:" + longTitle), "折り返しても元に戻せる");
ok(!/\r\n [\x80-\xBF]/.test(folded), "日本語を途中で割っていない");
const emoji = ICS.build([{ ...sample[0], title: "🥬".repeat(40) }]);
ok(emoji.split("\r\n").every((l) => Buffer.byteLength(l, "utf8") <= 75), "絵文字が続いても75オクテット以内");
ok(linesOf(emoji).includes("SUMMARY:" + "🥬".repeat(40)), "絵文字を壊さずに折り返す");

console.log("== 複数の予定 ==");
const many = ICS.build([sample[0], { uid: "doc-2@x", title: "備品発注伺い", date: "2026-09-05" }]);
ok(linesOf(many).filter((l) => l === "BEGIN:VEVENT").length === 2, "2件ぶんの予定ができる");
ok(ICS.filename("deadlines").endsWith(".ics"), "ファイル名の拡張子");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
