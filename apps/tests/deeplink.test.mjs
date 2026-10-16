/* shared/deeplink.js のURL解析は、ブラウザを使わずに確認する。 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = fs.readFileSync(path.join(ROOT, "apps/shared/deeplink.js"), "utf8");
const window = { location: { pathname: "/index.html" } };
vm.runInNewContext(source, { window });

const parse = (url) => JSON.parse(JSON.stringify(window.DeepLink.parse(url)));

assert.deepEqual(parse("myproject://meishi?action=scan"), {
  path: "meishi/index.html", params: { action: "scan" }
});
assert.deepEqual(parse("myproject://docs?action=scan"), {
  path: "docs-tracker/index.html", params: { action: "scan" }
});
assert.deepEqual(parse("myproject://kakeibo?action=scan"), {
  path: "kakeibo/index.html", params: { action: "scan" }
});
assert.deepEqual(parse("myproject://fridge?add=%E7%89%9B%E4%B9%B3"), {
  path: "fridge/index.html", params: { add: "牛乳" }
});
assert.deepEqual(parse("myproject://docs?todo=%E8%B3%87%E6%96%99%E3%82%92%E4%BD%9C%E3%82%8B"), {
  path: "docs-tracker/index.html", params: { todo: "資料を作る" }
});
assert.deepEqual(parse("myproject://docs?id=doc%2F001"), {
  path: "docs-tracker/index.html", params: { id: "doc/001" }
});

assert.equal(parse("myproject://unknown?action=scan"), null);
assert.equal(parse("myproject://docs?action=delete"), null);
assert.equal(parse("https://example.invalid/docs?action=scan"), null);
assert.equal(parse("myproject://fridge?add=%E0%A4%A"), null);

const longName = "あ".repeat(120);
assert.equal(parse("myproject://fridge?add=" + encodeURIComponent(longName)).params.add, "あ".repeat(100));

console.log("deeplink: すべて通過");
