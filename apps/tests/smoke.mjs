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
  ok((await lpage.title()) === "日常アプリ", "タイトル");
  ok((await lpage.locator("a.app").count()) === 2, "2つのアプリへのリンクがある");
  const hrefs = await lpage.locator("a.app").evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  ok(hrefs.join(",") === "fridge/,docs-tracker/", "リンク先が相対パス（公開後もそのまま動く）");
  ok((await lpage.locator("a.app img").count()) === 2, "アイコンが表示される");
  const iconOk = await lpage.locator("a.app img").first().evaluate((el) => el.naturalWidth > 0);
  ok(iconOk, "アイコン画像が実際に読み込める");
  ok((await lpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)) <= 1, "横スクロールが出ない");
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

console.log("\nJSエラー: " + (errors.length ? "\n  " + errors.join("\n  ") : "なし"));
if (errors.length) failures++;
await browser.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
