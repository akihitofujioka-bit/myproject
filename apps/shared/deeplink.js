/*
 * QRコードから起動されたときの受け口。
 *
 * 書類トラッカーが発行する QR には myproject://docs?id=xxx という文字列が入っている。
 * iPhone の標準カメラでこれを読むとアプリが起動するので、
 * ここで受け取って、該当の書類を開いた状態のページへ移動させる。
 *
 * ブラウザで開いているときは window.Capacitor が無いため、何もしない。
 */
(function (global) {
  "use strict";

  function route(url) {
    if (!url || url.indexOf("myproject://") !== 0) return;
    // myproject://docs?id=xxx → docs-tracker を id 付きで開く
    var m = /^myproject:\/\/docs\?id=(.+)$/.exec(url);
    if (!m) return;
    var id = decodeURIComponent(m[1]);

    // 独自スキーム（capacitor://）で配信されているとき location.origin は "null" になるため、
    // 絶対 URL を組み立てず、いま開いているページからの相対パスで移動する。
    var path = global.location.pathname || "/";
    var inSubdir = path.replace(/^\//, "").indexOf("/") !== -1;   // 子アプリの中にいるか
    var prefix = inSubdir ? "../" : "";
    global.location.href = prefix + "docs-tracker/index.html?id=" + encodeURIComponent(id);
  }

  var cap = global.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return;

  var App = cap.Plugins && cap.Plugins.App;
  if (!App) return;

  // アプリが動いている最中に QR を読まれた場合
  App.addListener("appUrlOpen", function (data) { route(data && data.url); });

  // アプリが起動していない状態で QR を読まれた場合（起動直後に取りに行く）。
  //
  // 最初のページの読み込みが終わる前に移動させると、画面が真っ白のまま止まってしまう。
  // load を待つだけでは足りず（WebView 側の初期表示の処理が続いているため）、
  // 少し間を置いてから移動する。
  if (typeof App.getLaunchUrl === "function") {
    var goLaunchUrl = function () {
      App.getLaunchUrl()
        .then(function (res) { setTimeout(function () { route(res && res.url); }, 600); })
        .catch(function () { /* 起動URLが無いときは何もしない */ });
    };
    if (global.document.readyState === "complete") goLaunchUrl();
    else global.addEventListener("load", goLaunchUrl);
  }
})(typeof window !== "undefined" ? window : this);
