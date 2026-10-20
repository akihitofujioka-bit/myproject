/* apps/shared/todochecklist.js（TODO の小さな項目を扱う純粋関数）のテスト。 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const win = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/todochecklist.js"), "utf8"))(win);
const T = win.TodoChecklist;

let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "  PASS  " : "  FAIL  ") + label);
  if (!condition) failures++;
};
let nextId = 0;
const makeId = () => "id-" + (++nextId);

const normal = T.normalize([
  { id: "a", text: " 架空の切符 ", done: true },
  { id: "b", text: "", done: false },
  { id: "c", text: "架空の資料", done: "yes" },
  null
]);
ok(normal.length === 1 && normal[0].text === "架空の切符" && normal[0].done, "壊れた項目を捨てて正規化する");
ok(T.normalize(Array.from({ length: 35 }, (_, i) => ({ id: String(i), text: "項目" + i, done: false }))).length === 30,
  "正規化は30件までにする");

const previous = [{ id: "old-a", text: "架空の切符", done: true }, { id: "old-b", text: "架空の資料", done: false }];
const fromLines = T.fromLines("架空の切符\n\n新しい確認\n架空の資料", previous, makeId);
ok(fromLines.length === 3 && fromLines[0].id === "old-a" && fromLines[0].done, "同じ文字の行はIDと完了状態を引き継ぐ");
ok(fromLines[1].text === "新しい確認" && !fromLines[1].done && fromLines[1].id.indexOf("id-") === 0,
  "新しい行には未完了のIDを付ける");
ok(T.toLines(fromLines) === "架空の切符\n新しい確認\n架空の資料", "チェックリストを行へ戻す");

const ai = T.parseAI('前置き {"items":[" 架空の切符 ","架空の切符","",12,"' + "長".repeat(70) + '"]} 後置き');
ok(ai && ai.length === 2 && ai[0] === "架空の切符" && ai[1].length === 60, "AI回答の空・重複・型・長さを検査する");
ok(T.parseAI('{"items":"違う型"}') === null && T.parseAI("回答なし") === null, "壊れたAI回答を拒む");

const memo = T.fromMemo("架空の旅行\n□ 架空の切符\n☑ 架空の資料", [
  { text: "架空の旅行", marked: false, checked: false },
  { text: "架空の切符", marked: true, checked: false },
  { text: "架空の資料", marked: true, checked: true }
], makeId);
ok(memo.title === "架空の旅行" && memo.checklist.length === 2, "印のない最初の行を件名、印の行を項目にする");
ok(!memo.checklist[0].done && memo.checklist[1].done, "メモのチェック状態を引き継ぐ");
const plainMemo = T.fromMemo("架空の確認\n補足", [
  { text: "架空の確認", marked: false, checked: false },
  { text: "補足", marked: false, checked: false }
], makeId);
ok(plainMemo.title === "架空の確認" && plainMemo.checklist.length === 0, "印のないメモは今までどおり先頭行を件名にする");

const single = T.fromMemo("☑ 架空の打合せ", [{ marked: true, checked: true, text: "架空の打合せ" }], () => "x");
ok(single.title === "架空の打合せ" && single.checklist.length === 0, "印の行が1つだけなら件名にする");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
