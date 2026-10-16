/*
 * apps/shared/docsai.js（書類の端末内 AI 提案の検査）のテスト。ブラウザ不要。
 *
 *   node apps/tests/docsai.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const win = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/docsai.js"), "utf8"))(win);
const D = win.DocsAI;

let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "  PASS  " : "  FAIL  ") + label);
  if (!condition) failures++;
};

ok(D.firstObject('前置き {"title":"架空の申請","meta":{"note":"{確認}"}} 後置き') ===
  '{"title":"架空の申請","meta":{"note":"{確認}"}}', "最初の JSON オブジェクトを取り出す");
ok(D.firstObject("JSON はありません") === "", "JSON がない回答を拒む");

ok(D.validDate("2028-02-29"), "実在するうるう日を受け付ける");
ok(!D.validDate("2027-02-29"), "実在しない日付を拒む");
ok(!D.validDate("2026-2-03"), "YYYY-MM-DD 以外を拒む");
ok(!D.validDate("2026-04-31"), "存在しない月末日を拒む");

const parsed = D.parse('提案です。```json\n{"title":"架空商事への回答書","dueOn":"2026-11-06","kind":"提出","summary":"架空の調査に回答する書類です。期限までに提出します。"}\n```');
ok(parsed && parsed.title === "架空商事への回答書" && parsed.kind === "提出", "説明付き回答から正しい提案を読む");
ok(D.parse('{"title":"架空の回覧","dueOn":"","kind":"回覧","summary":"架空の案内を回覧します。"}').dueOn === "", "期限不明の空文字を受け付ける");
ok(D.parse('{"title":"架空の申請","dueOn":"2026-02-30","kind":"申請","summary":"架空の申請です。"}') === null, "実在しない提案日を拒む");
ok(D.parse('{"title":"架空の申請","dueOn":"2026-10-30","kind":"会議","summary":"架空の会議です。"}') === null, "選択肢にない種別を拒む");
ok(D.parse('{"title":123,"dueOn":"2026-10-30","kind":"申請","summary":"架空の申請です。"}') === null, "型が違う回答を拒む");
ok(D.parse('{"title":"架空の申請","dueOn":"2026-10-30","kind":"申請"}') === null, "項目が欠けた回答を拒む");
ok(D.parse('{"title":"架空の申請","dueOn":"2026-10-30","kind":"申請","summary":"一文目です。二文目です。三文目です。"}') === null, "3文以上の要約を拒む");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
