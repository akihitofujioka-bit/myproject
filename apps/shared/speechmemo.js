/*
 * iPhone の端末内音声認識を使い、メモ欄へ文字を入れるための橋渡し。
 * 音声は保存せず、端末の外にも送らない。
 */
(function (global) {
  "use strict";

  var PLUGIN = "SpeechMemo";
  var partialListener = null;
  var pluginProxy = null;

  function capacitor() {
    return global.Capacitor || null;
  }

  function nativeAvailable() {
    try {
      var cap = capacitor();
      return !!(cap &&
                typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
                typeof cap.nativePromise === "function");
    } catch (e) {
      return false;
    }
  }

  function nativePromise(method) {
    return capacitor().nativePromise(PLUGIN, method, {});
  }

  function plugin() {
    var cap = capacitor();
    if (!cap) return null;
    if (cap.Plugins && cap.Plugins[PLUGIN]) return cap.Plugins[PLUGIN];
    if (!pluginProxy && typeof cap.registerPlugin === "function") {
      pluginProxy = cap.registerPlugin(PLUGIN);
    }
    return pluginProxy;
  }

  function removePartialListener() {
    var listener = partialListener;
    partialListener = null;
    if (listener && typeof listener.remove === "function") {
      return Promise.resolve(listener.remove()).catch(function () {});
    }
    return Promise.resolve();
  }

  function available() {
    if (!nativeAvailable()) return Promise.resolve(false);
    return nativePromise("isSupported").then(function (result) {
      return !!(result && result.supported);
    }).catch(function () {
      return false;
    });
  }

  function start(onPartial) {
    if (!nativeAvailable()) return Promise.reject(new Error("この端末では使えません"));
    var speechPlugin = plugin();
    return removePartialListener().then(function () {
      if (!speechPlugin || typeof speechPlugin.addListener !== "function") return null;
      return speechPlugin.addListener("partial", function (event) {
        if (typeof onPartial === "function") onPartial(String((event && event.text) || ""));
      });
    }).then(function (listener) {
      partialListener = listener || null;
      return nativePromise("start");
    }).then(function () {
      return undefined;
    }).catch(function (error) {
      return removePartialListener().then(function () { throw error; });
    });
  }

  function stop() {
    if (!nativeAvailable()) return Promise.reject(new Error("この端末では使えません"));
    return nativePromise("stop").then(function (result) {
      return removePartialListener().then(function () {
        return String((result && result.text) || "");
      });
    }, function (error) {
      return removePartialListener().then(function () { throw error; });
    });
  }

  global.SpeechMemo = {
    available: available,
    start: start,
    stop: stop
  };
})(typeof window !== "undefined" ? window : this);
