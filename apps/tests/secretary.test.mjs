/*
 * apps/shared/secretary.js（AI を使わずに秘書画面の材料を作る部品）のテスト。
 *
 *   node apps/tests/secretary.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const secretaryPath = path.join(ROOT, "apps/shared/secretary.js");
if (fs.existsSync(secretaryPath)) {
  new Function("window", fs.readFileSync(secretaryPath, "utf8"))(g);
}
const S = g.Secretary;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};
const sameRange = (question, today, from, to, found = true) => {
  const actual = S.range(question, today);
  return actual.from === from && actual.to === to && actual.found === found;
};

if (!S) {
  ok(false, "window.Secretary が公開されている");
} else {
  ok(sameRange("今日の予定は？", "2026-10-13", "2026-10-13", "2026-10-13"), "今日を選ぶ");
  ok(sameRange("明日の予定", "2026-10-13", "2026-10-14", "2026-10-14"), "明日を選ぶ");
  ok(sameRange("あさっては？", "2026-10-13", "2026-10-15", "2026-10-15"), "あさってを選ぶ");
  ok(sameRange("今週", "2026-10-13", "2026-10-12", "2026-10-18"), "今週は月曜から日曜");
  ok(sameRange("来週", "2026-10-13", "2026-10-19", "2026-10-25"), "来週は次の月曜から日曜");
  ok(sameRange("今月", "2026-10-13", "2026-10-01", "2026-10-31"), "今月を選ぶ");
  ok(sameRange("来月", "2026-10-13", "2026-11-01", "2026-11-30"), "来月を選ぶ");
  ok(sameRange("10月20日の予定", "2026-10-13", "2026-10-20", "2026-10-20"), "月日を選ぶ");
  ok(sameRange("20日の予定", "2026-10-13", "2026-10-20", "2026-10-20"), "日だけを選ぶ");
  ok(sameRange("火曜の予定", "2026-10-13", "2026-10-13", "2026-10-13"), "曜日だけなら今日以降で最初の日");
  ok(sameRange("来週火曜の予定", "2026-10-13", "2026-10-20", "2026-10-20"), "来週の曜日を選ぶ");
  ok(sameRange("予定を教えて", "2026-10-13", "2026-10-13", "2026-10-26", false), "期間なしは今日から14日間");
  ok(sameRange("来月", "2026-12-20", "2027-01-01", "2027-01-31"), "年末の来月は翌年");
  ok(sameRange("1月5日", "2026-12-20", "2027-01-05", "2027-01-05"), "過ぎた月日は翌年");

  const list = S.lines(
    { from: "2026-10-20", to: "2026-10-22" },
    {
      items: [
        { title: "架空の委員会", dueOn: "2026-10-20", dest: "第1会議室", time: "10:00", endTime: "12:00", calEventId: "cal-1" },
        { title: "架空の時刻なし予定", dueOn: "2026-10-21" }
      ],
      calendarEvents: [
        { id: "cal-1", title: "重複する予定", start: "2026-10-20T10:00:00", end: "2026-10-20T12:00:00", location: "別室" },
        { id: "cal-2", title: "架空の外部予定", start: "2026-10-20T09:00:00", end: "2026-10-20T09:30:00", location: "第2会議室" }
      ],
      todos: [{ title: "架空の資料提出", dueOn: "2026-10-22" }]
    }
  );
  ok(list.count === 4 && !list.cut, "結び付いた予定を1件にまとめる");
  ok(list.text.split("\n")[0] === "10/20(火) 9:00-9:30 架空の外部予定 @第2会議室", "日付・開始時刻順で予定を書く");
  ok(list.text.includes("10/20(火) 10:00-12:00 架空の委員会 @第1会議室"), "予定アプリの時刻と場所を書く");
  ok(list.text.includes("10/22(木) 期限 架空の資料提出（やること）"), "期限付きのやることを書く");

  const helped = S.lines(
    { from: "2026-10-20", to: "2026-10-20" },
    { items: [{ title: "架空のメモ予定", dueOn: "2026-10-20", note: "10:00〜11:00 開始" }], calendarEvents: [], todos: [] },
    { timeOf: () => "10:00", endTimeOf: () => "11:00" }
  );
  ok(helped.text.includes("10:00-11:00"), "渡された時刻取得関数を使う");

  const many = S.lines(
    { from: "2026-10-20", to: "2026-10-20" },
    { items: Array.from({ length: 61 }, (_, i) => ({ title: "架空の予定" + i, dueOn: "2026-10-20" })), calendarEvents: [], todos: [] }
  );
  ok(many.cut && many.count === 60 && many.text.split("\n").length === 60, "61件は先頭60件で切る");

  const free = S.freeSlots(
    { from: "2026-10-20", to: "2026-10-21" },
    [
      { date: "2026-10-20", start: "07:00", end: "08:00" },
      { date: "2026-10-20", start: "10:00", end: "12:00" },
      { date: "2026-10-20", start: "11:00", end: "13:00" },
      { date: "2026-10-20", start: "18:00", end: "19:00" },
      { date: "2026-10-21", allDay: true }
    ]
  );
  ok(free === "10/20(火) 空き 8:30-10:00, 13:00-17:15\n10/21(水) 終日の予定あり", "重なる予定をまとめ、勤務時間内の空きを出す");
  ok(S.wantsFree("来週は空いていますか") && !S.wantsFree("来週の予定"), "空き時間を求める言葉を判定する");
  ok(S.wantsDraft("予定にして") && S.wantsDraft("やることを追加") && !S.wantsDraft("予定を教えて"), "下書きを求める言葉を判定する");

  const fenced = S.checkDraft(
    "説明です。\n```json\n{\"kind\":\"event\",\"title\":\"架空の打合せ\",\"date\":\"2026-10-21\",\"start\":\"10:00\"}\n```\n以上です。",
    "来週火曜10時に架空の打合せを入れて",
    "2026-10-13"
  );
  ok(fenced.ok && fenced.draft.date === "2026-10-20", "説明やJSON囲みの中の最初のオブジェクトを読み、質問の日付を優先する");

  ok(!S.checkDraft("読めない文字", "架空の予定を追加", "2026-10-13").ok, "JSONを読めない場合は失敗にする");
  const fallbackQuestion = "架空の確認を予定にしてください。追加の説明を十分に長く書いた質問です。";
  const cleaned = S.checkDraft(
    '{"kind":"other","title":"","date":"2026-02-30","start":"25:00","end":"09:30","place":3,"memo":null}',
    fallbackQuestion,
    "2026-10-13"
  );
  ok(cleaned.ok && cleaned.draft.kind === "event", "不明な種類は予定にする");
  ok(cleaned.draft.date === "" && cleaned.draft.start === "" && cleaned.draft.end === "09:30", "あり得ない日付・時刻を空欄にする");
  ok(cleaned.draft.title === fallbackQuestion.slice(0, 30) && cleaned.draft.title.length === 30, "空の件名は質問の先頭30字にする");
  ok(cleaned.draft.place === "3" && cleaned.draft.memo === "", "下書きの各値を安全な文字列にする");
  ok(S.draftInstructions("2026-10-13").includes("2026-10-13") && S.draftInstructions("2026-10-13").includes('"kind":"event|todo"'), "JSONだけを返す下書き指示を作る");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
