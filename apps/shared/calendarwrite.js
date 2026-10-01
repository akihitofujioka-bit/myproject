/*
 * iPhone のカレンダーへ直接書き込むための橋渡し（CalendarWriterPlugin）。
 *
 * ＜なぜ .ics ではなくこちらを使うのか＞
 * これまでは .ics ファイルを共有シート経由で渡していたが、
 *  ・「カレンダーに登録」を押すと共有の画面が出てしまい、操作が分かりにくい
 *  ・同じ会議を登録し直すと、カレンダー側が別の予定として増やしてしまう
 * という困りごとがあった（利用者からの指摘: 2026-09-24）。
 *
 * このモジュールは、前回書き込んだときの識別子（eventId）を一緒に渡すことで、
 * 同じ予定を上書きする。識別子はアプリ側（localStorage）で覚えておく。
 *
 * ブラウザで開いているとき、またはプラグインが無いときは available() が false を返し、
 * 呼び出し側はこれまでどおり .ics ファイル経由に切り替える。
 */
(function (global) {
  "use strict";

  var PLUGIN = "CalendarWriter";

  function available() {
    try {
      var cap = global.Capacitor;
      return !!(cap &&
                typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
                typeof cap.nativePromise === "function");
    } catch (e) {
      return false;
    }
  }

  function isSupported() {
    if (!available()) return Promise.resolve({ supported: false, authorized: false });
    return global.Capacitor.nativePromise(PLUGIN, "isSupported", {});
  }

  function requestAccess() {
    if (!available()) return Promise.resolve({ granted: false, reason: "not-native" });
    return global.Capacitor.nativePromise(PLUGIN, "requestAccess", {});
  }

  /**
   * 予定をまとめて書き込む。
   *
   * events: [{
   *   key:       この予定を見分けるための文字列（戻り値で対応づける）
   *   eventId:   前回書き込んだときの識別子。あれば上書きする（重複を防ぐ）
   *   title, date（"YYYY-MM-DD"）, startTime / endTime（"HH:MM"、空なら終日）
   *   location, notes, alarms（何分前に知らせるかの配列）
   * }]
   *
   * 戻り値: { ok, reason, ids: { key: eventId }, failed: [{ key, reason }] }
   * 許可されていないときは一度だけ許可を求め、断られたら ok:false を返す
   * （呼び出し側は .ics 経由に切り替える）。
   */
  function save(events) {
    var list = (events || []).filter(function (e) { return e && e.date; });
    if (!list.length) return Promise.resolve({ ok: false, reason: "no-events", ids: {}, failed: [] });
    if (!available()) return Promise.resolve({ ok: false, reason: "not-native", ids: {}, failed: [] });

    return isSupported().then(function (res) {
      if (res && res.authorized) return true;
      return requestAccess().then(function (r) { return !!(r && r.granted); });
    }).then(function (allowed) {
      if (!allowed) return { ok: false, reason: "not-authorized", ids: {}, failed: [] };
      return global.Capacitor.nativePromise(PLUGIN, "saveEvents", { events: list }).then(function (res) {
        var ids = {};
        ((res && res.saved) || []).forEach(function (s) {
          if (s && s.key && s.eventId) ids[s.key] = s.eventId;
        });
        return {
          ok: !!(res && res.ok),
          reason: (res && res.reason) || "",
          ids: ids,
          failed: (res && res.failed) || []
        };
      }, function (e) {
        return { ok: false, reason: (e && e.message) || "save-failed", ids: {}, failed: [] };
      });
    });
  }

  global.CalendarWrite = {
    available: available,
    isSupported: isSupported,
    requestAccess: requestAccess,
    save: save
  };
})(typeof window !== "undefined" ? window : this);
