/*
 * apps/messenger の動作確認（Playwright）。
 * ブラウザを2つ立ち上げて「あきひと」と「たろう」に見立て、中継サーバーごしに実際にやりとりさせる。
 *
 *   npm i -D playwright && npx playwright install chromium
 *   node apps/tests/messenger.smoke.mjs
 *
 * ブラウザの実行ファイルを直接指定したいときは環境変数 CHROMIUM_PATH を使う。
 * アプリ自体は依存ライブラリなしで動く。このテストだけが Playwright を使う。
 */
import fs from "node:fs";
import os from "node:os";
import http from "node:http";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------- 中継サーバーと、アプリを配る簡易サーバー ---------------- */

const RELAY_PORT = 8700 + Math.floor(Math.random() * 200);
const RELAY = `http://127.0.0.1:${RELAY_PORT}`;
const DATA_FILE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "messenger-smoke-")), "relay.json");

function startRelay() {
  const child = spawn(process.execPath, [path.join(ROOT, "server/server.mjs")], {
    env: { ...process.env, PORT: String(RELAY_PORT), DATA_FILE },
    stdio: ["ignore", "ignore", "pipe"]
  });
  child.stderr.on("data", (b) => console.error("  [relay] " + String(b).trim()));
  return child;
}

async function waitForRelay(timeoutMs = 8000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try { if ((await fetch(RELAY + "/health")).ok) return true; } catch (e) { /* 起動待ち */ }
    await sleep(100);
  }
  throw new Error("中継サーバーが起動しませんでした");
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".png": "image/png", ".webmanifest": "application/manifest+json", ".json": "application/json" };

const APP_PORT = RELAY_PORT + 1;
const APP = `http://127.0.0.1:${APP_PORT}`;
const files = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, APP).pathname).replace(/^\/+/, "");
  const target = path.join(ROOT, rel.endsWith("/") || rel === "" ? rel + "index.html" : rel);
  if (!target.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(target, (err, body) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "content-type": TYPES[path.extname(target)] || "application/octet-stream" });
    res.end(body);
  });
});
await new Promise((r) => files.listen(APP_PORT, r));

let relay = startRelay();
await waitForRelay();

/* ---------------- ブラウザ ---------------- */

const launchOptions = { args: ["--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);

const errors = [];
async function newPhone(label) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(label + " pageerror: " + e.message));
  page.on("console", (m) => {
    // このテストは途中でわざと中継サーバーを止めるため、そのときの通信エラーは想定内として除く
    var expected = /ERR_CONNECTION_REFUSED|ERR_INCOMPLETE_CHUNKED_ENCODING|ERR_NETWORK_CHANGED|ERR_CONNECTION_RESET/;
    if (m.type() === "error" && !expected.test(m.text())) errors.push(label + " console: " + m.text());
  });
  page.on("dialog", (dlg) => dlg.accept());
  await page.goto(APP + "/apps/messenger/");
  return { ctx, page, label };
}

const setUp = async (phone, name) => {
  await phone.page.fill("#setupName", name);
  await phone.page.fill("#setupServer", RELAY);
  await phone.page.click("#setupStart");
  await phone.page.waitForSelector("#homeScreen.active", { timeout: 8000 });
  await phone.page.waitForSelector("#homeLamp.online", { timeout: 10000 });
};

const a = await newPhone("あきひと");
const b = await newPhone("たろう");

/* ---------------- はじめの設定 ---------------- */
console.log("== はじめの設定 ==");
ok((await a.page.title()) === "ふたりのメッセージ", "タイトル");
ok(await a.page.locator("#setupScreen.active").isVisible(), "初回は設定画面から始まる");
ok((await a.page.locator(".notice").first().textContent()).includes("監査は受けていません"),
  "監査を受けていないことを最初に伝えている");

await a.page.click("#setupStart");
ok(await a.page.locator("#setupScreen.active").isVisible(), "名前が空のままでは進めない");

await setUp(a, "あきひと");
await setUp(b, "たろう");
ok(await a.page.locator("#homeScreen.active").isVisible(), "設定が終わると一覧画面になる");
ok((await a.page.locator("#homeStatus").textContent()).includes("接続済み"), "中継サーバーにつながる");
ok(await a.page.locator("#contactEmpty").isVisible(), "最初は相手がいない");

/* ---------------- ペアリング ---------------- */
console.log("== 相手の追加（コードの交換）==");
await a.page.click("#addContact");
await a.page.click("#makeInvite");
await a.page.waitForSelector("#inviteBox", { state: "visible", timeout: 8000 });
await a.page.waitForFunction(() => document.getElementById("inviteCode").value.startsWith("MSG1.i."), null, { timeout: 8000 });
const inviteCode = await a.page.inputValue("#inviteCode");
ok(inviteCode.startsWith("MSG1.i."), "招待コードができる");

await b.page.click("#addContact");
await b.page.fill("#pasteCode", inviteCode);
await b.page.click("#applyCode");
await b.page.waitForSelector("#replyBox", { state: "visible", timeout: 5000 });
const replyCode = await b.page.inputValue("#replyCode");
ok(replyCode.startsWith("MSG1.r."), "返信コードができる");

await a.page.fill("#pasteCode", replyCode);
await a.page.click("#applyCode");
await a.page.waitForSelector("#homeScreen.active", { timeout: 8000 });
await a.page.waitForSelector("#contactList li", { timeout: 8000 });
ok((await a.page.locator("#contactList li").count()) === 1, "あきひとの一覧に相手が出る");
ok((await a.page.locator("#contactList .name").textContent()) === "たろう", "相手の名前が出る");

await b.page.click("#pairBack");
await b.page.waitForSelector("#contactList li", { timeout: 8000 });
ok((await b.page.locator("#contactList .name").textContent()) === "あきひと", "たろうの一覧にも相手が出る");

// 同じコードをもう一度読ませても増えない
await b.page.click("#addContact");
await b.page.fill("#pasteCode", inviteCode);
await b.page.click("#applyCode");
await b.page.waitForSelector("#toast.show", { timeout: 8000 });
await b.page.click("#pairBack");
ok((await b.page.locator("#contactList li").count()) === 1, "同じ相手は二重に登録されない");

/* ---------------- 安全番号 ---------------- */
console.log("== 安全番号 ==");
const openTalk = async (phone) => {
  await phone.page.click("#contactList li");
  await phone.page.waitForSelector("#talkScreen.active", { timeout: 8000 });
};
await openTalk(a);
await openTalk(b);
const showSafety = async (phone) => {
  await phone.page.click("#openSafety");
  await phone.page.waitForSelector("#safetyModal.open", { timeout: 8000 });
  await phone.page.waitForFunction(() => document.getElementById("safetyDigits").textContent.length > 50, null, { timeout: 8000 });
  return (await phone.page.locator("#safetyDigits").textContent()).trim();
};
const digitsA = await showSafety(a);
const digitsB = await showSafety(b);
ok(/^\d{5}( \d{5}){11}$/.test(digitsA), "60桁が表示される");
ok(digitsA === digitsB, "双方の安全番号が一致する");
await a.page.click("#closeSafety");
await b.page.click("#closeSafety");

/* ---------------- 文章のやりとり ---------------- */
console.log("== メッセージのやりとり ==");
const bubbles = (phone) => phone.page.locator("#messageInner .msg:not(.system) .bubble");

await a.page.fill("#text", "おはようございます");
await a.page.click("#sendBtn");
ok(await b.page.locator("#messageInner .msg.in", { hasText: "おはようございます" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "たろうの画面に届く");
ok((await a.page.locator("#messageInner .msg.out .meta").last().textContent()).includes("送信済み"),
  "送った側は「送信済み」になる");

await b.page.fill("#text", "こちらこそ、よろしくお願いします");
await b.page.click("#sendBtn");
ok(await a.page.locator("#messageInner .msg.in", { hasText: "こちらこそ" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "返事も届く");

for (let i = 0; i < 3; i++) {
  await a.page.fill("#text", "続けて" + i);
  await a.page.click("#sendBtn");
}
ok(await b.page.locator("#messageInner .msg.in", { hasText: "続けて2" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "続けて送っても順に届く");

/* ---------------- 写真 ---------------- */
console.log("== 写真の添付 ==");
await a.page.setInputFiles("#photoInput", path.join(ROOT, "apps/messenger/icon-512.png"));
await a.page.waitForSelector("#photoPreview", { state: "visible", timeout: 8000 });
ok((await a.page.locator("#photoInfo").textContent()).includes("KB"), "送る前に大きさが表示される");
await a.page.fill("#text", "写真です");
await a.page.click("#sendBtn");

const photoIn = b.page.locator("#messageInner .msg.in", { hasText: "写真です" });
ok(await photoIn.waitFor({ timeout: 10000 }).then(() => true, () => false), "写真つきメッセージが届く");
ok((await photoIn.locator("img").count()) === 1, "写真が表示される");
await photoIn.locator("img").evaluate(
  (el) => el.complete && el.naturalWidth > 0 ? true : new Promise((r) => { el.onload = r; el.onerror = r; }));
ok(await photoIn.locator("img").evaluate((el) => el.naturalWidth > 0), "写真が実際に読み込める");
ok((await photoIn.locator("img").getAttribute("src")).startsWith("data:image/jpeg;base64,"),
  "写真は端末内のデータとして表示される（外部から読み込まない）");
await photoIn.locator("img").click();
ok(await b.page.locator("#imageModal.open").isVisible(), "写真を押すと大きく表示される");
await b.page.click("#closeImage");
ok(!(await a.page.locator("#photoPreview").isVisible()), "送ったあとは添付が消える");

/* ---------------- 中継サーバーには暗号文しか残らない ---------------- */
console.log("== 中継の途中で読めないこと ==");
await sleep(1400);
{
  const saved = fs.existsSync(DATA_FILE) ? fs.readFileSync(DATA_FILE, "utf8") : "";
  ok(!saved.includes("おはようございます") && !saved.includes("写真です"),
    "中継サーバーの保存ファイルに本文が現れない");
}

/* ---------------- 消えるメッセージ（時間） ---------------- */
console.log("== 消えるメッセージ（時間で消える）==");
ok((await a.page.locator("#talkSub").textContent()).includes("オフ"), "はじめは「オフ（消えない）」");
ok((await a.page.locator("#messageInner .meta").last().textContent()).indexOf("消えます") === -1,
  "オフのうちは消える予定が付かない");

await a.page.click("#openVanish");
await a.page.waitForSelector("#vanishModal.open", { timeout: 8000 });
ok((await a.page.locator("#vanishSelect option").first().textContent()).includes("オフ"),
  "選択肢の先頭が「オフ（消えない）」");
ok((await a.page.locator("#vanishModal .notice").textContent()).includes("撮影"),
  "撮影までは防げないことを画面で伝えている");
await a.page.selectOption("#vanishSelect", String(60 * 60 * 1000));
await a.page.click("#applyVanish");
await a.page.waitForFunction(() => document.getElementById("talkSub").textContent.includes("1時間後"), null, { timeout: 8000 });
ok((await a.page.locator("#talkSub").textContent()).includes("1時間後"), "設定が画面に出る");
ok(await b.page.locator("#messageInner .msg.system", { hasText: "1時間後" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "相手の画面にも設定変更が伝わる");
ok((await b.page.locator("#talkSub").textContent()).includes("1時間後"), "相手側の表示も切り替わる");

await a.page.fill("#text", "これは1時間で消えます");
await a.page.click("#sendBtn");
const vanishing = b.page.locator("#messageInner .msg.in", { hasText: "これは1時間で消えます" });
ok(await vanishing.waitFor({ timeout: 8000 }).then(() => true, () => false), "設定後のメッセージが届く");
ok((await vanishing.locator(".meta").textContent()).includes("消えます"), "受け取った側に残り時間が出る");
ok((await a.page.locator("#messageInner .msg.out .meta").last().textContent()).includes("消えます"),
  "送った側にも残り時間が出る");

// 期限を過ぎたものが実際に消えることを確かめる（保存されている期限を過去にずらす）
await b.page.evaluate(() => new Promise((resolve, reject) => {
  const req = indexedDB.open("myproject-messenger");
  req.onsuccess = () => {
    const db = req.result;
    const tx = db.transaction("messages", "readwrite");
    const store = tx.objectStore("messages");
    store.getAll().onsuccess = (ev) => {
      for (const row of ev.target.result) {
        if (row.expiresAt) { row.expiresAt = Date.now() - 1000; store.put(row); }
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  };
  req.onerror = () => reject(req.error);
}));
await b.page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
ok(await b.page.locator("#messageInner .msg", { hasText: "これは1時間で消えます" })
  .waitFor({ state: "detached", timeout: 8000 }).then(() => true, () => false),
  "期限を過ぎたメッセージは端末から消える");
ok(await b.page.locator("#messageInner .msg", { hasText: "おはようございます" }).count() === 1,
  "設定より前のメッセージは残る（あとから期限は付かない）");

/* ---------------- 消える機能をオフに戻す ---------------- */
console.log("== 消える機能をオフに戻す ==");
await a.page.fill("#text", "まだ消える予定のメッセージ");
await a.page.click("#sendBtn");
await b.page.locator("#messageInner .msg.in", { hasText: "まだ消える予定" }).waitFor({ timeout: 8000 });

await a.page.click("#openVanish");
await a.page.waitForSelector("#vanishModal.open", { timeout: 8000 });
await a.page.selectOption("#vanishSelect", "0");
await a.page.click("#applyVanish");
await a.page.waitForFunction(() => document.getElementById("talkSub").textContent.includes("オフ"), null, { timeout: 8000 });
ok((await a.page.locator("#talkSub").textContent()).includes("オフ"), "オフに戻せる");
ok((await a.page.locator("#vanishHint").textContent()).includes("消えません"), "オフであることが入力欄の下にも出る");
ok(await b.page.locator("#messageInner .msg.system", { hasText: "オフ" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "オフも相手に伝わる");
ok(await b.page.locator("#messageInner .msg.in", { hasText: "まだ消える予定" })
  .locator(".meta").textContent().then((t) => !t.includes("消えます")),
  "オフに戻すと、消える予定だったものも残る");

await a.page.fill("#text", "オフのあとのメッセージ");
await a.page.click("#sendBtn");
const afterOff = b.page.locator("#messageInner .msg.in", { hasText: "オフのあとのメッセージ" });
await afterOff.waitFor({ timeout: 8000 });
ok(!(await afterOff.locator(".meta").textContent()).includes("消えます"), "オフのあとは消える予定が付かない");

/* ---------------- 1回だけのメッセージ ---------------- */
console.log("== 1回だけのメッセージ ==");
await a.page.click("#onceToggle");
ok((await a.page.locator("#onceToggle").getAttribute("class")).includes("on"), "「1回だけ」を選べる");
await a.page.fill("#text", "ここだけの話です");
await a.page.setInputFiles("#photoInput", path.join(ROOT, "apps/messenger/icon-192.png"));
await a.page.waitForSelector("#photoPreview", { state: "visible", timeout: 8000 });
await a.page.click("#sendBtn");
await a.page.waitForFunction(
  () => document.getElementById("messageInner").textContent.includes("1回だけのメッセージを送りました"),
  null, { timeout: 8000 });
ok(!(await a.page.locator("#onceToggle").getAttribute("class")).includes("on"),
  "送ると「1回だけ」は自動で解除される（誤送信を防ぐため）");
ok((await a.page.locator("#messageInner .msg.out").last().textContent()).includes("1回だけのメッセージを送りました"),
  "送った側には内容を残さない");
ok(!(await a.page.locator("#messageInner").textContent()).includes("ここだけの話です"),
  "送った側の履歴に本文が残らない");

const onceIn = b.page.locator("#messageInner .msg.in").last();
ok(await b.page.locator(".once").waitFor({ timeout: 10000 }).then(() => true, () => false),
  "受け取った側では「1回だけのメッセージ」として届く");
ok(!(await b.page.locator("#messageInner").textContent()).includes("ここだけの話です"),
  "開くまでは本文が画面に出ない");
await onceIn.locator("button").click();
await b.page.waitForSelector("#onceModal.open", { timeout: 8000 });
await b.page.waitForFunction(() => document.getElementById("onceBody").textContent.length > 0, null, { timeout: 8000 });
ok(await b.page.locator("#onceModal.open").isVisible(), "「開く」で内容が出る");
ok((await b.page.locator("#onceBody").textContent()).includes("ここだけの話です"), "本文が読める");
await b.page.locator("#onceBody img").evaluate(
  (el) => el.complete && el.naturalWidth > 0 ? true : new Promise((r) => { el.onload = r; el.onerror = r; }));
ok(await b.page.locator("#onceBody img").evaluate((el) => el.naturalWidth > 0), "写真も実際に読み込める");
await b.page.click("#closeOnce");
await b.page.waitForFunction(
  () => document.getElementById("messageInner").textContent.includes("表示済み"), null, { timeout: 8000 });
ok(!(await b.page.locator("#messageInner").textContent()).includes("ここだけの話です"),
  "閉じると本文は消える");
ok((await b.page.locator("#messageInner .msg.in").last().textContent()).includes("表示済み"),
  "「表示済み」の跡だけ残る");

// 端末に本当に残っていないことを、保存の中身で確かめる
const leftovers = await b.page.evaluate(() => new Promise((resolve, reject) => {
  const req = indexedDB.open("myproject-messenger");
  req.onsuccess = () => {
    const all = req.result.transaction("messages", "readonly").objectStore("messages").getAll();
    all.onsuccess = () => resolve(JSON.stringify(all.result));
    all.onerror = () => reject(all.error);
  };
  req.onerror = () => reject(req.error);
}));
ok(!leftovers.includes("ここだけの話です"), "端末の保存領域にも本文が残らない");

/* ---------------- 回線が切れているとき ---------------- */
console.log("== 回線が切れているとき ==");
relay.kill("SIGTERM");
await sleep(500);
await a.page.fill("#text", "圏外から送ります");
await a.page.click("#sendBtn");
await a.page.waitForFunction(
  () => /未送信/.test(document.getElementById("messageInner").textContent), null, { timeout: 15000 })
  .catch(() => {});
ok((await a.page.locator("#messageInner .msg.out .meta").last().textContent()).includes("未送信"),
  "送れないときは「未送信」と分かる");

relay = startRelay();
await waitForRelay();
ok(await b.page.locator("#messageInner .msg.in", { hasText: "圏外から送ります" })
  .waitFor({ timeout: 25000 }).then(() => true, () => false), "回線が戻ると自動で送り直される");
ok(await a.page.locator("#messageInner .msg.out", { hasText: "圏外から送ります" })
  .locator(".meta").textContent().then((t) => t.includes("送信済み")), "送信済みに変わる");

/* ---------------- 再読込しても残る ---------------- */
console.log("== 再読込 ==");
await b.page.reload();
await b.page.waitForSelector("#homeScreen.active", { timeout: 8000 });
ok((await b.page.locator("#contactList li").count()) === 1, "再読込しても相手が残る");
await b.page.click("#contactList li");
await b.page.waitForSelector("#talkScreen.active", { timeout: 8000 });
ok((await b.page.locator("#messageInner").textContent()).includes("おはようございます"), "履歴も残る");

/* ---------------- 未読の数 ---------------- */
console.log("== 未読 ==");
await b.page.click("#talkBack");
await a.page.fill("#text", "一覧にいるときの着信");
await a.page.click("#sendBtn");
ok(await b.page.locator("#contactList .badge:not(.quiet)").waitFor({ timeout: 8000 }).then(() => true, () => false),
  "トークを開いていないときは未読の数が出る");
await b.page.click("#contactList li");
await b.page.waitForSelector("#talkScreen.active", { timeout: 8000 });
await b.page.click("#talkBack");
await b.page.waitForSelector("#homeScreen.active", { timeout: 8000 });
ok((await b.page.locator("#contactList .badge:not(.quiet)").count()) === 0, "開くと未読が消える");

/* ---------------- スマートフォンでの見え方 ---------------- */
console.log("== スマートフォン表示 ==");
for (const phone of [a, b]) {
  const overflow = await phone.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(overflow <= 1, phone.label + "：横スクロールが出ない");
}
if (!(await a.page.locator("#talkScreen.active").isVisible())) {
  await a.page.click("#contactList li");
  await a.page.waitForSelector("#talkScreen.active", { timeout: 8000 });
}
const fontOk = await a.page.evaluate(() => parseFloat(getComputedStyle(document.getElementById("text")).fontSize) >= 16);
ok(fontOk, "入力欄の文字が16px以上（iOSで勝手に拡大されない）");
ok(await a.page.evaluate(() => !!document.querySelector('link[rel="manifest"]')), "マニフェストを読み込んでいる");

/* ---------------- 設定画面 ---------------- */
console.log("== 設定 ==");
await a.page.click("#talkBack");
await a.page.click("#openSettings");
ok((await a.page.locator("#myId").textContent()).length === 32, "自分の宛先番号が出る");
await a.page.click("#testServer");
ok(await a.page.locator("#serverInfo", { hasText: "つながりました" })
  .waitFor({ timeout: 8000 }).then(() => true, () => false), "中継サーバーの状態を確かめられる");

/* ---------------- 後片付け ---------------- */
console.log("\nJSエラー: " + (errors.length ? "\n  " + errors.join("\n  ") : "なし"));
if (errors.length) failures++;

await browser.close();
relay.kill("SIGTERM");
files.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
