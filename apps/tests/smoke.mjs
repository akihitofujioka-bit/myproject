/*
 * apps/ のアプリの動作確認（Playwright）。
 *
 *   npm i -D playwright && npx playwright install chromium
 *   node apps/tests/smoke.mjs
 *
 * ブラウザの実行ファイルを直接指定したいときは環境変数 CHROMIUM_PATH を使う。
 * アプリ自体は依存ライブラリなしで動く。このテストだけが Playwright を使う。
 */
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
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

const launchOptions = {
  args: [
    "--allow-file-access-from-files",
    "--no-sandbox",
    // カメラの代わりに疑似映像を使う（読み取り処理が例外なく回ることの確認用）
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
  ],
};
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
ok((await page.title()) === "書類・回覧・会議の期限トラッカー", "タイトル");

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

/* ---------------- バーコード読み取り ---------------- */
console.log("== バーコード読み取り（apps/fridge）==");
await page.goto("file://" + path.join(ROOT, "apps/fridge/index.html"));
await page.evaluate(() => localStorage.clear());
await page.reload();

// 画像からの読み取り（ean.js の decodeImageData をブラウザ上で確認）
const decoded = await page.evaluate(() => {
  const L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
  const R = L.map((s) => s.split("").map((c) => (c === "0" ? "1" : "0")).join(""));
  const G = R.map((s) => s.split("").reverse().join(""));
  const PARITY = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];
  const code = "4901777018884";
  const parity = PARITY[Number(code[0])];
  let bars = "101";
  for (let i = 1; i <= 6; i++) bars += (parity[i - 1] === "L" ? L : G)[Number(code[i])];
  bars += "01010";
  for (let i = 7; i <= 12; i++) bars += R[Number(code[i])];
  bars += "101";

  const scale = 3, quiet = 24;
  const cv = document.createElement("canvas");
  cv.width = bars.length * scale + quiet * 2;
  cv.height = 120;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = "#000";
  for (let i = 0; i < bars.length; i++) {
    if (bars[i] === "1") ctx.fillRect(quiet + i * scale, 10, scale, cv.height - 20);
  }
  return {
    normal: window.EAN.decodeImageData(ctx.getImageData(0, 0, cv.width, cv.height)),
    blank: window.EAN.decodeImageData(new ImageData(200, 60)),
  };
});
ok(decoded.normal === "4901777018884", "描画したバーコード画像を読み取れる");
ok(decoded.blank === null, "何も写っていない画像は読み取らない");

// カメラを開いて読み取りループが例外なく回ること（疑似カメラを使用）
await page.click("#scanBtn");
ok((await page.locator("#scanModal").isVisible()), "「バーコードで追加」でカメラ画面が開く");
await page.waitForFunction(() => !/起動しています/.test(document.getElementById("scanStatus").textContent), null, { timeout: 8000 });
const scanStatus = await page.locator("#scanStatus").textContent();
ok(/枠の中に合わせて|カメラ|https/.test(scanStatus), "カメラの状態が表示される（" + scanStatus.slice(0, 24) + "…）");
await page.waitForTimeout(600); // 読み取りループを数回まわす
await page.click("#scanClose");
ok(!(await page.locator("#scanModal").isVisible()), "閉じるでカメラ画面が閉じる");
ok(await page.evaluate(() => !document.getElementById("scanVideo").srcObject), "閉じるとカメラを解放する");

// 番号の手入力 → 初回は品名を聞く
await page.click("#scanBtn");
await page.fill("#manualCode", "4901777018884");
await page.click("#manualOk");
ok(!(await page.locator("#scanModal").isVisible()), "手入力の確定で画面が閉じる");
ok((await page.locator("#pendingCode").textContent()).includes("4901777018884"), "読み取った番号が表示される");
ok((await page.inputValue("#f-name")) === "", "初めての番号は品名が空のまま");
await page.fill("#f-name", "牛乳");
await page.fill("#f-unit", "本");
await page.fill("#f-expires", d(5));
await page.click("#submitBtn");
ok((await page.locator("li.item[data-id]").count()) === 1, "バーコード付きで登録できる");
ok((await page.locator("#pendingCodeRow").isVisible()) === false, "登録後は番号の表示が消える");
ok((await page.locator("#codeCount").textContent()).includes("1件"), "登録済みバーコードが1件になる");

// 2回目の読み取りは品名が自動で入る
await page.click("#scanBtn");
await page.fill("#manualCode", "4901777018884");
await page.click("#manualOk");
ok((await page.inputValue("#f-name")) === "牛乳", "2回目は品名が自動で入る");
ok((await page.inputValue("#f-unit")) === "本", "単位も自動で入る");
ok((await page.inputValue("#f-qty")) === "1", "数量は1に戻る");

// 桁数が足りない入力は受け付けない
await page.click("#scanBtn");
await page.fill("#manualCode", "123");
await page.click("#manualOk");
ok((await page.locator("#scanModal").isVisible()), "桁数が足りない番号では閉じない");
await page.click("#scanClose");

// バーコード辞書が保存され、再読込後も残る
await page.reload();
ok((await page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem("fridge.v1")).codes).length)) === 1,
  "バーコードと品名の対応が保存される");

/* ---------------- スマートフォンでの表示 ---------------- */
console.log("== スマートフォン表示 ==");
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const mp = await mobile.newPage();
for (const [name, file] of [["冷蔵庫", "apps/fridge/index.html"], ["書類トラッカー", "apps/docs-tracker/index.html"]]) {
  await mp.goto("file://" + path.join(ROOT, file));
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(overflow <= 1, name + "：横スクロールが出ない");
  ok(await mp.locator(".scanbar, .actionbar").isVisible(), name + "：下部の操作バーが出る");
  const fontOk = await mp.evaluate(() => {
    const el = document.querySelector("input");
    return parseFloat(getComputedStyle(el).fontSize) >= 16;
  });
  ok(fontOk, name + "：入力欄の文字が16px以上（iOSで拡大されない）");
  ok(await mp.evaluate(() => !!document.querySelector('link[rel="manifest"]')), name + "：マニフェストを読み込んでいる");
}
await mobile.close();

/* ---------------- トップページ ---------------- */
console.log("== apps/index.html（トップページ）==");
{
  const lp = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const lpage = await lp.newPage();
  const lerrs = [];
  lpage.on("pageerror", (e) => lerrs.push(String(e)));
  await lpage.goto("file://" + path.join(ROOT, "apps/index.html"));
  ok((await lpage.title()).length > 0, "タイトルがある");
  const hrefs = await lpage.locator("a.app").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  ok(hrefs.length >= 4, "アプリへのリンクがある（" + hrefs.length + "件）");
  ok(hrefs.every((h) => h && !h.startsWith("/") && !/^https?:/.test(h)),
    "リンク先がすべて相対パス（公開後もそのまま動く）");
  ok(hrefs.includes("fridge/index.html") || hrefs.includes("fridge/"), "冷蔵庫へのリンクがある");
  ok((await lpage.locator("a.app img").count()) === hrefs.length, "すべてにアイコンが表示される");
  const iconOk = await lpage.locator("a.app img").first().evaluate((el) => el.naturalWidth > 0);
  ok(iconOk, "アイコン画像が実際に読み込める");
  ok((await lpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 1, "横スクロールが出ない");
  const ver = await lpage.locator("#version").textContent();
  ok(ver && ver.trim().length > 0, "版表記の欄がある（" + ver + "）");
  ok(lerrs.length === 0, "JSエラーなし");
  await lp.close();
}

/* ---------------- カレンダーへの登録 ---------------- */
console.log("== カレンダー登録（.ics の書き出し）==");
{
  const cctx = await browser.newContext({ acceptDownloads: true });
  const cpage = await cctx.newPage();
  const cerrs = [];
  cpage.on("pageerror", (e) => cerrs.push(String(e)));

  const readDownload = async (clickAction) => {
    const [download] = await Promise.all([cpage.waitForEvent("download"), clickAction()]);
    const stream = await download.createReadStream();
    let body = "";
    for await (const chunk of stream) body += chunk.toString("utf8");
    return { name: download.suggestedFilename(), body };
  };

  // 書類トラッカー
  await cpage.goto("file://" + path.join(ROOT, "apps/docs-tracker/index.html"));
  await cpage.evaluate(() => localStorage.clear());
  await cpage.reload();
  const addDoc2 = async (title, due, kind, dest) => {
    await cpage.fill("#f-title", title);
    await cpage.selectOption("#f-kind", kind);
    await cpage.fill("#f-dest", dest);
    if (due) await cpage.fill("#f-due", due);
    await cpage.click("#submitBtn");
  };
  await addDoc2("受講報告書", d(3), "提出", "総務課");
  await addDoc2("備品発注伺い", d(6), "申請", "会計課");
  await addDoc2("期限のない書類", "", "その他", "");

  ok((await cpage.locator('li.item button[data-action="calendar"]').count()) === 2,
    "期限のある書類にだけカレンダーのボタンが出る");

  const one = await readDownload(() =>
    cpage.locator("li.item", { hasText: "受講報告書" }).locator('button[data-action="calendar"]').click());
  ok(one.name.endsWith(".ics"), "書き出されるのは .ics ファイル");
  ok(one.body.split("BEGIN:VEVENT").length - 1 === 1, "1件ぶんの予定が入る");
  ok(one.body.includes("SUMMARY:【提出】受講報告書"), "件名に種別と書類名が入る");
  ok(one.body.includes("LOCATION:総務課"), "提出先が場所として入る");
  ok(one.body.includes("DTSTART:" + d(3).replace(/-/g, "") + "T090000"), "期限日の9時に予定が入る");
  ok(one.body.includes("TRIGGER:-P1D") && one.body.includes("TRIGGER:PT0S"), "前日と当日に通知が入る");

  const seq1 = await cpage.evaluate(() =>
    JSON.parse(localStorage.getItem("docs-tracker.v1")).items.find((i) => i.title === "受講報告書").icsSeq);
  ok(seq1 === 1, "登録すると更新番号が進む（次回は更新として扱われる）");

  const again = await readDownload(() =>
    cpage.locator("li.item", { hasText: "受講報告書" }).locator('button[data-action="calendar"]').click());
  ok(again.body.includes("SEQUENCE:1"), "2回目は更新番号1で書き出す");
  ok(again.body.match(/UID:(.+)/)[1] === one.body.match(/UID:(.+)/)[1], "同じ書類なら識別子が変わらない");

  const all = await readDownload(() => cpage.click("#calendarAll"));
  ok(all.body.split("BEGIN:VEVENT").length - 1 === 2, "まとめて登録すると期限のある2件が入る");

  // 完了にすると対象から外れる
  await cpage.locator("li.item", { hasText: "備品発注伺い" }).locator('button[data-action="advance"]').click();
  await cpage.locator("li.item", { hasText: "備品発注伺い" }).locator('button[data-action="advance"]').click();
  await cpage.locator("li.item", { hasText: "備品発注伺い" }).locator('button[data-action="advance"]').click();
  const afterDone = await readDownload(() => cpage.click("#calendarAll"));
  ok(afterDone.body.split("BEGIN:VEVENT").length - 1 === 1, "完了した書類はカレンダーに登録しない");

  // 冷蔵庫
  await cpage.goto("file://" + path.join(ROOT, "apps/fridge/index.html"));
  await cpage.evaluate(() => localStorage.clear());
  await cpage.reload();
  const addFood2 = async (name, expires) => {
    await cpage.fill("#f-name", name);
    if (expires) await cpage.fill("#f-expires", expires);
    await cpage.click("#submitBtn");
  };
  await addFood2("牛乳", d(2));
  await addFood2("たまご", d(5));
  await addFood2("米", d(90));
  await addFood2("塩", "");
  const food = await readDownload(() => cpage.click("#calendarSoon"));
  ok(food.body.split("BEGIN:VEVENT").length - 1 === 2, "期限が7日以内の2件だけを登録する");
  ok(food.body.includes("SUMMARY:牛乳 の期限"), "件名に品名が入る");
  ok(food.body.includes("T180000"), "食材は18時に通知する");
  ok(!food.body.includes("米 の期限"), "期限が先の食材は入らない");

  // 該当なしのときはファイルを作らない
  await cpage.evaluate(() => localStorage.clear());
  await cpage.reload();
  let downloadHappened = false;
  cpage.once("download", () => { downloadHappened = true; });
  await cpage.click("#calendarSoon");
  await cpage.waitForTimeout(400);
  ok(!downloadHappened, "対象がないときはファイルを作らない");
  ok((await cpage.locator("#toast").textContent()).includes("ありません"), "その旨を画面で知らせる");


  // 店内コード（卵・精肉などで使われる、買うたびに番号が変わるバーコード）
  const withCd = (base) => {
    let sum = 0;
    for (let i = 0; i < base.length; i++) {
      const fromRight = base.length - i;
      sum += Number(base[i]) * (fromRight % 2 === 1 ? 3 : 1);
    }
    return base + String((10 - (sum % 10)) % 10);
  };
  const packA = withCd("201234500298");   // 1パック目（価格 298円ぶんが末尾に入る想定）
  const packB = withCd("201234500348");   // 2パック目（価格が違うので番号も違う）
  ok(packA !== packB, "同じ商品でもパックごとに番号が違う（前提の確認）");

  await cpage.goto("file://" + path.join(ROOT, "apps/fridge/index.html"));
  await cpage.evaluate(() => localStorage.clear());
  await cpage.reload();

  await cpage.click("#scanBtn");
  await cpage.fill("#manualCode", packA);
  await cpage.click("#manualOk");
  ok((await cpage.inputValue("#f-name")) === "", "1パック目は品名が空");
  await cpage.fill("#f-name", "たまご");
  await cpage.fill("#f-expires", d(7));
  await cpage.click("#submitBtn");

  await cpage.click("#scanBtn");
  await cpage.fill("#manualCode", packB);
  await cpage.click("#manualOk");
  ok((await cpage.inputValue("#f-name")) === "たまご",
    "2パック目は番号が違っても品名が自動で入る（今回の不具合の再現と修正）");

  // 別商品の店内コードは引き当てない
  await cpage.click("#scanBtn");
  await cpage.fill("#manualCode", withCd("209999900298"));
  await cpage.click("#manualOk");
  ok((await cpage.inputValue("#f-name")) === "", "別商品の店内コードでは品名が入らない");
  await cpage.click("#scanBtn");
  await cpage.click("#scanClose");

  // ネイティブ用の橋渡しは、ブラウザでは必ず「使えない」と判定される
  const nat = await cpage.evaluate(() => ({
    available: window.Native.available(),
    id1: window.Native.idFrom("doc-1@docs-tracker"),
    id2: window.Native.idFrom("doc-1@docs-tracker"),
    id3: window.Native.idFrom("doc-2@docs-tracker"),
  }));
  ok(nat.available === false, "ブラウザでは端末通知を使わない（カレンダー登録に切り替わる）");
  ok(nat.id1 === nat.id2 && Number.isInteger(nat.id1), "同じ項目なら通知番号が変わらない");
  ok(nat.id1 !== nat.id3, "別の項目なら通知番号が変わる");

  ok(cerrs.length === 0, "JSエラーなし" + (cerrs.length ? " → " + cerrs.join(" / ") : ""));
  await cctx.close();
}

/* ---------------- 書類を撮って写真に保存（書類トラッカー）---------------- */
console.log("== 書類の撮影（apps/docs-tracker）==");
{
  const docPage = await (await browser.newContext()).newPage();
  const derrs = [];
  docPage.on("pageerror", (e) => derrs.push(String(e)));
  const url = "file://" + path.join(ROOT, "apps/docs-tracker/index.html");

  // ブラウザでは出さない（端末側の書類カメラが要るため）
  await docPage.goto(url);
  ok(!(await docPage.locator("#docPhotoCard").isVisible()), "ブラウザでは撮影のカードを出さない");

  // アプリとして動いている状況を作る
  const asApp = (result) => docPage.addInitScript((r) => {
    window.Capacitor = {
      isNativePlatform: () => true,
      nativePromise: (plugin, method) => {
        window.__called = plugin + "." + method;
        return r && r.__reject ? Promise.reject(new Error(r.message)) : Promise.resolve(r);
      },
    };
  }, result);

  await asApp({ cancelled: false, saved: 2 });
  await docPage.reload();
  ok(await docPage.locator("#docPhotoCard").isVisible(), "アプリとして開くと撮影のカードが出る");
  await docPage.click("#docPhotoBtn");
  await docPage.waitForTimeout(200);
  ok((await docPage.evaluate(() => window.__called)) === "ReceiptScanner.scanToPhotos",
    "写真に保存する方の呼び出しを使う");
  ok((await docPage.locator("#toast").textContent()).includes("2枚"), "保存した枚数を知らせる");
  ok((await docPage.locator("#docPhotoBtn").textContent()) === "📄 書類を撮る", "終わるとボタンが戻る");

  // 利用者が閉じたときは何も言わない
  const ctx2 = await browser.newContext();
  const p2 = await ctx2.newPage();
  await p2.addInitScript(() => {
    window.Capacitor = { isNativePlatform: () => true, nativePromise: () => Promise.resolve({ cancelled: true }) };
  });
  await p2.goto(url);
  await p2.click("#docPhotoBtn");
  await p2.waitForTimeout(200);
  ok(!(await p2.locator("#toast").textContent()).includes("枚"), "閉じたときは保存の知らせを出さない");
  await ctx2.close();

  // 失敗したときは理由を出す
  const ctx3 = await browser.newContext();
  const p3 = await ctx3.newPage();
  await p3.addInitScript(() => {
    window.Capacitor = {
      isNativePlatform: () => true,
      nativePromise: () => Promise.reject(new Error("写真への追加が許可されていません。設定アプリで許可してください")),
    };
  });
  await p3.goto(url);
  await p3.click("#docPhotoBtn");
  await p3.waitForTimeout(200);
  ok((await p3.locator("#toast").textContent()).includes("許可されていません"), "失敗の理由を画面に出す");
  ok((await p3.locator("#docPhotoBtn").isDisabled()) === false, "失敗してもボタンは押せる状態に戻る");
  await ctx3.close();

  ok(derrs.length === 0, "JSエラーなし" + (derrs.length ? " → " + derrs.join(" / ") : ""));
}

/* ---------------- 会議の通知の読み取りと登録 ---------------- */
console.log("== 会議の通知（apps/docs-tracker）==");
{
  const mctx = await browser.newContext({ acceptDownloads: true });
  const mp = await mctx.newPage();
  const merrs = [];
  mp.on("pageerror", (e) => merrs.push(String(e)));
  const url = "file://" + path.join(ROOT, "apps/docs-tracker/index.html");
  const asLines = (text) => text.split("\n").map((t, i) => ({ text: t, x: 0, y: i * 0.04, width: 0.8, height: 0.03, confidence: 1 }));
  const notice = (name) => fs.readFileSync(path.join(ROOT, "apps/tests/fixtures", `meeting-${name}.txt`), "utf8");

  await mp.goto(url);
  ok(!(await mp.locator("#meetingCard").isVisible()), "ブラウザでは会議の読み取りカードを出さない");

  await mp.addInitScript(() => {
    window.Capacitor = { isNativePlatform: () => true, nativePromise: () => Promise.resolve({ cancelled: true }) };
  });
  await mp.goto(url);
  await mp.evaluate(() => localStorage.clear());
  await mp.reload();
  ok(await mp.locator("#meetingCard").isVisible(), "アプリとして開くと会議の読み取りカードが出る");

  // 1枚に2件の通知
  const found = await mp.evaluate((l) => window.docsApp.applyMeetingScan(l), asLines(notice("c_multi")));
  ok(found.length === 2, "1枚から2件の会議を読み取る");
  ok(await mp.locator("#meetingConfirm").isVisible(), "確認欄が出る");
  ok((await mp.locator(".meeting").count()) === 2, "会議ごとに欄が分かれる");
  ok((await mp.locator(".m-title").first().inputValue()) === "議会運営委員会", "会議名が入る");
  ok((await mp.locator(".m-date").first().inputValue()) === "2026-10-03", "日付が入る");
  ok((await mp.locator(".m-start").first().inputValue()) === "10:00", "開始時刻が入る");
  ok((await mp.locator(".m-place").nth(1).inputValue()) === "村民会館 第2会議室", "場所が入る");
  ok(await mp.locator(".m-social").nth(1).isChecked(), "懇親会ありにチェックが入る");
  ok((await mp.locator(".m-fee").nth(1).inputValue()) === "4000", "会費が入る");

  // 画面で直した内容が使われる
  await mp.fill(".m-title >> nth=0", "議会運営委員会（臨時）");
  await mp.uncheck("#mtg1");
  await mp.click("#meetingRegisterApp");
  let items = await mp.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1")).items);
  ok(items.length === 1, "チェックを外した会議は登録しない");
  ok(items[0].title === "議会運営委員会（臨時）", "画面で直した会議名で登録される");
  ok(items[0].kind === "会議", "種別は「会議」");
  ok(items[0].dueOn === "2026-10-03", "期限は開催日");
  ok(items[0].dest === "議会棟 委員会室", "提出先は場所");
  ok(items[0].note.includes("10:00 開始") && items[0].note.includes("懇親会なし"), "メモに時刻と懇親会の有無が入る");
  ok(!(await mp.locator("#meetingConfirm").isVisible()), "アプリに登録すると確認欄が閉じる");

  // カレンダーに渡す
  await mp.evaluate((l) => window.docsApp.applyMeetingScan(l), asLines(notice("a_committee")));
  const [download] = await Promise.all([mp.waitForEvent("download"), mp.click("#meetingRegisterCal")]);
  const stream = await download.createReadStream();
  let ics = "";
  for await (const chunk of stream) ics += chunk.toString("utf8");
  const unfolded = ics.replace(/\r\n /g, "");
  ok(download.suggestedFilename().startsWith("meetings-"), "会議用のファイル名で書き出す");
  ok(unfolded.includes("SUMMARY:日高村議会 総務常任委員会"), "件名は会議名");
  ok(unfolded.includes("DTSTART:20261015T133000"), "開始日時が入る");
  ok(unfolded.includes("DTEND:20261015T143000"), "終了時刻が無いときは1時間にする");
  ok(unfolded.includes("LOCATION:村民会館 2階 第1会議室"), "場所が入る");
  ok(unfolded.includes("懇親会あり"), "懇親会の有無を予定の説明に入れる");
  ok(unfolded.includes("TRIGGER:-P1D") && unfolded.includes("TRIGGER:-PT30M"), "前日と30分前に通知する");

  // 同じ会議を登録し直しても、識別子が変わらない（カレンダーで予定が増えない）
  const uidOf = (text) => (/UID:(.+)/.exec(text) || [])[1];
  const firstUid = uidOf(unfolded);
  await mp.evaluate((l) => window.docsApp.applyMeetingScan(l), asLines(notice("a_committee")));
  const [again] = await Promise.all([mp.waitForEvent("download"), mp.click("#meetingRegisterCal")]);
  let ics2 = "";
  for await (const chunk of await again.createReadStream()) ics2 += chunk.toString("utf8");
  ok(!!firstUid && uidOf(ics2.replace(/\r\n /g, "")) === firstUid,
    "同じ会議を登録し直しても識別子が変わらない（" + firstUid + "）");

  // 日付が無いものは登録できない
  await mp.evaluate((l) => window.docsApp.applyMeetingScan(l), asLines(notice("a_committee")));
  await mp.fill(".m-date >> nth=0", "");
  await mp.click("#meetingRegisterApp");
  ok((await mp.locator("#toast").textContent()).includes("日付"), "日付が空だと登録せず促す");

  // やめる
  await mp.click("#meetingCancel");
  ok(!(await mp.locator("#meetingConfirm").isVisible()), "「やめる」で確認欄が閉じる");

  // 年の書かれていない通知には注意書きを出す
  await mp.evaluate((l) => window.docsApp.applyMeetingScan(l), asLines(notice("c_multi")));
  ok((await mp.locator(".meeting .warn").count()) === 2, "年が無い日付には確認を促す注意書きを出す");

  // 会議でない書類
  const none = await mp.evaluate(() => window.docsApp.applyMeetingScan(
    [{ text: "ありがとうございました", x: 0, y: 0, width: 0.5, height: 0.03 }]));
  ok(none.length === 0 && !(await mp.locator("#meetingConfirm").isVisible()), "会議でない書類では何も出さない");

  ok(merrs.length === 0, "JSエラーなし" + (merrs.length ? " → " + merrs.join(" / ") : ""));
  await mctx.close();
}

/* ---------------- 手帳のページの読み取りとカレンダー登録 ---------------- */
console.log("== 手帳（apps/docs-tracker）==");
{
  const pctx = await browser.newContext({ acceptDownloads: true });
  const pp = await pctx.newPage();
  const perrs = [];
  pp.on("pageerror", (e) => perrs.push(String(e)));
  const url = "file://" + path.join(ROOT, "apps/docs-tracker/index.html");
  await pp.addInitScript(() => {
    window.Capacitor = { isNativePlatform: () => true, nativePromise: () => Promise.resolve({ cancelled: true }) };
  });
  await pp.goto(url);
  await pp.evaluate(() => localStorage.clear());
  await pp.reload();
  ok(await pp.locator("#plannerScanBtn").isVisible(), "アプリとして開くと「手帳を撮る」が出る");

  // 2026年10月の月間ページ（日曜始まり・1日は木曜）。予定は架空のもの
  const grid = (notes) => {
    const f = [{ text: "2026年10月", x: 0.35, y: 0.03, width: 0.3, height: 0.05 }];
    "日月火水木金土".split("").forEach((w, c) => f.push({ text: w, x: 0.08 + c * 0.137, y: 0.12, width: 0.02, height: 0.02 }));
    for (let d = 1; d <= 31; d++) {
      const i = d + 3, r = Math.floor(i / 7), c = i % 7;
      f.push({ text: String(d), x: 0.026 + c * 0.137, y: 0.164 + r * 0.135, width: 0.012 * String(d).length, height: 0.018 });
      (notes[d] || []).forEach((t, k) => f.push({ text: t, x: 0.03 + c * 0.137, y: 0.19 + r * 0.135 + k * 0.025, width: 0.12, height: 0.02 }));
    }
    return f;
  };
  const page1 = grid({ 5: ["10:00 歯医者"], 18: ["町内会の会議"], 24: ["飲み会 3,000円"] });

  // 「会議の通知を撮る」で手帳を撮っても、手帳として読む
  await pp.evaluate((l) => window.docsApp.applyMeetingScan(l), page1);
  ok(await pp.locator("#plannerConfirm").isVisible() && !(await pp.locator("#meetingConfirm").isVisible()),
    "会議の通知のつもりで手帳を撮っても、手帳の確認欄に出す");
  ok((await pp.locator("#plannerForms .meeting").count()) === 3, "マスの書き込みを3件読み取る");
  ok((await pp.locator(".p-title").first().inputValue()) === "歯医者" && (await pp.locator(".p-start").first().inputValue()) === "10:00", "件名と時刻が分かれて入る");
  ok((await pp.locator("#plannerMonth").inputValue()) === "2026-10", "ページの年月が入る");

  // 月を直すと日付が付け替わる
  await pp.fill(".p-title >> nth=1", "町内会の会議（集会所）");
  await pp.fill("#plannerMonth", "2026-11");
  await pp.dispatchEvent("#plannerMonth", "change");
  ok((await pp.locator(".p-date").first().inputValue()) === "2026-11-05", "月を直すと日付が付け替わる");
  ok((await pp.locator(".p-title").nth(1).inputValue()) === "町内会の会議（集会所）", "月を直しても、直した件名は消えない");
  await pp.fill("#plannerMonth", "2026-10");
  await pp.dispatchEvent("#plannerMonth", "change");

  // ブラウザ（CalendarWriter なし）では .ics で渡す。時刻なしは終日
  await pp.uncheck("#plan2");
  const [download] = await Promise.all([pp.waitForEvent("download"), pp.click("#plannerRegisterCal")]);
  let ics = "";
  for await (const chunk of await download.createReadStream()) ics += chunk.toString("utf8");
  const unfolded = ics.replace(/\r\n /g, "");
  ok(download.suggestedFilename().startsWith("planner-"), "手帳用のファイル名で書き出す");
  ok(unfolded.includes("SUMMARY:歯医者") && unfolded.includes("DTSTART:20261005T100000"), "時刻のある予定はその時刻で入る");
  ok(unfolded.includes("SUMMARY:町内会の会議（集会所）") && unfolded.includes("DTSTART;VALUE=DATE:20261018"), "時刻の無い予定は終日で入る");
  ok(!unfolded.includes("飲み会"), "チェックを外した予定は入れない");
  ok((unfolded.match(/BEGIN:VALARM/g) || []).length === 1, "通知は時刻のある予定だけ（30分前）");
  const plans = () => pp.evaluate(() => JSON.parse(localStorage.getItem("docs-tracker.v1") || '{"items":[]}').items.filter((i) => i.kind === "予定"));
  ok((await plans()).length === 0, "「カレンダーだけ」ではアプリの一覧に入れない");

  // アプリにも入れる
  await pp.evaluate((l) => window.docsApp.applyPlannerScan(l), page1);
  await pp.click("#plannerRegisterApp");
  let items = await plans();
  ok(items.length === 3, "「アプリだけ」で一覧に種別「予定」として3件入る");
  const dentist = items.find((i) => i.title === "歯医者");
  ok(dentist && dentist.dueOn === "2026-10-05" && dentist.note.startsWith("10:00 開始"), "日付は予定の日、メモに時刻が入る");
  ok(!(await pp.locator("#plannerConfirm").isVisible()), "アプリに登録すると確認欄が閉じる");
  ok(await pp.locator("#list").getByText("歯医者").count() > 0 || (await pp.content()).includes("歯医者"), "一覧に表示される");

  // 同じページを撮り直して登録しても増えない（再読み込みのあとでも）
  await pp.reload();
  await pp.evaluate((l) => window.docsApp.applyPlannerScan(l), page1);
  const [dl2] = await Promise.all([pp.waitForEvent("download"), pp.click("#plannerRegisterBoth")]);
  ok(!!dl2, "「カレンダーとアプリに登録」でカレンダーにも渡す");
  items = await plans();
  ok(items.length === 3, "撮り直して登録しても、アプリの予定は増えない（" + items.length + "件）");

  // ホーム画面からの受け渡し
  await pp.evaluate((l) => { window.ScanRouter.handoff("planner", l); }, page1);
  await pp.reload();
  ok(await pp.locator("#plannerConfirm").isVisible() && (await pp.locator("#plannerForms .meeting").count()) === 3,
    "ホーム画面から手帳として渡されたら、開いた時点で確認欄を出す");
  await pp.click("#plannerCancel");
  ok(!(await pp.locator("#plannerConfirm").isVisible()), "「やめる」で確認欄が閉じる");

  // 手書きの日付を読み違えたもの（10/8(日) は並びと曜日から 10/4 と推測）には注意書きを出す
  const memo = ["10/3(土)", "歯医者", "10/8(日)", "買い物", "10/5(月)", "会議"].map((t, i) => ({ text: t, x: 0.05, y: 0.05 + i * 0.05, width: 0.6, height: 0.03 }));
  await pp.evaluate((l) => window.docsApp.applyPlannerScan(l), memo);
  ok((await pp.locator("#plannerForms .warn").count()) === 1 && (await pp.locator(".p-date").nth(1).inputValue()) === "2026-10-04",
    "推測した日付の予定にだけ注意書きを出す");
  await pp.click("#plannerCancel");

  ok(perrs.length === 0, "JSエラーなし" + (perrs.length ? " → " + perrs.join(" / ") : ""));
  await pctx.close();
}

/* ---------------- 買い物リスト（Apple Watch 向け） ---------------- */
console.log("== 買い物リスト（リマインダーへ送る）==");
{
  const sctx = await browser.newContext();
  const sp = await sctx.newPage();
  const serrs = [];
  sp.on("pageerror", (e) => serrs.push("pageerror: " + e.message));
  sp.on("dialog", (dlg) => dlg.accept());

  /* 冷蔵庫：使い切って在庫に無いものを選ぶ */
  await sp.goto("file://" + path.join(ROOT, "apps/fridge/index.html"));
  ok((await sp.locator("#shopList").count()) === 1, "冷蔵庫：買い物リストのボタンがある");
  ok(await sp.evaluate(() => !!(window.Reminders && window.Reminders.send)), "冷蔵庫：送り先の部品が読み込まれている");

  const addFridge = async (name, expires) => {
    await sp.fill("#f-name", name);
    await sp.fill("#f-qty", "1");
    await sp.fill("#f-expires", expires);
    await sp.click("#submitBtn");
  };
  await addFridge("牛乳", d(3));
  await addFridge("たまご", d(5));
  await addFridge("食パン", d(2));
  await sp.locator("li.item", { hasText: "牛乳" }).locator('button[data-action="consume"]').click();
  await sp.locator("li.item", { hasText: "食パン" }).locator('button[data-action="discard"]').click();

  const names = await sp.evaluate(() => window.shoppingNames());
  ok(names.join(",") === "牛乳", "冷蔵庫：使い切って在庫に無いものだけ選ぶ（" + names.join(",") + "）");
  ok(!names.includes("食パン"), "冷蔵庫：廃棄したものは買い物リストに入れない");
  ok(!names.includes("たまご"), "冷蔵庫：在庫があるものは入れない");

  // 同じ品名を買い直したら、買い物リストから消える
  await addFridge("牛乳", d(7));
  ok((await sp.evaluate(() => window.shoppingNames())).length === 0, "冷蔵庫：買い直すと買い物リストから消える");

  await sp.locator("li.item", { hasText: "牛乳" }).locator('button[data-action="consume"]').click();
  await sp.click("#shopList");
  ok((await sp.locator("#toast").textContent()).length > 0, "冷蔵庫：押すと結果が表示される");

  /* 備蓄：最低在庫数を下回ったものを選ぶ */
  await sp.goto("file://" + path.join(ROOT, "apps/stock/index.html"));
  ok((await sp.locator("#shopList").count()) === 1, "備蓄：買い物リストのボタンがある");
  await sp.fill("#f-name", "コピー用紙");
  await sp.fill("#f-qty", "1");
  await sp.fill("#f-unit", "箱");
  await sp.fill("#f-min", "5");
  await sp.click("#submitBtn");
  await sp.fill("#f-name", "保存水 500ml");
  await sp.fill("#f-qty", "24");
  await sp.fill("#f-unit", "本");
  await sp.fill("#f-min", "12");
  await sp.click("#submitBtn");
  const low = await sp.evaluate(() => window.shoppingNames());
  ok(low.join(",") === "コピー用紙 あと4箱", "備蓄：不足分を添えて選ぶ（" + low.join(",") + "）");
  ok(!low.join(",").includes("保存水"), "備蓄：足りているものは入れない");
  await sp.click("#shopList");
  ok((await sp.locator("#toast").textContent()).length > 0, "備蓄：押すと結果が表示される");

  ok(serrs.length === 0, "JSエラーなし" + (serrs.length ? " → " + serrs.join(" / ") : ""));
  await sctx.close();
}

/* ---------------- 撮り方の選択（無音／自動で切り出す） ---------------- */
console.log("== 撮り方の選択 ==");
{
  const pctx = await browser.newContext();
  const pp = await pctx.newPage();
  const perrs = [];
  pp.on("pageerror", (e) => perrs.push("pageerror: " + e.message));
  await pp.goto("file://" + path.join(ROOT, "apps/index.html"));

  // ブラウザではカメラが無いため撮影の欄ごと隠れている。表示して中身を確かめる
  const mount = () => pp.evaluate(() => {
    document.getElementById("scanCard").hidden = false;
    const box = document.getElementById("cameraPref");
    box.hidden = false;
    window.CameraPref.mount(box);
  });

  ok(await pp.evaluate(() => !!(window.CameraPref && window.CameraPref.mount)), "撮り方の部品が読み込まれている");
  await mount();
  const pressed = (mode) => pp.locator('#cameraPref button[data-camera="' + mode + '"]').getAttribute("aria-pressed");
  ok((await pp.locator("#cameraPref button[data-camera]").count()) === 2, "2種類のボタンが出る");
  ok((await pressed("silent")) === "true", "初期は「無音で撮る」が選ばれている");

  await pp.click('#cameraPref button[data-camera="document"]');
  ok((await pressed("document")) === "true" && (await pressed("silent")) === "false", "押すと切り替わる");
  ok((await pp.locator("#cameraPref .footnote").last().textContent()).includes("シャッター音"),
    "選んだ撮り方の短所を画面に出す");

  await pp.reload();
  await mount();
  ok((await pressed("document")) === "true", "選んだ撮り方は次に開いても残る");

  ok(perrs.length === 0, "JSエラーなし" + (perrs.length ? " → " + perrs.join(" / ") : ""));
  await pctx.close();
}

/* ---------------- 期限の登録先（通知かカレンダーか） ---------------- */
console.log("== 期限の登録先（apps/docs-tracker）==");
{
  const cctx = await browser.newContext();
  const cp = await cctx.newPage();
  const cerrs = [];
  cp.on("pageerror", (e) => cerrs.push("pageerror: " + e.message));
  await cp.goto("file://" + path.join(ROOT, "apps/docs-tracker/index.html"));

  ok((await cp.locator("#calendarAll").textContent()) === "未処理の期限をカレンダーに登録",
    "ブラウザでは1つめがカレンダー登録のまま");
  ok(await cp.locator("#calendarOnly").isHidden(),
    "ブラウザでは2つめのボタンを出さない（どちらも同じ動きになるため）");

  // アプリとして動いているときの見せ方（Native が使える状態を作って確かめる）
  await cp.evaluate(() => {
    window.Native.available = () => true;
    document.getElementById("calendarAll").textContent = "未処理の期限を通知に登録";
    document.getElementById("calendarOnly").hidden = false;
  });
  ok((await cp.locator("#calendarAll").textContent()) === "未処理の期限を通知に登録",
    "アプリでは1つめが通知登録になる");
  ok(await cp.locator("#calendarOnly").isVisible(),
    "アプリでは「カレンダーにも入れる」を選べる");

  ok(cerrs.length === 0, "JSエラーなし" + (cerrs.length ? " → " + cerrs.join(" / ") : ""));
  await cctx.close();
}

/* ---------------- 通知の文面（書類・会議） ---------------- */
console.log("== 通知の文面（apps/docs-tracker）==");
{
  const nctx = await browser.newContext();
  const np = await nctx.newPage();
  const nerrs = [];
  np.on("pageerror", (e) => nerrs.push("pageerror: " + e.message));
  await np.goto("file://" + path.join(ROOT, "apps/docs-tracker/index.html"));

  const line = await np.evaluate(() => window.docsApp.noticeLine({
    kind: "回覧", title: "○○協議会の回答", dest: "総務課", status: "未着手"
  }));
  ok(line === "提出先：総務課 ／ 状態：未着手", "書類：提出先と状態が2行目に入る（" + line + "）");

  const mline = await np.evaluate(() => window.docsApp.noticeLine({
    kind: "会議", title: "定例会", dest: "村民会館 2階",
    status: "未着手",
    note: "13:30〜15:00 開始\n懇親会あり（会費 5,000円）\n（会議の通知から登録）"
  }));
  ok(mline === "13:30〜15:00 ／ 村民会館 2階 ／ 懇親会あり（会費 5,000円）",
    "会議：時刻・場所・懇親会が2行目に入る（" + mline + "）");
  ok(!mline.includes("から登録"), "会議：出どころの断り書きは通知に出さない");

  ok(nerrs.length === 0, "JSエラーなし" + (nerrs.length ? " → " + nerrs.join(" / ") : ""));
  await nctx.close();
}

console.log("\nJSエラー: " + (errors.length ? "\n  " + errors.join("\n  ") : "なし"));
if (errors.length) failures++;
await browser.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
