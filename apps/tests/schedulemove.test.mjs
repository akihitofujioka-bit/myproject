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

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
