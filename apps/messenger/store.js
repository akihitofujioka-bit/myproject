/*
 * 端末の中への保存。ブラウザの IndexedDB を使う。
 *
 * 保存するもの
 *   kv        自分の身元（秘密鍵を含む）、設定、作りかけの招待
 *   sessions  相手ごとの会話状態（鍵の現在地）。1通ごとに更新する
 *   messages  やりとりの履歴（復号したあとの本文と写真）
 *   outbox    送信できなかった暗号文。回線が戻ったら送り直す
 *
 * ここに入るものはすべて端末の中だけにあり、中継サーバーには送られない。
 * 写真を扱うため localStorage（約5MB）ではなく IndexedDB を使っている。
 */
(function (global) {
  "use strict";

  var DB_NAME = "myproject-messenger";
  var DB_VERSION = 1;
  var STORES = ["kv", "sessions", "messages", "outbox"];
  var dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      var req = global.indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv", { keyPath: "k" });
        if (!db.objectStoreNames.contains("sessions")) db.createObjectStore("sessions", { keyPath: "peerId" });
        if (!db.objectStoreNames.contains("messages")) {
          var messages = db.createObjectStore("messages", { keyPath: "id" });
          messages.createIndex("byPeer", ["peerId", "at"]);
        }
        if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "id" });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
    return dbPromise;
  }

  function run(storeName, mode, work) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(storeName, mode);
        var result;
        var request = work(tx.objectStore(storeName));
        if (request) request.onsuccess = function () { result = request.result; };
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = function () { reject(tx.error); };
        tx.onabort = function () { reject(tx.error); };
      });
    });
  }

  var get = function (store, key) { return run(store, "readonly", function (s) { return s.get(key); }); };
  var put = function (store, value) { return run(store, "readwrite", function (s) { return s.put(value); }); };
  var del = function (store, key) { return run(store, "readwrite", function (s) { return s.delete(key); }); };
  var all = function (store) { return run(store, "readonly", function (s) { return s.getAll(); }); };

  /* ---------------- 設定・身元 ---------------- */

  function getValue(key) {
    return get("kv", key).then(function (row) { return row ? row.v : null; });
  }
  function setValue(key, value) {
    return put("kv", { k: key, v: value });
  }

  /* ---------------- 会話（相手ごと） ---------------- */

  function listSessions() {
    return all("sessions").then(function (rows) {
      return rows.sort(function (a, b) { return (b.lastAt || 0) - (a.lastAt || 0); });
    });
  }

  function getSession(peerId) { return get("sessions", peerId); }

  function putSession(session) {
    var row = JSON.parse(JSON.stringify(session));
    row.peerId = session.peer.id;
    return put("sessions", row);
  }

  // 相手ごと：会話状態・履歴・送信待ちをまとめて消す
  function removePeer(peerId) {
    return listMessages(peerId).then(function (messages) {
      return Promise.all(messages.map(function (m) { return del("messages", m.id); }));
    }).then(function () {
      return all("outbox");
    }).then(function (rows) {
      return Promise.all(rows.filter(function (r) { return r.peerId === peerId; })
        .map(function (r) { return del("outbox", r.id); }));
    }).then(function () {
      return del("sessions", peerId);
    });
  }

  /* ---------------- 履歴 ---------------- */

  function newId() {
    var bytes = global.crypto.getRandomValues(new Uint8Array(12));
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += bytes[i].toString(16).padStart(2, "0");
    return s;
  }

  function listMessages(peerId) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction("messages", "readonly");
        var range = global.IDBKeyRange.bound([peerId, 0], [peerId, Infinity]);
        var req = tx.objectStore("messages").index("byPeer").getAll(range);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function addMessage(message) {
    var row = Object.assign({ id: newId(), at: Date.now() }, message);
    return put("messages", row).then(function () { return row; });
  }

  function removeMessage(id) { return del("messages", id); }

  function patchMessage(id, patch) {
    return get("messages", id).then(function (row) {
      if (!row) return null;
      Object.assign(row, patch);
      return put("messages", row).then(function () { return row; });
    });
  }

  /* ---------------- 送信できなかったぶん ---------------- */

  function addOutbox(item) { return put("outbox", item); }
  function listOutbox() { return all("outbox"); }
  function removeOutbox(id) { return del("outbox", id); }

  /* ---------------- 全消去 ---------------- */

  function clearAll() {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORES, "readwrite");
        STORES.forEach(function (name) { tx.objectStore(name).clear(); });
        tx.oncomplete = resolve;
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  global.MsgStore = {
    open: open,
    getValue: getValue,
    setValue: setValue,
    listSessions: listSessions,
    getSession: getSession,
    putSession: putSession,
    removePeer: removePeer,
    listMessages: listMessages,
    addMessage: addMessage,
    patchMessage: patchMessage,
    removeMessage: removeMessage,
    addOutbox: addOutbox,
    listOutbox: listOutbox,
    removeOutbox: removeOutbox,
    clearAll: clearAll,
    newId: newId
  };
})(typeof window !== "undefined" ? window : this);
