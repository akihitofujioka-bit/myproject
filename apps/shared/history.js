/*
 * AI との会話、読み取った書類、手書きメモの履歴を端末内に保存する。
 * 保存先は IndexedDB の ichishi-history。外部への送信は行わない。
 */
(function (global) {
  "use strict";

  var DB_NAME = "ichishi-history";
  var DB_VERSION = 1;
  var STORE_NAME = "entries";
  var dbPromise = null;
  var dbSource = null;

  function forgetConnection(promise) {
    if (dbPromise === promise) dbPromise = null;
  }

  function open(indexedDB) {
    if (!indexedDB && dbPromise) return dbPromise;
    var source = indexedDB || dbSource || global.indexedDB;
    if (!source || typeof source.open !== "function") {
      return Promise.reject(new Error("unavailable"));
    }
    dbSource = source;

    // 引数を渡した場合は、テスト用などの保存先へ明示的に切り替える。
    if (indexedDB || !dbPromise) {
      var opening = new Promise(function (resolve, reject) {
        var request;
        try {
          request = source.open(DB_NAME, DB_VERSION);
        } catch (error) {
          reject(error);
          return;
        }
        request.onupgradeneeded = function () {
          var db = request.result;
          if (!db.objectStoreNames.contains(STORE_NAME)) {
            var store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
            store.createIndex("updatedAt", "updatedAt", { unique: false });
            store.createIndex("kind", "kind", { unique: false });
          }
        };
        request.onsuccess = function () {
          var db = request.result;
          db.onclose = function () { forgetConnection(opening); };
          db.onversionchange = function () {
            forgetConnection(opening);
            if (typeof db.close === "function") db.close();
          };
          resolve(db);
        };
        request.onerror = function () { reject(request.error || new Error("unavailable")); };
      });
      dbPromise = opening;
      opening.catch(function () { forgetConnection(opening); });
    }
    return dbPromise;
  }

  function reconnectable(error) {
    return error && ["InvalidStateError", "TransactionInactiveError", "AbortError"].indexOf(error.name) !== -1;
  }

  function runAttempt(method, value, hasValue, retried) {
    var connection = open();
    return connection.then(function (db) {
      return new Promise(function (resolve, reject) {
        var request, transaction;
        var readOnly = method === "get" || method === "getAll";
        try {
          transaction = db.transaction(STORE_NAME, readOnly ? "readonly" : "readwrite");
          var store = transaction.objectStore(STORE_NAME);
          request = hasValue ? store[method](value) : store[method]();
        } catch (error) {
          reject(error);
          return;
        }
        if (readOnly) {
          request.onsuccess = function () { resolve(request.result); };
        } else {
          transaction.oncomplete = function () { resolve(request.result); };
          transaction.onerror = function () { reject(transaction.error || request.error || new Error("履歴を操作できませんでした")); };
          transaction.onabort = function () { reject(transaction.error || request.error || new Error("履歴を操作できませんでした")); };
        }
        request.onerror = function () { reject(request.error || new Error("履歴を操作できませんでした")); };
      });
    }).catch(function (error) {
      if (!retried && reconnectable(error)) {
        forgetConnection(connection);
        return runAttempt(method, value, hasValue, true);
      }
      throw error;
    });
  }

  function run(method, value) {
    var hasValue = arguments.length > 1;
    return runAttempt(method, value, hasValue, false);
  }

  function now() {
    return new Date().toISOString();
  }

  function newerThan(previous) {
    var current = now();
    if (!previous || current > previous) return current;
    return new Date(new Date(previous).getTime() + 1).toISOString();
  }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 9);
  }

  function normalize(text) {
    return String(text == null ? "" : text)
      .normalize("NFKC")
      .replace(/[ァ-ヶ]/g, function (character) {
        return String.fromCharCode(character.charCodeAt(0) - 0x60);
      })
      .toLowerCase();
  }

  function titleFrom(text) {
    var lines = String(text == null ? "" : text).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (line) return Array.from(line).slice(0, 30).join("");
    }
    return "";
  }

  function add(entry) {
    var timestamp = now();
    var saved = Object.assign({}, entry, {
      id: uid(),
      createdAt: timestamp,
      updatedAt: timestamp
    });
    return run("put", saved).then(function () { return saved; });
  }

  function get(id) {
    return run("get", id).then(function (entry) { return entry || null; });
  }

  function update(id, patch) {
    return get(id).then(function (entry) {
      if (!entry) throw new Error("履歴が見つかりません");
      var saved = Object.assign({}, entry, patch || {});
      saved.id = entry.id;
      saved.createdAt = entry.createdAt;
      saved.updatedAt = newerThan(entry.updatedAt);
      return run("put", saved).then(function () { return saved; });
    });
  }

  function appendMessage(id, message) {
    return get(id).then(function (entry) {
      if (!entry) throw new Error("履歴が見つかりません");
      var messages = Array.isArray(entry.messages) ? entry.messages.slice() : [];
      messages.push({
        role: message.role,
        text: message.text,
        at: now()
      });
      return update(id, { messages: messages });
    });
  }

  function list(options) {
    options = options || {};
    var words = normalize(options.query).trim().split(/\s+/).filter(Boolean);
    return run("getAll").then(function (entries) {
      return (entries || []).filter(function (entry) {
        if (options.kind && entry.kind !== options.kind) return false;
        var messageText = (entry.messages || []).map(function (message) { return message.text || ""; }).join(" ");
        var searchable = normalize([entry.title || "", entry.body || "", messageText].join(" "));
        return words.every(function (word) { return searchable.indexOf(word) !== -1; });
      }).sort(function (a, b) {
        return String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""));
      });
    });
  }

  function remove(id) {
    return run("delete", id).then(function () {});
  }

  function clear() {
    return run("clear").then(function () {});
  }

  global.AIHistory = {
    open: open,
    add: add,
    update: update,
    appendMessage: appendMessage,
    get: get,
    list: list,
    remove: remove,
    clear: clear,
    normalize: normalize,
    titleFrom: titleFrom
  };
})(typeof window !== "undefined" ? window : this);
