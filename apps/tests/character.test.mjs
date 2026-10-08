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

console.log(failures ? `\n${failures} 件失敗` : "\nすべて成功");
process.exit(failures ? 1 : 0);
