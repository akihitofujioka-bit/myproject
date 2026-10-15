/*
 * 名刺を端末内の IndexedDB に保存する。
 * 保存先は meishi。外部への送信は行わない。
 */
(function (global) {
  "use strict";

  var DB_NAME = "meishi";
  var DB_VERSION = 1;
  var STORE_NAME = "cards";
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
            store.createIndex("createdAt", "createdAt", { unique: false });
            store.createIndex("scheduleId", "meeting.scheduleId", { unique: false });
            store.createIndex("calEventId", "meeting.calEventId", { unique: false });
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
          transaction.onerror = function () { reject(transaction.error || request.error || new Error("名刺を操作できませんでした")); };
          transaction.onabort = function () { reject(transaction.error || request.error || new Error("名刺を操作できませんでした")); };
        }
        request.onerror = function () { reject(request.error || new Error("名刺を操作できませんでした")); };
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
    return "m-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 9);
  }

  function normalize(text) {
    return String(text == null ? "" : text)
      .normalize("NFKC")
      .replace(/[ァ-ヶ]/g, function (character) {
        return String.fromCharCode(character.charCodeAt(0) - 0x60);
      })
      .toLowerCase();
  }

  function add(card) {
    var timestamp = now();
    var saved = Object.assign({}, card, {
      id: uid(),
      createdAt: timestamp,
      updatedAt: timestamp
    });
    if (!Array.isArray(saved.phones)) saved.phones = [];
    if (saved.meeting == null) saved.meeting = null;
    return run("put", saved).then(function () { return saved; });
  }

  function get(id) {
    return run("get", id).then(function (card) { return card || null; });
  }

  function update(id, changes) {
    return get(id).then(function (card) {
      if (!card) throw new Error("名刺が見つかりません");
      var saved = Object.assign({}, card, changes || {});
      saved.id = card.id;
      saved.createdAt = card.createdAt;
      saved.updatedAt = newerThan(card.updatedAt);
      return run("put", saved).then(function () { return saved; });
    });
  }

  function list(options) {
    options = options || {};
    var words = normalize(options.query).trim().split(/\s+/).filter(Boolean);
    return run("getAll").then(function (cards) {
      return (cards || []).filter(function (card) {
        var meetingTitle = card.meeting && card.meeting.title || "";
        var searchable = normalize([
          card.name || "",
          card.company || "",
          card.department || "",
          card.title || "",
          card.memo || card.note || "",
          meetingTitle
        ].join(" "));
        return words.every(function (word) { return searchable.indexOf(word) !== -1; });
      }).sort(function (a, b) {
        return String(b.createdAt || "").localeCompare(String(a.createdAt || ""));
      });
    });
  }

  function remove(id) {
    return run("delete", id).then(function () {});
  }

  function byMeeting(options) {
    options = options || {};
    var scheduleId = options.scheduleId || "";
    var calEventId = options.calEventId || "";
    if (!scheduleId && !calEventId) return Promise.resolve([]);
    return list({}).then(function (cards) {
      return cards.filter(function (card) {
        var meeting = card.meeting;
        if (!meeting) return false;
        return Boolean(
          scheduleId && meeting.scheduleId === scheduleId ||
          calEventId && meeting.calEventId === calEventId
        );
      });
    });
  }

  global.MeishiStore = {
    open: open,
    add: add,
    update: update,
    get: get,
    list: list,
    remove: remove,
    byMeeting: byMeeting
  };
})(typeof window !== "undefined" ? window : this);
