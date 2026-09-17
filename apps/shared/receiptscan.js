/*
 * 書類カメラ（iOS アプリ内の ReceiptScanner プラグイン）への橋渡し。
 *
 * 2つの使い方がある。
 *   scan()          … 撮って文字を読み取る（家計簿のレシート読み取り）
 *   scanToPhotos()  … 撮って写真アプリに保存する（書類トラッカーの書類撮影）
 *
 * どちらも VisionKit の書類カメラを使う。書類カメラは映像から1コマを切り出す
 * 仕組みのため、シャッター音は鳴らない（Apple 純正の「メモ」の書類スキャンと同じ）。
 *
 * アプリとして動いていて、かつプラグインが登録されているときだけ使える。
 * ブラウザで開いたときは available() が false を返し、呼び出し側はボタンを出さない。
 * 撮影も文字認識も端末内で完結し、画像・文字を外部へ送らない。
 */
(function (global) {
  "use strict";

  var PLUGIN = "ReceiptScanner";

  function available() {
    // 判定は nativescan.js（バーコード読み取り）と同じ方式に揃えている。
    //
    // Capacitor.isPluginAvailable() は使わない。このアプリは素の HTML で
    // @capacitor/core の JS ランタイムを読み込んでいないため、注入される
    // window.Capacitor には Plugins が無く、isPluginAvailable() は
    // 「Cannot convert undefined or null to object」で例外になる。
    // その例外で家計簿画面のスクリプトが止まり、ボタンが出なかった（2026-09-16）。
    try {
      var cap = global.Capacitor;
      return !!(cap &&
                typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
                typeof cap.nativePromise === "function");
    } catch (e) {
      return false;
    }
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

  /**
   * 書類カメラを開いて撮り、そのまま写真アプリに保存する。
   * 戻り値: { cancelled: boolean, saved: 保存した枚数 }
   * 利用者が閉じたときは cancelled: true（失敗ではない）。
   */
  function scanToPhotos() {
    if (!available()) return Promise.resolve({ cancelled: true, saved: 0 });
    return global.Capacitor.nativePromise(PLUGIN, "scanToPhotos", {}).then(function (res) {
      return { cancelled: !!(res && res.cancelled), saved: (res && res.saved) || 0 };
    });
  }

  global.ReceiptScan = { available: available, scan: scan, scanToPhotos: scanToPhotos };
})(typeof window !== "undefined" ? window : this);
