/*
 * 配布用 Android アプリ（mobile-messenger/）の検査。
 *
 *   node apps/tests/android-package.test.mjs
 *
 * 2つのことを見る。
 *  1. Android プロジェクトの設定（権限・通信・バックアップ・署名・アイコン）が意図どおりか
 *  2. APK に入るのと同じ www/ の中身が、ブラウザで実際に動くか（Playwright）
 *
 * この作業環境では Android SDK を取得できないため、APK 自体の組み立ては確認していない。
 * 確認しているのは「組み立てる材料が正しいこと」まで。
 */
import fs from "node:fs";
import os from "node:os";
import http from "node:http";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const APP = path.join(ROOT, "mobile-messenger");
const ANDROID = path.join(APP, "android");
const RES = path.join(ANDROID, "app/src/main/res");

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};
const read = (file) => (fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------- 1. Android プロジェクトの設定 ---------------- */

console.log("== 求める権限 ==");
const manifest = read(path.join(ANDROID, "app/src/main/AndroidManifest.xml"));
ok(manifest.length > 0, "AndroidManifest.xml がある");
const permissions = [...manifest.matchAll(/<uses-permission[^>]*android:name="([^"]+)"/g)].map((m) => m[1]);
ok(permissions.length === 1 && permissions[0] === "android.permission.INTERNET",
  "求める権限はインターネット接続だけ（実際: " + (permissions.join(", ") || "なし") + "）");
ok(!/CAMERA|READ_MEDIA|READ_EXTERNAL_STORAGE|CONTACTS|LOCATION/.test(manifest),
  "カメラ・写真・連絡先・位置情報の権限は求めない");

console.log("== 鍵と履歴を端末の外へ出さない ==");
ok(/android:allowBackup="false"/.test(manifest), "自動バックアップを無効にしている");
ok(/android:dataExtractionRules="@xml\/data_extraction_rules"/.test(manifest), "端末間の移行の対象から外す設定を指している");
ok(/android:fullBackupContent="@xml\/backup_rules"/.test(manifest), "古い端末向けのバックアップ除外も指している");
const extraction = read(path.join(RES, "xml/data_extraction_rules.xml"));
ok(/<cloud-backup>[\s\S]*<exclude domain="root"[\s\S]*<\/cloud-backup>/.test(extraction), "クラウドへの複製から除外している");
ok(/<device-transfer>[\s\S]*<exclude domain="root"[\s\S]*<\/device-transfer>/.test(extraction), "端末間の移行から除外している");

console.log("== 通信 ==");
ok(/android:usesCleartextTraffic="false"/.test(manifest), "暗号化されていない http を使わない");
const netConfig = read(path.join(RES, "xml/network_security_config.xml"));
ok(/cleartextTrafficPermitted="false"/.test(netConfig), "通信の決まりでも http を禁じている");
ok(/android:networkSecurityConfig="@xml\/network_security_config"/.test(manifest), "その決まりを実際に適用している");

console.log("== 画面の撮影 ==");
const activity = read(path.join(ANDROID, "app/src/main/java/jp/myproject/messenger/MainActivity.java"));
ok(/FLAG_SECURE/.test(activity), "スクリーンショットと画面録画を止める設定が入っている");
ok(/super\.onCreate\(savedInstanceState\);[\s\S]*FLAG_SECURE/.test(activity), "画面ができたあとに設定している");

console.log("== 署名と版 ==");
const gradle = read(path.join(ANDROID, "app/build.gradle"));
ok(/signingConfigs\s*\{[\s\S]*release/.test(gradle), "配布用の署名の設定がある");
ok(/keystore\.properties/.test(gradle), "署名鍵はファイルから読む（コードに書かない）");
ok(/applicationIdSuffix\s+"\.debug"/.test(gradle), "動作確認用は別のアプリとして入る（配布用と取り違えない）");
ok(/versionName\s+"1\.0\.0"/.test(gradle), "版の番号が付いている");
const ignore = read(path.join(APP, ".gitignore"));
ok(/keystore\.properties/.test(ignore) && /\*\.keystore/.test(ignore), "署名鍵はリポジトリに入らない");
ok(!fs.existsSync(path.join(APP, "keystore.properties")), "署名鍵の設定ファイルが置き去りになっていない");
for (const stray of ["messenger-release.keystore", "release.keystore", "app.jks"]) {
  ok(!fs.existsSync(path.join(APP, stray)), "署名鍵そのものが置き去りになっていない（" + stray + "）");
}

console.log("== アイコン ==");
for (const density of ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"]) {
  const dir = path.join(RES, "mipmap-" + density);
  const files = ["ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png", "ic_launcher_monochrome.png"];
  ok(files.every((f) => fs.existsSync(path.join(dir, f)) && fs.statSync(path.join(dir, f)).size > 200),
    density + " のアイコン4種がある");
}
const adaptive = read(path.join(RES, "mipmap-anydpi-v26/ic_launcher.xml"));
ok(/<monochrome/.test(adaptive), "壁紙に色を合わせる表示（Android 13 以降）に対応している");
ok(/#2F6FED/i.test(read(path.join(RES, "values/ic_launcher_background.xml"))), "アイコンの地の色がアプリの色と揃っている");
ok(fs.existsSync(path.join(RES, "drawable/splash.xml")), "起動画面が歪まない作りになっている");
ok(/splash_background/.test(read(path.join(RES, "values-night/colors.xml"))), "暗い配色のときの起動画面も用意している");

console.log("== アプリに入る中身 ==");
const WWW = path.join(APP, "www");
if (!fs.existsSync(WWW)) {
  console.error("  www がありません。先に `cd mobile-messenger && npm run build` を実行してください。");
  process.exit(2);
}
const packed = fs.readdirSync(WWW, { recursive: true }).map(String).sort();
ok(packed.includes("index.html") && packed.includes("crypto.js"), "メッセージアプリ本体が入っている");
ok(!packed.some((f) => /fridge|docs-tracker/.test(f)), "冷蔵庫・書類トラッカーは入っていない（配布先に業務書類の画面を渡さない）");
ok(!packed.includes("sw.js"), "アプリ内では不要な Service Worker を除いている");
ok(!packed.some((f) => /ics\.js/.test(f)), "使わない共有部品は入れていない");
ok(read(path.join(WWW, "index.html")).includes('src="shared/native.js"'), "共有部品への参照が階層に合っている");
const assets = path.join(ANDROID, "app/src/main/assets");
ok(fs.existsSync(path.join(assets, "public/index.html")), "その中身が Android 側にも写っている（cap sync 済み）");
ok(JSON.parse(read(path.join(assets, "capacitor.config.json"))).appId === "jp.myproject.messenger",
  "アプリの識別子が配布用のものになっている");

/* ---------------- 2. APK に入るのと同じ中身を、実際に動かす ---------------- */

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.log("\n（Playwright が無いため、実際の動作確認は省略しました）");
  console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
  process.exit(failures ? 1 : 0);
}

console.log("== 実際に動かす（APK に入るのと同じ www を使う）==");

const RELAY_PORT = 8600 + Math.floor(Math.random() * 150);
const RELAY = `http://127.0.0.1:${RELAY_PORT}`;
const DATA_FILE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "android-pkg-")), "relay.json");
const relay = spawn(process.execPath, [path.join(ROOT, "server/server.mjs")], {
  env: { ...process.env, PORT: String(RELAY_PORT), DATA_FILE }, stdio: ["ignore", "ignore", "inherit"]
});
for (let i = 0; i < 60; i++) {
  try { if ((await fetch(RELAY + "/health")).ok) break; } catch (e) { /* 起動待ち */ }
  await sleep(100);
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".png": "image/png", ".webmanifest": "application/manifest+json" };
const APP_PORT = RELAY_PORT + 1;
const BASE = `http://127.0.0.1:${APP_PORT}`;
const files = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, BASE).pathname).replace(/^\/+/, "") || "index.html";
  const target = path.join(WWW, rel.endsWith("/") ? rel + "index.html" : rel);
  if (!target.startsWith(WWW)) { res.writeHead(403); return res.end(); }
  fs.readFile(target, (err, body) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "content-type": TYPES[path.extname(target)] || "application/octet-stream" });
    res.end(body);
  });
});
await new Promise((r) => files.listen(APP_PORT, r));

const launchOptions = { args: ["--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);
const errors = [];
const newPhone = async (label, name) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(label + ": " + e.message));
  page.on("dialog", (d) => d.accept());
  await page.goto(BASE + "/");
  await page.fill("#setupName", name);
  await page.fill("#setupServer", RELAY);
  await page.click("#setupStart");
  await page.waitForSelector("#homeLamp.online", { timeout: 12000 });
  return page;
};

const a = await newPhone("あきひと", "あきひと");
const b = await newPhone("たろう", "たろう");
ok(true, "起動して中継サーバーにつながる（アプリ一覧を経由せず直接メッセージ画面が出る）");
ok((await a.title()) === "ふたりのメッセージ", "アプリの表題");

await a.click("#addContact");
await a.click("#makeInvite");
await a.waitForFunction(() => document.getElementById("inviteCode").value.startsWith("MSG1.i."), null, { timeout: 8000 });
const invite = await a.inputValue("#inviteCode");
await b.click("#addContact");
await b.fill("#pasteCode", invite);
await b.click("#applyCode");
await b.waitForSelector("#replyBox", { state: "visible", timeout: 8000 });
await a.fill("#pasteCode", await b.inputValue("#replyCode"));
await a.click("#applyCode");
await a.waitForSelector("#contactList li", { timeout: 8000 });
ok(true, "招待コードの交換ができる");

await a.click("#contactList li");
await a.waitForSelector("#talkScreen.active", { timeout: 8000 });
await b.click("#pairBack");
await b.click("#contactList li");
await b.waitForSelector("#talkScreen.active", { timeout: 8000 });

await a.setInputFiles("#photoInput", path.join(WWW, "icon-512.png"));
await a.waitForSelector("#photoPreview", { state: "visible", timeout: 8000 });
await a.fill("#text", "配布版から送ります");
await a.click("#sendBtn");
const arrived = b.locator("#messageInner .msg.in", { hasText: "配布版から送ります" });
ok(await arrived.waitFor({ timeout: 12000 }).then(() => true, () => false), "文章と写真が相手に届く");
await arrived.locator("img").evaluate(
  (el) => (el.complete && el.naturalWidth > 0) ? true : new Promise((r) => { el.onload = r; el.onerror = r; }));
ok(await arrived.locator("img").evaluate((el) => el.naturalWidth > 0), "写真が実際に表示できる");

await a.click("#openVanish");
await a.waitForSelector("#vanishModal.open", { timeout: 8000 });
ok((await a.locator("#vanishSelect option").count()) === 6, "消えるメッセージの選択肢が出る（オフを含む6通り）");
await a.click("#closeVanish");
ok(errors.length === 0, "JSエラーなし" + (errors.length ? " → " + errors.join(" / ") : ""));

await browser.close();
relay.kill("SIGTERM");
files.close();
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
