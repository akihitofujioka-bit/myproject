/*
 * キャラクター写真の保存と表示を共通化する。
 *
 * 写真は端末内の IndexedDB だけに保存し、外部へは送らない。
 */
(function (global) {
  "use strict";

  var DB_NAME = "character";
  var DB_VERSION = 1;
  var STORE_NAME = "slots";
  var SLOTS = ["top", "fridge", "docs-tracker", "stock", "kakeibo", "cards"];
  var albumStatuses = {};

  function todayString(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function dateParts(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    var parts = { year: Number(match[1]), month: Number(match[2]) - 1, day: Number(match[3]) };
    var check = new Date(parts.year, parts.month, parts.day);
    if (check.getFullYear() !== parts.year || check.getMonth() !== parts.month || check.getDate() !== parts.day) return null;
    return parts;
  }

  function utcDay(parts) {
    return Date.UTC(parts.year, parts.month, parts.day) / 86400000;
  }

  function pickIndex(count, interval, startDate, today) {
    if (count <= 0) return -1;
    if (count === 1) return 0;

    var start = dateParts(startDate);
    var current = dateParts(todayString(today));
    if (!start || !current) return 0;

    var startDay = utcDay(start);
    var currentDay = utcDay(current);
    if (currentDay < startDay) return 0;

    var elapsed;
    if (interval === "week") {
      var weekday = new Date(Date.UTC(start.year, start.month, start.day)).getUTCDay();
      var daysFromMonday = (weekday + 6) % 7;
      elapsed = Math.floor((currentDay - (startDay - daysFromMonday)) / 7);
    } else if (interval === "month") {
      elapsed = (current.year - start.year) * 12 + (current.month - start.month);
    } else {
      elapsed = currentDay - startDay;
    }
    return elapsed < 0 ? 0 : elapsed % count;
  }

  function veilAlpha(veil) {
    if (veil === "light") return 0.55;
    if (veil === "strong") return 0.85;
    return 0.7;
  }

  function normalize(record, slot) {
    record = record && typeof record === "object" ? record : {};
    var album = record.album;
    if (!album || typeof album !== "object" || typeof album.id !== "string" || typeof album.title !== "string") album = null;
    else album = { id: album.id, title: album.title };
    return {
      slot: slot,
      interval: record.interval === "week" || record.interval === "month" ? record.interval : "day",
      veil: record.veil === "light" || record.veil === "strong" ? record.veil : "normal",
      startDate: dateParts(record.startDate) ? record.startDate : todayString(new Date()),
      photos: Array.isArray(record.photos) ? record.photos : [],
      album: album,
      albumIds: Array.isArray(record.albumIds) ? record.albumIds : [],
      manualPhotos: Array.isArray(record.manualPhotos) ? record.manualPhotos : []
    };
  }

  function albumDiff(oldIds, newIds) {
    oldIds = Array.isArray(oldIds) ? oldIds : [];
    newIds = Array.isArray(newIds) ? newIds : [];
    var oldSet = {};
    oldIds.forEach(function (id) { oldSet[id] = true; });
    return {
      keep: newIds.filter(function (id) { return !!oldSet[id]; }),
      add: newIds.filter(function (id) { return !oldSet[id]; }),
      order: newIds.slice()
    };
  }

  function albumNotice(status, title) {
    if (status === "ok") return "";
    if (status === "limited" || status === "denied") {
      return "設定アプリ → プライバシー → 写真 で『すべての写真』を許可してください";
    }
    if (status === "not-found") return "アルバム『" + title + "』が見つかりません。選び直してください";
    return "";
  }

  function base64Blob(data) {
    var binary = global.atob(String(data || "").replace(/^data:[^,]*,/, ""));
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new global.Blob([bytes], { type: "image/jpeg" });
  }

  function openDatabase() {
    return new Promise(function (resolve, reject) {
      if (!global.indexedDB) {
        reject(new Error("IndexedDB を利用できません"));
        return;
      }
      var request = global.indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = function () {
        var db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: "slot" });
      };
      request.onsuccess = function () { resolve(request.result); };
      request.onerror = function () { reject(request.error || new Error("データベースを開けません")); };
    });
  }

  function load(slot) {
    return openDatabase().then(function (db) {
      return new Promise(function (resolve, reject) {
        var transaction = db.transaction(STORE_NAME, "readonly");
        var request = transaction.objectStore(STORE_NAME).get(slot);
        request.onsuccess = function () { resolve(normalize(request.result, slot)); };
        request.onerror = function () { reject(request.error || new Error("写真を読み込めません")); };
        transaction.oncomplete = function () { db.close(); };
        transaction.onabort = function () { db.close(); };
      });
    });
  }

  function save(record) {
    var value = normalize(record, record && record.slot);
    return openDatabase().then(function (db) {
      return new Promise(function (resolve, reject) {
        var transaction = db.transaction(STORE_NAME, "readwrite");
        transaction.objectStore(STORE_NAME).put(value);
        transaction.oncomplete = function () {
          db.close();
          resolve();
        };
        transaction.onerror = function () {
          db.close();
          reject(transaction.error || new Error("写真を保存できません"));
        };
        transaction.onabort = function () {
          db.close();
          reject(transaction.error || new Error("写真を保存できません"));
        };
      });
    });
  }

  function canvasBlob(source, width, height) {
    return new Promise(function (resolve, reject) {
      var canvas = global.document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      var context = canvas.getContext("2d");
      context.drawImage(source, 0, 0, width, height);
      canvas.toBlob(function (blob) {
        if (blob) resolve(blob);
        else reject(new Error("写真を変換できません"));
      }, "image/jpeg", 0.85);
    });
  }

  function resizedDimensions(width, height, maxSide) {
    var scale = Math.min(1, (maxSide || 1080) / Math.max(width, height));
    return { width: Math.round(width * scale), height: Math.round(height * scale) };
  }

  function resizeWithImage(file, maxSide) {
    return new Promise(function (resolve, reject) {
      var url = global.URL.createObjectURL(file);
      var image = new global.Image();
      image.onload = function () {
        var size = resizedDimensions(image.naturalWidth, image.naturalHeight, maxSide);
        canvasBlob(image, size.width, size.height).then(resolve, reject).finally(function () {
          global.URL.revokeObjectURL(url);
        });
      };
      image.onerror = function () {
        global.URL.revokeObjectURL(url);
        reject(new Error("写真を読み込めません"));
      };
      image.src = url;
    });
  }

  function resize(file, maxSide) {
    if (typeof global.createImageBitmap !== "function") return resizeWithImage(file, maxSide);
    return global.createImageBitmap(file).then(function (bitmap) {
      var size = resizedDimensions(bitmap.width, bitmap.height, maxSide);
      return canvasBlob(bitmap, size.width, size.height).finally(function () {
        if (typeof bitmap.close === "function") bitmap.close();
      });
    });
  }

  function watchMark(record, today) {
    record = normalize(record, record && record.slot);
    if (!record.photos.length) return "clear";
    return todayString(today) + ":" + pickIndex(record.photos.length, record.interval, record.startDate, today) + ":" + record.photos.length;
  }

  function currentPhotoURL(slot) {
    return load(slot).then(function (record) {
      var index = pickIndex(record.photos.length, record.interval, record.startDate, new Date());
      return index < 0 ? null : global.URL.createObjectURL(record.photos[index]);
    }).catch(function () {
      return null;
    });
  }

  function applyBackground(slot) {
    return load(slot).then(function (record) {
      var index = pickIndex(record.photos.length, record.interval, record.startDate, new Date());
      if (!global.document || !global.document.body) return;

      var background = global.document.getElementById("charBg");
      // 前に表示した写真の URL は使い終わったので解放する
      if (background && background.dataset.url) global.URL.revokeObjectURL(background.dataset.url);
      // 写真をすべて消したときは、元の背景に戻す
      if (index < 0) {
        if (background) background.remove();
        global.document.documentElement.classList.remove("has-char-bg");
        return;
      }

      var url = global.URL.createObjectURL(record.photos[index]);
      if (!background) {
        background = global.document.createElement("div");
        background.id = "charBg";
        global.document.body.insertBefore(background, global.document.body.firstChild);
      }
      background.dataset.url = url;
      background.style.cssText = "position:fixed;inset:0;z-index:-1;background:center / cover no-repeat url(\"" + url + "\")";

      var veil = global.document.createElement("div");
      veil.style.cssText = "position:absolute;inset:0;background:rgba(255,255,255," + veilAlpha(record.veil) + ")";
      background.innerHTML = "";
      background.appendChild(veil);

      var style = global.document.getElementById("charBgStyle");
      if (!style) {
        style = global.document.createElement("style");
        style.id = "charBgStyle";
        style.textContent = "html.has-char-bg body { background: transparent; }";
        global.document.head.appendChild(style);
      }
      global.document.documentElement.classList.add("has-char-bg");
    }).catch(function () {
      /* 読み込めないときは元の背景のままにする */
    });
  }

  var character = {
    SLOTS: SLOTS,
    pickIndex: pickIndex,
    veilAlpha: veilAlpha,
    normalize: normalize,
    albumDiff: albumDiff,
    albumNotice: albumNotice,
    albumStatus: function (slot) { return albumStatuses[slot] || "ok"; },
    todayString: todayString,
    load: load,
    save: save,
    resize: resize,
    watchMark: watchMark,
    currentPhotoURL: currentPhotoURL,
    applyBackground: applyBackground,
    _store: { load: load, save: save }
  };

  function syncAlbum(slot, plugin) {
    var store = character._store;
    return store.load(slot).then(function (record) {
      record = normalize(record, slot);
      if (!record.album) {
        albumStatuses[slot] = "ok";
        return { status: "ok", added: 0, failed: 0 };
      }
      return Promise.resolve(plugin.assetIds({ albumId: record.album.id })).then(function (result) {
        var status = result && result.status;
        if (status !== "ok") {
          status = status === "limited" ? "limited" : "denied";
          albumStatuses[slot] = status;
          return { status: status, added: 0, failed: 0 };
        }

        var ids = Array.isArray(result.ids) ? result.ids : [];
        var diff = albumDiff(record.albumIds, ids);
        var photosById = {};
        record.albumIds.forEach(function (id, index) {
          if (record.photos[index]) photosById[id] = record.photos[index];
        });
        var added = 0;
        var failed = 0;
        var chain = Promise.resolve();
        diff.add.forEach(function (id) {
          chain = chain.then(function () {
            return Promise.resolve(plugin.loadPhoto({ id: id, maxSide: 1080 })).then(function (photo) {
              try {
                photosById[id] = base64Blob(photo && photo.data);
                added++;
              } catch (e) {
                failed++;
              }
            }, function () {
              failed++;
            });
          });
        });
        return chain.then(function () {
          var keptIds = diff.order.filter(function (id) { return !!photosById[id]; });
          var next = normalize(record, slot);
          next.albumIds = keptIds;
          next.photos = keptIds.map(function (id) { return photosById[id]; });
          return store.save(next).then(function () {
            albumStatuses[slot] = "ok";
            return { status: "ok", added: added, failed: failed };
          });
        });
      }, function () {
        albumStatuses[slot] = "not-found";
        return { status: "not-found", added: 0, failed: 0 };
      });
    });
  }

  character.syncAlbum = syncAlbum;
  global.Character = character;
})(typeof window !== "undefined" ? window : this);
