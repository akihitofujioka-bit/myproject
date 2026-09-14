/*
 * 家計簿（apps/kakeibo）の動作確認。
 *
 *   npm i -D playwright && npx playwright install chromium
 *   node apps/tests/kakeibo.test.mjs
 *
 * ブラウザの実行ファイルを直接指定したいときは環境変数 CHROMIUM_PATH を使う。
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
const APP = "file://" + path.join(ROOT, "apps/kakeibo/index.html");
const FIXTURES = path.join(ROOT, "apps/tests/fixtures");

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};
const pad = (n) => String(n).padStart(2, "0");
const d = (offset) => {
  const x = new Date();
  x.setDate(x.getDate() + offset);
  return [x.getFullYear(), pad(x.getMonth() + 1), pad(x.getDate())].join("-");
};
const thisMonth = () => d(0).slice(0, 7);

const launchOptions = { args: ["--allow-file-access-from-files", "--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);
const ctx = await browser.newContext({ acceptDownloads: true });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("dialog", (dlg) => dlg.accept());

const fresh = async () => {
  await page.goto(APP);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
};

const record = async ({ amount, category, date, store = "", note = "" }) => {
  await page.fill("#f-amount", String(amount));
  if (date) await page.fill("#f-date", date);
  if (store) {
    await page.fill("#f-store", store);
    await page.dispatchEvent("#f-store", "change"); // 費目の自動推定を走らせる
  }
  if (note) await page.fill("#f-note", note);
  if (category) await page.selectOption("#f-category", category);
  await page.click("#submitBtn");
};

const statNum = (n) => page.locator("#stats .stat").nth(n).locator(".num").textContent();

/* ---------------- 記録と集計 ---------------- */
console.log("== 記録と集計 ==");
await fresh();
ok((await page.title()) === "家計簿", "タイトル");
ok((await page.inputValue("#f-date")) === d(0), "日付の初期値は今日");

await record({ amount: 3480, category: "食費", date: d(0), store: "〇〇スーパー" });
await record({ amount: 1280, category: "日用品", date: d(0), store: "△△ドラッグ" });
await record({ amount: 890, category: "交通費", date: d(0), store: "駅" });
ok((await page.locator("li.item[data-id]").count()) === 3, "3件記録できる");
ok((await statNum(0)) === "5,650", "今月の合計が出る");
ok((await statNum(3)) === "3", "件数が出る");

ok((await page.locator("#breakdown .bar-label").count()) === 3, "費目別の内訳が3行");
ok((await page.locator("#breakdown .bar-label").first().textContent()) === "食費", "金額が大きい費目から並ぶ");
const topWidth = await page.locator("#breakdown .bar-fill").first().evaluate((el) => el.style.width);
ok(topWidth === "100%", "いちばん大きい費目の棒が最大幅");
ok((await page.locator("#breakdown .bar-value").first().textContent()).includes("3,480"), "金額を棒の横に直接書く");
ok((await page.locator("#breakdown .bar-value").first().textContent()).includes("62%"), "全体に占める割合も出す");

/* ---------------- 費目の自動推定 ---------------- */
console.log("== 費目の自動推定 ==");
const guesses = await page.evaluate(() => ({
  superMarket: window.kakeiboApp.guessCategory("××スーパー 駅前店"),
  drug: window.kakeiboApp.guessCategory("マツモトドラッグ"),
  clinic: window.kakeiboApp.guessCategory("さくらクリニック"),
  gas: window.kakeiboApp.guessCategory("東京ガス"),
  unknown: window.kakeiboApp.guessCategory("謎の店"),
  history: window.kakeiboApp.guessCategory("〇〇スーパー"),
}));
ok(guesses.superMarket === "食費", "「スーパー」から食費を推定");
ok(guesses.drug === "日用品", "「ドラッグ」から日用品を推定");
ok(guesses.clinic === "医療費", "「クリニック」から医療費を推定");
ok(guesses.gas === "水道光熱費", "「ガス」から水道光熱費を推定");
ok(guesses.unknown === "", "手がかりが無ければ推定しない");
ok(guesses.history === "食費", "過去に使った費目を優先する");

// 店名を入れると費目が自動で選ばれる
await page.fill("#f-store", "さくらクリニック");
await page.dispatchEvent("#f-store", "change");
ok((await page.inputValue("#f-category")) === "医療費", "店名の入力で費目が切り替わる");
await page.fill("#f-store", "");

// よく行く店のボタン
ok((await page.locator("#recentChips .chip").count()) === 3, "よく行く店のボタンが出る");
await page.locator('#recentChips .chip[data-store="〇〇スーパー"]').click();
ok((await page.inputValue("#f-store")) === "〇〇スーパー", "押すと店名が入る");
ok((await page.inputValue("#f-category")) === "食費", "押すと費目も入る");

/* ---------------- 月の切り替え ---------------- */
console.log("== 月の切り替え ==");
await page.click("#prevMonth");
ok((await statNum(0)) === "0", "前の月は0円");
ok((await page.locator("#breakdownEmpty").textContent()).includes("ありません"), "記録が無い月はその旨を出す");
await page.click("#thisMonth");
ok((await statNum(0)) === "5,650", "「今月」で戻る");

// 先月ぶんを入れると、その月に表示が移る
const lastMonthDay = (() => {
  const x = new Date();
  x.setMonth(x.getMonth() - 1, 15);
  return [x.getFullYear(), pad(x.getMonth() + 1), pad(x.getDate())].join("-");
})();
await record({ amount: 5000, category: "交際費", date: lastMonthDay, store: "先月の店" });
ok((await page.locator("#monthLabel").textContent()) === (Number(lastMonthDay.slice(0, 4)) + "年" + Number(lastMonthDay.slice(5, 7)) + "月"),
  "先月の記録を入れると先月の画面に移る");
ok((await statNum(0)) === "5,000", "先月の合計だけを数える");
await page.click("#thisMonth");
ok((await statNum(1)) !== "—", "前月比が出る");

/* ---------------- 予算 ---------------- */
console.log("== 予算 ==");
ok(!(await page.locator("#budgetCard").isVisible()), "予算を決めていなければ出さない");

// 今月の合計は 5,650 円。予算に対する割合で表示が変わる
const budgetClass = () => page.locator("#budgetFill").evaluate((el) => el.className);
await page.fill("#f-budget", "10000");
await page.click("#saveSettings");
ok(await page.locator("#budgetCard").isVisible(), "予算を決めると出る");
ok((await budgetClass()) === "budget-fill", "予算の6割ならふつうの色（5,650／10,000）");
const budgetText = await page.locator("#budgetText").textContent();
ok(budgetText.includes("5,650円") && budgetText.includes("10,000円"), "使った額と予算を書く（" + budgetText.trim() + "）");
ok(budgetText.includes("残り 4,350円"), "残りを書く");

await page.fill("#f-budget", "6500");
await page.click("#saveSettings");
ok((await budgetClass()).includes("warn"), "8割を超えたら色が変わる（5,650／6,500 = 87%）");

await page.fill("#f-budget", "5000");
await page.click("#saveSettings");
ok((await budgetClass()).includes("over"), "予算を超えたら色が変わる");
ok((await page.locator("#budgetText").textContent()).includes("650円 超過"), "超過額を書く");

await page.fill("#f-budget", "");
await page.click("#saveSettings");
ok(!(await page.locator("#budgetCard").isVisible()), "予算を空にすると出なくなる");

/* ---------------- 費目の変更 ---------------- */
console.log("== 費目の設定 ==");
await page.fill("#f-cats", "食費、日用品、こども費");
await page.click("#saveSettings");
const opts = await page.locator("#f-category option").evaluateAll((els) => els.map((e) => e.value));
ok(opts.includes("こども費"), "費目を増やせる");
ok(opts.includes("未分類"), "「未分類」は常に選べる");
ok(!opts.includes("交通費"), "外した費目は選択肢から消える");
ok((await page.locator("li.item", { hasText: "駅" }).locator(".badge.cat").textContent()) === "交通費",
  "外した費目でも、記録済みの内容はそのまま残る");

/* ---------------- 編集・削除・同じ内容で記録 ---------------- */
console.log("== 編集・削除 ==");
await page.locator("li.item", { hasText: "△△ドラッグ" }).locator('button[data-action="edit"]').click();
ok((await page.inputValue("#f-amount")) === "1280", "編集でフォームに値が入る");
await page.fill("#f-amount", "1500");
await page.click("#submitBtn");
ok((await statNum(0)) === "5,870", "編集が合計に反映される");
ok((await page.locator("li.item[data-id]").count()) === 3, "編集で件数が増えない");

await page.locator("li.item", { hasText: "〇〇スーパー" }).locator('button[data-action="same"]').click();
ok((await page.inputValue("#f-store")) === "〇〇スーパー", "「同じ内容で記録」で店名が入る");
ok((await page.inputValue("#f-amount")) === "", "金額は空にする（毎回違うため）");
ok((await page.inputValue("#f-date")) === d(0), "日付は今日にする");
await page.fill("#f-amount", "1000");
await page.click("#submitBtn");
ok((await page.locator("li.item[data-id]").count()) === 4, "続けて記録できる");

await page.locator("li.item", { hasText: "駅" }).locator('button[data-action="delete"]').click();
ok((await page.locator("li.item[data-id]").count()) === 3, "削除できる");

/* ---------------- 検索・絞り込み ---------------- */
console.log("== 検索・絞り込み ==");
await page.fill("#q", "ドラッグ");
ok((await page.locator("li.item[data-id]").count()) === 1, "検索で絞れる");
await page.fill("#q", "");
await page.click('#catFilter .chip[data-cat="食費"]');
ok((await page.locator("li.item[data-id]").count()) === 2, "費目で絞れる");
await page.click('#catFilter .chip[data-cat="すべて"]');

/* ---------------- 保存の維持 ---------------- */
console.log("== 保存 ==");
await page.reload();
ok((await page.locator("li.item[data-id]").count()) === 3, "再読込後も残る");
ok((await page.locator("#f-cats").inputValue()).includes("こども費"), "費目の設定も残る");

/* ---------------- 明細CSVの取り込み ---------------- */
console.log("== 明細CSVの取り込み ==");
const helpers = await page.evaluate(() => ({
  d1: window.kakeiboApp.toIsoDate("2026/9/3"),
  d2: window.kakeiboApp.toIsoDate("2026年9月3日"),
  d3: window.kakeiboApp.toIsoDate("26-09-03"),
  d4: window.kakeiboApp.toIsoDate("なし"),
  a1: window.kakeiboApp.toAmount("3,480"),
  a2: window.kakeiboApp.toAmount("￥2,100"),
  a3: window.kakeiboApp.toAmount("１２８０"),
  a4: window.kakeiboApp.toAmount(""),
  csv: window.kakeiboApp.parseCsv('a,b\n"x,y",2\n"い""ろ",3\n'),
}));
ok(helpers.d1 === "2026-09-03", "2026/9/3 を読める");
ok(helpers.d2 === "2026-09-03", "2026年9月3日 を読める");
ok(helpers.d3 === "2026-09-03", "26-09-03 を読める");
ok(helpers.d4 === "", "日付でないものは空にする");
ok(helpers.a1 === 3480, "3,480 を読める");
ok(helpers.a2 === 2100, "￥2,100 を読める");
ok(helpers.a3 === 1280, "全角数字を読める");
ok(Number.isNaN(helpers.a4), "空欄は金額にしない");
ok(helpers.csv.length === 3 && helpers.csv[1][0] === "x,y", "引用符の中のカンマを保つ");
ok(helpers.csv[2][0] === 'い"ろ', "二重引用符を1文字に戻す");

for (const [file, label] of [["card-utf8.csv", "UTF-8"], ["card-sjis.csv", "Shift_JIS"]]) {
  await fresh();
  await page.setInputFiles("#importCsvFile", path.join(FIXTURES, file));
  await page.waitForSelector("#csvCard:not([hidden])");
  ok(true, label + "：ファイルを読み込んで列の選択画面が出る");
  ok((await page.locator("#csvDate").inputValue()) === "0", label + "：日付の列を当てる");
  ok((await page.locator("#csvStore").inputValue()) === "1", label + "：内容の列を当てる");
  ok((await page.locator("#csvAmount").inputValue()) === "2", label + "：金額の列を当てる");
  ok((await page.locator("#csvPreview th").first().textContent()) === "ご利用日", label + "：見出しを読めている（文字化けしない）");

  await page.click("#csvImportRun");
  await page.waitForSelector("#csvCard", { state: "hidden" });
  const toastText = await page.locator("#toast").textContent();
  ok(toastText.includes("4件を取り込みました"), label + "：4件を取り込む（" + toastText.trim() + "）");
  ok(toastText.includes("重複 1件"), label + "：同じ内容の行を除外する");
  ok(toastText.includes("読めない行 1件"), label + "：読めない行を数える");

  await page.goto(APP);
  const imported = await page.evaluate(() => JSON.parse(localStorage.getItem("kakeibo.v1")).items);
  ok(imported.length === 4, label + "：4件が保存される");
  const sm = imported.find((it) => it.store.indexOf("スーパー") >= 0);
  ok(sm && sm.amount === 3480 && sm.date === "2026-09-01", label + "：日付と金額が正しい");
  ok(sm && sm.category === "食費", label + "：店名から費目を推定する");
  const clinic = imported.find((it) => it.store.indexOf("クリニック") >= 0);
  ok(clinic && clinic.amount === 2100, label + "：￥つきの金額を読める");
  ok(clinic && clinic.category === "医療費", label + "：クリニックは医療費にする");
}

// 同じファイルをもう一度取り込んでも増えない
await page.setInputFiles("#importCsvFile", path.join(FIXTURES, "card-utf8.csv"));
await page.waitForSelector("#csvCard:not([hidden])");
await page.click("#csvImportRun");
ok((await page.evaluate(() => JSON.parse(localStorage.getItem("kakeibo.v1")).items.length)) === 4,
  "同じ明細を二度取り込んでも増えない");

/* ---------------- CSVの書き出し ---------------- */
console.log("== CSVの書き出し ==");
await page.locator("#monthLabel").waitFor();
// 取り込んだ明細は2026年9月なので、その月に移動する
await page.evaluate(() => {
  document.getElementById("q").value = "";
});
let guard = 0;
while ((await page.locator("#monthLabel").textContent()) !== "2026年9月" && guard++ < 36) {
  await page.click("#prevMonth");
}
ok((await page.locator("#monthLabel").textContent()) === "2026年9月", "取り込んだ月まで戻れる");
const [download] = await Promise.all([page.waitForEvent("download"), page.click("#exportCsv")]);
const stream = await download.createReadStream();
let body = "";
for await (const chunk of stream) body += chunk.toString("utf8");
ok(download.suggestedFilename() === "kakeibo-2026-09.csv", "ファイル名に月が入る");
ok(body.charCodeAt(0) === 0xFEFF, "Excel で文字化けしないよう BOM を付ける");
ok(body.split("\r\n")[0].replace(/^﻿/, "") === "日付,費目,金額,店名,メモ", "見出しの行");
ok(body.split("\r\n").filter((l) => l.trim()).length === 5, "見出し＋4件");
ok(body.includes("2026-09-01,食費,3480,"), "内容が入る");

/* ---------------- スマートフォンでの表示 ---------------- */
console.log("== スマートフォン表示 ==");
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
const mp = await mobile.newPage();
await mp.goto(APP);
ok((await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 1, "横スクロールが出ない");
ok(await mp.locator(".actionbar").isVisible(), "下部の操作バーが出る");
ok(await mp.evaluate(() => parseFloat(getComputedStyle(document.querySelector("input")).fontSize) >= 16),
  "入力欄の文字が16px以上（iOSで拡大されない）");
ok(await mp.evaluate(() => !!document.querySelector('link[rel="manifest"]')), "マニフェストを読み込んでいる");
await mobile.close();

console.log("\nJSエラー: " + (errors.length ? "\n  " + errors.join("\n  ") : "なし"));
if (errors.length) failures++;
await browser.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
