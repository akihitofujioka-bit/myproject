/*
 * apps/ の中身を mobile/www/ に写す。
 * アプリ本体は apps/ 側だけを直せばよく、こちらは組み立て直すだけにする。
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const WWW = path.resolve(HERE, "..", "www");

fs.rmSync(WWW, { recursive: true, force: true });
fs.mkdirSync(WWW, { recursive: true });

for (const dir of ["fridge", "docs-tracker", "stock", "kakeibo", "cards", "shared"]) {
  fs.cpSync(path.join(ROOT, "apps", dir), path.join(WWW, dir), { recursive: true });
}
fs.copyFileSync(path.join(ROOT, "apps/index.html"), path.join(WWW, "index.html"));

// アプリの中では Service Worker は不要（ファイルは端末内にあるため）。
// 登録処理は残っていても失敗するだけだが、混乱を避けるため取り除く。
for (const file of ["fridge/sw.js", "docs-tracker/sw.js", "stock/sw.js", "kakeibo/sw.js", "cards/sw.js"]) {
  fs.rmSync(path.join(WWW, file), { force: true });
}

// アプリの中では「ホーム画面に追加する」案内は意味を持たない（既にアイコンから起動しているため）。
// ブラウザ版には必要なので apps/ 側には残し、ここで取り除く。
{
  const indexPath = path.join(WWW, "index.html");
  const before = fs.readFileSync(indexPath, "utf8");
  // コメントの中身は「-->」を含まない範囲に限る。そうしないと、手前にある別のコメントから
  // 取り除き始め、間にある節（キャラクター写真の設定など）まで消してしまう
  const after = before.replace(/\n*[ \t]*<!--(?:(?!-->)[^])*?data-web-only(?:(?!-->)[^])*-->\n*[ \t]*<section data-web-only>[^]*?<\/section>/g, "");
  if (after === before) throw new Error("data-web-only の節が見つかりませんでした");
  fs.writeFileSync(indexPath, after);
  console.log("アプリでは不要な案内（data-web-only）を取り除きました");
}

// 版表記。「いま入っているアプリがどの版か」を画面で確かめられるよう、
// 組み立てた日時と git のコミット番号をトップページに埋め込む。
// 未コミットの変更を含むときは番号の後ろに + を付ける。
{
  const git = (...args) => {
    try { return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim(); }
    catch { return ""; }
  };
  const hash = git("rev-parse", "--short", "HEAD") || "不明";
  const dirty = git("status", "--porcelain", "--", "apps", "mobile/scripts") !== "";
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
  const version = `${stamp}（${hash}${dirty ? "+" : ""}）`;

  const indexPath = path.join(WWW, "index.html");
  const before = fs.readFileSync(indexPath, "utf8");
  const after = before.replace(/(<span id="version">)[^<]*(<\/span>)/, `$1${version}$2`);
  if (after === before) throw new Error('版表記の欄（<span id="version">）が見つかりませんでした');
  fs.writeFileSync(indexPath, after);
  fs.writeFileSync(path.join(WWW, "version.txt"), version + "\n");
  console.log(`版: ${version}`);
}

const count = fs.readdirSync(WWW, { recursive: true }).length;
console.log(`www を作りました（${count} 項目）: ${WWW}`);
