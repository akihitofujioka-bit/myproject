/*
 * Apple Watch で使うための部品の確認。
 *
 *   node apps/tests/watch.test.mjs
 *
 * 見ているのは次の2つ。どちらもブラウザを使わず Node だけで動く。
 *  - 通知の文面（native.js）… 手首で1行目と2行目だけ見て判断できるか
 *  - 買い物リストの送り先（reminders.js）… ショートカットへ渡す URL と、
 *    ショートカットが無い環境でコピーに切り替わるか
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

/* ---------- 通知の文面 ---------- */
console.log("== 通知の文面（Apple Watch の1行目・2行目）==");
{
  const win = load({}, "apps/shared/native.js");
  const N = win.Native;

  ok(N.whenLabel(0) === "本日", "0分前 → 本日");
  ok(N.whenLabel(30) === "30分後", "30分前 → 30分後（会議の直前通知）");
  ok(N.whenLabel(180) === "3時間後", "180分前 → 3時間後");
  ok(N.whenLabel(1440) === "明日", "1440分前 → 明日");
  ok(N.whenLabel(4320) === "3日後", "4320分前 → 3日後");
  ok(N.whenLabel(43200) === "1か月後", "43200分前 → 1か月後（備蓄の早出し通知）");

  const doc = {
    title: "【回覧】○○協議会の回答",
    location: "総務課",
    summaryLine: "提出先：総務課 ／ 状態：未着手",
    description: "状態：未着手\n（書類・回覧の期限トラッカーから登録）"
  };
  const t1 = N.notice(doc, 1440);
  ok(t1.title === "明日：【回覧】○○協議会の回答", "書類：1行目に期限と件名（" + t1.title + "）");
  ok(t1.body === "提出先：総務課 ／ 状態：未着手", "書類：2行目に提出先と状態（" + t1.body + "）");
  ok(N.notice(doc, 0).title === "本日：【回覧】○○協議会の回答", "書類：当日は「本日」になる");

  // summaryLine が無い古い呼び出しでも、場所と説明から組み立てられる
  const old = {
    title: "牛乳 の期限（1本）",
    location: "冷蔵",
    description: "開封済み\n（冷蔵庫の在庫管理から登録）"
  };
  const t2 = N.notice(old, 0);
  ok(t2.body === "冷蔵 ／ 開封済み", "summaryLine が無くても場所と補足が出る（" + t2.body + "）");
  ok(N.notice({ title: "x", description: "（冷蔵庫の在庫管理から登録）" }, 0).body === "",
    "「（○○から登録）」だけの説明は2行目に出さない");

  const long = N.notice({ title: "あ".repeat(80), summaryLine: "い".repeat(80) }, 0);
  ok(long.title.length === 60 && long.title.endsWith("…"), "長すぎる1行目は60文字で切る");
  ok(long.body.length === 60 && long.body.endsWith("…"), "長すぎる2行目は60文字で切る");
}

/* ---------- 買い物リスト ---------- */
console.log("== 買い物リスト（リマインダーへ送る）==");
{
  const win = load({ navigator: { userAgent: "Mozilla/5.0 (Macintosh)" } }, "apps/shared/reminders.js");
  const R = win.Reminders;

  ok(R.clean([" 牛乳 ", "牛乳", "", null, "卵"]).join(",") === "牛乳,卵",
    "空欄と重複を取り除く");

  const u = R.url("牛乳\n卵", "買い物リストに追加");
  ok(u.startsWith("shortcuts://run-shortcut?name="), "ショートカットを呼ぶ URL になる");
  ok(u.includes("&input=text&text="), "文字を渡す形になっている");
  ok(decodeURIComponent(u.split("&text=")[1]) === "牛乳\n卵", "品名は1行に1つ渡す");
  ok(u.includes(encodeURIComponent("買い物リストに追加")), "ショートカット名が入る");

  ok(R.onIOS() === false, "パソコンのブラウザでは iPhone と判定しない");
}
{
  const win = load({ navigator: { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)" } },
    "apps/shared/reminders.js");
  ok(win.Reminders.onIOS() === true, "iPhone では iPhone と判定する");
}
{
  const win = load({ navigator: { userAgent: "Mozilla/5.0 (Macintosh)", maxTouchPoints: 5 } },
    "apps/shared/reminders.js");
  ok(win.Reminders.onIOS() === true, "iPad（パソコン版 Safari を名乗る）も iPhone 側と判定する");
}

/* 送り先の切り替え */
console.log("== 送り先の切り替え ==");
{
  // iPhone：ショートカットへ渡す
  const win = { navigator: { userAgent: "Mozilla/5.0 (iPhone)" }, location: { href: "" } };
  load(win, "apps/shared/reminders.js");
  const res = await win.Reminders.send(["牛乳", "卵", "牛乳"]);
  ok(res.ok && res.how === "shortcut" && res.count === 2, "iPhone ではショートカットへ渡す（重複は1つに）");
  ok(win.location.href.startsWith("shortcuts://"), "ショートカットの URL へ移動する");
}
{
  // パソコン：コピーに切り替える
  let copied = null;
  const win = {
    navigator: {
      userAgent: "Mozilla/5.0 (Macintosh)",
      clipboard: { writeText: (t) => { copied = t; return Promise.resolve(); } }
    },
    location: { href: "" }
  };
  load(win, "apps/shared/reminders.js");
  const res = await win.Reminders.send(["コピー用紙 あと2箱"]);
  ok(res.ok && res.how === "copied", "パソコンではコピーに切り替える");
  ok(copied === "コピー用紙 あと2箱", "コピーした中身が正しい");
  ok(win.location.href === "", "パソコンではショートカットの URL へ移動しない");
}
{
  // 送るものが無いとき
  const win = { navigator: { userAgent: "Mozilla/5.0 (iPhone)" }, location: { href: "" } };
  load(win, "apps/shared/reminders.js");
  const res = await win.Reminders.send([]);
  ok(res.how === "empty" && res.ok === false, "送るものが無ければ何もしない");
  ok(win.location.href === "", "送るものが無ければ画面も動かさない");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
