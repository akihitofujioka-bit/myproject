/*
 * 名刺アプリの画面テスト（Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> node apps/tests/meishiapp.test.mjs
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
const MIME = { ".html": "text/html", ".js": "text/javascript", ".png": "image/png", ".webmanifest": "application/manifest+json" };
const server = http.createServer((request, response) => {
  let pathname = decodeURIComponent(new URL(request.url, "http://x").pathname);
  if (pathname.endsWith("/")) pathname += "index.html";
  const file = path.join(ROOT, pathname);
  if (!file.startsWith(ROOT)) { response.writeHead(404).end(); return; }
  fs.readFile(file, (error, data) => {
    if (error) { response.writeHead(404).end(); return; }
    response.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
    response.end(data);
  });
});
await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(0, "127.0.0.1", resolve);
});

const BASE = `http://127.0.0.1:${server.address().port}/apps/`;
const launchOptions = process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {};
const browser = await chromium.launch(launchOptions);
let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "PASS " : "FAIL ") + label);
  if (!condition) failures++;
};

// 架空データ。photo は 1×1 ピクセルの JPEG。
const fakeNative = () => {
  const photo = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9k=";
  window.__meishiFake = {
    camera: {
      cancelled: false,
      photo: photo,
      lines: [
        { text: "架空商事株式会社", height: 12 },
        { text: "未来企画部", height: 10 },
        { text: "課長", height: 9 },
        { text: "山田 架空", height: 20 },
        { text: "TEL 090-1111-2222", height: 8 },
        { text: "sample@example.invalid", height: 8 },
        { text: "〒100-0000 東京都架空区見本1-2", height: 8 }
      ]
    },
    library: {
      cancelled: false,
      photo: photo,
      boxes: [
        { text: "見本未来合同会社", x: 0, y: 0, width: 10, height: 8 },
        { text: "佐藤 見本", x: 0, y: 10, width: 10, height: 18 }
      ]
    }
  };
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      DocumentReader: {
        pickImage: options => {
          window.__pickImageOptions = options;
          return Promise.resolve(window.__meishiFake.library);
        }
      }
    },
    nativePromise: (plugin, method, options) => {
      if (plugin === "ReceiptScanner" && method === "scan") return Promise.resolve(window.__meishiFake.camera);
      if (plugin === "CalendarReader" && method === "isSupported") return Promise.resolve({ supported: true, authorized: localStorage.getItem("test.calendarDenied") !== "1" });
      if (plugin === "CalendarReader" && method === "requestAccess") {
        window.__calendarRequests = (window.__calendarRequests || 0) + 1;
        return Promise.resolve({ granted: false });
      }
      if (plugin === "CalendarReader" && method === "listCalendars") return Promise.resolve({ calendars: [{ id: "cal-1", title: "架空カレンダー" }] });
      if (plugin === "CalendarReader" && method === "listEvents") return Promise.resolve({ events: [
        { id: "cal-linked", calendarId: "cal-1", title: "架空の連携会議", date: "2026-10-15", startTime: "10:00" },
        { id: "cal-only", calendarId: "cal-1", title: "架空のカレンダー予定", date: "2026-10-15", startTime: "14:00" },
        { id: "cal-next", calendarId: "cal-1", title: "翌日の架空予定", date: "2026-10-16", startTime: "09:00" }
      ] });
      return Promise.resolve({ cancelled: true });
    }
  };
};

async function reset(page) {
  await page.goto(BASE + "meishi/index.html");
  await page.evaluate(async () => {
    localStorage.clear();
    await new Promise(resolve => {
      const request = indexedDB.deleteDatabase("meishi");
      request.onsuccess = request.onerror = request.onblocked = resolve;
    });
    localStorage.setItem("schedule.v1", JSON.stringify([
      { id: "schedule-linked", title: "架空の連携会議", dueOn: "2026-10-15", time: "10:00", calEventId: "cal-linked" },
      { id: "schedule-only", title: "壱師だけの架空会議", dueOn: "2026-10-15", time: "11:00" },
      { id: "schedule-next", title: "翌日の壱師予定", dueOn: "2026-10-16", time: "13:00" }
    ]));
  });
  await page.goto(BASE + "meishi/index.html");
  await page.waitForFunction(() => window.MeishiStore && document.getElementById("listView"));
}

const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.addInitScript(fakeNative);

try {
  await reset(page);
  ok(await page.evaluate(() => typeof window.ScanRouter?.pickLines === "function"), "ScanRouter を receiptscan.js より前に読み込む");

  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  ok(await page.locator("#f-name").inputValue() === "山田 架空", "撮影結果を氏名へ振り分ける");
  ok(await page.locator("#f-company").inputValue() === "架空商事株式会社", "撮影結果を会社へ振り分ける");
  ok((await page.locator("#editPhoto").getAttribute("src") || "").startsWith("blob:"), "確認画面に写真を出す");
  await page.fill("#f-receivedOn", "2026-10-15");
  await page.dispatchEvent("#f-receivedOn", "change");
  await page.waitForFunction(() => document.querySelectorAll("#meetingOptions input").length === 3);
  ok(await page.locator("#meetingOptions").innerText().then(text => text.includes("架空の連携会議") && text.includes("壱師だけの架空会議") && text.includes("架空のカレンダー予定")), "同日の壱師・カレンダー予定を重複なしで出す");
  await page.check('#meetingOptions input[value="schedule-only|"]');
  await page.click("#saveBtn");
  await page.waitForFunction(() => !document.getElementById("listView").hidden && document.getElementById("cardList").textContent.includes("山田 架空"));
  ok((await page.locator("#cardList").innerText()).includes("架空商事株式会社") && (await page.locator("#cardList").innerText()).includes("課長"), "保存後の一覧に氏名・会社・役職を出す");

  // 保存後に同じ壱師予定がカレンダーと結び付いても、保存済み予定を別候補として足さない。
  await page.evaluate(() => {
    const schedules = JSON.parse(localStorage.getItem("schedule.v1"));
    schedules.find(item => item.id === "schedule-only").calEventId = "cal-only";
    localStorage.setItem("schedule.v1", JSON.stringify(schedules));
  });
  await page.reload();
  await page.waitForFunction(() => document.getElementById("cardList").textContent.includes("山田 架空"));
  await page.getByRole("button", { name: /山田 架空/ }).click();
  await page.click("#editBtn");
  await page.waitForFunction(() => document.querySelectorAll("#meetingOptions input").length > 0);
  ok(await page.locator("#meetingOptions input").count() === 2, "予定: scheduleId が同じ保存済み予定と候補を重複表示しない");
  ok(await page.locator('#meetingOptions input[value="schedule-only|cal-only"]:checked').count() === 1, "予定: 後からカレンダー連携した同じ壱師予定を選択状態にする");
  await page.click("#cancelEditBtn");
  await page.evaluate(() => {
    const schedules = JSON.parse(localStorage.getItem("schedule.v1"));
    schedules.find(item => item.id === "schedule-only").calEventId = "";
    localStorage.setItem("schedule.v1", JSON.stringify(schedules));
  });
  await page.reload();
  await page.waitForFunction(() => document.getElementById("cardList").textContent.includes("山田 架空"));

  await page.click("#pickBtn");
  await page.waitForFunction(() => document.getElementById("f-name").value === "佐藤 見本");
  ok(await page.evaluate(() => window.__pickImageOptions.withPhoto === true), "写真選択で withPhoto を渡す");
  await page.click("#saveBtn");
  await page.waitForFunction(() => !document.getElementById("listView").hidden && document.getElementById("cardList").textContent.includes("佐藤 見本"));
  ok(true, "写真から読んだ名刺も保存して一覧へ戻る");

  await page.evaluate(() => { window.__meishiFake.camera = { cancelled: false, lines: [], photo: "" }; });
  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  ok((await page.locator("#readWarning").innerText()).includes("文字を読み取れませんでした。手で入力できます"), "0行なら手入力できる旨を出す");
  ok(await page.locator("#f-name").inputValue() === "", "0行なら空欄の確認画面を出す");
  await page.click("#cancelEditBtn");

  await page.evaluate(() => { window.__meishiFake.camera = { cancelled: false, lines: [{ text: "   ", height: 8 }], photo: "" }; });
  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  ok((await page.locator("#readWarning").innerText()).includes("文字を読み取れませんでした。手で入力できます"), "空白行だけなら手入力できる旨を出す");
  ok(await page.locator("#f-name").inputValue() === "", "空白行だけなら空欄の確認画面を出す");
  await page.click("#cancelEditBtn");

  // 先の検索が遅れて完了しても、後の検索結果を上書きしない。
  await page.evaluate(() => {
    window.__realMeishiList = window.MeishiStore.list;
    window.__completedListQueries = [];
    window.MeishiStore.list = options => new Promise(resolve => {
      const query = options.query;
      const delay = query === "先の検索" ? 100 : 10;
      const card = query === "先の検索"
        ? { id: "old-result", name: "古い検索結果", company: "", title: "" }
        : { id: "new-result", name: "新しい検索結果", company: "", title: "" };
      setTimeout(() => {
        window.__completedListQueries.push(query);
        resolve([card]);
      }, delay);
    });
  });
  await page.fill("#search", "先の検索");
  await page.fill("#search", "後の検索");
  await page.waitForFunction(() => window.__completedListQueries.length === 2);
  await page.waitForFunction(() => document.getElementById("cardList").textContent.includes("新しい検索結果"));
  ok(!(await page.locator("#cardList").innerText()).includes("古い検索結果"), "遅い古い検索結果で新しい検索結果を上書きしない");
  await page.evaluate(() => { window.MeishiStore.list = window.__realMeishiList; });

  await page.fill("#search", "架空商事");
  await page.waitForFunction(() => document.querySelectorAll("#cardList .person-card").length === 1);
  await page.click("#cardList .person-card");
  await page.waitForFunction(name => document.getElementById("detailName").textContent === name, "山田 架空");
  ok((await page.locator("#detailView").innerText()).includes("山田 架空"), "検索結果から詳細を開く");
  ok((await page.locator('#detailView a[href^="tel:"]').getAttribute("href")) === "tel:090-1111-2222", "電話を tel: リンクにする");
  ok((await page.locator('#detailView a[href^="mailto:"]').getAttribute("href")) === "mailto:sample@example.invalid", "メールを mailto: リンクにする");
  ok(await page.locator("#detailAddress a").count() === 0, "住所をリンクにしない");
  ok((await page.locator("#detailMeeting a").getAttribute("href")) === "../schedule/index.html?id=schedule-only", "壱師の予定を予定アプリへリンクする");

  await page.click("#editBtn");
  await page.fill("#f-title", "部長");
  await page.click("#saveBtn");
  await page.waitForFunction(() => !document.getElementById("detailView").hidden && document.getElementById("detailView").textContent.includes("部長"));
  ok(true, "名刺を編集できる");

  const id = await page.evaluate(() => window.MeishiStore.list({ query: "山田 架空" }).then(items => items[0].id));
  await page.goto(BASE + "meishi/index.html?id=" + encodeURIComponent(id));
  await page.waitForFunction(() => !document.getElementById("detailView").hidden);
  ok((await page.locator("#detailView").innerText()).includes("山田 架空"), "?id= で詳細を開く");

  await page.goto(BASE + "meishi/index.html?id=missing-id");
  await page.waitForFunction(() => !document.getElementById("listView").hidden && document.getElementById("toast").textContent.includes("見つかりませんでした"));
  ok(true, "無い id は一覧のまま通知する");

  await page.fill("#search", "");
  await page.getByRole("button", { name: /山田 架空/ }).click();
  await page.waitForFunction(name => document.getElementById("detailName").textContent === name, "山田 架空");
  await page.evaluate(() => { window.confirm = () => true; });
  await page.click("#deleteBtn");
  await waitAsync(page, async cardId => !(await window.MeishiStore.get(cardId)), id);
  ok(!(await page.locator("#cardList").innerText()).includes("山田 架空"), "確認後に名刺を削除できる");
  await page.evaluate(async () => {
    const cards = await window.MeishiStore.list({});
    await Promise.all(cards.map(card => window.MeishiStore.remove(card.id)));
  });
  await page.reload();
  await page.waitForFunction(() => !document.getElementById("listView").hidden);

  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  await page.fill("#f-name", "保存 失敗");
  await page.evaluate(() => {
    window.__realMeishiAdd = window.MeishiStore.add;
    window.MeishiStore.add = () => Promise.reject(new Error("架空の失敗"));
  });
  await page.click("#saveBtn");
  await page.waitForFunction(() => document.getElementById("toast").textContent.includes("名刺を保存できません"));
  ok(await page.locator("#editView").isVisible(), "保存失敗でも確認画面を閉じない");

  // 日付を変えたとき、古い選択を外して候補を入れ替える。
  await page.fill("#f-receivedOn", "2026-10-15");
  await page.dispatchEvent("#f-receivedOn", "change");
  await page.waitForFunction(() => document.querySelectorAll("#meetingOptions input").length === 3);
  await page.check('#meetingOptions input[value="schedule-only|"]');
  await page.fill("#f-receivedOn", "2026-10-16");
  await page.dispatchEvent("#f-receivedOn", "change");
  await page.waitForFunction(() => document.querySelectorAll("#meetingOptions input").length === 2);
  ok(await page.locator("#meetingOptions input:checked").count() === 0, "日付変更で無くなった予定の選択を外す");

  // カレンダーだけの予定と、消えた予定は詳細で文字だけにする。
  await page.evaluate(async () => {
    window.MeishiStore.add = window.__realMeishiAdd;
    const base = { name: "予定リンク確認", company: "架空確認社", department: "", title: "", phones: [], email: "", address: "", url: "", receivedOn: "2026-10-15", memo: "", photo: null };
    await window.MeishiStore.add(Object.assign({}, base, { url: "https://example.invalid/meishi", meeting: { scheduleId: "", calEventId: "cal-only", title: "架空のカレンダー予定", date: "2026-10-15" } }));
    await window.MeishiStore.add(Object.assign({}, base, { name: "消えた予定確認", url: "javascript:alert(1)", meeting: { scheduleId: "missing-schedule", calEventId: "", title: "消えた架空予定", date: "2026-10-15" } }));
  });
  await page.goto(BASE + "meishi/index.html");
  await page.waitForFunction(() => document.querySelectorAll("#cardList .person-card").length === 2);
  await page.getByRole("button", { name: /予定リンク確認/ }).click();
  await page.waitForFunction(name => document.getElementById("detailName").textContent === name, "予定リンク確認");
  ok(await page.locator("#detailMeeting a").count() === 0, "カレンダーだけの予定は文字だけにする");
  ok((await page.locator('#detailFields a[href="https://example.invalid/meishi"]').count()) === 1, "http(s) の URL はリンクにする");
  await page.click("#backToListBtn");
  await page.getByRole("button", { name: /消えた予定確認/ }).click();
  await page.waitForFunction(name => document.getElementById("detailName").textContent === name, "消えた予定確認");
  ok(await page.locator("#detailMeeting a").count() === 0, "消えた壱師の予定は文字だけにする");
  ok(await page.locator("#detailFields a").filter({ hasText: "javascript:alert(1)" }).count() === 0, "http(s) 以外の URL はリンクにしない");
  ok((await page.locator("#detailFields").innerText()).includes("javascript:alert(1)"), "http(s) 以外の URL は文字で出す");

  await page.click("#editBtn");
  ok((await page.locator("#meetingOptions input:checked").count()) === 1, "候補から消えた保存済み予定を編集画面で選択したまま出す");
  ok((await page.locator("#meetingOptions").innerText()).includes("2026-10-15 消えた架空予定"), "候補から消えた保存済み予定に日付と予定名を出す");
  await page.click("#saveBtn");
  await page.waitForFunction(() => !document.getElementById("detailView").hidden);
  const missingMeeting = await page.evaluate(() => window.MeishiStore.list({ query: "消えた予定確認" }).then(items => items[0].meeting));
  ok(missingMeeting && missingMeeting.scheduleId === "missing-schedule" && missingMeeting.title === "消えた架空予定", "候補から消えた予定を何も変えずに保存しても保持する");

  // 未許可のときは、開いただけでは許可を求めず、確認画面を開いたときに 1 回だけ求める。
  await page.evaluate(() => localStorage.setItem("test.calendarDenied", "1"));
  await page.goto(BASE + "meishi/index.html");
  await page.waitForFunction(() => window.MeishiStore && document.getElementById("listView"));
  await page.waitForTimeout(200);
  ok(await page.evaluate(() => (window.__calendarRequests || 0) === 0), "開いただけではカレンダーの許可を求めない");
  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  await page.waitForFunction(() => window.__calendarRequests === 1);
  await page.click("#cancelEditBtn");
  await page.click("#shootBtn");
  await page.waitForFunction(() => !document.getElementById("editView").hidden);
  await page.waitForTimeout(200);
  ok(await page.evaluate(() => window.__calendarRequests === 1), "確認画面を開いたときに 1 回だけ許可を求める");
  await page.evaluate(() => localStorage.removeItem("test.calendarDenied"));

  const home = await browser.newPage();
  await home.goto(BASE + "index.html");
  ok(await home.getByRole("link", { name: /名刺/ }).count() === 1, "ホームに名刺の入口がある");
  await home.close();
  ok(errors.length === 0, "名刺画面で JS エラーがない" + (errors.length ? " " + errors.join(" / ") : ""));
} finally {
  await browser.close();
  server.close();
}

process.exit(failures ? 1 : 0);
