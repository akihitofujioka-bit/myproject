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

  /* ---------- 通知の文面 ---------- */

  /*
   * Apple Watch は通知の1行目（太字）と2行目しか見えない場面が多い。
   * そこで1行目に「いつまでか＋件名」、2行目に場所・状態を入れ、
   * 手首を見ただけで判断できるようにする。
   */

  // 通知が鳴る時点から見て、期限までどれだけあるかを表す言葉
  function whenLabel(minutesBefore) {
    var m = Number(minutesBefore) || 0;
    if (m <= 0) return "本日";
    if (m < 60) return m + "分後";
    if (m < 1440) return Math.round(m / 60) + "時間後";
    var days = Math.round(m / 1440);
    if (days === 1) return "明日";
    if (days % 30 === 0) return (days / 30) + "か月後";
    return days + "日後";
  }

  // 「（○○から登録）」のような出どころの断り書きは、手首では読む価値がないため省く
  function firstDetail(description) {
    var lines = String(description || "").split("\n");
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (line && !/^（.*）$/.test(line)) return line;
    }
    return "";
  }

  function clip(text, max) {
    var t = String(text || "");
    return t.length > max ? t.slice(0, max - 1) + "…" : t;
  }

  /**
   * 1件ぶんの通知の文面を作る。
   * ev.summaryLine があればそれを2行目に使い、無ければ場所と説明から組み立てる。
   */
  function notice(ev, minutesBefore) {
    var parts = [];
    if (ev.summaryLine) parts.push(ev.summaryLine);
    else {
      if (ev.location) parts.push(ev.location);
      var detail = firstDetail(ev.description);
      if (detail) parts.push(detail);
    }
    return {
      title: clip(whenLabel(minutesBefore) + "：" + (ev.title || ""), 60),
      body: clip(parts.join(" ／ "), 60)
    };
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
          var text = notice(ev, minutesBefore);
          list.push({
            id: (idFrom(ev.uid) + index) % 2000000000,
            title: text.title,
            body: text.body,
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
    notice: notice,
    whenLabel: whenLabel,
    idFrom: idFrom
  };
})(typeof window !== "undefined" ? window : this);
