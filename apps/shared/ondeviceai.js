/*
 * iPhone の端末内 AI を Web 画面から呼ぶ橋渡し。
 * 入力と回答は端末の外へ送らない。
 */
(function (global) {
  "use strict";

  function plugin() {
    var cap = global.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return null;
    return cap.Plugins && cap.Plugins.OnDeviceAI;
  }

  function invoke(method, args) {
    var ai = plugin();
    if (ai && typeof ai[method] === "function") return ai[method](args || {});
    var cap = global.Capacitor;
    if (cap && typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
        typeof cap.nativePromise === "function") {
      return cap.nativePromise("OnDeviceAI", method, args || {});
    }
    return null;
  }

  function status() {
    return invoke("status", {}) || Promise.resolve({ available: false, reason: "unsupported" });
  }

  function respond(args) {
    var request = invoke("respond", args || {});
    if (request) return request;
    var error = new Error("この端末では端末内 AI を使えません");
    error.code = "unavailable";
    return Promise.reject(error);
  }

  global.OnDeviceAI = {
    status: status,
    respond: respond
  };
})(typeof window !== "undefined" ? window : this);
