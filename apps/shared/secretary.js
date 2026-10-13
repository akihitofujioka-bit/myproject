/*
 * 質問から予定の期間を決め、AI 秘書へ渡す一覧・空き時間・下書きを整える。
 * AI や保存先には触れず、決まった規則だけで処理する。
 */
(function (global) {
  "use strict";

  var DAY_NAMES = ["日", "月", "火", "水", "木", "金", "土"];
  var DAY_MS = 24 * 60 * 60 * 1000;

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function parseDate(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
    if (!match) return null;
    var year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    var date = new Date(year, month - 1, day, 12);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
    return date;
  }

  function ymd(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function addDays(date, amount) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate() + amount, 12);
  }

  function validDate(year, month, day) {
    return Boolean(parseDate(year + "-" + pad(month) + "-" + pad(day)));
  }

  // 年のない月日は、今日以降で最初に来る同じ月日にする。
  function closestMonthDay(month, day, today) {
    for (var add = 0; add <= 8; add++) {
      var year = today.getFullYear() + add;
      if (!validDate(year, month, day)) continue;
      var candidate = new Date(year, month - 1, day, 12);
      if (candidate >= today) return candidate;
    }
    return null;
  }

  // 日だけの指定は、今日以降で最初に来るその日付にする。
  function closestDay(day, today) {
    for (var add = 0; add <= 24; add++) {
      var candidate = new Date(today.getFullYear(), today.getMonth() + add, day, 12);
      if (candidate.getDate() === day && candidate >= today) return candidate;
    }
    return null;
  }

  function oneDay(date) {
    var value = ymd(date);
    return { from: value, to: value, found: true };
  }

  function range(question, todayValue) {
    var today = parseDate(todayValue);
    if (!today) return { from: "", to: "", found: false };
    var text = String(question || "").replace(/[０-９]/g, function (character) {
      return String.fromCharCode(character.charCodeAt(0) - 0xFEE0);
    });
    var match;

    match = text.match(/来週\s*[^\s、。,.!?！？]{0,2}?\s*([日月火水木金土])曜/);
    if (match) {
      var nextMonday = addDays(today, 7 - ((today.getDay() + 6) % 7));
      var wanted = DAY_NAMES.indexOf(match[1]);
      return oneDay(addDays(nextMonday, (wanted + 6) % 7));
    }

    match = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
    if (match) {
      var monthDay = closestMonthDay(Number(match[1]), Number(match[2]), today);
      if (monthDay) return oneDay(monthDay);
    }

    match = text.match(/(^|[^月\d])(\d{1,2})\s*日(?!間|後|以内|前|ほど)/);
    if (match) {
      var dayOnly = closestDay(Number(match[2]), today);
      if (dayOnly) return oneDay(dayOnly);
    }

    if (text.indexOf("あさって") >= 0 || text.indexOf("明後日") >= 0) return oneDay(addDays(today, 2));
    if (text.indexOf("明日") >= 0) return oneDay(addDays(today, 1));
    if (text.indexOf("今日") >= 0) return oneDay(today);

    match = text.match(/([日月火水木金土])曜/);
    if (match) {
      var dayNumber = DAY_NAMES.indexOf(match[1]);
      return oneDay(addDays(today, (dayNumber - today.getDay() + 7) % 7));
    }

    var monday = addDays(today, -((today.getDay() + 6) % 7));
    if (text.indexOf("来週") >= 0) {
      var nextWeek = addDays(monday, 7);
      return { from: ymd(nextWeek), to: ymd(addDays(nextWeek, 6)), found: true };
    }
    if (text.indexOf("今週") >= 0) {
      return { from: ymd(monday), to: ymd(addDays(monday, 6)), found: true };
    }
    if (text.indexOf("来月") >= 0) {
      var nextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1, 12);
      return {
        from: ymd(nextMonth),
        to: ymd(new Date(nextMonth.getFullYear(), nextMonth.getMonth() + 1, 0, 12)),
        found: true
      };
    }
    if (text.indexOf("今月") >= 0) {
      return {
        from: ymd(new Date(today.getFullYear(), today.getMonth(), 1, 12)),
        to: ymd(new Date(today.getFullYear(), today.getMonth() + 1, 0, 12)),
        found: true
      };
    }
    return { from: ymd(today), to: ymd(addDays(today, 13)), found: false };
  }

  function displayDate(value) {
    var date = parseDate(value);
    return date ? (date.getMonth() + 1) + "/" + date.getDate() + "(" + DAY_NAMES[date.getDay()] + ")" : "";
  }

  function cleanTime(value) {
    var match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return "";
    return Number(match[1]) + ":" + match[2];
  }

  function draftTime(value) {
    var match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return "";
    return pad(Number(match[1])) + ":" + match[2];
  }

  function sortableTime(value) {
    var match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    return match ? pad(Number(match[1])) + ":" + match[2] : "";
  }

  function inRange(date, selectedRange) {
    return date && date >= String(selectedRange.from || "") && date <= String(selectedRange.to || "");
  }

  function lines(selectedRange, data, helpers) {
    data = data || {};
    helpers = helpers || {};
    var rows = [];
    var linkedIds = {};

    (data.items || []).forEach(function (item, index) {
      if (!item || !inRange(String(item.dueOn || ""), selectedRange || {})) return;
      var start = helpers.timeOf ? helpers.timeOf(item) : item.time;
      var end = helpers.endTimeOf ? helpers.endTimeOf(item) : item.endTime;
      if (item.calEventId) linkedIds[String(item.calEventId)] = true;
      rows.push({
        date: String(item.dueOn),
        start: cleanTime(start),
        end: cleanTime(end),
        title: String(item.title || "").trim(),
        place: String(item.dest || "").trim(),
        todo: false,
        order: index
      });
    });

    (data.calendarEvents || []).forEach(function (event, index) {
      if (!event || linkedIds[String(event.id || "")]) return;
      var date = parseDate(String(event.date || "")) ? String(event.date) : "";
      if (!inRange(date, selectedRange || {})) return;
      rows.push({
        date: date,
        start: cleanTime(event.startTime),
        end: cleanTime(event.endTime),
        title: String(event.title || "").trim(),
        place: String(event.place || "").trim(),
        todo: false,
        order: 100000 + index
      });
    });

    (data.todos || []).forEach(function (todo, index) {
      if (!todo || !inRange(String(todo.dueOn || ""), selectedRange || {})) return;
      rows.push({
        date: String(todo.dueOn),
        start: "",
        end: "",
        title: String(todo.title || "").trim(),
        place: "",
        todo: true,
        order: 200000 + index
      });
    });

    rows.sort(function (a, b) {
      if (a.date !== b.date) return a.date.localeCompare(b.date);
      var aTime = sortableTime(a.start), bTime = sortableTime(b.start);
      if (Boolean(aTime) !== Boolean(bTime)) return aTime ? -1 : 1;
      if (aTime !== bTime) return aTime.localeCompare(bTime);
      return a.order - b.order;
    });

    var cut = rows.length > 60;
    rows = rows.slice(0, 60);
    return {
      text: rows.map(function (row) {
        var parts = [displayDate(row.date)];
        if (row.todo) parts.push("期限");
        else if (row.start) parts.push(row.start + (row.end ? "-" + row.end : ""));
        parts.push(row.title + (row.todo ? "（やること）" : ""));
        if (row.place) parts.push("@" + row.place);
        return parts.filter(Boolean).join(" ");
      }).join("\n"),
      count: rows.length,
      cut: cut
    };
  }

  function wantsFree(question) {
    var text = String(question || "");
    return text.indexOf("空き") >= 0 || text.indexOf("空いて") >= 0;
  }

  function minutes(value) {
    var match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
    if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return null;
    return Number(match[1]) * 60 + Number(match[2]);
  }

  function clock(value) {
    return Math.floor(value / 60) + ":" + pad(value % 60);
  }

  function freeSlots(selectedRange, busy) {
    var from = parseDate(selectedRange && selectedRange.from);
    var to = parseDate(selectedRange && selectedRange.to);
    if (!from || !to || from > to) return "";
    var output = [];
    var days = Math.round((Date.UTC(to.getFullYear(), to.getMonth(), to.getDate()) -
      Date.UTC(from.getFullYear(), from.getMonth(), from.getDate())) / DAY_MS);

    for (var offset = 0; offset <= days; offset++) {
      var date = addDays(from, offset);
      var dateValue = ymd(date);
      var sameDay = (busy || []).filter(function (entry) { return entry && entry.date === dateValue; });
      if (sameDay.some(function (entry) { return entry.allDay; })) {
        output.push(displayDate(dateValue) + " 終日の予定あり");
        continue;
      }
      var periods = sameDay.map(function (entry) {
        var start = minutes(entry.start), end = minutes(entry.end);
        if (start === null || end === null || end <= start) return null;
        start = Math.max(start, 8 * 60 + 30);
        end = Math.min(end, 17 * 60 + 15);
        return end > start ? [start, end] : null;
      }).filter(Boolean).sort(function (a, b) { return a[0] - b[0]; });
      var merged = [];
      periods.forEach(function (period) {
        var last = merged[merged.length - 1];
        if (last && period[0] <= last[1]) last[1] = Math.max(last[1], period[1]);
        else merged.push(period.slice());
      });
      var free = [], cursor = 8 * 60 + 30;
      merged.forEach(function (period) {
        if (cursor < period[0]) free.push(clock(cursor) + "-" + clock(period[0]));
        cursor = Math.max(cursor, period[1]);
      });
      if (cursor < 17 * 60 + 15) free.push(clock(cursor) + "-17:15");
      output.push(displayDate(dateValue) + " 空き" + (free.length ? " " + free.join(", ") : "なし"));
    }
    return output.join("\n");
  }

  function wantsDraft(question) {
    var text = String(question || "");
    return ["入れて", "登録", "追加", "やること", "忘れないように", "予定にして"].some(function (word) {
      return text.indexOf(word) >= 0;
    });
  }

  function draftInstructions(today) {
    return "今日は " + String(today || "") + " です。質問から登録用の下書きを作り、説明や囲みを付けず次の形のJSONだけを返してください。" +
      '{"kind":"event|todo","title":"…","date":"YYYY-MM-DD","start":"HH:mm","end":"HH:mm","place":"…","memo":"…"}';
  }

  function firstObject(text) {
    text = String(text || "");
    for (var start = text.indexOf("{"); start >= 0; start = text.indexOf("{", start + 1)) {
      var depth = 0, quoted = false, escaped = false;
      for (var index = start; index < text.length; index++) {
        var character = text[index];
        if (quoted) {
          if (escaped) escaped = false;
          else if (character === "\\") escaped = true;
          else if (character === '"') quoted = false;
        } else if (character === '"') quoted = true;
        else if (character === "{") depth++;
        else if (character === "}" && --depth === 0) {
          try {
            var value = JSON.parse(text.slice(start, index + 1));
            if (value && typeof value === "object" && !Array.isArray(value)) return value;
          } catch (error) {
            break;
          }
        }
      }
    }
    return null;
  }

  function stringValue(value) {
    return value == null ? "" : String(value);
  }

  function checkDraft(aiText, question, today) {
    var value = firstObject(aiText);
    if (!value) return { ok: false };
    var selected = range(question, today);
    var date = parseDate(stringValue(value.date)) ? stringValue(value.date) : "";
    if (selected.found && selected.from === selected.to) date = selected.from;
    var title = stringValue(value.title).trim() || String(question || "").trim().slice(0, 30);
    var start = draftTime(value.start);
    var end = draftTime(value.end);
    if (start && end && minutes(end) < minutes(start)) end = "";
    return {
      ok: true,
      draft: {
        kind: value.kind === "todo" ? "todo" : "event",
        title: title,
        date: date,
        start: start,
        end: end,
        place: stringValue(value.place),
        memo: stringValue(value.memo)
      }
    };
  }

  global.Secretary = {
    range: range,
    lines: lines,
    wantsFree: wantsFree,
    freeSlots: freeSlots,
    wantsDraft: wantsDraft,
    draftInstructions: draftInstructions,
    checkDraft: checkDraft
  };
})(typeof window !== "undefined" ? window : this);
