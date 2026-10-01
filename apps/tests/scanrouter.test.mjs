/*
 * apps/shared/scanrouter.js（撮った書類をレシート/会議の通知/手帳に振り分ける）のテスト。ブラウザ不要。
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
  ["receipt.js", "meeting.js", "planner.js", "scanrouter.js"].forEach((f) => {
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

console.log("== 手帳 ==");
const TODAY = new Date(2026, 9, 1);
// 2026年10月の月間ページ（日曜始まり）。手書きの予定は架空のもの
function monthGrid(notes) {
  const f = [{ text: "2026年10月", x: 0.35, y: 0.03, width: 0.3, height: 0.05 }];
  "日月火水木金土".split("").forEach((w, c) => f.push({ text: w, x: 0.08 + c * 0.137, y: 0.12, width: 0.02, height: 0.02 }));
  for (let d = 1; d <= 31; d++) {
    const i = d + 3, r = Math.floor(i / 7), c = i % 7;   // 1日は木曜
    f.push({ text: String(d), x: 0.026 + c * 0.137, y: 0.164 + r * 0.135, width: 0.012 * String(d).length, height: 0.018 });
    (notes[d] || []).forEach((t, k) => f.push({ text: t, x: 0.03 + c * 0.137, y: 0.19 + r * 0.135 + k * 0.025, width: 0.12, height: 0.02 }));
  }
  return f;
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(monthGrid({ 3: ["会費 3,000円"], 10: ["18:00 懇親会 5000円"], 21: ["支払 1,280円"] }), { today: TODAY });
  ok(r.type === "planner", "金額が書いてある月間の手帳をレシートと間違えない", r.type);
  ok(r.planner && r.planner.entries.length === 3, "手帳の予定を3件取り出す", r.planner && r.planner.entries);
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(monthGrid({ 15: ["町内会の会議"], 22: ["委員会"] }), { today: TODAY });
  ok(r.type === "planner", "マスに「会議」「委員会」と書いてあっても会議の通知と間違えない", r.type);
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["10/3(土)", "歯医者 2,000円", "10/4(日)", "買い物", "10/6(火)", "打合せ"]), { today: TODAY });
  ok(r.type === "planner", "日付ごとのメモ（3日ぶん）は手帳", r.type);
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["来週の買い物", "米 5kg", "予算 3,000円"]), { today: TODAY });
  ok(r.type === "unknown", "金額らしい数字が1つあるだけではレシートにしない", r.type);
}
{
  const g = makeSandbox();
  const r = g.ScanRouter.classify(frag(["サンプル商店", "2026/09/18", "お茶 ¥150", "パン ¥220", "お預り ¥1,000", "お釣 ¥630"]), { today: TODAY });
  ok(r.type === "receipt", "「合計」が読めなくても、明細とお預り・お釣があればレシート", r.type);
}
{
  const g = makeSandbox();
  ok(g.ScanRouter.destinationFor("planner") === "docs-tracker/index.html", "手帳は書類トラッカーへ（確認してカレンダーに登録）");
  g.ScanRouter.handoff("planner", frag(["10/3(土)"]));
  ok(g.ScanRouter.takeHandoff("meeting") === null, "手帳の受け渡しを会議として取り出さない");
  ok(g.ScanRouter.takeHandoff("planner") !== null, "会議側が先に見ても、手帳宛ての受け渡しは消えずに残る");
}

console.log("== 向きの選択 ==");
{
  // 横倒しの写真を左右2つの向きで読んだ結果。正しい向きの方だけ、日付がマス目に並ぶ
  const g = makeSandbox();
  const right = monthGrid({ 5: ["歯医者"], 20: ["会議"] });
  // 逆さに読んだときは、同じ文字が取れても位置がばらばらで、数字も読み違える
  const wrong = right.map((f, i) => ({ ...f, text: /^\d+$/.test(f.text) ? String((Number(f.text) * 7) % 31 + 1) : f.text, x: (i * 0.37) % 1, y: (i * 0.53) % 1 }));
  ok(g.ScanRouter.pickLines([wrong, right], { today: TODAY }) === right, "意味の通る向き（マス目が取れる方）を選ぶ");
  ok(g.ScanRouter.pickLines([right, wrong], { today: TODAY }) === right, "候補の順番によらない");
  const receipt = frag(["サンプル商店", "2026/09/18", "お茶 ¥150", "合計 ¥150"]);
  const garbled = frag(["051¥ 計合", "茶お", "81/90/6202"]);
  ok(g.ScanRouter.pickLines([garbled, receipt]) === receipt, "レシートなら合計が取れる向きを選ぶ");
  ok(g.ScanRouter.pickLines([receipt]) === receipt, "候補が1つならそのまま");
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
