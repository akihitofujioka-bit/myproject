/*
 * apps/shared/contacts.js（通知文から連絡先を取り出す）のテスト。ブラウザ不要。
 *
 *   node apps/tests/contacts.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const src = fs.readFileSync(path.join(ROOT, "apps/shared/contacts.js"), "utf8");
new Function("window", src)(g);
const C = g.Contacts;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

const f = C.find("問い合わせ先 総務課 電話 ０３－００００－００００（内線 123）\nmail: kakuu@example.jp 詳細 https://example.jp/a\n再掲 03-0000-0000");
ok(JSON.stringify(f.phones) === JSON.stringify(["03-0000-0000", "内線 123"]), "全角を直し、重複を除き、出た順");
ok(JSON.stringify(f.emails) === JSON.stringify(["kakuu@example.jp"]), "メール");
ok(JSON.stringify(f.urls) === JSON.stringify(["https://example.jp/a"]), "URL");
ok(C.find("090-0000-0000 と 0300000000").phones.length === 2, "携帯と区切り無し");
ok(C.find("令和8年10月22日 13:30").phones.length === 0, "日付・時刻を電話と取り違えない");
ok(C.noteLine(f) === "問い合わせ: 電話 03-0000-0000 / 内線 123 / メール kakuu@example.jp", "メモの 1 行（URL は入れない）");
ok(C.noteLine(C.find("なし")) === "", "無ければ空");
ok(C.linkify("電話 03-0000-0000 <b>") === '電話 <a href="tel:0300000000">03-0000-0000</a> &lt;b&gt;', "電話のリンクとエスケープ");
ok(C.linkify("a@example.jp\nb").includes('<a href="mailto:a@example.jp">a@example.jp</a><br>b'), "メールのリンクと改行");

ok(C.linkify("架空センター 03ー0000ー0000") === '架空センター <a href="tel:0300000000">03-0000-0000</a>', "文中の長音はそのまま");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて成功");
process.exit(failures ? 1 : 0);
