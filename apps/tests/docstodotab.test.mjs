/*
 * 書類と TODO のタブ分離、TODO の追加・完了操作を確かめる画面テスト。
 *
 *   NODE_PATH=<playwright の場所> CHROMIUM_PATH=<headless_shell> node apps/tests/docstodotab.test.mjs
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

await page.goto(base + "docs-tracker/index.html");
await page.evaluate(() => localStorage.clear());
await page.reload();

ok(await page.locator("#docsTab").getAttribute("aria-pressed") === "true", "最初は書類タブを開く");
ok(await page.locator('#f-kind option', { hasText: "TODO" }).count() === 0, "書類の種別にTODOを出さない");

await page.fill("#f-title", "架空の申請書");
await page.selectOption("#f-kind", "申請");
await page.click("#submitBtn");

await page.click("#todoTab");
ok(await page.locator("#todoTab").getAttribute("aria-pressed") === "true", "TODOタブを開ける");
ok((await page.locator("#jumpAdd").textContent()).trim() === "追加する", "下の登録ボタンをTODO用に変える");
await page.fill("#todo-title", "架空の確認作業");
await page.fill("#todo-due", "2099-10-21");
await page.fill("#todo-note", "架空データの確認");
await page.click("#todoSubmitBtn");

let saved = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
let todo = saved.items.find(item => item.title === "架空の確認作業");
ok(todo && todo.kind === "TODO" && todo.status === "未着手", "TODOを共通データ形式で追加する");
ok((await page.locator("#todoList").textContent()).includes("架空の確認作業"), "追加したTODOを未完了一覧に出す");
ok(await page.locator('#todoList input[type="checkbox"]').count() === 1, "TODOに本物のチェックボックスを出す");

await page.locator('#todoList input[type="checkbox"]').click();
saved = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
todo = saved.items.find(item => item.title === "架空の確認作業");
ok(todo.status === "完了" && !!todo.doneAt, "チェックすると完了日時を保存する");
ok((await page.locator("#todoDoneList").textContent()).includes("架空の確認作業"), "完了したTODOを下の一覧へ移す");

await page.locator('#todoDoneList input[type="checkbox"]').click();
saved = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
todo = saved.items.find(item => item.title === "架空の確認作業");
ok(todo.status === "未着手" && todo.doneAt === "", "チェックを外すと未着手へ戻す");

await page.click("#docsTab");
ok(!(await page.locator("#list").textContent()).includes("架空の確認作業"), "TODOを書類一覧に出さない");
ok((await page.locator("#list").textContent()).includes("架空の申請書"), "書類は書類一覧に出す");
ok((await page.locator("#stats .stat").first().locator(".num").textContent()).trim() === "1", "書類だけを件数に数える");
const ids = await page.evaluate(() => {
  const items = JSON.parse(localStorage.getItem("docs-tracker.v1")).items;
  return {
    todo: items.find(item => item.kind === "TODO").id,
    doc: items.find(item => item.kind !== "TODO").id
  };
});
await page.evaluate(id => window.applyDeepAction({ id }), ids.todo);
ok(await page.locator("#todoTab").getAttribute("aria-pressed") === "true", "TODOのIDはTODOタブで開く");
await page.evaluate(id => window.applyDeepAction({ id }), ids.doc);
ok(await page.locator("#docsTab").getAttribute("aria-pressed") === "true", "書類のIDは書類タブで開く");
ok(errors.length === 0, "JavaScript エラーなし " + errors.join(" / "));

await browser.close();
srv.close();
process.exit(failures ? 1 : 0);
