/*
 * 冷蔵庫の献立提案で使う、在庫の並べ替え・指示文・回答整形のテスト。ブラウザ不要。
 *
 *   node apps/tests/fridgeai.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/fridgeai.js"), "utf8"))(g);
const F = g.FridgeAI;

let failures = 0;
const ok = (condition, label) => {
  console.log((condition ? "  PASS  " : "  FAIL  ") + label);
  if (!condition) failures++;
};

const stock = [
  { name: "架空豆腐", qty: 1, unit: "丁", expiresOn: "2026-10-18", note: "" },
  { name: "架空ねぎ", qty: 2, unit: "本", expiresOn: "", note: "青い部分も使う" },
  { name: "架空きのこ", qty: 1, unit: "袋", expiresOn: "2026-10-16", note: "" }
];

const sorted = F.sortInventory(stock);
ok(sorted.map(item => item.name).join(",") === "架空きのこ,架空豆腐,架空ねぎ", "期限が近い順、期限なしを最後に並べる");
ok(stock[0].name === "架空豆腐", "元の在庫配列を変更しない");

const request = F.buildRequest(stock, "2026-10-16");
ok(request.prompt.indexOf("架空きのこ、1袋、今日まで") < request.prompt.indexOf("架空豆腐、1丁、あと2日"), "指示文でも期限が近い食材を先にする");
ok(request.prompt.includes("架空ねぎ、2本、期限なし、メモ: 青い部分も使う"), "数量・期限・メモを指示文に含める");
ok(request.instructions.includes("在庫だけを主な食材") && request.prompt.includes("異なる献立を3つ"), "在庫を使う3提案だと明示する");

const answer = "説明の前置き\n" + JSON.stringify({ menus: [
  { name: "架空きのこ汁", ingredients: ["架空きのこ", "架空ねぎ"], description: "さっと煮ます。" },
  { name: "架空豆腐焼き", ingredients: ["架空豆腐", "架空ねぎ"], description: "両面を焼きます。" },
  { name: "架空炒め", ingredients: ["架空きのこ", "架空豆腐", "架空豆腐"], description: "一緒に炒めます。" }
] }) + "\n以上です";
const menus = F.parseResponse(answer, stock);
ok(menus && menus.length === 3 && menus[0].name === "架空きのこ汁", "回答文の最初の JSON オブジェクトから3提案を取り出す");
ok(menus[2].ingredients.join(",") === "架空きのこ,架空豆腐", "使用食材を在庫名に限定し、重複を除く");

ok(F.parseResponse('{"menus":[]}', stock) === null, "3提案でない回答を使わない");
ok(F.parseResponse('{"menus":[{"name":"案1","ingredients":["在庫外"],"description":"説明"},{"name":"案2","ingredients":["架空豆腐"],"description":"説明"},{"name":"案3","ingredients":["架空ねぎ"],"description":"説明"}]}', stock) === null, "在庫の食材を使わない提案を使わない");
ok(F.parseResponse("JSONではありません", stock) === null, "JSON でない回答を使わない");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
