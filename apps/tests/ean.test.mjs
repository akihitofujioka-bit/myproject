/*
 * apps/fridge/ean.js（自前のバーコード読み取り）の単体テスト。ブラウザ不要。
 *
 *   node apps/tests/ean.test.mjs
 *
 * テスト用にバーコードを「作る側」（エンコーダ）をこのファイル内に持ち、
 * 作った縞模様を読み取れるかを確認する。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = fs.readFileSync(path.join(ROOT, "apps/fridge/ean.js"), "utf8");
const fakeWindow = {};
new Function("window", src)(fakeWindow);
const EAN = fakeWindow.EAN;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

/* ---------- テスト用エンコーダ ---------- */
const L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
const R = L.map((s) => s.split("").map((c) => (c === "0" ? "1" : "0")).join(""));
const G = R.map((s) => s.split("").reverse().join(""));
const PARITY = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];

const checkDigit = (digits) => {
  let sum = 0;
  for (let i = 0; i < digits.length; i++) {
    const fromRight = digits.length - i;
    sum += Number(digits[i]) * (fromRight % 2 === 0 ? 1 : 3);
  }
  return String((10 - (sum % 10)) % 10);
};

const ean13 = (first12) => first12 + checkDigit(first12);
const ean8 = (first7) => first7 + checkDigit(first7);

// バーコードの白黒パターン（"1"=黒）を作る
const encode13 = (code) => {
  const parity = PARITY[Number(code[0])];
  let s = "101";
  for (let i = 1; i <= 6; i++) s += (parity[i - 1] === "L" ? L : G)[Number(code[i])];
  s += "01010";
  for (let i = 7; i <= 12; i++) s += R[Number(code[i])];
  return s + "101";
};
const encode8 = (code) => {
  let s = "101";
  for (let i = 0; i < 4; i++) s += L[Number(code[i])];
  s += "01010";
  for (let i = 4; i < 8; i++) s += R[Number(code[i])];
  return s + "101";
};

// モジュール列を、1モジュール scale 画素・前後に静穏帯つきの配列にする
const toBits = (modules, scale = 3, quiet = 20) => {
  const out = [];
  for (let i = 0; i < quiet; i++) out.push(0);
  for (const ch of modules) for (let i = 0; i < scale; i++) out.push(ch === "1" ? 1 : 0);
  for (let i = 0; i < quiet; i++) out.push(0);
  return Uint8Array.from(out);
};

/* ---------- テスト ---------- */
console.log("== チェックディジット ==");
ok(EAN.checksumOk("4901777018888") === EAN.checksumOk("4901777018888"), "同じ入力で同じ結果");
ok(EAN.checksumOk(ean13("490177701888")), "正しいチェックディジットを受け付ける");
ok(!EAN.checksumOk("4901777018881"), "誤ったチェックディジットを弾く");
ok(!EAN.checksumOk("49017770188"), "桁数が違うものを弾く");
ok(!EAN.checksumOk("49017a7018888"), "数字以外を弾く");

console.log("== EAN-13（JAN-13）の読み取り ==");
const samples13 = [
  ean13("490177701888"), // 日本の事業者コード
  ean13("456995100000"),
  ean13("400638133393"),
  ean13("012345678905").slice(0, 12) + checkDigit("012345678905".slice(0, 12)), // 先頭0（UPC-A相当）
  ean13("999999999999"),
  ean13("000000000000")
];
for (const code of samples13) {
  ok(EAN.decodeRow(toBits(encode13(code))) === code, "読み取り " + code);
}

console.log("== 拡大・縮小と位置ずれ ==");
const code = ean13("490177701888");
for (const scale of [1, 2, 3, 5, 9]) {
  ok(EAN.decodeRow(toBits(encode13(code), scale)) === code, "1モジュール " + scale + "画素");
}
ok(EAN.decodeRow(toBits(encode13(code), 3, 2)) === code, "静穏帯が狭くても読める");

console.log("== 上下逆さま（左右反転）==");
const flipped = Uint8Array.from(Array.from(toBits(encode13(code))).reverse());
ok(EAN.decodeRow(flipped) === null, "反転したままでは読めない（想定どおり）");
ok(EAN.decodeRow(Uint8Array.from(Array.from(flipped).reverse())) === code, "戻せば読める");

console.log("== EAN-8（JAN-8）==");
const code8 = ean8("4912345");
ok(EAN.decodeRow(toBits(encode8(code8))) === code8, "読み取り " + code8);

console.log("== 誤検出しないこと ==");
ok(EAN.decodeRow(Uint8Array.from(Array(400).fill(0))) === null, "真っ白は読めない");
ok(EAN.decodeRow(Uint8Array.from(Array(400).fill(1))) === null, "真っ黒は読めない");
let rng = 12345;
const noise = Uint8Array.from(Array(600), () => {
  rng = (rng * 1103515245 + 12345) & 0x7fffffff;
  return (rng >> 16) & 1;
});
ok(EAN.decodeRow(noise) === null, "ランダムな縞は読めない");
// 1桁だけ壊した縞模様は、チェックディジットで弾かれる
const broken = encode13(code).split("");
broken.splice(20, 7, ...L[(Number(code[3]) + 1) % 10].split(""));
ok(EAN.decodeRow(toBits(broken.join(""))) !== code, "1桁壊れたものを正解として返さない");

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
