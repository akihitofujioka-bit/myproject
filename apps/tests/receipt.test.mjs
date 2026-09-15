/*
 * apps/shared/receipt.js（レシートの認識結果から合計・日付・店名を取り出す）のテスト。ブラウザ不要。
 *
 *   node apps/tests/receipt.test.mjs
 *
 * fixtures/receipt-*.json は、fixtures/receipt-*.txt を模擬レシート画像にして
 * iPhone と同じ文字認識（Vision）を Mac で走らせた「本物の認識結果」。
 * 作り直すとき: apps/tests/tools/render-receipt.swift と mobile/tools/ocr-probe.swift
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const FIX = path.join(ROOT, "apps/tests/fixtures");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/receipt.js"), "utf8"))(g);
const R = g.Receipt;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

// 断片を手早く作る（1行1断片。位置は行番号から）
const frag = (texts) => texts.map((t, i) => ({ text: t, x: 0, y: i * 0.04, width: 0.8, height: 0.03, confidence: 1 }));

console.log("== 文字の正規化 ==");
ok(R.normalize("１，２８０円") === "1,280円", "全角の数字と読点を半角にする");
ok(R.normalize("サンプルスーパー") === "サンプルスーパー", "長音「ー」はそのまま残す");
ok(R.normalize("￥５００") === "¥500", "全角の円記号を半角にする");

console.log("== 金額の取り出し ==");
ok(R.amountsIn("合計 ¥1,205").map((a) => a.value).join() === "1205", "桁区切りつき");
ok(R.amountsIn("お買上合計 1,980円").map((a) => a.value).join() === "1980", "円つき");
ok(R.amountsIn("消費税(8%) ¥89").map((a) => a.value).join() === "89", "「8%」は金額にしない");
ok(R.amountsIn("合計 3点 ¥540").map((a) => a.value).join() === "3,540", "点数と金額の両方を拾う（選ぶのは呼び出し側）");
ok(R.findTotal(R.rowsFromLines(frag(["TEL 0889-24-1234"]))) === null, "電話番号の行だけでは合計にしない");

console.log("== 同じ行の断片をまとめる ==");
const rows = R.rowsFromLines([
  { text: "合計", x: 0.05, y: 0.50, width: 0.1, height: 0.03 },
  { text: "¥1,205", x: 0.70, y: 0.505, width: 0.2, height: 0.03 },
  { text: "お預り", x: 0.05, y: 0.55, width: 0.1, height: 0.03 },
  { text: "¥2,000", x: 0.70, y: 0.552, width: 0.2, height: 0.03 },
]);
ok(rows.length === 2, "縦位置が近い断片は1行にまとまる");
ok(rows[0].text === "合計 ¥1,205", "左から右の順につながる");

console.log("== 合計 ==");
const totalOf = (texts) => { const t = R.findTotal(R.rowsFromLines(frag(texts))); return t && t.value; };
ok(totalOf(["小計 ¥1,116", "合計 ¥1,205", "お預り ¥2,000", "お釣り ¥795"]) === 1205, "小計・お預り・お釣りを避けて合計を取る");
ok(totalOf(["税込合計", "¥2,376", "お支払い ¥2,376"]) === 2376, "合計の金額が次の行にあっても取る");
ok(totalOf(["合計 3点 ¥540"]) === 540, "「3点」ではなく金額を取る");
ok(totalOf(["お買上合計 1,980円", "お預り 2,000円"]) === 1980, "お買上合計");
ok(totalOf(["合計（税抜） ¥1,000", "合計（税込） ¥1,100"]) === 1100, "税込の合計を優先する");
ok(totalOf(["合計 ¥1,000", "合計 ¥1,100"]) === 1100, "合計が2つあれば下のほうを取る");
const low = R.findTotal(R.rowsFromLines(frag(["牛乳 ¥248", "たまご ¥298", "¥546"])));
ok(low && low.value === 546 && low.confidence === "low", "見出しが無ければ最大の金額を低い確度で返す");
ok(totalOf(["ありがとうございました"]) == null, "金額が無ければ null");

console.log("== 日付 ==");
const dateOf = (texts) => { const d = R.findDate(R.rowsFromLines(frag(texts))); return d && d.value; };
ok(dateOf(["2026年9月15日(月) 18:42"]) === "2026-09-15", "2026年9月15日");
ok(dateOf(["2026/09/14 12:03"]) === "2026-09-14", "2026/09/14");
ok(dateOf(["令和8年9月12日"]) === "2026-09-12", "令和8年 → 2026年");
ok(dateOf(["R8.9.12"]) === "2026-09-12", "R8.9.12");
ok(dateOf(["26.09.13 07:55"]) === "2026-09-13", "26.09.13（2桁の年）");
ok(dateOf(["2026-9-5"]) === "2026-09-05", "2026-9-5");
ok(dateOf(["2026/13/40"]) == null, "ありえない日付は採用しない");
ok(dateOf(["TEL 0889-24-1234"]) == null, "電話番号を日付にしない");

console.log("== 店名 ==");
const storeOf = (texts, known) => { const s = R.findStore(R.rowsFromLines(frag(texts)), known); return s && s.value; };
ok(storeOf(["サンプルスーパー 日高店", "高知県高岡郡日高村本郷1-2-3", "TEL 0889-24-1234"]) === "サンプルスーパー 日高店", "先頭の行を店名にする");
ok(storeOf(["領収書", "なんとか薬局", "令和8年9月12日"]) === "なんとか薬局", "「領収書」は飛ばす");
ok(storeOf(["2026/09/14 12:03", "△△ドラッグ 佐川店"]) === "△△ドラッグ 佐川店", "日付の行は飛ばす");
ok(storeOf(["AAドラッグ 佐川店", "洗剤 ¥398"], ["△△ドラッグ"]) === "AAドラッグ 佐川店", "過去の店名が本文に無ければ先頭行の推定に戻る");
ok(storeOf(["サンプルスーパー 日高店"], ["サンプルスーパー"]) === "サンプルスーパー", "過去に入れた店名が含まれていればそれを使う");

console.log("== 本物の認識結果（Vision）で通し確認 ==");
const cases = [
  ["a_super", { total: 1205, date: "2026-09-15", store: "サンプルスーパー 日高店" }],
  ["b_drug", { total: 2376, date: "2026-09-14", store: /ドラッグ 佐川店$/ }],
  ["c_pharmacy", { total: 1980, date: "2026-09-12", store: "なんとか薬局" }],
  ["d_conveni", { total: 540, date: "2026-09-13", store: "コンビニ 日高駅前店" }],
];
for (const [name, want] of cases) {
  const lines = JSON.parse(fs.readFileSync(path.join(FIX, `receipt-${name}.json`), "utf8")).lines;
  const r = R.parse(lines, { knownStores: [] });
  ok(r.total && r.total.value === want.total && r.total.confidence === "high", `${name}: 合計 ${want.total}`);
  ok(r.date && r.date.value === want.date, `${name}: 日付 ${want.date}`);
  const storeOk = want.store instanceof RegExp ? want.store.test(r.store && r.store.value) : (r.store && r.store.value === want.store);
  ok(storeOk, `${name}: 店名 ${r.store && r.store.value}`);
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
