/*
 * Word・Excel・PDF を iPhone 側で読み、予定の確認画面へ渡す橋渡し。
 * ファイルの内容は保存せず、外部にも送らない。
 */
(function (global) {
  "use strict";

  var BANNER_ID = "documentReaderBanner";

  function plugin() {
    var cap = global.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return null;
    return cap.Plugins && cap.Plugins.DocumentReader;
  }

  function available() {
    var cap = global.Capacitor;
    return !!(cap && typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
      (plugin() || typeof cap.nativePromise === "function"));
  }

  function invoke(method, options) {
    var reader = plugin();
    if (reader && typeof reader[method] === "function") return reader[method](options || {});
    var cap = global.Capacitor;
    if (cap && typeof cap.nativePromise === "function") {
      return cap.nativePromise("DocumentReader", method, options || {});
    }
    return null;
  }

  function pick() {
    return invoke("pick") || Promise.resolve({ cancelled: true });
  }

  function pickImage(options) {
    return invoke("pickImage", options) || Promise.resolve({ cancelled: true });
  }

  function hasShared() {
    return invoke("hasShared") || Promise.resolve({ has: false, name: "" });
  }

  function takeShared() {
    var request = invoke("takeShared");
    if (!request) return Promise.resolve(null);
    return request.then(function (result) {
      return result && result.name ? result : null;
    });
  }

  function toMeetings(result, today) {
    var value = result || {};
    var tables = Array.isArray(value.tables) ? value.tables : [];
    var lines = Array.isArray(value.lines) ? value.lines : [];
    var meetings;
    if (global.ScheduleTable && global.ScheduleTable.isSchedule(tables)) {
      meetings = global.ScheduleTable.parse(tables, today);
    } else {
      meetings = global.Meeting.parse(lines, {}).map(function (meeting) {
        meeting.source = "file";
        return meeting;
      });
    }
    return { meetings: meetings, text: lines.join("\n") };
  }

  // 起動直後の自動移動は WebView が操作不能になることがあるため、帯のボタンで移動する。
  function showSharedBanner(name, schedulePath) {
    var old = global.document.getElementById(BANNER_ID);
    if (old) old.parentNode.removeChild(old);

    var bar = global.document.createElement("div");
    bar.id = BANNER_ID;
    bar.setAttribute("role", "status");
    bar.style.cssText = [
      "position:fixed", "left:0", "right:0", "top:0", "z-index:41",
      "background:#1b2a48", "color:#f4efe4",
      "padding:calc(10px + env(safe-area-inset-top)) 14px 10px",
      "display:flex", "align-items:center", "gap:10px", "font-size:14px",
      "box-shadow:0 2px 8px rgba(0,0,0,.25)"
    ].join(";");

    var text = global.document.createElement("span");
    text.style.flex = "1";
    text.textContent = "共有された「" + name + "」を予定アプリで読む";

    var open = global.document.createElement("a");
    open.textContent = "開く";
    open.href = schedulePath + "?shared=1";
    open.style.cssText = "min-height:36px;padding:6px 14px;border-radius:8px;background:#f4efe4;color:#1b2a48;font-weight:700;display:flex;align-items:center;text-decoration:none";

    var close = global.document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "閉じる");
    close.textContent = "✕";
    close.style.cssText = "min-height:36px;padding:6px 10px;border-radius:8px;border:0;background:transparent;color:#f4efe4;font-size:16px";
    close.addEventListener("click", function () { bar.parentNode.removeChild(bar); });

    bar.appendChild(text);
    bar.appendChild(open);
    bar.appendChild(close);
    global.document.body.appendChild(bar);
  }

  function watchShared(schedulePath) {
    if (!available() || !schedulePath) return;
    var check = function () {
      hasShared().then(function (result) {
        if (result && result.has) showSharedBanner(result.name || "ファイル", schedulePath);
      }).catch(function () { /* 共有ファイルが無いときは何もしない */ });
    };
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", check, { once: true });
    } else {
      check();
    }
    var app = global.Capacitor.Plugins && global.Capacitor.Plugins.App;
    if (app && typeof app.addListener === "function") {
      app.addListener("resume", check);
    } else if (typeof global.Capacitor.addListener === "function") {
      global.Capacitor.addListener("App", "resume", check);
    }
  }

  global.DocumentReader = {
    available: available,
    pick: pick,
    pickImage: pickImage,
    takeShared: takeShared,
    hasShared: hasShared,
    toMeetings: toMeetings,
    watchShared: watchShared
  };
})(typeof window !== "undefined" ? window : this);
