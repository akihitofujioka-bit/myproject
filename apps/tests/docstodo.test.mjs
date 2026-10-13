/*
 * 書類・やることの名前、種別、保存データ、メモ機能の画面テスト。
 *
 *   NODE_PATH=<playwright の場所> CHROMIUM_PATH=<headless_shell> node apps/tests/docstodo.test.mjs
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
  console.error("Playwright が見つかりません。指定された NODE_PATH を確認してください。");
  process.exit(1);
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png" };
const srv = http.createServer((q, r) => {
  const p = path.join(ROOT, decodeURIComponent(q.url.split("?")[0]));
  fs.readFile(p, (e, d) => {
    if (e) { r.writeHead(404); r.end(); return; }
    r.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
    r.end(d);
  });
});
await new Promise(resolve => srv.listen(0, resolve));
const base = `http://127.0.0.1:${srv.address().port}/apps/`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("dialog", d => d.accept());
let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "PASS " : "FAIL ") + label);
  if (!condition) failures++;
};

await page.goto(base + "index.html");
ok((await page.locator('a[href="docs-tracker/index.html"] .name').textContent()).trim() === "書類・やること", "トップ画面のアプリ名");

await page.goto(base + "docs-tracker/index.html");
ok((await page.title()) === "書類・やること", "画面の題名");
ok((await page.locator("h1").textContent()).trim() === "書類・やること", "画面の見出し");
ok(await page.locator('#f-kind option', { hasText: "やること" }).count() === 1, "種別にやることがある");

await page.evaluate(() => {
  localStorage.clear();
  localStorage.setItem("docs-tracker.v1", JSON.stringify({
    v: 1,
    calIds: {},
    memos: [{ id: "m1", text: "架空のメモ", createdAt: "2026-10-13T00:00:00Z", updatedAt: "2026-10-13T00:00:00Z", movedTo: [] }],
    items: [{
      id: "d1", title: "架空の準備", kind: "やること", dest: "", dueOn: "", status: "未着手",
      priority: "中", note: "", createdAt: "2026-10-13T00:00:00Z", doneAt: "", scheduleId: "s1"
    }]
  }));
});
await page.reload();
ok((await page.locator("#list").textContent()).includes("架空の準備"), "やることが一覧に出る");
ok((await page.locator("#stats .stat").first().locator(".num").textContent()).trim() === "1", "やることを未処理件数に数える");

await page.fill("#f-title", "架空の申請書");
await page.selectOption("#f-kind", { label: "申請" });
await page.click("#submitBtn");
const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
ok(saved.memos.length === 1 && saved.memos[0].text === "架空のメモ", "別の書類を登録してもメモが残る");
ok(saved.items.find(it => it.id === "d1").scheduleId === "s1", "別の書類を登録しても予定の番号が残る");

// メモの保存と、予定・やることへの移動
await page.evaluate(() => localStorage.clear());
await page.reload();
await page.click("#memoTab");
ok(!(await page.locator("#docsActionbar").isVisible()), "メモのタブでは書類のボタン帯を隠す");
await page.fill("#memoText", "10月22日 14時から 架空の打合せ 第2会議室");
await page.click("#memoSave");
let memo = page.locator(".memo-item").first();
ok((await memo.textContent()).includes("10月22日 14時から 架空の打合せ 第2会議室"), "保存したメモが一覧の先頭に出る");
ok(await memo.locator('button[data-action="schedule"]').count() === 1, "日付のあるメモに予定に入れるボタンが出る");
ok(await memo.locator('button[data-action="todo"]').count() === 1, "日付のあるメモにやることにするボタンが出る");

await page.fill("#memoText", "架空の思いつき");
await page.click("#memoSave");
memo = page.locator(".memo-item", { hasText: "架空の思いつき" });
ok(await memo.locator('button[data-action="schedule"], button[data-action="todo"]').count() === 0, "日付も期限もないメモに移動ボタンは出ない");

const datedMemo = page.locator(".memo-item", { hasText: "10月22日 14時から 架空の打合せ 第2会議室" });
await datedMemo.locator('button[data-action="schedule"]').click();
const pending = await page.evaluate(() => JSON.parse(sessionStorage.getItem("pendingScan")));
ok(pending.type === "memo", "予定に入れるとメモとして受け渡す");
await datedMemo.locator("a.memo-schedule-link").click();
await page.waitForSelector("#meetingConfirm:not([hidden])");
ok(await page.locator("#meetingForms .scan-result").count() === 1, "予定アプリの確認欄に1件出る");
ok(await page.locator("#meetingForms .m-date").inputValue() === "2026-10-22", "予定アプリで日付を取り出す");
await page.click('[data-meeting-mode="app"]');
const scheduleData = await page.evaluate(() => JSON.parse(localStorage.getItem("schedule.v1")));
ok(scheduleData.items[0].note.includes("（メモから登録）"), "予定のメモに出どころが入る");

await page.goto(base + "docs-tracker/index.html");
await page.click("#memoTab");
const todoMemo = page.locator(".memo-item", { hasText: "10月22日 14時から 架空の打合せ 第2会議室" });
await todoMemo.locator('button[data-action="todo"]').click();
ok(await page.locator("#f-title").inputValue() === "10月22日 14時から 架空の打合せ 第2会議室".slice(0, 40), "やることの件名を入力欄に入れる");
ok(await page.locator("#f-kind").inputValue() === "やること", "種別をやることにする");
ok(await page.locator("#f-note").inputValue() === "10月22日 14時から 架空の打合せ 第2会議室", "本文をメモ欄に入れる");
await page.click("#submitBtn");
await page.click("#memoTab");
ok((await page.locator(".memo-item", { hasText: "10月22日 14時から 架空の打合せ 第2会議室" }).textContent()).includes("やることにした"), "登録後にやることにした印が出る");

let ideaMemo = page.locator(".memo-item", { hasText: "架空の思いつき" });
await ideaMemo.locator('button[data-action="edit"]').click();
await page.fill("#memoText", "架空の思いつき（編集済み）");
await page.click("#memoSave");
ok(await page.locator(".memo-item", { hasText: "架空の思いつき（編集済み）" }).count() === 1, "メモを編集できる");
ideaMemo = page.locator(".memo-item", { hasText: "架空の思いつき（編集済み）" });
await ideaMemo.locator('button[data-action="delete"]').click();
ok(await page.locator(".memo-item", { hasText: "架空の思いつき（編集済み）" }).count() === 0, "確認後にメモを削除できる");

// 端末内の音声認識でメモ欄へ文字を入れる（保存は利用者が行う）
const speechPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await speechPage.addInitScript(() => {
  const listeners = {};
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      SpeechMemo: {
        isSupported: async () => ({ supported: true }),
        addListener: async (name, listener) => { listeners[name] = listener; },
        start: async () => { listeners.partial({ text: "10/22 架空の" }); },
        stop: async () => ({ text: "10/22 架空の打合せ" })
      }
    },
    nativePromise(plugin, method, options) {
      return this.Plugins[plugin][method](options || {});
    }
  };
});
await speechPage.goto(base + "docs-tracker/index.html");
await speechPage.evaluate(() => localStorage.clear());
await speechPage.reload();
await speechPage.click("#memoTab");
ok(await speechPage.locator("#speechMemoButton").isVisible(), "端末内の音声認識が使えると音声ボタンが出る");
await speechPage.click("#speechMemoButton");
ok(await speechPage.locator("#memoText").inputValue() === "10/22 架空の", "音声認識の途中の文字を入力欄に出す");
ok((await speechPage.locator("#speechMemoButton").textContent()).includes("● 聞いています…（もう一度押すと止まる）"), "録音中の文をボタンに出す");
await speechPage.click("#speechMemoButton");
ok(await speechPage.locator("#memoText").inputValue() === "10/22 架空の打合せ", "音声認識を止めたら最後の文字を入力欄に残す");
ok(await speechPage.locator(".memo-item").count() === 0, "音声認識を止めてもメモは自動保存しない");
await speechPage.close();

const unsupportedSpeechPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await unsupportedSpeechPage.addInitScript(() => {
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: { SpeechMemo: { isSupported: async () => ({ supported: false }) } },
    nativePromise(plugin, method, options) { return this.Plugins[plugin][method](options || {}); }
  };
});
await unsupportedSpeechPage.goto(base + "docs-tracker/index.html");
ok(await unsupportedSpeechPage.locator("#speechMemoButton").count() === 0, "端末内の音声認識が使えなければ音声ボタンを出さない");
await unsupportedSpeechPage.close();

const browserSpeechPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await browserSpeechPage.goto(base + "docs-tracker/index.html");
ok(await browserSpeechPage.locator("#speechMemoButton").count() === 0, "ブラウザでは音声ボタンを出さない");
await browserSpeechPage.close();

const failedSpeechPage = await browser.newPage({ viewport: { width: 390, height: 844 } });
await failedSpeechPage.addInitScript(() => {
  window.Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      SpeechMemo: {
        isSupported: async () => ({ supported: true }),
        addListener: async () => {},
        start: async () => { throw new Error("この端末では使えません"); }
      }
    },
    nativePromise(plugin, method, options) { return this.Plugins[plugin][method](options || {}); }
  };
});
await failedSpeechPage.goto(base + "docs-tracker/index.html");
await failedSpeechPage.click("#memoTab");
await failedSpeechPage.click("#speechMemoButton");
ok((await failedSpeechPage.locator("#toast").textContent()).includes("この端末では使えません"), "音声認識を始められない理由を知らせに出す");
await failedSpeechPage.close();

ok(errors.length === 0, "JavaScript エラーなし " + errors.join(" / "));

await browser.close();
srv.close();
process.exit(failures ? 1 : 0);
