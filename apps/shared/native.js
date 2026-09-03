/*
 * ネイティブアプリ（Capacitor）として動いているときだけ、端末の通知機能を使うための橋渡し。
 *
 * ブラウザで開いているときは window.Capacitor が存在しないため、すべての関数が
 * 「使えない」を返し、呼び出し側はカレンダー登録（ics.js）に切り替える。
 * つまり、この仕組みが無くてもアプリは完全に動く。
 *
 * 注意：ネイティブ側の動作は Mac + Xcode でのビルドが必要なため未検証。
 * ブラウザでの「使えないと判定して素通りする」挙動のみテストしている。
 */
(function (global) {
  "use strict";

  function plugins() {
    var cap = global.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return null;
    return cap.Plugins || null;
  }

  function notifications() {
    var p = plugins();
    return p && p.LocalNotifications ? p.LocalNotifications : null;
  }

  // 文字列から通知の番号（32ビットの整数）を作る。同じ項目なら同じ番号になり、上書きされる
  function idFrom(uid) {
    var h = 2166136261;
    for (var i = 0; i < uid.length; i++) {
      h ^= uid.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return h % 2000000000;
  }

  function atLocal(dateStr, timeStr, minutesBefore) {
    var d = dateStr.split("-").map(Number);
    var t = (timeStr || "09:00").split(":").map(Number);
    var dt = new Date(d[0], d[1] - 1, d[2], t[0], t[1] || 0, 0, 0);
    if (minutesBefore) dt.setMinutes(dt.getMinutes() - minutesBefore);
    return dt;
  }

  function available() {
    return !!notifications();
  }

  /**
   * 期限の通知を端末に登録する。
   * events は ics.js と同じ形（uid / title / date / time / description / alarms）。
   * 戻り値は { ok: true, count: n } か { ok: false, reason: "..." }。
   * ok が false のときは、呼び出し側でカレンダー登録に切り替える。
   */
  function scheduleDeadlines(events) {
    var api = notifications();
    if (!api) return Promise.resolve({ ok: false, reason: "not-native" });

    return api.requestPermissions().then(function (res) {
      if (!res || res.display !== "granted") return { ok: false, reason: "denied" };

      var now = Date.now();
      var list = [];
      events.forEach(function (ev) {
        (ev.alarms || [1440, 0]).forEach(function (minutesBefore, index) {
          var at = atLocal(ev.date, ev.time, minutesBefore);
          if (at.getTime() <= now) return; // 過ぎた時刻には登録しない
          list.push({
            id: (idFrom(ev.uid) + index) % 2000000000,
            title: minutesBefore ? "明日が期限です" : "本日が期限です",
            body: ev.title,
            schedule: { at: at, allowWhileIdle: true }
          });
        });
      });
      if (!list.length) return { ok: false, reason: "no-future-time" };

      // iOS は端末全体で64件までしか保留できないため、期限が近いものを優先する
      list.sort(function (a, b) { return a.schedule.at - b.schedule.at; });
      var limited = list.slice(0, 60);

      return api.schedule({ notifications: limited }).then(function () {
        return { ok: true, count: limited.length, skipped: list.length - limited.length };
      }, function (e) {
        return { ok: false, reason: (e && e.message) || "schedule-failed" };
      });
    }, function () {
      return { ok: false, reason: "permission-error" };
    });
  }

  global.Native = {
    available: available,
    scheduleDeadlines: scheduleDeadlines,
    idFrom: idFrom
  };
})(typeof window !== "undefined" ? window : this);
