/*
 * 予定アプリの名刺連携と ?id=（Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> node apps/tests/schedulemeishi.test.mjs
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { waitAsync } from "./tools/waitasync.mjs";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright が見つかりません。");
  process.exit(1);
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const types = { ".html": "text/html", ".js": "text/javascript", ".png": "image/png" };
const srv = http.createServer((q, r) => {
  const p = path.join(ROOT, decodeURIComponent(q.url.split("?")[0]));
  fs.readFile(p, (e, d) => {
    if (e) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
    r.end(d);
  });
});
await new Promise((resolve, reject) => {
  srv.once("error", reject);
  srv.listen(0, "127.0.0.1", resolve);
});

const base = `http://127.0.0.1:${srv.address().port}/apps/`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
let fail = 0;
const ok = (condition, label) => {
  console.log((condition ? "PASS " : "FAIL ") + label);
  if (!condition) fail++;
};
const schedule = {
  version: 1,
  calIds: {},
  dismissedHints: [],
  items: [
    { id: "meeting-a", title: "架空連携会議", dueOn: "2026-10-20", calEventId: "cal-a", note: "" },
    { id: "meeting-b", title: "架空名刺なし会議", dueOn: "2026-10-21", calEventId: "cal-b", note: "" }
  ]
};

const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const pg = await context.newPage();
await pg.addInitScript(value => {
  localStorage.clear();
  localStorage.setItem("schedule.v1", JSON.stringify(value));
}, schedule);

try {
  await pg.goto(base + "schedule/index.html");
  await pg.waitForFunction(() => window.MeishiStore && document.querySelector('[data-id="meeting-a"]'));
  await pg.evaluate(async () => {
    const baseCard = { department: "", title: "", email: "", phones: [], address: "", url: "", memo: "" };
    await window.MeishiStore.add(Object.assign({}, baseCard, {
      name: "架空 一郎", company: "架空商事", meeting: { scheduleId: "meeting-a", calEventId: "", title: "架空連携会議" }
    }));
    await window.MeishiStore.add(Object.assign({}, baseCard, {
      name: "架空 二郎", company: "空想企画", meeting: { scheduleId: "meeting-a", calEventId: "", title: "架空連携会議" }
    }));
    await window.MeishiStore.add(Object.assign({}, baseCard, {
      name: "架空 三郎", company: "見本制作", meeting: { scheduleId: "", calEventId: "cal-a", title: "架空連携会議" }
    }));
  });

  await pg.locator('[data-id="meeting-a"] [data-action="edit"]').first().click();
  await waitAsync(pg, () => document.querySelectorAll("#meetingPeopleList a").length === 3);
  const peopleText = await pg.locator("#meetingPeople").innerText();
  ok(["架空 一郎", "架空 二郎", "架空 三郎", "架空商事", "空想企画", "見本制作"].every(text => peopleText.includes(text)), "予定番号とカレンダー番号で結び付いた3人の氏名・会社が並ぶ");
  const firstLink = pg.locator("#meetingPeopleList a").first();
  const firstCardId = new URL(await firstLink.getAttribute("href"), pg.url()).searchParams.get("id");
  await firstLink.click();
  await pg.waitForURL(url => url.pathname.endsWith("/meishi/index.html") && url.searchParams.get("id") === firstCardId);
  ok(true, "名刺を押すと名刺アプリの詳細URLへ移る");

  await pg.goto(base + "schedule/index.html");
  await pg.locator('[data-id="meeting-b"] [data-action="edit"]').first().click();
  await waitAsync(pg, async () => (await window.MeishiStore.byMeeting({ scheduleId: "meeting-b", calEventId: "cal-b" })).length === 0);
  ok(await pg.locator("#meetingPeople").isHidden(), "名刺がない予定では欄を出さない");

  await pg.evaluate(() => {
    window.__meetingResolvers = {};
    window.MeishiStore.byMeeting = options => new Promise(resolve => {
      window.__meetingResolvers[options.scheduleId] = resolve;
    });
  });
  await pg.locator('[data-id="meeting-a"] [data-action="edit"]').first().click();
  await pg.locator('[data-id="meeting-b"] [data-action="edit"]').first().click();
  await pg.evaluate(() => {
    window.__meetingResolvers["meeting-b"]([{ id: "card-b", name: "架空 後着", company: "後着産業" }]);
    window.__meetingResolvers["meeting-a"]([{ id: "card-a", name: "架空 遅延", company: "遅延開発" }]);
  });
  await pg.waitForFunction(() => document.getElementById("meetingPeopleList").textContent.includes("架空 後着"));
  const switchedText = await pg.locator("#meetingPeopleList").innerText();
  ok(switchedText.includes("架空 後着") && !switchedText.includes("架空 遅延"), "予定を開き直した後は前の予定の遅い結果を出さない");

  await pg.goto(base + "schedule/index.html?id=meeting-a");
  await pg.waitForFunction(() => document.getElementById("formTitle").textContent === "予定を編集");
  ok(await pg.locator("#f-title").inputValue() === "架空連携会議", "?id= で指定した予定の編集フォームを開く");

  await pg.goto(base + "schedule/index.html?id=missing-meeting");
  await pg.waitForFunction(() => document.getElementById("toast").textContent.includes("見つかりませんでした"));
  ok(await pg.locator("#formTitle").innerText() === "予定を登録", "存在しない id では一覧のままにする");
  ok((await pg.locator("#toast").innerText()).includes("予定が見つかりませんでした"), "存在しない id を通知する");

  const broken = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await broken.addInitScript(value => {
    localStorage.setItem("schedule.v1", JSON.stringify(value));
    const failed = { open: () => {
      const request = {};
      setTimeout(() => {
        request.error = new Error("架空の保存先エラー");
        if (request.onerror) request.onerror();
      }, 0);
      return request;
    } };
    Object.defineProperty(window, "indexedDB", { configurable: true, value: failed });
  }, schedule);
  await broken.goto(base + "schedule/index.html?id=meeting-a");
  await broken.waitForFunction(() => document.getElementById("formTitle").textContent === "予定を編集");
  await broken.waitForTimeout(50);
  ok(await broken.locator("#meetingPeople").isHidden(), "名刺の保存先を開けないときは欄を出さない");
  await broken.fill("#f-title", "架空の修正版会議");
  ok(await broken.locator("#f-title").inputValue() === "架空の修正版会議", "名刺の保存先を開けなくても編集フォームを使える");
  await broken.close();
} finally {
  await context.close();
  await browser.close();
  srv.close();
}

process.exit(fail ? 1 : 0);
