/*
 * apps/ の2つのアプリの動作確認（Playwright）。
 *
 *   npm i -D playwright && npx playwright install chromium
 *   node apps/tests/smoke.mjs
 *
 * ブラウザの実行ファイルを直接指定したいときは環境変数 CHROMIUM_PATH を使う。
 * アプリ自体は依存ライブラリなしで動く。このテストだけが Playwright を使う。
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright が見つかりません。`npm i -D playwright && npx playwright install chromium` を実行してください。");
  process.exit(2);
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};
const d = (offset) => {
  const x = new Date();
  x.setDate(x.getDate() + offset);
  return [x.getFullYear(), String(x.getMonth() + 1).padStart(2, "0"), String(x.getDate()).padStart(2, "0")].join("-");
};

const launchOptions = { args: ["--allow-file-access-from-files", "--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;

const browser = await chromium.launch(launchOptions);
const ctx = await browser.newContext();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("dialog", (dlg) => dlg.accept());

/* ---------------- 冷蔵庫アプリ ---------------- */
console.log("== apps/fridge ==");
await page.goto("file://" + path.join(ROOT, "apps/fridge/index.html"));
ok((await page.title()) === "冷蔵庫の在庫・賞味期限管理", "タイトル");
ok(await page.evaluate(() => {
  try { localStorage.setItem("t", "1"); localStorage.removeItem("t"); return true; } catch (e) { return false; }
}), "localStorage 利用可");

const addFood = async (name, expires, place = "冷蔵", qty = "2") => {
  await page.fill("#f-name", name);
  await page.fill("#f-qty", qty);
  await page.selectOption("#f-place", place);
  await page.fill("#f-expires", expires);
  await page.click("#submitBtn");
};

await addFood("牛乳", d(-2));
await addFood("たまご", d(2));
await addFood("冷凍うどん", d(60), "冷凍");
const stat = (n) => page.locator("#stats .stat").nth(n).locator(".num").textContent();
ok((await page.locator("li.item[data-id]").count()) === 3, "3件追加できる");
ok((await stat(0)) === "3", "在庫3件");
ok((await stat(1)) === "1", "期限切れ1件");
ok((await stat(2)) === "1", "3日以内1件");
ok((await page.locator("li.item").first().locator(".item-name").textContent()) === "牛乳", "期限が近い順に並ぶ");
ok((await page.locator("li.item").first().getAttribute("class")).includes("expired"), "期限切れの色分け");
ok((await page.locator("li.item").first().locator(".due").textContent()).includes("2日超過"), "超過日数の表示");

await page.fill("#q", "うどん");
ok((await page.locator("li.item[data-id]").count()) === 1, "検索で絞り込める");
await page.fill("#q", "");
await page.click('.chip[data-place="冷凍"]');
ok((await page.locator("li.item[data-id]").count()) === 1, "保管場所で絞り込める");
await page.click('.chip[data-place="すべて"]');

await page.locator("li.item", { hasText: "たまご" }).locator('button[data-action="dec"]').click();
ok((await page.locator("li.item", { hasText: "たまご" }).locator(".badge").first().textContent()) === "1個", "1つ減らすと数量が減る");

await page.locator("li.item", { hasText: "牛乳" }).locator('button[data-action="edit"]').click();
ok((await page.inputValue("#f-name")) === "牛乳", "編集でフォームに値が入る");
await page.fill("#f-name", "低脂肪牛乳");
await page.click("#submitBtn");
ok((await page.locator("li.item").first().locator(".item-name").textContent()) === "低脂肪牛乳", "編集が反映される");
ok((await page.locator("li.item[data-id]").count()) === 3, "編集で件数が増えない");

await page.locator("li.item", { hasText: "低脂肪牛乳" }).locator('button[data-action="discard"]').click();
ok((await page.locator("li.item[data-id]").count()) === 2, "廃棄で在庫から消える");
ok((await page.locator("#lossList li").count()) === 1, "廃棄が記録に残る");
ok((await stat(3)) === "1", "今月の廃棄1件");

await page.locator("li.item", { hasText: "たまご" }).locator('button[data-action="consume"]').click();
ok((await page.locator("li.item[data-id]").count()) === 1, "使い切りで在庫から消える");
ok((await page.locator("#lossList li").count()) === 1, "使い切りは廃棄記録に入らない");

ok((await page.locator("#recent .chip").count()) >= 2, "よく買うものが履歴から出る");
await page.locator("#recent .chip").first().click();
ok((await page.inputValue("#f-name")).length > 0, "クイック追加で品名が入る");
await page.click('.chip[data-plus="7"]');
ok((await page.inputValue("#f-expires")) === d(7), "「1週間後」で日付が入る");

await page.reload();
ok((await page.locator("li.item[data-id]").count()) === 1, "再読込後もデータが残る");

/* ---------------- 書類トラッカー ---------------- */
console.log("== apps/docs-tracker ==");
await page.goto("file://" + path.join(ROOT, "apps/docs-tracker/index.html"));
ok((await page.title()) === "書類・回覧の期限トラッカー", "タイトル");

const addDoc = async (title, due, kind = "提出", pri = "中") => {
  await page.fill("#f-title", title);
  await page.selectOption("#f-kind", kind);
  await page.fill("#f-dest", "総務課");
  await page.fill("#f-due", due);
  await page.selectOption("#f-pri", pri);
  await page.click("#submitBtn");
};

await addDoc("受講報告書", d(-1), "提出", "高");
await addDoc("備品発注伺い", d(0), "申請");
await addDoc("研修案内の回覧", d(10), "回覧");
ok((await page.locator("li.item[data-id]").count()) === 3, "3件登録できる");
ok((await stat(0)) === "3", "未処理3件");
ok((await stat(1)) === "1", "期限超過1件");
ok((await stat(2)) === "1", "今日まで1件");
ok((await page.locator("li.item").first().locator(".item-name").textContent()) === "受講報告書", "期限が近い順に並ぶ");
ok((await page.locator("li.item").first().getAttribute("class")).includes("expired"), "期限超過の色分け");
ok((await page.locator("li.item").first().locator(".badge.pri-高").count()) === 1, "優先度「高」のバッジ");

const target = () => page.locator("li.item", { hasText: "受講報告書" });
await target().locator('button[data-action="advance"]').click();
ok((await target().locator(".badge.status").textContent()) === "対応中", "未着手→対応中");
await target().locator('button[data-action="advance"]').click();
await target().locator('button[data-action="advance"]').click();
ok((await page.locator("li.item[data-id]").count()) === 2, "完了は「未完了」から外れる");
ok((await stat(1)) === "0", "完了で期限超過が減る");

await page.click('.chip[data-status="完了"]');
ok((await page.locator("li.item[data-id]").count()) === 1, "完了フィルタ");
ok((await page.locator("li.item").first().getAttribute("class")).includes("done"), "完了の見た目");
ok((await page.locator("li.item").first().locator('button[data-action="advance"]').count()) === 0, "完了に「次へ」は出ない");

await page.locator("li.item").first().locator('button[data-action="back"]').click();
await page.click('.chip[data-status="未完了"]');
ok((await page.locator("li.item[data-id]").count()) === 3, "1つ戻すと未完了に戻る");

await page.selectOption("#kindFilter", "回覧");
ok((await page.locator("li.item[data-id]").count()) === 1, "種別で絞り込める");
await page.selectOption("#kindFilter", "すべて");
await page.fill("#q", "発注");
ok((await page.locator("li.item[data-id]").count()) === 1, "検索で絞り込める");
await page.fill("#q", "");

await page.click('.chip[data-plus="0"]');
ok((await page.inputValue("#f-due")) === d(0), "「今日」で日付が入る");
await page.click('.chip[data-eom="1"]');
const now = new Date();
const eomStr = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"),
  String(new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate())].join("-");
ok((await page.inputValue("#f-due")) === eomStr, "「今月末」で月末が入る");

await page.locator("li.item", { hasText: "研修案内の回覧" }).locator('button[data-action="delete"]').click();
ok((await page.locator("li.item[data-id]").count()) === 2, "削除できる");
await page.reload();
ok((await page.locator("li.item[data-id]").count()) === 2, "再読込後もデータが残る");

const exported = await page.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")));
ok(exported.v === 1 && Array.isArray(exported.items) && "dueOn" in exported.items[0] && "status" in exported.items[0],
  "書き出しJSONの項目名（/brief が読む形式）");

console.log("\nJSエラー: " + (errors.length ? "\n  " + errors.join("\n  ") : "なし"));
if (errors.length) failures++;
await browser.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
