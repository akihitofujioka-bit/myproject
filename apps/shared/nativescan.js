/*
 * アプリとして動いているときに、端末側の読み取り機能でバーコードを読む。
 *
 * ブラウザ版は、これまでどおり画面内のカメラと自前デコーダ（fridge/ean.js）を使う。
 * アプリ版だけ、iOS の Vision フレームワークによる読み取りに切り替える。
 * こちらは QR や Code128・Code39 など2次元・1次元の多くの形式に対応し、精度も速度も上。
 *
 * 読み取りは端末の中だけで完結し、映像も結果もどこにも送信しない
 * （読み取り部品の中身は Apple 純正の AVFoundation と Vision のみで、通信のコードを持たない）。
 *
 * 呼び出しには Capacitor.nativePromise() を使う。
 * Capacitor.Plugins は、まとめツール（バンドラ）で組んだアプリでしか埋まらないため、
 * このプロジェクトのように素の <script> で読み込む作りでは当てにできない。
 */
(function (global) {
  "use strict";

  var PLUGIN = "CapacitorBarcodeScanner";

  // プラグインが使うフォーマット番号（html5-qrcode の定義に合わせてある）
  var FORMAT = {
    ALL: 17,
    QR_CODE: 0,
    CODE_39: 3,
    CODE_128: 5,
    EAN_13: 9,
    EAN_8: 10,
    UPC_A: 14
  };

  /**
   * 端末側の読み取りが使えるか。使えないときは呼び出し側が今までの方法に戻る。
   */
  function available() {
    var cap = global.Capacitor;
    return !!(cap &&
              typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
              typeof cap.nativePromise === "function");
  }

  /**
   * バーコードを読む。読めたら文字列、利用者が閉じたときや失敗したときは null を返す。
   * @param {number} hint  NativeScan.FORMAT のいずれか（省略時は ALL）
   * @param {string} guide 画面に出す案内文
   */
  function scan(hint, guide) {
    if (!available()) return Promise.resolve(null);
    return global.Capacitor.nativePromise(PLUGIN, "scanBarcode", {
      hint: typeof hint === "number" ? hint : FORMAT.ALL,
      scanInstructions: guide || "枠の中にコードを合わせてください",
      scanButton: false,
      cameraDirection: 1   // 背面カメラ
    }).then(function (res) {
      return (res && res.ScanResult) ? String(res.ScanResult) : null;
    }).catch(function () {
      // 利用者が閉じた場合もここに来る。エラー扱いにはしない
      return null;
    });
  }

  global.NativeScan = { available: available, scan: scan, FORMAT: FORMAT };
})(typeof window !== "undefined" ? window : this);
