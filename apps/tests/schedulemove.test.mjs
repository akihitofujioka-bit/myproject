/*
 * 書類トラッカーから予定アプリへ会議・予定を引っ越す処理のテスト。
 * ブラウザを使わず、偽物の localStorage で確認する。
 *
 *   node apps/tests/schedulemove.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/schedulemove.js"), "utf8"))(g);
const Move = g.ScheduleMove;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

function fakeStorage(initial, failKey) {
  const values = { ...initial };
  const writes = [];
  return {
    values,
    writes,
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : null;
    },
    setItem(key, value) {
      writes.push(key);
      if (key === failKey) throw new Error(key + " を保存できません");
      values[key] = String(value);
    },
    removeItem(key) {
      delete values[key];
    }
  };
}

function json(value) {
  return JSON.stringify(value);
}

console.log("== 会議・予定だけを引っ越す ==");
{
  const original = {
    version: 1,
    items: [
      { id: "m1", kind: "会議", title: "星空委員会", dueOn: "2026-10-12" },
      { id: "d1", kind: "書類", title: "青空調査票", dueOn: "2026-10-13" },
      { id: "p1", kind: "予定", title: "若葉公園の下見", dueOn: "2026-10-14" },
      { id: "r1", kind: "回覧", title: "虹色だより", dueOn: "2026-10-15" },
      { id: "a1", kind: "申請", title: "月見台使用申請", dueOn: "2026-10-16" }
    ],
    calIds: { "meeting-m1": "EVENT-1" }
  };
  const raw = json(original);
  const storage = fakeStorage({ "docs-tracker.v1": raw });
  const result = Move.run(storage);
  const schedule = JSON.parse(storage.values["schedule.v1"]);
  const docs = JSON.parse(storage.values["docs-tracker.v1"]);

  ok(result.moved === 2 && result.skipped === false && result.error === "", "2件を引っ越した結果を返す");
  ok(schedule.version === 1 && schedule.items.map((item) => item.id).join(",") === "m1,p1",
    "会議・予定だけが schedule.v1 に移る");
  ok(docs.items.map((item) => item.id).join(",") === "d1,r1,a1",
    "書類・回覧・申請は docs-tracker.v1 に残る");
  ok(storage.values["docs-tracker.v1.backup-2026-10"] === raw, "控えは元の文字列と同じ");
  ok(schedule.calIds && schedule.calIds["meeting-m1"] === "EVENT-1", "カレンダーとの対応表（calIds）も予定へ写す");
  ok(storage.writes.join(",") === "docs-tracker.v1.backup-2026-10,schedule.v1,docs-tracker.v1",
    "控え、予定、書類の順で保存する");

  const afterFirst = { ...storage.values };
  const second = Move.run(storage);
  ok(second.moved === 0 && second.skipped === true && second.error === "", "2回目は何もしない");
  ok(JSON.stringify(storage.values) === JSON.stringify(afterFirst), "2回目に保存内容を変えない");
}
{
  const original = json({ version: 1, items: [{ id: "m0", kind: "会議", title: "朝凪会議" }] });
  const oldBackup = "以前に作った控え";
  const storage = fakeStorage({
    "docs-tracker.v1": original,
    "docs-tracker.v1.backup-2026-10": oldBackup
  });
  Move.run(storage);
  ok(storage.values["docs-tracker.v1.backup-2026-10"] === oldBackup, "既存の控えは上書きしない");
}

console.log("== 元データが無い・壊れている ==");
{
  const storage = fakeStorage({});
  const result = Move.run(storage);
  ok(result.moved === 0 && result.skipped === false && result.error === "", "元データが無くても正常に終わる");
  ok(storage.values["schedule.v1"] === json({ version: 1, items: [] }), "空の schedule.v1 を作る");
  ok(!Object.prototype.hasOwnProperty.call(storage.values, "docs-tracker.v1"), "無い docs-tracker.v1 は作らない");
}
{
  const broken = "{こわれたデータ";
  const storage = fakeStorage({ "docs-tracker.v1": broken });
  const result = Move.run(storage);
  ok(result.moved === 0 && result.skipped === false && result.error === "", "壊れた元データでも正常に終わる");
  ok(storage.values["schedule.v1"] === json({ version: 1, items: [] }), "壊れた元データでは予定を空にする");
  ok(storage.values["docs-tracker.v1"] === broken, "壊れた docs-tracker.v1 には触れない");
}

console.log("== 何度も取り込んで重なった予定は 1 件にまとめる ==");
{
  const meeting = (id, note) => ({ id, kind: "会議", title: "星空委員会", dest: "若葉会館", dueOn: "2026-10-12", note });
  const original = { v: 1, items: [
    meeting("m1", "13:30〜15:00 開始\n（カレンダーから登録）"),
    meeting("m2", "13:30〜15:00 開始\n（カレンダーから登録）"),
    meeting("m3", "10:00 開始"),
    { id: "p1", kind: "予定", title: "星空委員会", dest: "若葉会館", dueOn: "2026-10-12", note: "13:30 開始" },
    meeting("m4", "13:30〜15:00 開始\n（カレンダーから登録）")
  ] };
  const storage = fakeStorage({ "docs-tracker.v1": json(original) });
  const result = Move.run(storage);
  const schedule = JSON.parse(storage.values["schedule.v1"]);
  ok(schedule.items.map((item) => item.id).join(",") === "m1,m3,p1", "種別・件名・日付・開始時刻・場所が同じものは最初の 1 件だけ残す");
  ok(result.moved === 3, "まとめたあとの件数を返す");
  ok(JSON.parse(storage.values["docs-tracker.v1.backup-2026-10"]).items.length === 5, "控えには重なった予定も残る");
}

console.log("== 保存に失敗したときに元へ戻す ==");
{
  const original = json({ version: 1, items: [{ id: "p2", kind: "予定", title: "夕凪広場の点検" }] });
  const storage = fakeStorage({ "docs-tracker.v1": original }, "schedule.v1");
  const result = Move.run(storage);
  ok(result.moved === 0 && result.error !== "", "schedule.v1 の保存失敗でも理由を返す");
  ok(storage.values["docs-tracker.v1"] === original, "予定の保存失敗時も docs-tracker.v1 は元のまま");
  ok(!Object.prototype.hasOwnProperty.call(storage.values, "schedule.v1"), "保存に失敗した schedule.v1 を残さない");
}
{
  const original = json({
    version: 1,
    items: [
      { id: "m2", kind: "会議", title: "銀河連絡会" },
      { id: "d2", kind: "提出", title: "木漏れ日報告書" }
    ]
  });
  const storage = fakeStorage({ "docs-tracker.v1": original }, "docs-tracker.v1");
  const result = Move.run(storage);
  ok(result.moved === 0 && result.skipped === false && result.error !== "", "失敗の理由を返す");
  ok(storage.values["docs-tracker.v1"] === original, "docs-tracker.v1 は元のまま");
  ok(!Object.prototype.hasOwnProperty.call(storage.values, "schedule.v1"), "途中で作った schedule.v1 を消す");
}

console.log("== 予定の種別と重なりを1回だけ整理する ==");
{
  const original = json({
    version: 1,
    items: [
      { id: "a1", kind: "会議", title: "架空の星空会", dueOn: "2026-10-20", note: "13:30 開始" },
      { id: "a2", kind: "予定", title: "架空の星空会", dueOn: "2026-10-20", startTime: "13:30" },
      { id: "b1", kind: "会議", title: "架空の青空研修", dueOn: "2026-10-21", dest: "架空会館", calEventId: "CAL-1", note: "架空の資料を持参" },
      { id: "b2", kind: "予定", title: "架空の青空研修", dueOn: "2026-10-21", startTime: "10:00", endTime: "12:00", note: "懇親会あり" },
      { id: "c1", kind: "会議", title: "架空の若葉訪問", dueOn: "2026-10-22", startTime: "09:00" },
      { id: "c2", kind: "会議", title: "架空の若葉訪問", dueOn: "2026-10-22", startTime: "11:00" },
      { id: "d1", kind: "会議", title: "架空の月見会", dueOn: "2026-10-23" }
    ],
    calIds: { "架空の鍵": "架空の予定番号" }
  });
  const storage = fakeStorage({ "schedule.v1": original });
  const result = Move.unify(storage);
  const schedule = JSON.parse(storage.values["schedule.v1"]);
  const rich = schedule.items.find((item) => item.id === "b2");

  ok(result.merged === 2 && result.skipped === false && result.error === "", "時刻が同じ組と片方に時刻が無い組をまとめる");
  ok(schedule.items.length === 5, "2組をまとめて2件減らす");
  ok(schedule.items.every((item) => item.kind === "予定"), "会議を含むすべての種別を予定にする");
  ok(schedule.items.some((item) => item.id === "c1") && schedule.items.some((item) => item.id === "c2"), "開始時刻が違う予定はまとめない");
  ok(rich && rich.dest === "架空会館" && rich.calEventId === "CAL-1", "情報の多い方を残し、場所とカレンダー番号を引き継ぐ");
  ok(rich && rich.note === "懇親会あり\n架空の資料を持参", "消す方だけにあるメモを末尾へ引き継ぐ");
  ok(schedule.calIds["架空の鍵"] === "架空の予定番号", "予定以外の保存内容も保つ");
  ok(storage.values["schedule.v1.backup-unify-2026-10"] === original, "変更前の控えを作る");
  ok(storage.values["migration.schedule-unify-2026-10"] === "1", "整理済みの印を付ける");

  const afterFirst = { ...storage.values };
  const second = Move.unify(storage);
  ok(second.merged === 0 && second.skipped === true && second.error === "", "2回目は何もしない");
  ok(JSON.stringify(storage.values) === JSON.stringify(afterFirst), "2回目に保存内容を変えない");
}
{
  const storage = fakeStorage({ "schedule.v1": json({ version: 1, items: [
    { id: "f1", kind: "予定", title: "架空の朝空講座", dueOn: "2026-10-25", dest: "架空の広場", note: "懇親会あり", calEventId: "CAL-2" },
    { id: "f2", kind: "予定", title: "架空の朝空講座", dueOn: "2026-10-25", startTime: "10:00" },
    { id: "f3", kind: "予定", title: "架空の朝空講座", dueOn: "2026-10-25", startTime: "11:00" }
  ] }) });
  Move.unify(storage);
  const items = JSON.parse(storage.values["schedule.v1"]).items;
  ok(items.length === 2, "時刻なしを1件へまとめた後も、異なる2つの開始時刻はまとめない");
}
{
  const original = json({ version: 1, items: [
    { id: "e1", kind: "会議", title: "架空の夕空会", dueOn: "2026-10-24", note: "14:00 開始" },
    { id: "e2", kind: "予定", title: "架空の夕空会", dueOn: "2026-10-24", startTime: "14:00" }
  ] });
  const storage = fakeStorage({ "schedule.v1": original }, "schedule.v1");
  const result = Move.unify(storage);
  ok(result.merged === 1 && result.skipped === false && result.error !== "", "保存失敗でも、まとめる予定だった件数と理由を返す");
  ok(storage.values["schedule.v1"] === original, "保存失敗では schedule.v1 を元のままにする");
  ok(!Object.prototype.hasOwnProperty.call(storage.values, "migration.schedule-unify-2026-10"), "保存失敗では整理済みの印を付けない");
}
{
  const storage = fakeStorage({ "schedule.v1": "{こわれた予定" });
  const result = Move.unify(storage);
  ok(result.merged === 0 && result.error === "", "壊れた予定データでは内容を変えずに終わる");
  ok(storage.values["schedule.v1"] === "{こわれた予定" && storage.values["migration.schedule-unify-2026-10"] === "1", "壊れた予定データには整理済みの印だけ付ける");
}

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
