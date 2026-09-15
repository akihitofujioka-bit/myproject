/*
 * レシート撮影（iOS アプリ内の ReceiptScanner プラグイン）への橋渡し。
 *
 * アプリとして動いていて、かつプラグインが登録されているときだけ使える。
 * ブラウザで開いたときは available() が false を返し、呼び出し側はボタンを出さない。
 * 撮影も文字認識も端末内で完結し、画像・文字を外部へ送らない。
 */
(function (global) {
  "use strict";

  var PLUGIN = "ReceiptScanner";

  function available() {
    var cap = global.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return false;
    if (typeof cap.nativePromise !== "function") return false;
    if (typeof cap.isPluginAvailable === "function") return cap.isPluginAvailable(PLUGIN);
    return true;
  }

  /**
   * 書類カメラを開いてレシートを撮り、認識した行の断片を返す。
   * 戻り値: { cancelled: boolean, lines: [{ text, x, y, width, height, confidence }] }
   * 利用者が閉じたときは cancelled: true（失敗ではない）。
   */
  function scan() {
    if (!available()) return Promise.resolve({ cancelled: true, lines: [] });
    return global.Capacitor.nativePromise(PLUGIN, "scan", {}).then(function (res) {
      return { cancelled: !!(res && res.cancelled), lines: (res && res.lines) || [] };
    });
  }

  global.ReceiptScan = { available: available, scan: scan };
})(typeof window !== "undefined" ? window : this);
