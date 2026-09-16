/*
 * iPhone アプリ内で注入される「本物の」Capacitor ブリッジ（native-bridge.js）を
 * Node 上で動かし、アプリ側の「ネイティブ機能が使えるか」の判定が正しく働くことを確かめる。
 *
 *   node apps/tests/nativebridge.test.mjs
 *
 * 背景: このアプリは素の HTML で @capacitor/core の JS ランタイムを読み込まない。
 * そのため注入される window.Capacitor には Plugins が無く、Capacitor.isPluginAvailable()
 * を呼ぶと例外になる。receiptscan.js がそれを呼んでいたため、家計簿の「レシートを撮る」
 * ボタンが出なかった（2026-09-16）。このテストはその再発を防ぐ。
 *
 * mobile/node_modules が無い環境（Playwright 用の CI など）では、ブリッジのテストだけ
 * 飛ばして「ブラウザでは使えない判定になる」ことだけを確かめる。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const BRIDGE = path.join(ROOT, "mobile/node_modules/@capacitor/ios/Capacitor/Capacitor/assets/native-bridge.js");
const MODULES = ["apps/shared/nativescan.js", "apps/shared/receiptscan.js"];

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

// アプリ側の共通モジュールを、与えた window に読み込む
function loadModules(win) {
  for (const m of MODULES) {
    const src = fs.readFileSync(path.join(ROOT, m), "utf8");
    new Function("window", src)(win);
  }
}

/* ---------- ブラウザ（Capacitor なし）---------- */
console.log("== ブラウザで開いたとき（window.Capacitor が無い）==");
{
  const win = {};
  loadModules(win);
  ok(win.NativeScan.available() === false, "バーコード読み取り：使えない判定になる");
  ok(win.ReceiptScan.available() === false, "レシート撮影：使えない判定になる");
}

/* ---------- iPhone アプリ（本物の注入ブリッジ）---------- */
console.log("== iPhone アプリ内（本物の native-bridge.js を注入）==");
if (!fs.existsSync(BRIDGE)) {
  console.log("  SKIP  mobile/node_modules が無いため、ブリッジの検証は飛ばします（cd mobile && npm install で有効になります）");
} else {
  // WKWebView にある最小限の DOM を用意する（ブリッジの初期化に必要なぶんだけ）
  function Document() {}
  Object.defineProperty(Document.prototype, "cookie", { get() { return ""; }, set() {}, configurable: true });
  function XMLHttpRequest() {}
  XMLHttpRequest.prototype = { open() {}, send() {}, setRequestHeader() {} };
  const doc = Object.create(Document.prototype);
  Object.assign(doc, { addEventListener() {}, dispatchEvent() {}, cookie: "" });
  const prompt = () => "false";
  const win = {
    console,
    navigator: { userAgent: "Mozilla/5.0 (iPhone)" },
    location: { href: "capacitor://localhost/kakeibo/index.html", origin: "capacitor://localhost" },
    webkit: { messageHandlers: { bridge: { postMessage() {} } } }, // これがあると iOS と判定される
    addEventListener() {}, document: doc, Document, XMLHttpRequest, prompt,
    fetch: async () => ({}), Headers: class {}, Request: class {}, Response: class {}, CustomEvent: class {},
    WEBVIEW_SERVER_URL: "capacitor://localhost",
  };
  const bridge = fs.readFileSync(BRIDGE, "utf8");
  new Function("window", "self", "globalThis", "Document", "XMLHttpRequest", "prompt", bridge)(
    win, win, win, Document, XMLHttpRequest, prompt);

  const cap = win.Capacitor;
  ok(cap && cap.getPlatform() === "ios" && cap.isNativePlatform() === true, "ブリッジが iOS として初期化される");
  ok(typeof cap.nativePromise === "function", "nativePromise が使える");
  ok(cap.Plugins === undefined, "前提の確認：Plugins は存在しない（JS ランタイム未読込のため）");

  let threw = false;
  try { cap.isPluginAvailable("ReceiptScanner"); } catch (e) { threw = true; }
  ok(threw, "前提の確認：isPluginAvailable() は例外になる（だからアプリ側で使ってはいけない）");

  loadModules(win);
  let ns = null, rs = null, err = null;
  try { ns = win.NativeScan.available(); rs = win.ReceiptScan.available(); } catch (e) { err = e; }
  ok(err === null, "アプリ側の判定が例外を出さない" + (err ? "（" + err.message + "）" : ""));
  ok(ns === true, "バーコード読み取り：使える判定になる");
  ok(rs === true, "レシート撮影：使える判定になる（今回の不具合の再現と修正）");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
