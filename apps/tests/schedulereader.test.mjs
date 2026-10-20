/*
 * 予定の読み取り確認画面と「気づいたこと」の確認（偽のカレンダーを使う。Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> node apps/tests/schedulereader.test.mjs
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

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
const b = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const pg = await b.newPage({ viewport: { width: 390, height: 844 } });
const errs = [];
pg.on("pageerror", e => errs.push(e.message));
pg.on("dialog", d => d.accept());
let fail = 0;
const ok = (condition, label) => {
  console.log((condition ? "PASS " : "FAIL ") + label);
  if (!condition) fail++;
};

// 偽のカレンダーには、読み取り結果と重なる予定を 1 件置く。
await pg.addInitScript(() => {
  window.__cal = {
    events: [{
      id: "E7", calendarId: "C1", title: "架空の委員会", date: "2026-10-22",
      startTime: "10:00", endTime: "11:00", place: "架空会議室"
    }]
  };
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      DocumentReader: {
        pick: () => window.__doc.pickError
          ? Promise.reject(new Error(window.__doc.pickError))
          : Promise.resolve(window.__doc.pickResult || { cancelled: true }),
        hasShared: () => Promise.resolve(location.search.includes("testBanner=1")
          ? { has: true, name: "架空.pdf" }
          : { has: !!window.__doc.shared, name: window.__doc.shared ? window.__doc.shared.name : "" }),
        takeShared: () => {
          window.__doc.takeCount++;
          const result = window.__doc.shared;
          window.__doc.shared = null;
          return Promise.resolve(result || {});
        }
      }
    },
    nativePromise: (plugin, method) => {
      if (method === "isSupported") return Promise.resolve({ supported: true, authorized: true });
      if (method === "listCalendars") return Promise.resolve({ calendars: [{ id: "C1", title: "仕事", color: "#FF9500" }] });
      if (method === "listEvents") return Promise.resolve({ events: window.__cal.events.map(e => ({ ...e })) });
      return Promise.resolve({ cancelled: true });
    }
  };
  const sharedResult = location.search.includes("testShared=1") ? {
    name: "共有された架空.pdf", kind: "pdf", ocr: false, tables: [],
    lines: ["架空検討委員会", "日時 令和8年10月22日（木）午後1時30分から", "場所 架空市役所 第1会議室"]
  } : null;
  window.__doc = { pickResult: null, pickError: "", shared: sharedResult, takeCount: 0 };
});

try {
  await pg.goto(base + "schedule/index.html");
  await pg.evaluate(() => {
    localStorage.clear();
    localStorage.setItem("docs-tracker.v1", JSON.stringify({ v: 1, items: [], calIds: {} }));
  });
  await pg.reload();
  await pg.waitForTimeout(600);

  const tableResult = {
    name: "架空予定表.xlsx", kind: "xlsx", lines: [], ocr: false,
    tables: [[
      ["月日", "曜", "行事", "時間", "会場"],
      ["10月22日", "木", "架空の定例会", "10:00〜12:00", "議場"],
      ["10/28", "水", "架空の研修", "13時30分", "第1会議室"],
      ["", "", "（備考）", "", ""]
    ]]
  };
  await pg.evaluate(result => { window.__doc.pickResult = result; }, tableResult);
  await pg.click("#documentReadBtn");
  await pg.waitForFunction(() => document.querySelectorAll("#meetingForms .scan-result").length === 2);
  ok(await pg.locator("#meetingForms .scan-result").count() === 2, "Task 10: 予定表から 2 件出る");
  ok((await pg.locator("#meetingConfirmTitle").innerText()) === "ファイルから読み取った予定（確認して登録）", "Task 10: ファイル用の見出し");

  const noticeResult = {
    name: "架空通知.docx", kind: "docx", ocr: false, tables: [],
    lines: [
      "架空市 第3回 架空検討委員会の開催について",
      "日時 令和8年10月22日（木）午後1時30分から",
      "場所 架空市役所 第1会議室",
      "当日は資料を持参してください。",
      "出欠を10月20日（火）までに提出してください。",
      "問い合わせ 架空課 電話 03-0000-0000"
    ]
  };
  await pg.evaluate(result => { window.__doc.pickResult = result; }, noticeResult);
  await pg.click("#documentReadBtn");
  await pg.waitForFunction(() => document.querySelectorAll("#meetingForms .scan-result").length === 1);
  ok(await pg.locator(".m-date").inputValue() === "2026-10-22", "Task 10: 通知の日付");
  ok(await pg.locator(".m-todo").count() === 2, "Task 10: 通知のTODO候補が 2 件");
  ok((await pg.locator("#meetingForms").innerText()).includes("問い合わせ: 電話 03-0000-0000"), "Task 10: 通知の連絡先");

  await pg.evaluate(result => { window.__doc.pickResult = { ...result, ocr: true }; }, noticeResult);
  await pg.click("#documentReadBtn");
  await pg.waitForFunction(() => !document.getElementById("documentOcrNotice").hidden);
  ok((await pg.locator("#documentOcrNotice").innerText()).includes("特によく確かめてください"), "Task 10: OCR の注意");

  await pg.evaluate(() => { window.__doc.pickResult = { name: "空の架空.pdf", kind: "pdf", lines: [], tables: [], ocr: false }; });
  await pg.click("#documentReadBtn");
  await pg.waitForFunction(() => !document.getElementById("documentTextCard").hidden);
  ok((await pg.locator("#documentTextCard").innerText()).includes("取り出した文字"), "Task 10: 予定が無いときは取り出した文字の欄");
  ok(await pg.locator("#documentManualBtn").isVisible(), "Task 10: 予定が無いときは手入力ボタン");

  await pg.evaluate(() => { window.__doc.pickError = "ファイルが壊れているため読めませんでした"; });
  await pg.click("#documentReadBtn");
  await pg.waitForFunction(() => document.getElementById("toast").textContent.includes("ファイルが壊れているため読めませんでした"));
  ok((await pg.locator("#toast").innerText()).includes("このファイルは読めませんでした（ファイルが壊れているため読めませんでした）"), "Task 10: 読めない理由を知らせる");
  await pg.evaluate(() => { window.__doc.pickError = ""; });

  const shared = await pg.evaluate(async result => {
    window.__doc.shared = result;
    const first = await window.DocumentReader.takeShared();
    const second = await window.DocumentReader.takeShared();
    return { first, second };
  }, noticeResult);
  ok(shared.first && shared.first.name === "架空通知.docx" && shared.second === null, "Task 10: 共有ファイルは 1 回だけ取り出す");

  await pg.evaluate(() => window.scheduleApp.renderMeetings([{
    title: "読み取った架空の会議",
    date: "2026-10-22",
    startTime: "10:30",
    endTime: "11:30",
    place: "架空別室",
    social: { has: false, fee: null },
    source: "meeting",
    rows: [
      "当日は資料を持参",
      "出欠を10/20までに提出",
      "電話 03-0000-0000",
      "10月22日（水）"
    ]
  }]));

  const formText = await pg.locator("#meetingForms .scan-result").innerText();
  ok(formText.includes("10:00 の「架空の委員会」と重なります"), "Task 7: 重複の注意が出る");
  ok(formText.includes("10/22 は木曜ですが、通知には水曜とあります"), "Task 7: 曜日の食い違いが出る");
  ok(formText.includes("問い合わせ: 電話 03-0000-0000"), "Task 7: 連絡先の行が出る");
  ok(await pg.locator(".m-contact").isChecked(), "Task 7: 連絡先は最初から選ばれている");
  ok(await pg.locator(".m-todo").count() === 2, "Task 7: TODO候補が 2 件出る");
  ok(await pg.locator(".m-todo:checked").count() === 2, "Task 7: TODO候補は最初から選ばれている");

  await pg.locator(".m-todo").first().uncheck();
  await pg.click('[data-meeting-mode="app"]');
  const saved = await pg.evaluate(() => ({
    schedule: JSON.parse(localStorage.getItem("schedule.v1")),
    docs: JSON.parse(localStorage.getItem("docs-tracker.v1"))
  }));
  ok(saved.schedule.items.length === 1 && saved.schedule.items[0].note.includes("問い合わせ: 電話 03-0000-0000"), "Task 7: 予定のメモに選んだ連絡先が入る");
  ok(saved.docs.items.length === 1 && saved.docs.items[0].kind === "TODO", "Task 7: 選んだTODO 1 件だけが増える");
  ok(errs.length === 0, "Task 7: JS エラーなし " + errs.join(" / "));

  // 今日から 30 日以内の重なりだけを「気づいたこと」に出す。
  const addDays = days => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
  const dates = { near: addDays(5), phone: addDays(6), far: addDays(31) };
  await pg.evaluate(d => {
    localStorage.setItem("schedule.v1", JSON.stringify({
      version: 1,
      calIds: {},
      dismissedHints: [],
      items: [
        { id: "h1", kind: "予定", title: "架空の相談会", dueOn: d.near, note: "10:00〜11:00 開始" },
        { id: "h2", kind: "予定", title: "架空の説明会", dueOn: d.near, note: "10:30〜11:30 開始" },
        { id: "phone", kind: "予定", title: "架空の連絡", dueOn: d.phone, note: "連絡先 03-0000-0000" },
        { id: "f1", kind: "予定", title: "31日後の架空会議A", dueOn: d.far, note: "10:00〜11:00 開始" },
        { id: "f2", kind: "予定", title: "31日後の架空会議B", dueOn: d.far, note: "10:30〜11:30 開始" }
      ]
    }));
  }, dates);
  await pg.reload();
  await pg.waitForTimeout(600);

  ok(await pg.locator("#hintsCard li").count() === 1, "Task 8: 30日以内の重なりが 1 件出る");
  ok(!(await pg.locator("#hintsCard").innerText()).includes("31日後"), "Task 8: 31日後の重なりは出ない");
  ok(await pg.locator('#listGroups li[data-id="phone"] a[href="tel:0300000000"]').count() === 1, "Task 8: メモの電話番号を押せる");

  await pg.getByRole("button", { name: "この指摘を消す" }).click();
  ok(await pg.locator("#hintsCard").isHidden(), "Task 8: 指摘を消せる");
  await pg.reload();
  await pg.waitForTimeout(300);
  ok(await pg.locator("#hintsCard").isHidden(), "Task 8: 開き直しても消した指摘は出ない");

  await pg.fill("#f-title", "保存確認用の架空予定");
  await pg.fill("#f-date", dates.phone);
  await pg.click("#submitBtn");
  const dismissed = await pg.evaluate(() => JSON.parse(localStorage.getItem("schedule.v1")).dismissedHints);
  ok(Array.isArray(dismissed) && dismissed.length === 1, "Task 8: 別の予定を保存しても消した指摘が残る");

  await pg.click('#listGroups li[data-id="h2"] button[data-action="edit"]');
  await pg.fill("#f-start", "10:45");
  await pg.click("#submitBtn");
  ok(!(await pg.locator("#hintsCard").isHidden()) && await pg.locator("#hintsCard li").count() === 1, "Task 8: 時刻を変えると新しい指摘として再び出る");
  ok(errs.length === 0, "Task 8: JS エラーなし " + errs.join(" / "));

  await pg.goto(base + "schedule/index.html?testShared=1");
  await pg.waitForFunction(() => document.querySelectorAll("#meetingForms .scan-result").length === 1);
  ok(await pg.locator("#meetingForms .scan-result").count() === 1, "Task 10: 起動時の共有ファイルを確認欄に出す");
  ok(await pg.evaluate(() => window.__doc.takeCount) === 1, "Task 10: 起動時の takeShared は 1 回だけ");

  await pg.goto(base + "index.html?testBanner=1");
  await pg.waitForFunction(() => !!document.getElementById("documentReaderBanner"));
  ok((await pg.locator("#documentReaderBanner").innerText()).includes("共有された「架空.pdf」を予定アプリで読む"), "Task 10: トップ画面に共有ファイルの帯");
  ok((await pg.locator("#documentReaderBanner a").getAttribute("href")) === "schedule/index.html?shared=1", "Task 10: 帯のリンク先");
  ok(errs.length === 0, "Task 10: JS エラーなし " + errs.join(" / "));
} finally {
  await b.close();
  srv.close();
}

process.exit(fail ? 1 : 0);
