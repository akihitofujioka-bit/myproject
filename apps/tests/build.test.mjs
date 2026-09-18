/*
 * mobile/scripts/build-www.mjs（アプリ用 www の組み立て）の確認。
 * ブラウザは使わない。node apps/tests/build.test.mjs で実行する。
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const WWW = path.join(ROOT, "mobile/www");
let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

console.log("== build-www.mjs ==");
const out = execFileSync("node", [path.join(ROOT, "mobile/scripts/build-www.mjs")], { encoding: "utf8" });
ok(/www を作りました/.test(out), "組み立てが完了する");

const index = fs.readFileSync(path.join(WWW, "index.html"), "utf8");
const m = index.match(/<span id="version">([^<]*)<\/span>/);
ok(!!m, "トップページに版表記が埋め込まれる");
// 例: 2026-09-18 09:13（3b8fdb8）／未コミットの変更があるときは 3b8fdb8+
ok(m && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}（[0-9a-f]{7,}\+?）$/.test(m[1]), "版表記が「日時（コミット番号）」の形（" + (m && m[1]) + "）");
ok(!/開発版/.test(index), "「開発版」の仮表示が残っていない");
ok(fs.readFileSync(path.join(WWW, "version.txt"), "utf8").trim() === (m && m[1]), "version.txt にも同じ版が書かれる");
ok(!/data-web-only/.test(index), "ブラウザ専用の案内が取り除かれている");
for (const f of ["shared/meeting.js", "shared/inbox.js", "shared/receipt.js", "cards/icon-192.png"]) {
  ok(fs.existsSync(path.join(WWW, f)), f + " が含まれる");
}
ok(!fs.existsSync(path.join(WWW, "fridge/sw.js")), "Service Worker は含まれない");

console.log(failures ? `\n${failures} 件失敗` : "\nすべて通過");
process.exit(failures ? 1 : 0);
