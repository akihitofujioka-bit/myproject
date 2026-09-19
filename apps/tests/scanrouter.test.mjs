/*
 * apps/shared/scanrouter.js（撮った書類をレシート/会議の通知に振り分ける）のテスト。ブラウザ不要。
 *
 *   node apps/tests/scanrouter.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

// scanrouter.js は Receipt / Meeting を使うため、同じ window（g）に順番に読み込む
function makeSandbox() {
  const g = {};
  // sessionStorage の最小限のまね（Node には無い）
  const store = {};
  g.sessionStorage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; }
  };
  ["receipt.js", "meeting.js", "scanrouter.js"].forEach((f) => {
    new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared", f), "utf8"))(g);
  });
  return g;
}

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

// 断片を手早く作る（1行1断片。位置は行番号から）
const frag = (texts) => texts.map((t, i) => ({ text: t, x: 0, y: i * 0.04, width: 0.8, height: 0.03, confidence: 1 }));

console.log("== 判定 ==");
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["サンプルスーパー", "2026年9月18日", "合計 ¥1,280"]));
  ok(r.type === "receipt", "合計額があればレシート");
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["○○地区会議開催のお知らせ", "令和8年10月15日(木)", "13:30〜", "○○コミュニティセンター"]));
  ok(r.type === "meeting", "会議名・日付・場所があれば会議の通知");
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["特に何も書かれていないメモ"]));
  ok(r.type === "unknown", "どちらでもなければ unknown");
}
{
  // 会議の通知に金額（懇親会費など）が書かれていて、たまたま合計らしき行にも見える場合
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["○○地区会議開催のお知らせ", "令和8年10月15日(木)", "懇親会費 合計 ¥3,000"]));
  ok(r.type === "ambiguous" || r.type === "meeting", "両方に当てはまる場合は ambiguous（会議側が勝つのも許容）");
}

console.log("== 受け渡し ==");
{
  const g = makeSandbox();
  const lines = frag(["合計 ¥1,280"]);
  ok(g.ScanRouter.handoff("receipt", lines) === true, "handoff は成功を返す");
  ok(g.ScanRouter.takeHandoff("receipt").length === lines.length, "同じ種類で取り出せる");
  ok(g.ScanRouter.takeHandoff("receipt") === null, "一度取り出したら消える");
}
{
  const g = makeSandbox();
  g.ScanRouter.handoff("receipt", frag(["合計 ¥1,280"]));
  ok(g.ScanRouter.takeHandoff("meeting") === null, "違う種類では取り出せない");
}
{
  const g = makeSandbox();
  g.ScanRouter.handoff("receipt", frag(["合計 ¥1,280"]));
  const raw = JSON.parse(g.sessionStorage.getItem("pendingScan"));
  raw.at = Date.now() - 6 * 60 * 1000; // 6分前
  g.sessionStorage.setItem("pendingScan", JSON.stringify(raw));
  ok(g.ScanRouter.takeHandoff("receipt") === null, "古い受け渡しは使わない");
}

console.log("== 振り分け先 ==");
{
  const g = makeSandbox();
  ok(g.ScanRouter.destinationFor("receipt") === "kakeibo/index.html", "レシートは家計簿へ");
  ok(g.ScanRouter.destinationFor("meeting") === "docs-tracker/index.html", "会議の通知は書類トラッカーへ");
  ok(g.ScanRouter.destinationFor("unknown") === null, "unknown には行き先が無い");
}

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
