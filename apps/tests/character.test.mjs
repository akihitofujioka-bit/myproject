/*
 * apps/shared/character.js（キャラクター写真の共通部品）のテスト。ブラウザ不要。
 *
 *   node apps/tests/character.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = { Blob, atob };
new Function("window", fs.readFileSync(path.join(ROOT, "apps/shared/character.js"), "utf8"))(g);

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

const C = g.Character;
const d = (s) => new Date(s + "T09:00:00");
// 数え始めの日は 0 番
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-08")) === 0, "day: 当日は 0");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-09")) === 1, "day: 翌日は 1");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-11")) === 0, "day: 3 日後は一周して 0");
// 2026-10-08 は木曜日。同じ週の日曜日までは 0、月曜日に 1
ok(C.pickIndex(3, "week", "2026-10-08", d("2026-10-11")) === 0, "week: 日曜日までは 0");
ok(C.pickIndex(3, "week", "2026-10-08", d("2026-10-12")) === 1, "week: 月曜日に 1");
ok(C.pickIndex(3, "month", "2026-10-08", d("2026-10-31")) === 0, "month: 月末までは 0");
ok(C.pickIndex(3, "month", "2026-10-08", d("2026-11-01")) === 1, "month: 1 日に 1");
ok(C.pickIndex(3, "month", "2026-10-08", d("2027-01-01")) === 0, "month: 年またぎ（3 か月後）");
ok(C.pickIndex(1, "day", "2026-10-08", d("2026-12-25")) === 0, "1 枚ならいつも 0");
ok(C.pickIndex(0, "day", "2026-10-08", d("2026-10-08")) === -1, "0 枚なら -1");
ok(C.pickIndex(3, "day", "2026-10-08", d("2026-10-01")) === 0, "時計を戻したら 0");
ok(C.veilAlpha("light") === 0.55 && C.veilAlpha("normal") === 0.7 && C.veilAlpha("strong") === 0.85, "膜の 3 段階");
ok(C.veilAlpha("xxx") === 0.7, "知らない値は normal");
const n = C.normalize({ photos: "壊れた値" }, "fridge");
ok(n.slot === "fridge" && n.interval === "day" && n.veil === "normal" && Array.isArray(n.photos) && n.photos.length === 0, "壊れた記録を最初の値で埋める");
ok(/^\d{4}-\d{2}-\d{2}$/.test(n.startDate), "startDate が無ければ今日");
ok(C.todayString(new Date(2026, 0, 5)) === "2026-01-05", "地域の日付で YYYY-MM-DD");
ok(C.SLOTS.join(",") === "top,fridge,docs-tracker,stock,kakeibo,cards", "6 つの枠");

const D = C.albumDiff(["a", "b", "c"], ["b", "c", "d"]);
ok(D.keep.join() === "b,c" && D.add.join() === "d" && D.order.join() === "b,c,d", "albumDiff: 増えた d だけ add、消えた a は除く");
ok(C.albumDiff(["a", "b"], ["b", "a"]).add.length === 0, "albumDiff: 並び替えだけなら add は空");
ok(C.albumDiff([], []).order.length === 0, "albumDiff: 空どうし");
const m = C.normalize({ album: "壊れた値", albumIds: 1, manualPhotos: null }, "top");
ok(m.album === null && Array.isArray(m.albumIds) && Array.isArray(m.manualPhotos), "normalize: アルバムの項目を埋める");
ok(C.albumNotice("ok", "キャラ") === "", "albumNotice: ok は空");
ok(/すべての写真/.test(C.albumNotice("limited", "キャラ")) && /すべての写真/.test(C.albumNotice("denied", "キャラ")), "albumNotice: 許可の案内");
ok(/キャラ.*見つかりません/.test(C.albumNotice("not-found", "キャラ")), "albumNotice: アルバムが無い");

let saved;
const originalStore = C._store;
C._store = {
  load: async () => C.normalize({
    slot: "top",
    startDate: "2026-09-01",
    photos: [new Blob(["old"], { type: "image/jpeg" })],
    album: { id: "album-1", title: "架空アルバム" },
    albumIds: ["old"],
    manualPhotos: []
  }, "top"),
  save: async (record) => { saved = record; }
};
const fakePlugin = {
  assetIds: async () => ({ status: "ok", ids: ["x", "y"] }),
  loadPhoto: async ({ id }) => {
    if (id === "y") throw new Error("架空の取得失敗");
    return { data: "eA==" };
  }
};
const synced = await C.syncAlbum("top", fakePlugin);
ok(synced.added === 1 && synced.failed === 1, "syncAlbum: 取得できない写真だけを飛ばす");
ok(saved.albumIds.join() === "x" && saved.photos.length === 1, "syncAlbum: 取得できた写真だけを保存する");
ok(saved.startDate === "2026-09-01", "syncAlbum: startDate を変えない");
C._store = originalStore;

ok(C.watchMark({ photos: [] }, d("2026-10-08")) === "clear", "watchMark: 写真 0 枚は clear");
const watchRecord = { photos: [{}, {}], interval: "day", startDate: "2026-10-08" };
ok(C.watchMark(watchRecord, d("2026-10-08")) === C.watchMark(watchRecord, d("2026-10-08")), "watchMark: 同じ日は同じ印");

// 写真は ArrayBuffer の形で保存し、読み出すと元の Blob に戻る（WebKit 対策）
{
  const src = new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" });
  const stored = await C.toStored(src);
  ok(stored.data instanceof ArrayBuffer && stored.type === "image/jpeg", "toStored: ArrayBuffer にする");
  const back = C.fromStored(stored);
  ok(back instanceof Blob && back.size === 3 && back.type === "image/jpeg", "fromStored: Blob に戻る");
  ok(C.fromStored(src) === src, "fromStored: 以前の Blob はそのまま");
  const broken = { type: "image/jpeg", arrayBuffer: () => Promise.reject(new Error("読めない")) };
  const rec = await C.toStoredRecord(C.normalize({ photos: [src, broken], albumIds: ["a", "b"], manualPhotos: [broken] }, "top"));
  ok(rec.photos.length === 1 && rec.albumIds.join() === "a" && rec.manualPhotos.length === 0, "toStoredRecord: 読めない写真と番号は捨てる");
}

// ランダム（シャッフル方式）: 1 周のうちに全部の写真が 1 回ずつ出て、境目でも同じ写真が続かない
{
  const days = (n) => { const x = new Date(2026, 9, 9); x.setDate(x.getDate() + n); return x; };
  const seq = []; for (let i = 0; i < 40; i++) seq.push(C.pickIndex(5, "day", "2026-10-09", days(i), "random"));
  let fair = true; for (let c = 0; c < 8; c++) { const s = seq.slice(c * 5, c * 5 + 5).sort().join(); if (s !== "0,1,2,3,4") fair = false; }
  ok(fair, "random: 1 周 5 日で 5 枚が 1 回ずつ出る");
  ok(seq.every((v, i) => i === 0 || v !== seq[i - 1]), "random: 同じ写真が 2 回続かない");
  ok(seq.join() !== "0,1,2,3,4,0,1,2,3,4,0,1,2,3,4,0,1,2,3,4,0,1,2,3,4,0,1,2,3,4,0,1,2,3,4,0,1,2,3,4", "random: 順番どおりではない");
  ok(C.pickIndex(5, "day", "2026-10-09", days(3), "random") === seq[3], "random: 同じ日は何度選んでも同じ写真");
  ok(C.pickIndex(1, "day", "2026-10-09", days(3), "random") === 0 && C.pickIndex(0, "day", "2026-10-09", days(3), "random") === -1, "random: 1 枚は 0、0 枚は -1");
  const two = []; for (let i = 0; i < 10; i++) two.push(C.pickIndex(2, "week", "2026-10-09", days(i * 7), "random"));
  ok(two.every((v, i) => i === 0 || v !== two[i - 1]), "random: 2 枚なら毎週交互");
  // 項目（スロット）が違えば、同じ設定でもランダムの並びは別になる（全項目ランダムで同じ写真になる不具合の再発防止）
  const bySlot = (slot) => { const r = []; for (let i = 0; i < 20; i++) r.push(C.pickIndex(10, "day", "2026-10-09", days(i), "random", slot)); return r.join(); };
  ok(bySlot("top") !== bySlot("docs") && bySlot("docs") !== bySlot("fridge") && bySlot("top") !== bySlot("fridge"), "random: 項目ごとに並びが違う");
  ok(bySlot("top") === bySlot("top"), "random: 同じ項目なら、いつ選んでも同じ並び");
  ok(C.pickIndex(5, "day", "2026-10-09", days(3), "random") === C.pickIndex(5, "day", "2026-10-09", days(3), "random", undefined), "random: スロット省略でも動く");
  ok(C.normalize({ order: "xxx" }, "top").order === "sequential" && C.normalize({ order: "random" }, "top").order === "random", "normalize: order を埋める");
}

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
