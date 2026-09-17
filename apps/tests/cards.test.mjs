/*
 * ポイントカード（apps/cards/）と、バーコードを描く部品（apps/shared/barcode.js）のテスト。
 *
 *   node apps/tests/cards.test.mjs
 *
 * 前半はブラウザ不要（描画部品の単体テスト）。後半は Playwright で画面を動かす。
 * 写真の代わりに、テスト内で作った小さな PNG を「撮影した画像」として渡す。
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

/* ================= 描画部品（Node だけで動く） ================= */
console.log("== apps/shared/barcode.js ==");
const src = fs.readFileSync(path.join(ROOT, "apps/shared/barcode.js"), "utf8");
const fakeWindow = {};
new Function("window", src)(fakeWindow);
const B = fakeWindow.Barcode;

// 読み取り側（fridge/ean.js）で、描いた EAN を読み戻せるかを確かめる
const eanSrc = fs.readFileSync(path.join(ROOT, "apps/fridge/ean.js"), "utf8");
const eanWin = {};
new Function("window", eanSrc)(eanWin);
const EAN = eanWin.EAN;

// モジュール列を、読み取り側が受け取る形（1 モジュール scale 画素、前後に静穏帯、0/1 の配列）にする
const toBits = (modules, scale = 3, quiet = 20) => {
  const bits = [];
  for (let i = 0; i < quiet; i++) bits.push(0);
  for (const m of modules) for (let s = 0; s < scale; s++) bits.push(m);
  for (let i = 0; i < quiet; i++) bits.push(0);
  return Uint8Array.from(bits);
};

ok(B.checkDigit("490123456789") === "4", "チェックディジット（JAN-13）");
ok(B.checksumOk("4901234567894") && !B.checksumOk("4901234567895"), "チェックディジットの検証");

for (const code of ["4901234567894", "4512345678906", "9784873115658"]) {
  const modules = B.encode(code, "ean13");
  ok(modules.length === 95, `EAN-13 ${code}: 95 モジュール`);
  ok(EAN.decodeRow(toBits(modules)) === code, `EAN-13 ${code}: 描いたものを読み戻せる`);
}
{
  const m8 = B.encode("12345670", "ean8");
  ok(m8.length === 67, "EAN-8: 67 モジュール");
  ok(EAN.decodeRow(toBits(m8)) === "12345670", "EAN-8: 描いたものを読み戻せる");
  const upc = B.encode("036000291452", "upca");
  ok(upc.length === 95 && EAN.decodeRow(toBits(upc)) === "0036000291452", "UPC-A: 先頭 0 付きの EAN-13 として読み戻せる");
}
{
  // 桁数やチェックディジットが合わないものは受け付けない
  let threw = 0;
  for (const [c, f] of [["4901234567895", "ean13"], ["12345", "ean13"], ["1234567", "ean8"], ["日本語", "code128"], ["", "code128"]]) {
    try { B.encode(c, f); } catch (e) { threw++; }
  }
  ok(threw === 5, "不正な番号は例外になる（5件）");
}

// Code128: 符号表の健全性（各文字は 6 本で合計 11 モジュール、STOP は 7 本で 13）
{
  const table = /var C128 = \[([\s\S]*?)\];/.exec(src)[1].match(/"(\d+)"/g).map((s) => s.replace(/"/g, ""));
  ok(table.length === 107, "Code128 の符号表は 107 個");
  const sums = table.map((p) => p.split("").reduce((a, c) => a + Number(c), 0));
  ok(sums.slice(0, 106).every((s) => s === 11) && sums[106] === 13, "Code128 の各符号は 11 モジュール（STOP は 13）");
  ok(table.slice(0, 106).every((p) => p.length === 6) && table[106].length === 7, "Code128 の各符号は 6 本（STOP は 7 本）");
  ok(new Set(table).size === 107, "Code128 の符号は重複しない");
}
{
  // 数字だけ 10 桁: [StartC, 5 組, check, STOP] の 8 個 → 7*11 + 13 = 90
  ok(B.encode("1234567890", "code128").length === 90, "Code128: 数字 10 桁は C セットで 90 モジュール");
  // 英字混じり: [StartB, 7 文字, check, STOP] = 10 個 → 9*11 + 13 = 112
  ok(B.encode("ABC-123", "code128").length === 112, "Code128: 英数字 7 文字は 112 モジュール");
  // 奇数桁の数字: 先頭 1 桁を B、残りを C で → [StartB, '1', CodeC, 2組, check, STOP] = 7 個 → 6*11+13 = 79
  ok(B.encode("12345", "code128").length === 79, "Code128: 奇数桁の数字は先頭だけ B セット");
  // モジュール列は 1 で始まり 1 で終わる（バーで始まりバーで終わる）
  const m = B.encode("ABC-123", "code128");
  ok(m[0] === 1 && m[m.length - 1] === 1 && m[m.length - 2] === 1, "Code128: 先頭と末尾はバー（STOP の終端バー 2 本）");
}
// 既知の例: "Wikipedia" の Code128-B のチェック文字は 88（出典: Wikipedia の Code 128 の記事）
{
  const text = "Wikipedia";
  let sum = 104;
  for (let i = 0; i < text.length; i++) sum += (text.charCodeAt(i) - 32) * (i + 1);
  ok(sum % 103 === 88, "Code128: チェック文字の計算例（Wikipedia → 88）");
}
ok(B.guessFormat("4901234567894") === "ean13", "形式の自動判断: 13 桁 → EAN-13");
ok(B.guessFormat("12345670") === "ean8", "形式の自動判断: 8 桁 → EAN-8");
ok(B.guessFormat("036000291452") === "upca", "形式の自動判断: 12 桁 → UPC-A");
ok(B.guessFormat("4901234567895") === "code128", "形式の自動判断: チェックディジット不一致の 13 桁 → Code128");
ok(B.guessFormat("MEMBER-0012") === "code128", "形式の自動判断: 英数字 → Code128");
ok(B.guessFormat("会員番号 123") === "qr", "形式の自動判断: 日本語 → QR");
ok(B.guessFormat("") === null && B.guessFormat("x".repeat(400)) === null, "形式の自動判断: 空・長すぎ → null");

/* ================= 画面（Playwright） ================= */
const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.error("Playwright が見つからないため、画面のテストは飛ばします。");
  console.log(failures ? `\n=> 失敗 ${failures} 件` : "\n=> すべて通過");
  process.exit(failures ? 1 : 0);
}

console.log("== apps/cards ==");
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".webmanifest": "application/manifest+json", ".png": "image/png" };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.endsWith("/")) p += "index.html";
  const file = path.join(ROOT, p);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
  res.end(fs.readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = "http://127.0.0.1:" + server.address().port;

const launchOptions = { args: ["--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("dialog", (dlg) => dlg.accept());

await page.goto(`${BASE}/apps/cards/index.html`);
ok((await page.title()) === "ポイントカード", "タイトル");
await page.waitForFunction(() => window.cardsApp && document.getElementById("emptyMsg"));
ok(!(await page.evaluate(() => window.cardsApp.isMemoryOnly())), "IndexedDB が使える");
ok(await page.locator("#emptyMsg").isVisible(), "最初は「カードがありません」");

// 「撮影した写真」の代わりに、ページ内で描いた 1200x750 の PNG を渡す
// --- 追加（写真 2 枚＋JAN の番号） ---
await page.click("#addBtn");
ok(await page.locator("#editModal").isVisible(), "「カードを追加」で登録画面が開く");
await page.fill("#f-name", "テスト薬局");
await page.evaluate(async () => {
  const mk = (label) => new Promise((resolve) => {
    const c = document.createElement("canvas"); c.width = 1200; c.height = 750;
    const g = c.getContext("2d"); g.fillStyle = "#e8f0ff"; g.fillRect(0, 0, 1200, 750);
    g.fillStyle = "#2f6fed"; g.font = "80px sans-serif"; g.fillText(label, 60, 200);
    c.toBlob((b) => resolve(new File([b], label + ".png", { type: "image/png" })), "image/png");
  });
  await window.cardsApp.takePhoto("front", await mk("FRONT"));
  await window.cardsApp.takePhoto("back", await mk("BACK"));
});
ok(await page.locator("#p-front").isVisible() && await page.locator("#p-back").isVisible(), "表・裏の写真が取り込まれて表示される");
ok(await page.evaluate(() => document.getElementById("p-front").naturalWidth === 1200), "写真は長辺 1600px 以下なら縮小されない");
await page.fill("#f-code", "4901234567894");
await page.dispatchEvent("#f-code", "input");
ok((await page.locator("#formatNote").textContent()).includes("JAN/EAN-13"), "番号を入れると表示形式が自動判断される");
await page.click("#saveBtn");
await page.waitForSelector("#editModal", { state: "hidden" });
ok((await page.locator("li.cardtile").count()) === 1, "保存すると一覧に 1 件出る");
ok((await page.locator("li.cardtile .name").textContent()) === "テスト薬局", "一覧に店名が出る");
ok((await page.locator("li.cardtile .code").textContent()) === "4901234567894", "一覧に番号が出る");
ok(await page.locator("li.cardtile img.thumb").isVisible(), "一覧に表面の写真が出る");

// 再読み込みしても残る（IndexedDB に保存されている）
await page.reload();
await page.waitForFunction(() => window.cardsApp && window.cardsApp.getCards().length === 1);
ok((await page.locator("li.cardtile").count()) === 1, "再読み込み後も残っている");
const stored = await page.evaluate(() => {
  const c = window.cardsApp.getCards()[0];
  return { front: c.front && c.front.size, back: c.back && c.back.size, type: c.front && c.front.type };
});
ok(stored.front > 0 && stored.back > 0 && stored.type === "image/jpeg", `写真は JPEG に変換して保存される（表 ${stored.front}B / 裏 ${stored.back}B）`);

// --- 表示（レジで見せる画面） ---
await page.click("li.cardtile button.open");
ok(await page.locator("#viewModal").isVisible(), "タップで表示画面が開く");
ok((await page.locator("#viewName").textContent()) === "テスト薬局", "表示画面に店名");
ok(await page.locator("#barcodeBox").isVisible(), "バーコードが描かれる");
const drawn = await page.evaluate(() => {
  const c = document.getElementById("barcodeCanvas");
  const g = c.getContext("2d");
  const d = g.getImageData(0, Math.floor(c.height / 2), c.width, 1).data;
  let black = 0, white = 0;
  for (let i = 0; i < d.length; i += 4) (d[i] < 128 ? black++ : white++);
  return { w: c.width, h: c.height, black, white };
});
ok(drawn.w >= 95 * 2 && drawn.black > 0 && drawn.white > drawn.black, `バーコードの中身が黒白の縞になっている（幅 ${drawn.w}px）`);
ok((await page.locator("#viewCode").textContent()) === "4901234567894", "番号も文字で出る");
ok((await page.locator("#viewPhotos img").count()) === 2, "表示画面に写真 2 枚");

// 描いたバーコードを、ブラウザの読み取り機能（BarcodeDetector）で読み戻せるか。
// 対応していない環境（Linux の Chromium など）では飛ばす
const detected = await page.evaluate(async () => {
  if (!("BarcodeDetector" in window)) return "unsupported";
  try {
    const formats = await window.BarcodeDetector.getSupportedFormats();
    if (!formats.includes("ean_13")) return "unsupported";
    const det = new window.BarcodeDetector({ formats: ["ean_13"] });
    const found = await det.detect(document.getElementById("barcodeCanvas"));
    return found.length ? found[0].rawValue : "none";
  } catch (e) { return "error:" + e.message; }
});
if (detected === "unsupported") console.log("  SKIP  描いた JAN をブラウザの読み取り機能で読み戻す（この環境は BarcodeDetector 非対応）");
else ok(detected === "4901234567894", `描いた JAN をブラウザの読み取り機能で読み戻せる（結果: ${detected}）`);

await page.click("#viewClose");
ok(await page.locator("#viewModal").isHidden(), "閉じるで戻る");

// --- Code128 と QR、「番号だけ」 ---
for (const [name, code, fmt, expectBox] of [
  ["会員証A", "MEMBER-0012", "auto", true],
  ["会員証B", "会員番号 123", "auto", true],
  ["会員証C", "0000", "none", false],
]) {
  await page.click("#addBtn");
  await page.fill("#f-name", name);
  await page.fill("#f-code", code);
  await page.selectOption("#f-format", fmt);
  await page.click("#saveBtn");
  await page.waitForSelector("#editModal", { state: "hidden" });
  await page.evaluate((n) => {
    const c = window.cardsApp.getCards().find((x) => x.name === n);
    window.cardsApp.openViewer(c.id);
  }, name);
  const boxShown = await page.locator("#barcodeBox").isVisible();
  ok(boxShown === expectBox, `${name}（${code} / ${fmt}）: ${expectBox ? "コードが描かれる" : "コードは描かれず番号だけ"}`);
  if (boxShown) {
    const back = await page.evaluate(async () => {
      if (!("BarcodeDetector" in window)) return "unsupported";
      try {
        const formats = await window.BarcodeDetector.getSupportedFormats();
        const want = ["code_128", "qr_code"].filter((f) => formats.includes(f));
        if (!want.length) return "unsupported";
        const det = new window.BarcodeDetector({ formats: want });
        const found = await det.detect(document.getElementById("barcodeCanvas"));
        return found.length ? found[0].format + ":" + found[0].rawValue : "none";
      } catch (e) { return "error:" + e.message; }
    });
    if (back === "unsupported") console.log(`  SKIP  ${name}: 描いたコードの読み戻し（BarcodeDetector 非対応）`);
    else ok(back.endsWith(":" + code), `${name}: 描いたコードをブラウザの読み取り機能で読み戻せる（${back}）`);
  }
  await page.click("#viewClose");
}
ok((await page.locator("li.cardtile").count()) === 4, "写真なしのカードも登録できる（合計 4 件）");

// 番号と形式が合わないときは保存しない
await page.click("#addBtn");
await page.fill("#f-name", "不正");
await page.fill("#f-code", "ABC");
await page.selectOption("#f-format", "ean13");
await page.click("#saveBtn");
ok(await page.locator("#editModal").isVisible(), "番号と形式が合わないときは保存されずに登録画面が残る");
await page.click("#cancelBtn");

// --- 検索・並び順 ---
await page.fill("#search", "薬局");
await page.dispatchEvent("#search", "input");
ok((await page.locator("li.cardtile").count()) === 1, "店名で絞り込める");
await page.fill("#search", "");
await page.dispatchEvent("#search", "input");
await page.click(".chip[data-sort='name']");
const names = await page.locator("li.cardtile .name").allTextContents();
ok(names.join(",") === [...names].sort((a, b) => a.localeCompare(b, "ja")).join(","), `名前順に並ぶ（${names.join(",")}）`);
await page.click(".chip[data-sort='recent']");
const recent = await page.locator("li.cardtile .name").allTextContents();
ok(recent[0] === "会員証C", `最近使った順では最後に開いたカードが先頭（${recent[0]}）`);

// --- 編集 ---
await page.evaluate(() => {
  const c = window.cardsApp.getCards().find((x) => x.name === "テスト薬局");
  window.cardsApp.openViewer(c.id);
});
await page.click("#viewEdit");
ok(await page.locator("#editModal").isVisible() && (await page.inputValue("#f-name")) === "テスト薬局", "表示画面の「編集」で登録画面が開き値が入っている");
await page.fill("#f-memo", "毎月 1 日はポイント 2 倍");
await page.click("#saveBtn");
await page.waitForSelector("#editModal", { state: "hidden" });
ok(await page.evaluate(() => window.cardsApp.getCards().find((x) => x.name === "テスト薬局").memo === "毎月 1 日はポイント 2 倍"), "編集した内容が保存される");
ok((await page.locator("li.cardtile").count()) === 4, "編集で件数は増えない");

// --- 控えの保存と読み込み ---
const exported = await page.evaluate(() => window.cardsApp.exportJson());
const parsed = JSON.parse(exported);
ok(parsed.app === "cards" && parsed.cards.length === 4, "JSON に 4 件入る");
ok(parsed.cards.find((c) => c.name === "テスト薬局").front.startsWith("data:image/jpeg;base64,"), "JSON に写真が data URL で入る");
const smaller = JSON.stringify({ app: "cards", version: 1, cards: parsed.cards.slice(0, 2) });
ok(await page.evaluate((t) => window.cardsApp.importJson(t), smaller), "JSON からの読み込みが成功する");
await page.waitForFunction(() => window.cardsApp.getCards().length === 2);
ok((await page.locator("li.cardtile").count()) === 2, "読み込むと置き換わる（2 件）");
ok(await page.evaluate(() => {
  const c = window.cardsApp.getCards().find((x) => x.name === "テスト薬局");
  return c.front instanceof Blob && c.front.size > 0 && c.back instanceof Blob;
}), "読み込んだ写真は Blob に戻る");
ok(await page.evaluate((t) => window.cardsApp.importJson(t), "{\"app\":\"other\"}") === false, "他のアプリの JSON は拒否する");

// --- 削除 ---
await page.evaluate(() => {
  const c = window.cardsApp.getCards().find((x) => x.name === "会員証A");
  window.cardsApp.openEditor(c);
});
await page.click("#deleteBtn");
await page.waitForFunction(() => window.cardsApp.getCards().length === 1);
ok((await page.locator("li.cardtile").count()) === 1, "削除すると一覧から消える");

// --- ブラウザ版の読み取りボタン（カメラなし環境でも例外を出さない） ---
await page.click("#addBtn");
await page.click("#scanBtn");
ok(await page.locator("#scanModal").isVisible(), "「番号を読み取る」で読み取り画面が開く");
await page.click("#scanClose");
await page.click("#cancelBtn");

ok(errors.length === 0, `JSエラーなし${errors.length ? " → " + errors.join(" / ") : ""}`);

await browser.close();
server.close();
console.log(failures ? `\n=> 失敗 ${failures} 件` : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
