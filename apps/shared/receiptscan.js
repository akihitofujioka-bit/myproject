/*
 * 書類カメラ（iOS アプリ内の ReceiptScanner プラグイン）への橋渡し。
 *
 * 2つの使い方がある。
 *   scan()          … 撮って文字を読み取る（家計簿のレシート読み取り）
 *   scanToPhotos()  … 撮って写真アプリに保存する（書類トラッカーの書類撮影）
 *
 * 撮り方は2種類あり、利用者が選べる（camerapref.js の設定を使う）。
 *   無音カメラ   … シャッター音が鳴らない。四隅の自動切り出しはしない
 *   書類カメラ   … 四隅を自動で切り出すが、シャッター音が鳴る
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
   * カメラを開いてレシートや手帳を撮り、認識した行の断片を返す。
   * options: { camera: "silent"|"document", purpose: "receipt"|"planner" }（どちらも省略可）
   * 戻り値: { cancelled: boolean, lines: [{ text, x, y, width, height, confidence }] }
   * 利用者が閉じたときは cancelled: true（失敗ではない）。
   */
  // 利用者が選んだ撮り方。設定が読み込まれていないときは無音カメラにする
  function cameraMode(options) {
    if (options && options.camera) return options.camera;
    return (global.CameraPref && global.CameraPref.get()) || "silent";
  }

  function scan(options) {
    if (!available()) return Promise.resolve({ cancelled: true, lines: [] });
    var args = { camera: cameraMode(options) };
    // 何を撮るか（"receipt" / "planner"）。案内文と、小さな文字をどこまで拾うかが変わる
    if (options && options.purpose) args.purpose = options.purpose;
    return global.Capacitor.nativePromise(PLUGIN, "scan", args).then(function (res) {
      return { cancelled: !!(res && res.cancelled), lines: (res && res.lines) || [] };
    });
  }

  /**
   * 書類カメラを開いて撮り、そのまま写真アプリに保存する。
   * 戻り値: { cancelled: boolean, saved: 保存した枚数 }
   * 利用者が閉じたときは cancelled: true（失敗ではない）。
   */
  function scanToPhotos(options) {
    if (!available()) return Promise.resolve({ cancelled: true, saved: 0 });
    return global.Capacitor.nativePromise(PLUGIN, "scanToPhotos", { camera: cameraMode(options) }).then(function (res) {
      return { cancelled: !!(res && res.cancelled), saved: (res && res.saved) || 0 };
    });
  }

  global.ReceiptScan = { available: available, scan: scan, scanToPhotos: scanToPhotos, cameraMode: cameraMode };
})(typeof window !== "undefined" ? window : this);
