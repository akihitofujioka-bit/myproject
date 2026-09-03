/*
 * ホーム画面に追加して使う（PWA）ための確認。
 * Service Worker が有効になり、通信できない状態でもアプリが起動することを見る。
 *
 *   npm i -D playwright && npx playwright install chromium
 *   node apps/tests/pwa.test.mjs
 *
 * このテスト自身がローカルに簡易サーバーを立てる（Service Worker は
 * file:// では動かず、http://localhost か https:// が要るため）。
 */
import { createRequire } from "node:module";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
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
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
};

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.endsWith("/")) p += "index.html";
  const file = path.join(ROOT, p);
  // リポジトリの外は読ませない
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
  res.end(fs.readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = "http://127.0.0.1:" + server.address().port;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

const launchOptions = { args: ["--no-sandbox"] };
if (process.env.CHROMIUM_PATH) launchOptions.executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);

for (const app of ["fridge", "docs-tracker"]) {
  const ctx = await browser.newContext({ serviceWorkers: "allow" });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await page.goto(`${BASE}/apps/${app}/index.html`);

  const active = await page.evaluate(() =>
    navigator.serviceWorker.ready.then((r) => !!r.active).catch((e) => "ERR:" + e.message));
  ok(active === true, `${app}: Service Worker が有効になる`);

  const manifest = await page.evaluate(() =>
    fetch("manifest.webmanifest").then((r) => r.json()).catch(() => null));
  ok(!!manifest && !!manifest.name && manifest.icons.length === 2 && manifest.start_url === "./",
    `${app}: マニフェストの内容（${manifest && manifest.name}）`);

  await ctx.setOffline(true);
  const resp = await page.reload().catch(() => null);
  ok(!!resp && resp.ok(), `${app}: 通信できない状態でも起動する`);
  ok((await page.locator("h1").count()) === 1, `${app}: 通信できない状態でも画面が出る`);
  if (app === "fridge") {
    ok(await page.evaluate(() => !!(window.EAN && window.EAN.decodeRow)),
      "fridge: 通信できない状態でもバーコード読み取りが使える");
  }
  ok(await page.evaluate(() => {
    try { localStorage.setItem("x", "1"); localStorage.removeItem("x"); return true; } catch (e) { return false; }
  }), `${app}: 通信できない状態でもデータを保存できる`);
  await ctx.setOffline(false);
  ok(errs.length === 0, `${app}: JSエラーなし${errs.length ? " → " + errs.join(" / ") : ""}`);
  await ctx.close();
}

await browser.close();
server.close();
console.log(failures ? `\n=> 失敗 ${failures} 件` : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
