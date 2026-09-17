/*
 * apps/shared/meeting.js（会議の開催通知から日時・場所・懇親会を取り出す）のテスト。ブラウザ不要。
 *
 *   node apps/tests/meeting.test.mjs
 *
 * fixtures/meeting-*.txt は、自治体でよくある開催通知の書き方を模したもの。
 * 実際の通知は書き方がまちまちなので、取り出した内容は必ず人が確認してから登録する。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const FIX = path.join(ROOT, "apps/tests/fixtures");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/meeting.js"), "utf8"))(g);
const M = g.Meeting;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

// 年の書かれていない日付の判定に使う「今日」を固定する
const TODAY = new Date(2026, 8, 17);
const load = (name) => fs.readFileSync(path.join(FIX, `meeting-${name}.txt`), "utf8").split("\n");
const parse = (name) => M.parse(load(name), { today: TODAY });

console.log("== 日付 ==");
ok(M.findDate("令和8年10月15日(木)", TODAY).value === "2026-10-15", "令和の年号");
ok(M.findDate("2026年11月7日(金)", TODAY).value === "2026-11-07", "西暦");
ok(M.findDate("2026/11/07", TODAY).value === "2026-11-07", "スラッシュ区切り");
ok(M.findDate("10月3日(金)", TODAY).value === "2026-10-03", "年が無ければ今年（今日より先）");
ok(M.findDate("1月5日", TODAY).value === "2027-01-05", "年が無く今年では過ぎている場合は翌年");
ok(M.findDate("10月3日", TODAY).confidence === "medium", "年が無い日付は確度を下げる");
ok(M.findDate("2026年2月30日", TODAY) === null, "ありえない日付は採らない");
ok(M.findDate("出席者は10名です", TODAY) === null, "日付でない数字を拾わない");

console.log("== 時刻 ==");
ok(M.findTimes("午後1時30分から").start === "13:30", "午後1時30分 → 13:30");
ok(M.findTimes("午前10時").start === "10:00", "午前10時 → 10:00");
ok(M.findTimes("午後2時").start === "14:00", "午後2時 → 14:00");
ok(M.findTimes("14:00~16:00").start === "14:00", "開始時刻（範囲）");
ok(M.findTimes("14:00~16:00").end === "16:00", "終了時刻（範囲）");
ok(M.findTimes("午後1時30分~午後3時").end === "15:00", "日本語の範囲");
ok(M.findTimes("13:30").start === "13:30", "24時間表記");
ok(M.findTimes("議題は3件です").start === null, "時刻でない数字を拾わない");

console.log("== 場所 ==");
ok(M.findPlace(["場所 村民会館 2階 第1会議室"]).value === "村民会館 2階 第1会議室", "「場所」の行");
ok(M.findPlace(["会 場  高知県立ふれあいセンター"]).value === "高知県立ふれあいセンター",
  "「会 場」のように字の間に空白があっても読む");
ok(M.findPlace(["場所", "議会棟 委員会室"]).value === "議会棟 委員会室", "ラベルだけの行なら次の行を見る");
ok(M.findPlace(["日時 10月3日"]) === null, "場所の記載が無ければ null");

console.log("== 懇親会 ==");
ok(M.findSocial(["なお、閉会後に懇親会を予定しております。(会費 5,000円)"]).has === true, "懇親会あり");
ok(M.findSocial(["なお、閉会後に懇親会を予定しております。(会費 5,000円)"]).fee === 5000, "会費を読む");
ok(M.findSocial(["※ 懇親会は行いません。"]).has === false, "「行いません」は無し");
ok(M.findSocial(["※ 懇親会は行いません。"]).stated === true, "無いと書いてあることを区別する");
ok(M.findSocial(["議題 1 議案第45号"]).stated === false, "記載が無いことも区別する");
ok(M.findSocial(["終了後、意見交換会を開催します(会費 4,000円)"]).has === true, "意見交換会も懇親会として扱う");

console.log("== 実際の通知（3種）==");
{
  const a = parse("a_committee");
  ok(a.length === 1, "委員会の通知：1件");
  ok(a[0].title === "日高村議会 総務常任委員会", "会議名（「開催通知」を落とす）");
  ok(a[0].date === "2026-10-15" && a[0].startTime === "13:30", "日付と開始時刻");
  ok(a[0].place === "村民会館 2階 第1会議室", "場所");
  ok(a[0].social.has === true && a[0].social.fee === 5000, "懇親会あり・会費5,000円");

  const b = parse("b_renraku");
  ok(b.length === 1, "総会の案内：1件");
  ok(b[0].date === "2026-11-07", "日付");
  ok(b[0].startTime === "14:00" && b[0].endTime === "16:00", "開始と終了");
  ok(b[0].place === "高知県立ふれあいセンター 大会議室", "会場");
  ok(b[0].social.has === false && b[0].social.stated === true, "懇親会なしと明記");

  const c = parse("c_multi");
  ok(c.length === 2, "1枚に2つの会議 → 2件に分ける");
  ok(c[0].title === "議会運営委員会" && c[0].date === "2026-10-03" && c[0].startTime === "10:00", "1件目");
  ok(c[1].title === "経済建設厚生常任委員会" && c[1].date === "2026-10-09" && c[1].startTime === "14:00", "2件目");
  ok(c[0].place === "議会棟 委員会室" && c[1].place === "村民会館 第2会議室", "それぞれの場所");
  ok(c[0].social.has === false && c[1].social.has === true, "懇親会の有無を会議ごとに分ける");
  ok(c[1].social.fee === 4000, "2件目の会費");
}

console.log("== 読み取れないもの ==");
ok(M.parse(["ありがとうございました"], { today: TODAY }).length === 0, "会議でない文書からは何も返さない");
ok(M.parse([], { today: TODAY }).length === 0, "空でも落ちない");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
