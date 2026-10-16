/*
 * myproject:// で起動されたときの共通の受け口。
 *
 * 書類トラッカーが発行するQRコードのほか、Siri・ショートカット、iPhoneの
 * ロック画面ウィジェット・Watchのコンプリケーションからの起動を受け取る。
 *
 * ＜プログラムから画面を移動させない理由＞
 * 起動直後に location を書き換えて移動すると、画面は表示されるのに
 * タップを一切受け付けない状態になることが分かった（WebView の作りの問題）。
 * そこで「開く」ボタンを出し、利用者が押したときに移動する形にしている。
 * 利用者の操作による移動なら正常に動く。
 *
 * ブラウザで開いているときは window.Capacitor が無いため、何もしない。
 */
(function (global) {
  "use strict";

  var BANNER_ID = "deeplinkBanner";

  function decodeValue(value) {
    try {
      return decodeURIComponent(value).slice(0, 100);
    } catch (e) {
      return null;
    }
  }

  function queryValue(query, name) {
    var parts = query.split("&");
    for (var i = 0; i < parts.length; i++) {
      var equal = parts[i].indexOf("=");
      if (equal >= 0 && parts[i].slice(0, equal) === name) return decodeValue(parts[i].slice(equal + 1));
    }
    return null;
  }

  // URLだけから移動先と引数を決める。画面やCapacitorには触れない。
  function parse(url) {
    if (typeof url !== "string") return null;
    var match = /^myproject:\/\/(meishi|docs|kakeibo|fridge)\?([^#]+)$/.exec(url);
    if (!match) return null;

    var app = match[1];
    var query = match[2];
    var action = queryValue(query, "action");
    var value;
    if ((app === "meishi" || app === "docs" || app === "kakeibo") && action === "scan") {
      return {
        path: (app === "docs" ? "docs-tracker" : app) + "/index.html",
        params: { action: "scan" }
      };
    }
    if (app === "fridge") {
      value = queryValue(query, "add");
      if (value !== null && value !== "") return { path: "fridge/index.html", params: { add: value } };
    }
    if (app === "docs") {
      value = queryValue(query, "todo");
      if (value !== null && value !== "") return { path: "docs-tracker/index.html", params: { todo: value } };
      value = queryValue(query, "id");
      if (value !== null && value !== "") return { path: "docs-tracker/index.html", params: { id: value } };
    }
    return null;
  }

  function relativePath(path) {
    var current = global.location.pathname || "/";
    var inSubdir = current.replace(/^\//, "").indexOf("/") !== -1;
    return (inSubdir ? "../" : "") + path;
  }

  function onTarget(path) {
    var dir = path.split("/")[0];
    return new RegExp("(?:^|/)" + dir + "/").test(global.location.pathname || "");
  }

  function searchOf(params) {
    var values = [];
    Object.keys(params).forEach(function (key) {
      values.push(encodeURIComponent(key) + "=" + encodeURIComponent(params[key]));
    });
    return values.length ? "?" + values.join("&") : "";
  }

  function labels(route) {
    if (route.params.action === "scan") {
      if (route.path.indexOf("meishi/") === 0) return { text: "名刺を撮る", button: "開く" };
      if (route.path.indexOf("docs-tracker/") === 0) return { text: "書類を撮る", button: "開く" };
      return { text: "レシートを撮る", button: "開く" };
    }
    if (route.params.add !== undefined) return { text: "冷蔵庫に『" + route.params.add + "』を追加", button: "開く" };
    if (route.params.todo !== undefined) return { text: "やること『" + route.params.todo + "』を追加", button: "開く" };
    return { text: "書類が見つかりました", button: "書類を開く" };
  }

  // 画面の上部に「開く」ボタンを出す
  function showBanner(route) {
    var old = document.getElementById(BANNER_ID);
    if (old) old.parentNode.removeChild(old);

    var bar = document.createElement("div");
    bar.id = BANNER_ID;
    bar.setAttribute("role", "status");
    bar.style.cssText = [
      "position:fixed", "left:0", "right:0", "top:0", "z-index:40",
      "background:#1b2a48", "color:#f4efe4",
      "padding:calc(10px + env(safe-area-inset-top)) 14px 10px",
      "display:flex", "align-items:center", "gap:10px",
      "font-size:14px", "box-shadow:0 2px 8px rgba(0,0,0,.25)"
    ].join(";");

    var label = labels(route);
    var text = document.createElement("span");
    text.style.flex = "1";
    // URL由来の品名・件名を含むため、HTMLとして解釈させない。
    text.textContent = label.text;

    var open = document.createElement("button");
    open.type = "button";
    open.textContent = label.button;
    open.style.cssText = "min-height:36px;padding:6px 14px;border-radius:8px;border:0;background:#f4efe4;color:#1b2a48;font-weight:700";
    open.addEventListener("click", function () {
      // 利用者の操作による移動なので、この経路なら問題は起きない
      global.location.href = relativePath(route.path) + searchOf(route.params);
    });

    var close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", "閉じる");
    close.textContent = "✕";
    close.style.cssText = "min-height:36px;padding:6px 10px;border-radius:8px;border:0;background:transparent;color:#f4efe4;font-size:16px";
    close.addEventListener("click", function () { bar.parentNode.removeChild(bar); });

    bar.appendChild(text);
    bar.appendChild(open);
    bar.appendChild(close);
    document.body.appendChild(bar);
  }

  function route(url) {
    var parsed = parse(url);
    if (!parsed) return;

    // すでに移動先を開いているなら、その画面に同じ処理を直接頼む。
    if (onTarget(parsed.path) && typeof global.applyDeepAction === "function") {
      global.applyDeepAction(parsed.params);
      return;
    }
    // 従来の書類IDだけは、古い画面の入口も引き続き使えるようにする。
    if (onTarget(parsed.path) && parsed.params.id !== undefined && typeof global.openDocById === "function") {
      global.openDocById(parsed.params.id);
      return;
    }
    showBanner(parsed);
  }

  global.DeepLink = { parse: parse };

  var cap = global.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return;

  var App = cap.Plugins && cap.Plugins.App;
  if (!App) return;

  // アプリが動いている最中に URL を開かれた場合
  App.addListener("appUrlOpen", function (data) { route(data && data.url); });

  // アプリが起動していない状態で URL を開かれた場合
  if (typeof App.getLaunchUrl === "function") {
    var go = function () {
      App.getLaunchUrl()
        .then(function (res) { setTimeout(function () { route(res && res.url); }, 300); })
        .catch(function () { /* 起動URLが無いときは何もしない */ });
    };
    if (global.document.readyState === "complete") go();
    else global.addEventListener("load", go);
  }
})(typeof window !== "undefined" ? window : this);
