/*
 * iPhone のカレンダーから予定を読み取るための橋渡し（CalendarReaderPlugin）。
 *
 * このアプリからカレンダーへの書き込みは、引き続き .ics ファイル経由（ics.js）で行う。
 * 読み取った予定をそのまま書き戻すと同じ予定が重複して増えるため、別の経路にしている。
 *
 * 読み取りは端末の中だけで完結し、外部へは送らない。
 * ブラウザで開いているとき、またはプラグインが登録されていないときは
 * available() が false を返し、呼び出し側はカレンダー由来の機能を出さない。
 */
(function (global) {
  "use strict";

  var PLUGIN = "CalendarReader";

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

  function listCalendars() {
    if (!available()) return Promise.resolve({ calendars: [] });
    return global.Capacitor.nativePromise(PLUGIN, "listCalendars", {});
  }

  function listEvents(calendarIds, days) {
    if (!available()) return Promise.resolve({ events: [] });
    return global.Capacitor.nativePromise(PLUGIN, "listEvents", { calendarIds: calendarIds || [], days: days || 60 });
  }

  /**
   * カレンダーの予定を、会議の確認欄（apps/docs-tracker）と同じ形に直す。
   * 懇親会の有無はカレンダーには無いため、常に「なし」で始める（人が直せる）。
   */
  function toMeeting(ev) {
    return {
      title: (ev && ev.title) || "",
      date: (ev && ev.date) || "",
      startTime: (ev && ev.startTime) || "",
      endTime: (ev && ev.endTime) || "",
      place: (ev && ev.place) || "",
      social: { has: false, fee: null },
      source: "calendar"
    };
  }

  global.CalendarRead = {
    available: available,
    isSupported: isSupported,
    requestAccess: requestAccess,
    listCalendars: listCalendars,
    listEvents: listEvents,
    toMeeting: toMeeting
  };
})(typeof window !== "undefined" ? window : this);
