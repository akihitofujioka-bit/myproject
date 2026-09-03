/*
 * 予定ファイル（.ics / iCalendar）を作る。
 *
 * iPhone・Android・Outlook などの標準カレンダーに読み込ませ、
 * 端末側の通知で期限を知らせるために使う。外部への通信は行わない。
 *
 * 仕様は RFC 5545 に従う。特に次の2点は守らないと読み込めないアプリがある。
 *  - 改行は CRLF
 *  - 1行は75オクテット以内（超える場合は次の行の先頭に半角空白を置いて折り返す）
 */
(function (global) {
  "use strict";

  function pad(n) { return String(n).padStart(2, "0"); }

  // テキスト中の特殊文字を仕様どおりに退避する
  function escapeText(value) {
    return String(value == null ? "" : value)
      .replace(/\\/g, "\\\\")
      .replace(/;/g, "\\;")
      .replace(/,/g, "\\,")
      .replace(/\r?\n/g, "\\n");
  }

  // 1行を75オクテット以内に折り返す。日本語（マルチバイト）を途中で割らない
  function foldLine(line) {
    var encoder = new TextEncoder();
    var out = [];
    var current = "";
    var currentBytes = 0;
    var limit = 74; // 継続行の先頭に置く空白のぶんを引いた値
    for (var i = 0; i < line.length; i++) {
      // サロゲートペア（絵文字など）は2つで1文字として扱う
      var ch = line[i];
      if (/[\uD800-\uDBFF]/.test(ch) && i + 1 < line.length) {
        ch += line[i + 1];
        i++;
      }
      var size = encoder.encode(ch).length;
      if (currentBytes + size > limit) {
        out.push(current);
        current = "";
        currentBytes = 0;
      }
      current += ch;
      currentBytes += size;
    }
    out.push(current);
    return out.join("\r\n ");
  }

  function utcStamp(date) {
    return date.getUTCFullYear() + pad(date.getUTCMonth() + 1) + pad(date.getUTCDate()) +
      "T" + pad(date.getUTCHours()) + pad(date.getUTCMinutes()) + pad(date.getUTCSeconds()) + "Z";
  }

  // 端末の地域設定で解釈される「浮動時刻」。時差の指定が要らず、扱いを間違えにくい
  function floatingStamp(dateStr, timeStr) {
    var t = (timeStr || "09:00").split(":");
    return dateStr.replace(/-/g, "") + "T" + pad(Number(t[0])) + pad(Number(t[1] || 0)) + "00";
  }

  function addMinutes(dateStr, timeStr, minutes) {
    var d = dateStr.split("-").map(Number);
    var t = (timeStr || "09:00").split(":").map(Number);
    var dt = new Date(d[0], d[1] - 1, d[2], t[0], t[1] || 0);
    dt.setMinutes(dt.getMinutes() + minutes);
    return floatingStamp(
      dt.getFullYear() + "-" + pad(dt.getMonth() + 1) + "-" + pad(dt.getDate()),
      pad(dt.getHours()) + ":" + pad(dt.getMinutes())
    );
  }

  function alarmTrigger(minutesBefore) {
    if (!minutesBefore) return "TRIGGER:PT0S";
    if (minutesBefore % 1440 === 0) return "TRIGGER:-P" + (minutesBefore / 1440) + "D";
    if (minutesBefore % 60 === 0) return "TRIGGER:-PT" + (minutesBefore / 60) + "H";
    return "TRIGGER:-PT" + minutesBefore + "M";
  }

  /**
   * 予定ファイルの中身を作る。
   *
   * events: [{
   *   uid: 端末をまたいで同じ予定と分かる識別子（同じUIDで読み込み直すと更新される）
   *   title: 件名
   *   date: "YYYY-MM-DD"（期限の日）
   *   time: "HH:MM"（省略時は09:00）
   *   durationMinutes: 予定の長さ（省略時は30分）
   *   description / location: 任意
   *   alarms: 何分前に鳴らすかの配列。既定は [1440, 0]（前日の同時刻と当日）
   *   sequence: 同じUIDで作り直した回数。増やすとカレンダー側が更新と判断する
   * }]
   */
  function build(events, options) {
    var opts = options || {};
    var name = opts.calendarName || "期限";
    var now = new Date();
    var lines = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//myproject//日常アプリ//JA",
      "CALSCALE:GREGORIAN",
      "METHOD:PUBLISH",
      "X-WR-CALNAME:" + escapeText(name)
    ];

    events.forEach(function (ev) {
      var alarms = ev.alarms || [1440, 0];
      lines.push("BEGIN:VEVENT");
      lines.push("UID:" + escapeText(ev.uid));
      lines.push("DTSTAMP:" + utcStamp(now));
      lines.push("SEQUENCE:" + (ev.sequence || 0));
      lines.push("DTSTART:" + floatingStamp(ev.date, ev.time));
      lines.push("DTEND:" + addMinutes(ev.date, ev.time, ev.durationMinutes || 30));
      lines.push("SUMMARY:" + escapeText(ev.title));
      if (ev.description) lines.push("DESCRIPTION:" + escapeText(ev.description));
      if (ev.location) lines.push("LOCATION:" + escapeText(ev.location));
      alarms.forEach(function (minutes) {
        lines.push("BEGIN:VALARM");
        lines.push("ACTION:DISPLAY");
        lines.push("DESCRIPTION:" + escapeText(ev.title));
        lines.push(alarmTrigger(minutes));
        lines.push("END:VALARM");
      });
      lines.push("END:VEVENT");
    });

    lines.push("END:VCALENDAR");
    return lines.map(foldLine).join("\r\n") + "\r\n";
  }

  /**
   * 作った予定ファイルを端末に渡す。
   * iPhone では共有シート（「カレンダーに追加」が出る）を優先し、
   * 使えない環境ではファイルの保存に切り替える。
   * 戻り値は "shared" / "downloaded" / "cancelled"。
   */
  function deliver(text, filename) {
    var blob = new Blob([text], { type: "text/calendar;charset=utf-8" });
    if (global.navigator && navigator.canShare && typeof File === "function") {
      var file;
      try {
        file = new File([blob], filename, { type: "text/calendar" });
      } catch (e) {
        file = null;
      }
      if (file && navigator.canShare({ files: [file] })) {
        return navigator.share({ files: [file] }).then(function () {
          return "shared";
        }, function (err) {
          // 利用者が閉じた場合は何もしない。それ以外は保存に切り替える
          if (err && err.name === "AbortError") return "cancelled";
          return download(blob, filename);
        });
      }
    }
    return Promise.resolve(download(blob, filename));
  }

  function download(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    return "downloaded";
  }

  function filename(prefix) {
    var d = new Date();
    return prefix + "-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + ".ics";
  }

  global.ICS = {
    build: build,
    deliver: deliver,
    filename: filename,
    escapeText: escapeText,
    foldLine: foldLine
  };
})(typeof window !== "undefined" ? window : this);
