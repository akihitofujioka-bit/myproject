/*
 * apps/shared/meishiai.js（名刺の端末内 AI 振り分け）のテスト。ブラウザ不要。
 *
 *   node apps/tests/meishiai.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = fs.readFileSync(path.join(ROOT, "apps/shared/meishiai.js"), "utf8");
const g = {};
new Function("window", source)(g);
const M = g.MeishiAI;

let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "  PASS  " : "  FAIL  ") + label);
  if (!condition) failures++;
};

ok(!!M, "MeishiAI が読み込める");

const extracted = M.extractJSON('説明です {"name":"山田 架空","company":"架空{商事}"} 続き');
ok(extracted.name === "山田 架空" && extracted.company === "架空{商事}", "回答文の最初の JSON を取り出す");

const lines = [
  "架空商事株式会社", "山田 架空", "TEL 090-1111-2222", "sample@example.invalid",
  "https://example.invalid", "東京都架空区見本1-2"
];
const checked = M.validate({
  name: "山田 架空",
  company: "架空商事株式会社",
  department: "存在しない部署",
  title: 123,
  phones: ["090-1111-2222", "123", "090-9999-9999", null],
  email: "sample@example.invalid",
  address: "東京都架空区見本1-2",
  url: "https://example.invalid"
}, lines);
ok(checked.name === "山田 架空" && checked.company === "架空商事株式会社", "元の文字にある文字列を採用する");
ok(checked.department === "" && checked.title === "", "元にない値と型が違う値を捨てる");
ok(JSON.stringify(checked.phones) === JSON.stringify(["090-1111-2222"]), "形が正しく元にある電話だけを採用する");
ok(checked.email === "sample@example.invalid" && checked.url === "https://example.invalid", "正しいメールと URL を採用する");

const badContacts = M.validate({
  email: "メールではない値", url: "javascript:alert(1)", phones: ["電話番号ではない値"]
}, ["メールではない値", "javascript:alert(1)", "電話番号ではない値"]);
ok(badContacts.email === "" && badContacts.url === "" && badContacts.phones.length === 0, "形が不正な連絡先を捨てる");

let threw = false;
try { M.extractJSON("JSON はありません"); } catch (error) { threw = error.code === "invalid_json"; }
ok(threw, "JSON がない回答は失敗にする");

g.OnDeviceAI = {
  status: () => Promise.resolve({ available: true }),
  respond: () => Promise.resolve({ text: '提案 {"name":"佐藤 見本","company":"見本未来合同会社","department":"","title":"","phones":[],"email":"","address":"","url":""}' })
};
const proposal = await M.suggest(["見本未来合同会社", "佐藤 見本"]);
ok(proposal.name === "佐藤 見本" && proposal.company === "見本未来合同会社", "端末内 AI の回答を検査して返す");

g.OnDeviceAI.status = () => Promise.resolve({ available: false, reason: "unsupported" });
let unavailable = false;
try { await M.suggest(["佐藤 見本"]); } catch (error) { unavailable = error.code === "unavailable"; }
ok(unavailable, "端末内 AI が使えないときは失敗として戻す");

g.OnDeviceAI.status = () => Promise.resolve({ available: true });
g.OnDeviceAI.respond = () => Promise.reject(new Error("架空の失敗"));
let rejected = false;
try { await M.suggest(["佐藤 見本"]); } catch (error) { rejected = error.message === "架空の失敗"; }
ok(rejected, "端末内 AI の失敗を呼び出し側へ戻す");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて成功");
process.exit(failures ? 1 : 0);
