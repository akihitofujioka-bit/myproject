/*
 * apps/shared/meishistore.js（名刺を端末内に保存する部品）のテスト。
 *
 *   node apps/tests/meishistore.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const storePath = path.join(ROOT, "apps/shared/meishistore.js");
if (fs.existsSync(storePath)) {
  new Function("window", fs.readFileSync(storePath, "utf8"))(g);
}
const M = g.MeishiStore;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

function request(run, transaction) {
  const req = {};
  queueMicrotask(() => {
    try {
      req.result = run();
      if (req.onsuccess) req.onsuccess({ target: req });
      if (transaction) queueMicrotask(() => {
        if (transaction.oncomplete) transaction.oncomplete({ target: transaction });
      });
    } catch (error) {
      req.error = error;
      if (req.onerror) req.onerror({ target: req });
      if (transaction) {
        transaction.error = error;
        if (transaction.onerror) transaction.onerror({ target: transaction });
      }
    }
  });
  return req;
}

function fakeIndexedDB() {
  const records = new Map();
  const store = transaction => ({
    put(value) {
      return request(() => {
        const saved = structuredClone(value);
        records.set(saved.id, saved);
        return saved.id;
      }, transaction);
    },
    get(id) {
      return request(() => records.has(id) ? structuredClone(records.get(id)) : undefined);
    },
    delete(id) {
      return request(() => { records.delete(id); }, transaction);
    },
    getAll() {
      return request(() => Array.from(records.values(), value => structuredClone(value)));
    },
    createIndex() {}
  });
  const db = {
    objectStoreNames: { contains: name => name === "cards" },
    createObjectStore() { return store(null); },
    transaction() {
      const transaction = {};
      transaction.objectStore = () => store(transaction);
      return transaction;
    }
  };
  return {
    open(name, version) {
      return request(() => {
        if (name !== "meishi" || version !== 1) throw new Error("データベース設定が違います");
        return db;
      });
    }
  };
}

function reconnectingIndexedDB() {
  const records = new Map();
  let openCount = 0;
  const store = transaction => ({
    put(value) {
      return request(() => {
        const saved = structuredClone(value);
        records.set(saved.id, saved);
        return saved.id;
      }, transaction);
    }
  });
  return {
    get openCount() { return openCount; },
    open() {
      openCount++;
      const firstConnection = openCount === 1;
      return request(() => ({
        objectStoreNames: { contains: () => true },
        transaction() {
          if (firstConnection) {
            const error = new Error("接続が切れました");
            error.name = "InvalidStateError";
            throw error;
          }
          const transaction = {};
          transaction.objectStore = () => store(transaction);
          return transaction;
        }
      }));
    }
  };
}

if (!M) {
  ok(false, "window.MeishiStore が公開されている");
} else {
  let unavailable = false;
  try {
    await M.open();
  } catch (error) {
    unavailable = error instanceof Error && error.message === "unavailable";
  }
  ok(unavailable, "IndexedDB が使えない場合は unavailable で失敗する");
  await M.open(fakeIndexedDB());

  const first = await M.add({
    name: "架空 一郎",
    company: "架空商事",
    department: "総務部",
    title: "架空主任",
    note: "架空展示会で面談",
    phones: ["000-0000-0001"],
    meeting: { scheduleId: "schedule-fiction-1", calEventId: "", title: "架空の交流会" }
  });
  ok(first.id.startsWith("m-") && Boolean(first.createdAt && first.updatedAt), "追加時に m- で始まる ID と日時を補う");

  await new Promise(resolve => setTimeout(resolve, 2));
  const defaults = await M.add({ name: "架空 二郎", company: "空想製作所" });
  ok(Array.isArray(defaults.phones) && defaults.phones.length === 0 && defaults.meeting === null, "電話と会った予定の既定値を補う");
  ok((await M.get(first.id)).company === "架空商事", "追加した名刺を取得する");

  const updated = await M.update(first.id, { title: "架空課長" });
  ok(updated.title === "架空課長" && updated.company === first.company && updated.updatedAt > first.updatedAt, "指定した項目だけを更新して更新日時を進める");

  let missingUpdate = false;
  try {
    await M.update("m-fiction-missing", { title: "更新しない" });
  } catch (error) {
    missingUpdate = error.message === "名刺が見つかりません";
  }
  ok(missingUpdate, "存在しない ID の更新は失敗する");

  await new Promise(resolve => setTimeout(resolve, 2));
  const newest = await M.add({
    name: "架空 三郎",
    company: "架空企画",
    department: "営業部",
    title: "架空担当",
    memo: "空想展示会で新規相談",
    meeting: { scheduleId: "", calEventId: "calendar-fiction-1", title: "架空事業の相談会" }
  });
  const listed = await M.list({});
  ok(listed[0].id === newest.id && listed[listed.length - 1].id === first.id, "作成日時の新しい順に並べる");
  ok((await M.list({ query: "架空商事" })).some(card => card.id === first.id), "会社名で探す");
  ok((await M.list({ query: "ソウム" })).length === 0, "読みが同じ別の文字には一致しない");
  ok((await M.list({ query: "架空　総務" })).length === 1, "複数語がすべて含まれる名刺を探す");
  ok((await M.list({ query: "空想展示会" })).length === 1, "メモでも探す");
  ok((await M.list({ query: "事業 相談会" })).length === 1, "会った予定の名前でも探す");

  const scheduleCards = await M.byMeeting({ scheduleId: "schedule-fiction-1", calEventId: "" });
  const calendarCards = await M.byMeeting({ scheduleId: "", calEventId: "calendar-fiction-1" });
  const emptyCards = await M.byMeeting({ scheduleId: "", calEventId: "" });
  ok(scheduleCards.length === 1 && scheduleCards[0].id === first.id, "scheduleId が一致する名刺を探す");
  ok(calendarCards.length === 1 && calendarCards[0].id === newest.id, "calEventId が一致する名刺を探す");
  ok(emptyCards.length === 0, "空の予定 ID では名刺に一致しない");

  const photo = new Blob(["架空の画像データ"], { type: "image/jpeg" });
  const withPhoto = await M.add({ name: "架空 写真子", company: "架空写真社", photo });
  const loadedPhoto = (await M.get(withPhoto.id)).photo;
  ok(loadedPhoto instanceof Blob && loadedPhoto.type === "image/jpeg" && await loadedPhoto.text() === "架空の画像データ", "写真の Blob を保存して取得する");

  await M.remove(defaults.id);
  ok(await M.get(defaults.id) === null, "1 件を削除する");

  let finishWrite;
  await M.open({
    open() {
      return request(() => ({
        objectStoreNames: { contains: () => true },
        transaction() {
          const transaction = {};
          transaction.objectStore = () => ({
            put() {
              finishWrite = () => transaction.oncomplete();
              return {};
            }
          });
          return transaction;
        }
      }));
    }
  });
  let writeResolved = false;
  const pendingWrite = M.add({ name: "架空 確定待子", company: "架空保存社" }).then(() => { writeResolved = true; });
  await Promise.resolve();
  await Promise.resolve();
  ok(!writeResolved && typeof finishWrite === "function", "request の後も transaction 完了までは書き込み成功にしない");
  finishWrite();
  await pendingWrite;
  ok(writeResolved, "transaction 完了で書き込み成功にする");

  let failOldOpen;
  const oldOpen = M.open({
    open() {
      const pending = {};
      failOldOpen = () => {
        pending.error = new Error("古い接続だけ失敗");
        if (pending.onerror) pending.onerror();
      };
      return pending;
    }
  });
  const oldFailure = oldOpen.catch(() => true);
  await M.open(fakeIndexedDB());
  failOldOpen();
  await oldFailure;
  const afterOldFailure = await M.add({ name: "架空 接続子", company: "架空接続社" });
  ok(Boolean(afterOldFailure.id), "古い open の失敗で新しい接続を捨てない");

  const reconnecting = reconnectingIndexedDB();
  await M.open(reconnecting);
  const recovered = await M.add({ name: "架空 再接続子", company: "架空再接続社" });
  ok(Boolean(recovered.id) && reconnecting.openCount === 2, "transaction が InvalidStateError でも1回だけ開き直して追加する");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
