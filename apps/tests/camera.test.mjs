/*
 * 撮り方の設定（apps/shared/camerapref.js）と、
 * それが撮影の呼び出しに渡ることの確認（apps/shared/receiptscan.js）。
 *
 *   node apps/tests/camera.test.mjs
 *
 * 無音カメラと書類カメラは一長一短のため利用者が選べる。
 * 選んだ内容が実際にネイティブ側へ渡らないと意味がないので、そこを見る。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

function load(win, file) {
  new Function("window", fs.readFileSync(path.join(ROOT, file), "utf8"))(win);
  return win;
}

// 端末に残る設定を模した入れ物
function fakeStorage(initial) {
  const data = Object.assign({}, initial);
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: (k) => { delete data[k]; },
    _data: data
  };
}

/* ---------- 設定の読み書き ---------- */
console.log("== 撮り方の設定 ==");
{
  const win = load({ localStorage: fakeStorage({}) }, "apps/shared/camerapref.js");
  ok(win.CameraPref.get() === "silent", "初期値は無音カメラ（会議中や窓口で使うため）");
  ok(win.CameraPref.set("document") === "document", "書類カメラに切り替えられる");
  ok(win.CameraPref.get() === "document", "切り替えた内容が残る");
  ok(win.CameraPref.set("でたらめ") === "silent", "知らない値が来たら無音カメラに戻す");
  ok(Object.keys(win.CameraPref.modes).join(",") === "silent,document", "選べるのは2種類");
}
{
  // 保存できない環境（プライベートブラウズなど）でも動く
  const win = load({
    localStorage: {
      getItem: () => { throw new Error("使えません"); },
      setItem: () => { throw new Error("使えません"); }
    }
  }, "apps/shared/camerapref.js");
  ok(win.CameraPref.get() === "silent", "設定を読めない環境でも無音カメラで動く");
  ok(win.CameraPref.set("document") === "document", "設定を保存できなくても落ちない");
}

/* ---------- 撮影の呼び出しに渡るか ---------- */
console.log("== 撮影の呼び出しに渡るか ==");
function nativeWindow(mode) {
  const calls = [];
  const win = {
    localStorage: fakeStorage(mode ? { "camera.v1": mode } : {}),
    Capacitor: {
      isNativePlatform: () => true,
      nativePromise: (plugin, method, args) => {
        calls.push({ plugin, method, args });
        return Promise.resolve({ cancelled: false, lines: [], saved: 1 });
      }
    }
  };
  load(win, "apps/shared/camerapref.js");
  load(win, "apps/shared/receiptscan.js");
  win.__calls = calls;
  return win;
}
{
  const win = nativeWindow(null);
  await win.ReceiptScan.scan();
  ok(win.__calls[0].args.camera === "silent", "既定では無音カメラを指定して呼ぶ");
}
{
  const win = nativeWindow("document");
  await win.ReceiptScan.scan();
  await win.ReceiptScan.scanToPhotos();
  ok(win.__calls[0].args.camera === "document", "レシートの撮影に設定が渡る");
  ok(win.__calls[1].args.camera === "document", "書類の撮影にも設定が渡る");
}
{
  const win = nativeWindow("silent");
  await win.ReceiptScan.scan({ camera: "document" });
  ok(win.__calls[0].args.camera === "document", "その場で撮り方を指定すると設定より優先される");
}
{
  // 設定が読み込まれていない画面でも落ちない
  const calls = [];
  const win = {
    Capacitor: {
      isNativePlatform: () => true,
      nativePromise: (plugin, method, args) => { calls.push(args); return Promise.resolve({}); }
    }
  };
  load(win, "apps/shared/receiptscan.js");
  await win.ReceiptScan.scan();
  ok(calls[0].camera === "silent", "設定が読み込まれていなくても無音カメラで呼ぶ");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
