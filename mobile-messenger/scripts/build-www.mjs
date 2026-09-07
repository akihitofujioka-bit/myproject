/*
 * 「ふたりのメッセージ」だけを www/ に組み立てる。
 *
 * mobile/ 側（日常アプリ3つをまとめたもの）とは別に用意している。
 * 知り合いに配るアプリに、業務書類を扱う「書類・回覧の期限トラッカー」を
 * 同梱しないためで、これは意図的な分離である。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const WWW = path.resolve(HERE, "..", "www");

fs.rmSync(WWW, { recursive: true, force: true });
fs.mkdirSync(WWW, { recursive: true });

// アプリを www の直下に置く。起動してすぐメッセージ画面が出るようにするため
fs.cpSync(path.join(ROOT, "apps/messenger"), WWW, { recursive: true });

// 共有部品は1つだけ使う（このアプリが使わない ics.js は入れない）
fs.mkdirSync(path.join(WWW, "shared"), { recursive: true });
fs.copyFileSync(path.join(ROOT, "apps/shared/native.js"), path.join(WWW, "shared/native.js"));

// アプリの中では Service Worker は不要（ファイルは端末内にあるため）
fs.rmSync(path.join(WWW, "sw.js"), { force: true });

// 階層が1つ上がるので、共有部品への参照だけ書き換える。
// 見落とすと画面が出なくなるため、置き換えられなければここで止める。
const indexFile = path.join(WWW, "index.html");
const before = fs.readFileSync(indexFile, "utf8");
const after = before.replace('src="../shared/native.js"', 'src="shared/native.js"');
if (after === before) {
  throw new Error("apps/messenger/index.html の shared/native.js の読み込み方が変わっています。このスクリプトを直してください。");
}
fs.writeFileSync(indexFile, after);

const count = fs.readdirSync(WWW, { recursive: true }).length;
console.log(`www を作りました（${count} 項目）: ${WWW}`);
