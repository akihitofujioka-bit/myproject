/*
 * apps/shared/history.js（AI と資料の履歴を端末内に保存する部品）のテスト。
 *
 *   node apps/tests/history.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const g = {};
const historyPath = path.join(ROOT, "apps/shared/history.js");
if (fs.existsSync(historyPath)) {
  new Function("window", fs.readFileSync(historyPath, "utf8"))(g);
}
const H = g.AIHistory;

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
    clear() {
      return request(() => { records.clear(); }, transaction);
    },
    getAll() {
      return request(() => Array.from(records.values(), value => structuredClone(value)));
    },
    createIndex() {}
  });
  const db = {
    objectStoreNames: { contains: name => name === "entries" },
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
        if (name !== "ichishi-history" || version !== 1) throw new Error("データベース設定が違います");
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

if (!H) {
  ok(false, "window.AIHistory が公開されている");
} else {
  ok(H.normalize("ＡＢＣ　カイギ") === H.normalize("abc かいぎ"), "全角・半角、カタカナ・ひらがな、大小をそろえる");
  let unavailable = false;
  try {
    await H.open();
  } catch (error) {
    unavailable = error instanceof Error && error.message === "unavailable";
  }
  ok(unavailable, "IndexedDB が使えない場合は unavailable で失敗する");
  await H.open(fakeIndexedDB());

  const document = await H.add({ kind: "document", title: "架空の通知", body: "第1委員会室で開催" });
  ok(Boolean(document.id && document.createdAt && document.updatedAt), "追加時に ID と日時を補う");

  ok((await H.list({ query: "ダイイチ" })).length === 0, "読みが同じ別の文字には一致しない");
  ok((await H.list({ query: "第１ 委員会" })).length === 1, "複数語がすべて含まれる資料を探す");

  const chat = await H.add({
    kind: "chat",
    title: "架空の相談",
    body: "",
    mode: "sparring",
    messages: [{ role: "user", text: "架空の公園について考えたい", at: "2026-10-13T01:00:00.000Z" }],
    sourceId: ""
  });
  ok((await H.list({ query: "公園" })).length === 1, "会話の本文も検索する");

  const appended = await H.appendMessage(chat.id, { role: "ai", text: "目的を整理しましょう" });
  ok(appended.messages.length === 2 && appended.updatedAt > chat.updatedAt, "会話を追記して更新日時を新しくする");

  const chats = await H.list({ kind: "chat" });
  const all = await H.list({});
  ok(chats.length === 1 && chats[0].kind === "chat", "会話だけに絞る");
  ok(all.length === 2 && all[0].id === chat.id, "更新日時の新しい順に並べる");

  const updated = await H.update(document.id, { title: "架空の開催通知（更新）" });
  ok(updated.title === "架空の開催通知（更新）" && updated.body === document.body, "指定した項目だけを更新する");

  let missingUpdate = false;
  try { await H.update("存在しない架空ID", { title: "更新しない" }); } catch (error) { missingUpdate = error.message === "履歴が見つかりません"; }
  ok(missingUpdate, "存在しない ID の更新は失敗する");
  let missingAppend = false;
  try { await H.appendMessage("存在しない架空ID", { role: "user", text: "追記しない" }); } catch (error) { missingAppend = error.message === "履歴が見つかりません"; }
  ok(missingAppend, "存在しない ID への会話追記は失敗する");

  await H.remove(document.id);
  ok(await H.get(document.id) === null, "1 件を削除する");
  await H.clear();
  ok((await H.list()).length === 0, "すべて削除する");

  let finishWrite;
  await H.open({
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
  const pendingWrite = H.add({ kind: "document", title: "架空の確定待ち", body: "保存中" }).then(() => { writeResolved = true; });
  await Promise.resolve();
  await Promise.resolve();
  ok(!writeResolved && typeof finishWrite === "function", "request の後も transaction 完了までは書き込み成功にしない");
  finishWrite();
  await pendingWrite;
  ok(writeResolved, "transaction 完了で書き込み成功にする");

  let failOldOpen;
  const oldOpen = H.open({
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
  await H.open(fakeIndexedDB());
  failOldOpen();
  await oldFailure;
  const afterOldFailure = await H.add({ kind: "document", title: "架空の新しい接続", body: "接続確認" });
  ok(Boolean(afterOldFailure.id), "古い open の失敗で新しい接続を捨てない");

  const reconnecting = reconnectingIndexedDB();
  await H.open(reconnecting);
  const recovered = await H.add({ kind: "document", title: "架空の再接続", body: "接続確認" });
  ok(Boolean(recovered.id) && reconnecting.openCount === 2, "transaction が InvalidStateError でも1回だけ開き直して追加する");

  const title = H.titleFrom("\n\n架空の議案について説明します。" + "あ".repeat(40));
  ok(title.length === 30 && title.startsWith("架空の議案"), "最初の空でない行を 30 字にする");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
