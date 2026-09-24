/*
 * カレンダーへの直接書き込み（apps/shared/calendarwrite.js）の確認。
 *
 *   node apps/tests/calendarwrite.test.mjs
 *
 * 見ているのは次の3つ。ブラウザも iPhone も使わず、Node だけで動く。
 *  - ブラウザでは使えない判定になり、.ics 経由に切り替わること
 *  - 許可を求める順番（許可済みなら聞き直さない）
 *  - 前回の識別子を渡し、戻ってきた識別子を鍵ごとに受け取れること
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

function load(win) {
  new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/calendarwrite.js"), "utf8"))(win);
  return win;
}

// iPhone アプリの中を模した window を作る。calls に呼び出しの記録が残る
function nativeWindow(responses) {
  const calls = [];
  const win = {
    Capacitor: {
      isNativePlatform: () => true,
      nativePromise: (plugin, method, args) => {
        calls.push({ plugin, method, args });
        const res = responses[method];
        return res instanceof Error ? Promise.reject(res) : Promise.resolve(res);
      }
    }
  };
  load(win);
  win.__calls = calls;
  return win;
}

/* ---------- ブラウザ ---------- */
console.log("== ブラウザで開いたとき ==");
{
  const win = load({});
  ok(win.CalendarWrite.available() === false, "使えない判定になる（.ics 経由に切り替わる）");
  const res = await win.CalendarWrite.save([{ key: "a", date: "2026-10-01", title: "会議" }]);
  ok(res.ok === false && res.reason === "not-native", "書き込まずに理由を返す");
}

/* ---------- 許可のやりとり ---------- */
console.log("== 許可のやりとり ==");
{
  const win = nativeWindow({
    isSupported: { supported: true, authorized: true },
    saveEvents: { ok: true, saved: [{ key: "mtg-1", eventId: "E1", updated: false }], failed: [] }
  });
  await win.CalendarWrite.save([{ key: "mtg-1", date: "2026-10-01", title: "会議" }]);
  ok(!win.__calls.some((c) => c.method === "requestAccess"), "許可済みなら聞き直さない");
}
{
  const win = nativeWindow({
    isSupported: { supported: true, authorized: false },
    requestAccess: { granted: true },
    saveEvents: { ok: true, saved: [{ key: "mtg-1", eventId: "E1" }], failed: [] }
  });
  const res = await win.CalendarWrite.save([{ key: "mtg-1", date: "2026-10-01", title: "会議" }]);
  ok(win.__calls.some((c) => c.method === "requestAccess"), "未許可なら一度だけ許可を求める");
  ok(res.ok === true && res.ids["mtg-1"] === "E1", "許可されたら書き込める");
}
{
  const win = nativeWindow({
    isSupported: { supported: true, authorized: false },
    requestAccess: { granted: false, reason: "ユーザーが拒否" }
  });
  const res = await win.CalendarWrite.save([{ key: "mtg-1", date: "2026-10-01", title: "会議" }]);
  ok(res.ok === false && res.reason === "not-authorized", "断られたら書き込まない（.ics 経由に切り替わる）");
  ok(!win.__calls.some((c) => c.method === "saveEvents"), "断られたら保存も呼ばない");
}

/* ---------- 重複させないための識別子 ---------- */
console.log("== 重複させないための識別子 ==");
{
  const win = nativeWindow({
    isSupported: { supported: true, authorized: true },
    saveEvents: {
      ok: true,
      saved: [{ key: "mtg-1", eventId: "E1", updated: true }, { key: "doc-2", eventId: "E2", updated: false }],
      failed: []
    }
  });
  const res = await win.CalendarWrite.save([
    { key: "mtg-1", eventId: "E1", date: "2026-10-01", title: "会議", startTime: "13:30", alarms: [1440, 30] },
    { key: "doc-2", date: "2026-10-05", title: "回答期限" }
  ]);
  const sent = win.__calls.find((c) => c.method === "saveEvents").args.events;
  ok(sent.length === 2, "2件まとめて渡す");
  ok(sent[0].eventId === "E1", "前回の識別子をそのまま渡す（同じ予定を書き換えるため）");
  ok(res.ids["mtg-1"] === "E1" && res.ids["doc-2"] === "E2", "鍵ごとに識別子を受け取れる");
}
{
  // 日付の無いものは送らない
  const win = nativeWindow({
    isSupported: { supported: true, authorized: true },
    saveEvents: { ok: true, saved: [], failed: [] }
  });
  const res = await win.CalendarWrite.save([{ key: "x", title: "日付なし" }]);
  ok(res.reason === "no-events" && !win.__calls.length, "日付が無いものは送らない");
}
{
  // プラグイン側で失敗したとき
  const win = nativeWindow({
    isSupported: { supported: true, authorized: true },
    saveEvents: { ok: false, reason: "no-calendar", saved: [], failed: [] }
  });
  const res = await win.CalendarWrite.save([{ key: "x", date: "2026-10-01", title: "会議" }]);
  ok(res.ok === false && res.reason === "no-calendar" && Object.keys(res.ids).length === 0,
    "書き込めなかったときは理由を返す（呼び出し側が .ics に切り替える）");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
