/*
 * QRコードから起動されたときの受け口。
 *
 * 書類トラッカーが発行する QR には myproject://docs?id=xxx が入っている。
 * iPhone の標準カメラでこれを読むとアプリが起動するので、ここで受け取る。
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

  function docPath() {
    var path = global.location.pathname || "/";
    var inSubdir = path.replace(/^\//, "").indexOf("/") !== -1;
    return (inSubdir ? "../" : "") + "docs-tracker/index.html";
  }

  function onDocsTracker() {
    return /docs-tracker\//.test(global.location.pathname || "");
  }

  // 画面の上部に「開く」ボタンを出す
  function showBanner(id) {
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

    var text = document.createElement("span");
    text.style.flex = "1";
    text.textContent = "QRコードを読み取りました";

    var open = document.createElement("button");
    open.type = "button";
    open.textContent = "書類を開く";
    open.style.cssText = "min-height:36px;padding:6px 14px;border-radius:8px;border:0;background:#f4efe4;color:#1b2a48;font-weight:700";
    open.addEventListener("click", function () {
      // 利用者の操作による移動なので、この経路なら問題は起きない
      global.location.href = docPath() + "?id=" + encodeURIComponent(id);
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
    if (!url || url.indexOf("myproject://") !== 0) return;
    var m = /^myproject:\/\/docs\?id=(.+)$/.exec(url);
    if (!m) return;
    var id = decodeURIComponent(m[1]);

    // すでに書類トラッカーを開いているなら、移動せずその場で絞り込む
    if (onDocsTracker() && typeof global.openDocById === "function") {
      global.openDocById(id);
      return;
    }
    showBanner(id);
  }

  var cap = global.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return;

  var App = cap.Plugins && cap.Plugins.App;
  if (!App) return;

  // アプリが動いている最中に QR を読まれた場合
  App.addListener("appUrlOpen", function (data) { route(data && data.url); });

  // アプリが起動していない状態で QR を読まれた場合
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
