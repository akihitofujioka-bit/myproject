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
  ok(S.range("今日から3日間の予定", "2026-10-13").from !== "2026-11-03", "3日間を3日の日付として読まない");
  ok(S.range("3日後の予定", "2026-10-13").from !== "2026-11-03", "3日後を3日の日付として読まない");
  ok(S.range("3日以内の予定", "2026-10-13").from !== "2026-11-03", "3日以内を3日の日付として読まない");
  ok(S.range("3日前の予定", "2026-10-13").from !== "2026-11-03", "3日前を3日の日付として読まない");
  ok(S.range("3日ほどの予定", "2026-10-13").from !== "2026-11-03", "3日ほどを3日の日付として読まない");
  ok(sameRange("火曜の予定", "2026-10-13", "2026-10-13", "2026-10-13"), "曜日だけなら今日以降で最初の日");
  ok(sameRange("来週火曜の予定", "2026-10-13", "2026-10-20", "2026-10-20"), "来週の曜日を選ぶ");
  ok(sameRange("来週の火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "来週と曜日の間の助詞を許す");
  ok(sameRange("来週は火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "来週と曜日の間の別の助詞も許す");
  ok(sameRange("来週の朝火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "来週と曜日の間の2字を許す");
  ok(sameRange("来週、火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "来週と曜日の間の読点を許す");
  ok(sameRange("来週の午後の火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "来週と曜日の間の4字を許す");
  ok(sameRange("来週の午後、火曜", "2026-10-13", "2026-10-20", "2026-10-20"), "4字までの語の後にある読点も許す");
  ok(sameRange("来週。火曜", "2026-10-13", "2026-10-13", "2026-10-13"), "句点をまたいだ曜日は来週として読まない");
  ok(sameRange("来週\n火曜", "2026-10-13", "2026-10-13", "2026-10-13"), "改行をまたいだ曜日は来週として読まない");
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
        { id: "cal-1", calendarId: "calendar-1", title: "重複する予定", date: "2026-10-20", startTime: "10:00", endTime: "12:00", place: "別室" },
        { id: "cal-2", calendarId: "calendar-1", title: "架空の外部予定", date: "2026-10-20", startTime: "09:00", endTime: "09:30", place: "第2会議室" },
        { id: "cal-3", calendarId: "calendar-1", title: "架空の終日行事", date: "2026-10-21", startTime: "", endTime: "", place: "中央広場" }
      ],
      todos: [{ title: "架空の資料提出", dueOn: "2026-10-22" }]
    }
  );
  ok(list.count === 5 && !list.cut, "実際のカレンダー形式でも結び付いた予定を1件にまとめる");
  ok(list.text.split("\n")[0] === "10/20(火) 9:00-9:30 架空の外部予定 @第2会議室", "日付・開始時刻順で予定を書く");
  ok(list.text.includes("10/20(火) 10:00-12:00 架空の委員会 @第1会議室"), "予定アプリの時刻と場所を書く");
  ok(list.text.includes("10/21(水) 架空の終日行事 @中央広場"), "開始時刻が空のカレンダー予定を終日の行として書く");
  ok(list.text.includes("10/22(木) 期限 架空の資料提出（TODO）"), "期限付きのTODOを書く");

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

  const multiDayEvents = [{
    id: "cal-multi", title: "架空の研修", date: "2026-10-20", endDate: "2026-10-22",
    startTime: "10:00", endTime: "15:00", place: "架空の研修所"
  }];
  const multiDay = S.lines(
    { from: "2026-10-20", to: "2026-10-22" },
    { items: [], calendarEvents: multiDayEvents, todos: [] }
  );
  ok(multiDay.count === 3 && multiDay.text.split("\n").length === 3, "複数日の予定を重なる各日に展開する");
  ok(multiDay.text.includes("10/20(火) 10:00 架空の研修 @架空の研修所"), "複数日予定の開始時刻は初日だけに書く");
  ok(multiDay.text.includes("10/21(水) 架空の研修（続き） @架空の研修所"), "複数日予定の中日は続きとして終日扱いで書く");
  ok(multiDay.text.includes("10/22(木) -15:00 架空の研修（続き） @架空の研修所"), "複数日予定の終了時刻は最終日だけに書く");

  const expanded = S.expandEvents({ from: "2026-10-20", to: "2026-10-22" }, multiDayEvents);
  ok(expanded.length === 3 && expanded[1].allDay && expanded[0].continuesAfter && expanded[2].continuesBefore, "空き時間用にも複数日予定を日ごとに展開する");

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
  const multiDayFree = S.freeSlots({ from: "2026-10-20", to: "2026-10-22" }, expanded);
  ok(multiDayFree === "10/20(火) 空き 8:30-10:00\n10/21(水) 終日の予定あり\n10/22(木) 空き 15:00-17:15", "複数日予定を初日は開始後、最終日は終了前まで埋まった時間として扱う");
  ok(S.freeSlots(
    { from: "2026-10-20", to: "2026-10-22" },
    expanded,
    { compact: true }
  ) === "10/20(火) 空きあり\n10/22(木) 空きあり", "短縮時は空きのある日だけを書く");
  ok(S.wantsFree("来週は空いていますか") && !S.wantsFree("来週の予定"), "空き時間を求める言葉を判定する");
  ok(!S.wantsDraft("今日のTODOを教えて"), "TODOを尋ねるだけなら下書きにしない");
  ok(!S.wantsDraft("TODOある？"), "TODOの有無を尋ねるだけなら下書きにしない");
  ok(!S.wantsDraft("登録済みの予定を教えて"), "登録済みの予定を尋ねるだけなら下書きにしない");
  ok(!S.wantsDraft("登録済みの予定を教えてください"), "丁寧な言い方で尋ねるだけなら下書きにしない");
  ok(!S.wantsDraft("追加の予定はありますか"), "ありますかで尋ねるだけなら下書きにしない");
  ok(S.wantsDraft("来週火曜10時に打合せを入れてもらえますか？"), "？で終わっても頼む言い方なら下書きにする");
  ok(!S.wantsDraft("追加の予定は？"), "追加の予定の有無を尋ねるだけなら下書きにしない");
  ok(S.wantsDraft("金曜までに資料提出をTODOに追加して"), "TODOへの追加依頼を下書きにする");
  ok(S.wantsDraft("資料提出をToDoに追加して"), "英字の大小が違うTODOも判定する");
  ok(S.wantsDraft("資料提出をトゥードゥーに追加して"), "読み上げたTODOも判定する");
  ok(S.wantsDraft("資料提出をやることに追加して"), "旧表現の追加依頼も判定する");
  ok(S.wantsDraft("来週火曜10時に打合せを入れて"), "予定への追加依頼を下書きにする");

  const charLimitedSource = S.lines(
    { from: "2026-10-20", to: "2026-10-20" },
    { items: [
      { title: "架空の予定一", dueOn: "2026-10-20" },
      { title: "架空の予定二", dueOn: "2026-10-20" }
    ], calendarEvents: [], todos: [] }
  );
  const firstLimitedLine = charLimitedSource.text.split("\n")[0];
  const charLimited = S.lines(
    { from: "2026-10-20", to: "2026-10-20" },
    { items: [
      { title: "架空の予定一", dueOn: "2026-10-20" },
      { title: "架空の予定二", dueOn: "2026-10-20" }
    ], calendarEvents: [], todos: [] },
    {},
    { maxChars: firstLimitedLine.length }
  );
  ok(charLimited.text === firstLimitedLine && charLimited.count === 1 && charLimited.cut, "一覧は文字数上限を超える行の前で切る");

  const fenced = S.checkDraft(
    "説明です。\n```json\n{\"kind\":\"event\",\"title\":\"架空の打合せ\",\"date\":\"2026-10-21\",\"start\":\"10:00\"}\n```\n以上です。",
    "来週火曜10時に架空の打合せを入れて",
    "2026-10-13"
  );
  ok(fenced.ok && fenced.draft.date === "2026-10-20", "説明やJSON囲みの中の最初のオブジェクトを読み、質問の日付を優先する");

  const assistedDate = S.checkDraft(
    '{"kind":"event","title":"架空の打合せ","date":"2026-10-21","start":"10:00"}',
    "来週の火曜10時に架空の打合せを入れて",
    "2026-10-13"
  );
  ok(assistedDate.ok && assistedDate.draft.date === "2026-10-20", "下書きでも助詞を挟んだ来週の曜日を規則側で選ぶ");

  const todoDraft = S.checkDraft(
    '{"kind":"todo","title":"架空の資料確認","date":"2026-10-20"}',
    "架空の資料確認をTODOに追加",
    "2026-10-13"
  );
  ok(todoDraft.ok && todoDraft.draft.kind === "todo", "TODOの下書きを保つ");
  const oldTodoDraft = S.checkDraft(
    '{"kind":"やること","title":"架空の旧回答","date":"2026-10-20"}',
    "架空の旧回答をTODOに追加",
    "2026-10-13"
  );
  ok(oldTodoDraft.ok && oldTodoDraft.draft.kind === "todo", "AIの旧表現をTODOとして受け付ける");

  const reversedTime = S.checkDraft(
    '{"kind":"event","title":"架空の面談","date":"2026-10-20","start":"10:00","end":"09:30"}',
    "架空の面談を追加",
    "2026-10-13"
  );
  ok(reversedTime.ok && reversedTime.draft.start === "10:00" && reversedTime.draft.end === "", "終了が開始より前なら終了を空欄にする");

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
  ok(S.freeSlots(
    { from: "2026-10-20", to: "2026-10-20" },
    [{ date: "2026-10-20", start: "08:30", end: "17:15" }]
  ) === "10/20(火) 空きなし", "勤務時間内に空きがない日を示す");
  ok(S.draftInstructions("2026-10-13").includes("2026-10-13") && S.draftInstructions("2026-10-13").includes('"kind":"event|TODO"'), "JSONだけを返す下書き指示を作る");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
