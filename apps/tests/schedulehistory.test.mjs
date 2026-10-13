/*
 * 予定アプリの履歴・手書きメモ画面（Playwright が必要）。
 *
 *   NODE_PATH=<playwright の場所> node apps/tests/schedulehistory.test.mjs
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

// Playwright の waitForFunction は async の条件を「すぐ満たした」と扱うため、読み込みを待ってから判定し直す
const waitAsync = async (target, predicate, arg, timeout = 30000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await target.evaluate(predicate, arg)) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("waitAsync: 条件を満たすまで待てませんでした");
};


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

const fakeNative = () => {
  window.__doc = {
    image: { cancelled: false, name: "架空メモ.jpg", text: "架空メモの一行目\n修正前", ocr: true },
    shared: location.search.includes("shared=1") ? {
      cancelled: false,
      name: "架空通知.pdf",
      kind: "pdf",
      ocr: true,
      tables: [],
      lines: ["架空検討会", "日時 令和8年10月22日（木）午後1時30分から", "場所 架空市役所 第１会議室"]
    } : null
  };
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      DocumentReader: {
        pick: () => Promise.resolve({ cancelled: true }),
        pickImage: () => window.__doc.imageError
          ? Promise.reject(new Error(window.__doc.imageError))
          : Promise.resolve(window.__doc.image),
        takeShared: () => {
          const value = window.__doc.shared;
          window.__doc.shared = null;
          return Promise.resolve(value || {});
        }
      }
    },
    nativePromise: (plugin, method) => {
      if (plugin === "ReceiptScanner" && method === "scan") {
        return Promise.resolve({ cancelled: false, lines: [{ text: "撮った架空メモ" }] });
      }
      if (method === "isSupported") return Promise.resolve({ supported: false, authorized: false });
      return Promise.resolve({ cancelled: true });
    }
  };
};

const pg = await browser.newPage({ viewport: { width: 390, height: 844 } });
const errors = [];
pg.on("pageerror", error => errors.push(error.message));
await pg.addInitScript(fakeNative);

try {
  await pg.goto(base + "schedule/index.html");
  await pg.evaluate(async () => {
    localStorage.clear();
    await new Promise(resolve => {
      const request = indexedDB.deleteDatabase("ichishi-history");
      request.onsuccess = request.onerror = request.onblocked = resolve;
    });
  });
  await pg.goto(base + "schedule/index.html?shared=1");
  await waitAsync(pg, async () => (await window.AIHistory.list({})).length === 1);

  await pg.click("#historyViewBtn");
  await pg.waitForFunction(() => document.getElementById("historyList").textContent.includes("架空通知.pdf"));
  ok(await pg.locator("#historySearch").isVisible(), "履歴に検索欄が出る");
  ok((await pg.locator("#historyKind option").allTextContents()).join("/") === "すべて/会話/書類/手書きメモ", "履歴に種類の絞り込みが出る");
  ok(await pg.getByRole("button", { name: "✍️ 手書きメモを撮る" }).isVisible(), "手書きメモを撮るボタンが出る");
  ok(await pg.getByRole("button", { name: "写真から" }).isVisible(), "写真からボタンが出る");
  ok((await pg.locator("#historyList").innerText()).includes("架空通知.pdf"), "共有書類が自動で履歴に残る");

  await pg.click("#listViewBtn");
  await pg.waitForFunction(() => document.querySelectorAll("#meetingForms .scan-result").length === 1);
  ok(await pg.locator('#meetingForms .scan-result[data-origin="document"]').count() === 1, "書類から読んだ確認行に出所を付ける");
  await pg.click("#meetingManualBtn");
  await pg.waitForFunction(() => document.querySelectorAll("#meetingForms .scan-result").length === 2);
  ok(await pg.locator('#meetingForms .scan-result[data-origin="manual"]').count() === 1, "手入力の確認行に出所を付ける");
  // 件名の欄が空のまま登録すると、予定アプリは既定の件名「会議」で登録する
  const documentRowTitle = (await pg.locator("#meetingForms .m-title").nth(0).inputValue()) || "会議";
  await pg.locator("#meetingForms .m-title").nth(1).fill("架空の手入力予定");
  await pg.locator("#meetingForms .m-date").nth(1).fill("2026-10-23");
  await pg.click('[data-meeting-mode="app"]');
  await waitAsync(pg, async title => {
    const entries = await window.AIHistory.list({ kind: "document" });
    return entries[0] && entries[0].eventTitles && entries[0].eventTitles.includes(title);
  }, documentRowTitle);
  ok(true, "書類と手入力を一緒に登録しても書類の件名が履歴に残る");
  const documentId = await pg.evaluate(async () => (await window.AIHistory.list({ kind: "document" }))[0].id);
  const documentAfterManual = await pg.evaluate(id => window.AIHistory.get(id), documentId);
  ok(documentRowTitle && documentAfterManual.eventTitles.join("/") === documentRowTitle, "書類の履歴には書類から読んだ行の件名だけを残す");

  await pg.click("#historyViewBtn");
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 1);
  await pg.click("#handwrittenImageBtn");
  await pg.waitForFunction(() => document.getElementById("handwrittenBody").value.includes("架空メモの一行目"));
  ok(await pg.locator("#handwrittenBody").inputValue() === "架空メモの一行目\n修正前", "写真の文字が編集欄に入る");
  await pg.fill("#handwrittenBody", "架空メモの一行目\n<b>架空</b>に修正");
  await pg.fill("#handwrittenTitle", "");
  await pg.click("#handwrittenSaveBtn");
  await waitAsync(pg, async () => (await window.AIHistory.list({ kind: "handwritten" })).length === 1);
  const handwritten = await pg.evaluate(async () => (await window.AIHistory.list({ kind: "handwritten" }))[0]);
  ok(handwritten.title === "架空メモの一行目", "題名が空なら本文の一行目になる");

  await pg.fill("#historySearch", "ダイイチ");
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 0);
  ok(true, "一致しない読みの検索は0件になる");
  await pg.fill("#historySearch", "第１");
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 1);
  ok(true, "全角数字でも書類を検索できる");
  await pg.fill("#historySearch", "");
  await pg.selectOption("#historyKind", "chat");
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 0);
  ok(true, "会話の絞り込みで書類が消える");

  await pg.selectOption("#historyKind", "");
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 2);
  await pg.evaluate(() => { window.confirm = () => false; });
  await pg.locator("#historyList [data-history-remove]").first().click();
  ok(await pg.locator("#historyList [data-history-id]").count() === 2, "1件削除はキャンセルすると消えない");
  await pg.click("#historyClearBtn");
  ok(await pg.locator("#historyList [data-history-id]").count() === 2, "すべて削除はキャンセルすると消えない");

  await pg.locator(`#historyList [data-history-id="${handwritten.id}"] [data-history-open]`).click();
  await pg.waitForFunction(() => !document.getElementById("historyDetail").hidden && document.getElementById("historyDetail").textContent.includes("修正"));
  ok(await pg.locator("#historyDetail b").count() === 0, "本文のHTMLは要素にならない");
  ok((await pg.locator("#historyDetail").innerText()).includes("<b>架空</b>"), "本文のHTMLを文字のまま表示する");
  await pg.locator(`#historyList [data-history-id="${documentId}"] [data-history-open]`).click();
  await pg.waitForFunction(() => {
    const detail = document.getElementById("historyDetail");
    return !detail.hidden && detail.textContent.includes("架空検討会");
  });
  ok(await pg.getByRole("button", { name: "この資料で壁打ち" }).isVisible(), "書類に壁打ちボタンが出る");
  ok(await pg.getByRole("button", { name: "この資料でブレスト" }).isVisible(), "書類にブレストボタンが出る");

  await pg.evaluate(async () => {
    await window.AIHistory.add({
      kind: "chat", title: "架空の会話", body: "", mode: "secretary",
      messages: [], sourceId: "", eventTitles: []
    });
    window.__chosenSource = null;
    window.chooseSource(entry => { window.__chosenSource = entry; });
  });
  await pg.waitForFunction(() => document.querySelectorAll("#historyList [data-history-id]").length === 2);
  ok(!(await pg.locator("#historyList").innerText()).includes("架空の会話"), "資料選択には書類と手書きメモだけが並ぶ");
  await pg.locator(`#historyList [data-history-id="${documentId}"] [data-history-select]`).click();
  await pg.waitForFunction(() => window.__chosenSource && window.__chosenSource.id);
  const chosenSource = await pg.evaluate(() => window.__chosenSource);
  ok(chosenSource.id === documentId && chosenSource.kind === "document", "資料選択のcallbackに選んだentryが渡る");

  const displayNoticeCounts = await pg.evaluate(async () => {
    const toast = document.getElementById("toast");
    let count = 0;
    const observer = new MutationObserver(() => {
      if (toast.textContent === "履歴を表示できません") count++;
    });
    observer.observe(toast, { childList: true });
    const realList = window.AIHistory.list;
    window.AIHistory.list = () => Promise.reject(new Error("架空の表示失敗"));
    window.setView("history");
    await new Promise(resolve => setTimeout(resolve, 20));
    window.setView("history");
    await new Promise(resolve => setTimeout(resolve, 20));
    const whileFailing = count;
    window.AIHistory.list = realList;
    window.setView("history");
    await new Promise(resolve => setTimeout(resolve, 20));
    window.AIHistory.list = () => Promise.reject(new Error("架空の再表示失敗"));
    window.setView("history");
    await new Promise(resolve => setTimeout(resolve, 20));
    const afterSuccess = count;
    window.AIHistory.list = realList;
    observer.disconnect();
    return { whileFailing, afterSuccess };
  });
  ok(displayNoticeCounts.whileFailing === 1 && displayNoticeCounts.afterSuccess === 2, "履歴の表示失敗は連続中1回だけ通知し、成功後は再通知する");

  const saveNoticeCounts = await pg.evaluate(async () => {
    const toast = document.getElementById("toast");
    let count = 0;
    const observer = new MutationObserver(() => {
      if (toast.textContent === "履歴を保存できません") count++;
    });
    observer.observe(toast, { childList: true });
    const realAdd = window.AIHistory.add;
    const save = async body => {
      document.getElementById("handwrittenBody").value = body;
      document.getElementById("handwrittenSaveBtn").click();
      await new Promise(resolve => setTimeout(resolve, 20));
    };
    window.AIHistory.add = () => Promise.reject(new Error("架空の保存失敗"));
    await save("架空の保存失敗一");
    await save("架空の保存失敗二");
    const whileFailing = count;
    window.AIHistory.add = realAdd;
    await save("架空の保存成功");
    window.AIHistory.add = () => Promise.reject(new Error("架空の再保存失敗"));
    await save("架空の保存再失敗");
    const afterSuccess = count;
    window.AIHistory.add = realAdd;
    observer.disconnect();
    return { whileFailing, afterSuccess };
  });
  ok(saveNoticeCounts.whileFailing === 1 && saveNoticeCounts.afterSuccess === 2, "履歴の保存失敗は連続中1回だけ通知し、成功後は再通知する");

  await pg.evaluate(() => { window.confirm = () => true; });
  await pg.locator(`#historyList [data-history-id="${handwritten.id}"] [data-history-remove]`).click();
  await waitAsync(pg, async id => !(await window.AIHistory.get(id)), handwritten.id);
  ok(true, "削除の確認でOKにすると履歴が実際に消える");
  ok(errors.length === 0, "履歴画面でJSエラーがない " + errors.join(" / "));

  const receivedContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const received = await receivedContext.newPage();
  await received.addInitScript(fakeNative);
  await received.addInitScript(() => localStorage.setItem("schedule.view", "history"));
  await received.goto(base + "schedule/index.html?shared=1");
  await received.waitForFunction(() => {
    const confirm = document.getElementById("meetingConfirm");
    return !document.getElementById("listView").hidden &&
      !confirm.hidden && confirm.textContent.includes("ファイルから読み取った予定");
  });
  ok(await received.locator("#meetingConfirm").isVisible(), "履歴表示で共有書類を受け取っても確認画面が見える");
  await receivedContext.close();

  const memoContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const memoReceived = await memoContext.newPage();
  await memoReceived.addInitScript(fakeNative);
  await memoReceived.addInitScript(() => {
    localStorage.setItem("schedule.view", "history");
    sessionStorage.setItem("pendingScan", JSON.stringify({
      type: "memo",
      lines: ["10月22日 14時から 架空の打合せ 第2会議室"],
      at: Date.now()
    }));
  });
  await memoReceived.goto(base + "schedule/index.html");
  await memoReceived.waitForFunction(() => {
    const confirm = document.getElementById("meetingConfirm");
    return !document.getElementById("listView").hidden && !confirm.hidden &&
      document.querySelectorAll("#meetingForms .scan-result").length === 1;
  });
  ok(await memoReceived.locator("#meetingConfirm").isVisible(), "履歴表示で音声メモを受け取っても確認画面が見える");
  await memoContext.close();

  const broken = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await broken.addInitScript(() => {
    const failed = { open: () => {
      const request = {};
      setTimeout(() => {
        request.error = new Error("壊れた保存先");
        if (request.onerror) request.onerror();
      }, 0);
      return request;
    } };
    Object.defineProperty(window, "indexedDB", { configurable: true, value: failed });
  });
  await broken.goto(base + "schedule/index.html");
  await broken.waitForTimeout(50);
  ok(!(await broken.locator("#toast").innerText()).includes("履歴を表示できません"), "壊れたDBでも一覧では履歴の通知を出さない");
  await broken.click("#historyViewBtn");
  await broken.waitForFunction(() => document.getElementById("toast").textContent.includes("履歴を表示できません"));
  ok(await broken.locator("#historyView").isVisible(), "壊れたDBでも履歴タブを開ける");
  ok((await broken.locator("#toast").innerText()).includes("履歴を表示できません"), "壊れたDBでは表示できない旨が出る");
  await broken.click("#listViewBtn");
  ok(await broken.locator("#listView").isVisible(), "履歴を保存できなくても一覧タブは動く");
  await broken.close();
} finally {
  await browser.close();
  srv.close();
}

process.exit(fail ? 1 : 0);
