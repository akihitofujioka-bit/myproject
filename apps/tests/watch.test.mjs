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

/* ---------- Apple Watch に送る一覧 ---------- */
console.log("== Apple Watch に送る一覧（watch.js）==");
{
  const TODAY = "2026-09-19";
  const NOW = Date.parse(TODAY + "T09:00:00+09:00");
  // 時差でずれないよう、日付だけを足し引きする
  const day = (n) => new Date(Date.parse(TODAY + "T00:00:00Z") + n * 86400000).toISOString().slice(0, 10);

  const store = {
    "docs-tracker.v1": {
      items: [
        { id: "1", title: "定例会", kind: "会議", dest: "村民会館 2階", dueOn: day(1),
          status: "未着手", note: "13:30〜15:00 開始\n懇親会あり（会費 5,000円）\n（会議の通知から登録）" },
        { id: "2", title: "遠い会議", kind: "会議", dest: "県庁", dueOn: day(30), status: "未着手", note: "" },
        { id: "3", title: "○○協議会の回答", kind: "回覧", dest: "総務課", dueOn: day(3), status: "対応中" },
        { id: "4", title: "期限切れの届出", kind: "提出", dest: "県", dueOn: day(-2), status: "未着手" },
        { id: "5", title: "終わった書類", kind: "提出", dest: "県", dueOn: day(1), status: "完了" },
        { id: "6", title: "ずっと先の提出", kind: "提出", dest: "県", dueOn: day(40), status: "未着手" }
      ]
    },
    "fridge.v1": {
      items: [{ id: "a", name: "たまご" }],
      log: [
        { name: "牛乳", action: "consume", at: new Date(NOW - 2 * 86400000).toISOString() },
        { name: "食パン", action: "discard", at: new Date(NOW - 1 * 86400000).toISOString() },
        { name: "たまご", action: "consume", at: new Date(NOW - 1 * 86400000).toISOString() },
        { name: "味噌", action: "consume", at: new Date(NOW - 40 * 86400000).toISOString() }
      ]
    },
    "stock.v1": {
      items: [
        { id: "s1", name: "コピー用紙", qty: 1, unit: "箱", minQty: 5 },
        { id: "s2", name: "保存水", qty: 24, unit: "本", minQty: 12 },
        { id: "s3", name: "乾電池", qty: 0, unit: "本", minQty: null }
      ]
    }
  };
  const win = {
    localStorage: { getItem: (k) => (store[k] ? JSON.stringify(store[k]) : null) },
    addEventListener: () => {}
  };
  load(win, "apps/shared/watch.js");
  const snap = win.Watch.snapshot({ today: TODAY, now: NOW });

  ok(snap.version === 1 && snap.today === TODAY, "一覧の形（version と今日の日付）");
  ok(snap.meetings.length === 1 && snap.meetings[0].title === "定例会", "会議：1週間先までを送る");
  ok(snap.meetings[0].time === "13:30〜15:00", "会議：開始時刻を取り出す");
  ok(snap.meetings[0].place === "村民会館 2階", "会議：場所を取り出す");
  ok(snap.meetings[0].social === "懇親会あり（会費 5,000円）", "会議：懇親会の有無を取り出す");
  ok(snap.meetings[0].days === 1, "会議：あと何日かを添える");

  const titles = snap.deadlines.map((d) => d.title);
  ok(titles.includes("○○協議会の回答"), "期限：2週間以内の書類を送る");
  ok(titles.includes("期限切れの届出"), "期限：過ぎたものも送る（まだ終わっていないため）");
  ok(!titles.includes("終わった書類"), "期限：完了したものは送らない");
  ok(!titles.includes("ずっと先の提出"), "期限：2週間より先は送らない");
  ok(!titles.includes("定例会"), "期限：会議は期限の欄に重ねない");
  ok(snap.deadlines[0].title === "期限切れの届出", "期限：差し迫った順に並ぶ");

  const shopping = snap.shopping.map((s) => s.name);
  ok(shopping.includes("牛乳"), "買い物：使い切って在庫に無いものを送る");
  ok(!shopping.includes("食パン"), "買い物：廃棄したものは送らない");
  ok(!shopping.includes("たまご"), "買い物：在庫があるものは送らない");
  ok(!shopping.includes("味噌"), "買い物：2週間より前に使い切ったものは送らない");
  ok(shopping.includes("コピー用紙 あと4箱"), "買い物：備蓄の不足分を添える");
  ok(shopping.includes("乾電池"), "買い物：最低在庫数が未設定でも、残り0なら送る");
  ok(!shopping.some((n) => n.indexOf("保存水") === 0), "買い物：足りている備蓄は送らない");

  ok(win.Watch.available() === false, "ブラウザでは送信しない判定になる");
}
{
  // 壊れたデータがあっても、送信自体は止めない
  const win = {
    localStorage: { getItem: (k) => (k === "fridge.v1" ? "こわれたデータ" : null) },
    addEventListener: () => {}
  };
  load(win, "apps/shared/watch.js");
  const snap = win.Watch.snapshot({ today: "2026-09-19", now: Date.now() });
  ok(snap.shopping.length === 0 && snap.meetings.length === 0, "壊れたデータは空として扱う");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
