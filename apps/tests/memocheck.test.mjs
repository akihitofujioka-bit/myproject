/* apps/shared/memocheck.js（メモのチェック印を扱う純粋関数）のテスト。 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const win = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/memocheck.js"), "utf8"))(win);
const M = win.MemoCheck;

let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "  PASS  " : "  FAIL  ") + label);
  if (!condition) failures++;
};

const parsed = M.parse("□ 未完了\n・箇条書き\n- [ ] 空欄\n* 星\n☑ 完了\n✓済み\n✔ 確認済み\n■終了\n- [x] 小文字\n- [X] 大文字\n普通の行");
ok(parsed.slice(0, 4).every((line) => line.marked && !line.checked), "未チェックの印を判定する");
ok(parsed.slice(4, 10).every((line) => line.marked && line.checked), "チェック済みの印を判定する");
ok(!parsed[10].marked && parsed[10].text === "普通の行", "印のない行は本文のままにする");
ok(parsed[0].text === "未完了" && parsed[1].text === "箇条書き", "印の後ろの空白を本文から外す");

ok(M.toggle("一行目\r\n- [ ] 二行目\r\n三行目", 1, true) === "一行目\r\n☑ 二行目\r\n三行目", "指定行だけをチェックして改行を保つ");
ok(M.toggle("□ 対象\n□ そのまま", 0, false) === "□ 対象\n□ そのまま", "チェックを外すと標準の印にする");
ok(M.toggle("普通の行\n□ 対象", 0, true) === "普通の行\n□ 対象", "印のない行は書き換えない");
ok(M.strip("☑ 完了\n普通\n- [ ] 未完了") === "完了\n普通\n未完了", "件名用に各行の印を外す");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
