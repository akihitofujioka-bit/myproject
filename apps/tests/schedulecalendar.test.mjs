/*
 * 予定アプリと iPhone のカレンダーの結び付きの確認（偽のカレンダーを使う。Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> CHROMIUM_PATH=<headless_shell> node apps/tests/schedulecalendar.test.mjs
 *
 * 壱師で件名や時刻を編集すると、元のカレンダーの予定がオレンジで重ねて残り、
 * 「カレンダーに入れる」で新しい予定ができてしまう不具合（2026-10-13）が戻らないようにする。
 */
import http from "node:http"; import fs from "node:fs"; import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright が見つかりません。`npm i -D playwright && npx playwright install chromium` を実行してください。");
  process.exit(1);
}
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const types = { ".html": "text/html", ".js": "text/javascript", ".png": "image/png" };
const srv = http.createServer((q, r) => { const p = path.join(ROOT, decodeURIComponent(q.url.split("?")[0])); fs.readFile(p, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" }); r.end(d); }); }).listen(0);
const base = `http://127.0.0.1:${srv.address().port}/apps/`;
const b = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}); const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
const errs = []; pg.on("pageerror", e => errs.push(e.message)); pg.on("dialog", d => d.accept());
let fail = 0; const ok = (c, l) => { console.log((c ? "PASS " : "FAIL ") + l); if (!c) fail++; };
const today = new Date().toISOString().slice(0, 10);
// 偽のカレンダー: 予定 E9 が 1 件。書き込みは記録して、同じ番号を返す（書き換え）か新しい番号を返す（新規）
await pg.addInitScript((d) => {
  window.__cal = { events: [{ id: "E9", calendarId: "C1", title: "架空の研修", date: d, startTime: "10:00", endTime: "11:00", place: "" }], saves: [] };
  window.Capacitor = { isNativePlatform: () => true, nativePromise: (plugin, method, args) => {
    const c = window.__cal;
    if (method === "isSupported") return Promise.resolve({ supported: true, authorized: true });
    if (method === "listCalendars") return Promise.resolve({ calendars: [{ id: "C1", title: "仕事", color: "#FF9500" }] });
    if (method === "listEvents") return Promise.resolve({ events: c.events.map(e => ({ ...e })) });
    if (method === "saveEvents") { c.saves.push(args.events);
      return Promise.resolve({ ok: true, saved: args.events.map(ev => { const id = ev.eventId || "NEW" + c.saves.length;
        const hit = c.events.find(e => e.id === id); const data = { id, calendarId: "C1", title: ev.title, date: ev.date, startTime: ev.startTime, endTime: ev.endTime, place: ev.location };
        if (hit) Object.assign(hit, data); else c.events.push(data); return { key: ev.key, eventId: id }; }) }); }
    if (method === "deleteEvents") { const ids = args.eventIds; c.deletes = (c.deletes || []).concat(ids);
      c.events = c.events.filter(e => ids.indexOf(e.id) < 0); return Promise.resolve({ ok: true, deleted: ids, missing: [], failed: [] }); }
    return Promise.resolve({ cancelled: true });
  } };
}, today);
await pg.goto(base + "schedule/index.html");
await pg.evaluate((d) => { localStorage.clear(); localStorage.setItem("schedule.v1", JSON.stringify({ version: 1, calIds: {}, items: [{ id: "a1", kind: "予定", title: "架空の研修", dueOn: d, note: "10:00〜11:00 開始" }] })); }, today);
await pg.reload(); await pg.waitForTimeout(600);
const orange = () => pg.$$eval("#listView li.external", ls => ls.map(l => l.textContent.trim().slice(0, 20)));
ok((await orange()).length === 0, "最初は、同じ予定がカレンダーの表示で重ならない");
ok(await pg.evaluate(() => JSON.parse(localStorage.getItem("schedule.v1")).items[0].calEventId) === "E9", "読み込んだとき、カレンダーの予定の番号を覚える");
// 編集で件名と時刻を変える
await pg.click('#listView li[data-id="a1"] button[data-action="edit"]'); await pg.waitForTimeout(500);
await pg.fill("#f-title", "架空の研修（変更）"); await pg.fill("#f-start", "13:00"); await pg.fill("#f-end", "14:00");
await pg.click("#submitBtn"); await pg.waitForTimeout(600);
ok((await orange()).length === 0, "編集しても、元のカレンダーの予定がオレンジで残らない（" + (await orange()).join(",") + "）");
// カレンダーに入れる → 元の E9 を書き換える
await pg.click('#listView li[data-id="a1"] button[data-action="calendar"]'); await pg.waitForTimeout(800);
const cal = await pg.evaluate(() => window.__cal);
ok(cal.saves.length === 1 && cal.saves[0][0].eventId === "E9", "カレンダーに入れると、元の予定（E9）を書き換える");
ok(cal.events.length === 1 && cal.events[0].title === "架空の研修（変更）" && cal.events[0].startTime === "13:00", "カレンダーの予定は 1 件のまま、中身が新しくなる");
ok((await orange()).length === 0, "書き込んだあとも、オレンジで重ならない");
// カレンダーアプリで予定を消して戻ってくると、オレンジの表示も消える
await pg.evaluate((d) => { window.__cal.events.push({ id: "E50", calendarId: "C1", title: "架空の祭り", date: d, startTime: "", endTime: "", place: "" }); }, today);
await pg.evaluate(() => document.dispatchEvent(new Event("visibilitychange"))); await pg.waitForTimeout(500);
ok((await orange()).length === 1, "カレンダーに足した予定は、戻ってきたときオレンジで出る");
await pg.evaluate(() => { window.__cal.events = window.__cal.events.filter((e) => e.id !== "E50"); });
await pg.evaluate(() => document.dispatchEvent(new Event("visibilitychange"))); await pg.waitForTimeout(500);
ok((await orange()).length === 0, "カレンダーで消して戻ってくると、オレンジの表示も消える");
// 予定を消すとき、カレンダーの予定も消すか聞き、はいならカレンダーからも消す
await pg.click('#listView li[data-id="a1"] button[data-action="delete"]'); await pg.waitForTimeout(600);
ok(await pg.evaluate(() => (window.__cal.deletes || []).join(",")) === "E9", "削除するとカレンダーの予定（E9）も消す");
ok((await orange()).length === 0, "削除したあと、カレンダーの予定がオレンジで残らない（" + (await orange()).join(",") + "）");
ok(await pg.evaluate(() => Object.values(JSON.parse(localStorage.getItem("schedule.v1")).calIds).indexOf("E9") < 0), "消した予定の番号を覚えたままにしない");
// 2 つ目の確認で「キャンセル」なら、一覧からだけ消し、カレンダーの予定は残す
await pg.evaluate((d) => { window.__cal.events.push({ id: "E60", calendarId: "C1", title: "架空の会議", date: d, startTime: "15:00", endTime: "16:00", place: "" });
  const data = JSON.parse(localStorage.getItem("schedule.v1")); data.items.push({ id: "a2", kind: "予定", title: "架空の会議", dueOn: d, note: "15:00〜16:00 開始", calEventId: "E60" });
  localStorage.setItem("schedule.v1", JSON.stringify(data)); }, today);
await pg.reload(); await pg.waitForTimeout(600);
pg.removeAllListeners("dialog"); let asked = 0;
pg.on("dialog", d => { asked++; if (asked === 1) d.accept(); else d.dismiss(); });
await pg.click('#listView li[data-id="a2"] button[data-action="delete"]'); await pg.waitForTimeout(600);
ok(asked === 2 && await pg.evaluate(() => (window.__cal.deletes || []).indexOf("E60") < 0), "キャンセルならカレンダーの予定は消さない");
ok((await orange()).length === 1, "一覧からだけ消すと、カレンダーの予定はオレンジで出る");
ok(errs.length === 0, "JS エラーなし " + errs.join(" / "));
await b.close(); srv.close(); process.exit(fail ? 1 : 0);
