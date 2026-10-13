/*
 * 予定の重複・移動時間不足・通知に書かれた曜日の食い違いを見つける。
 * 予定は端末内だけで比較し、外部には送らない。
 */
(function (global) {
  "use strict";

  var TRAVEL_MINUTES = 15;
  var WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

  function toMinutes(time) {
    var m = String(time || "").match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    var hour = Number(m[1]);
    var minute = Number(m[2]);
    if (hour > 23 || minute > 59) return null;
    return hour * 60 + minute;
  }

  function endMinutes(item) {
    var start = toMinutes(item.start);
    if (start == null) return null;
    var end = toMinutes(item.end);
    return end == null ? start + 60 : end;
  }

  function identity(item) {
    return item.id + "@" + item.date + "T" + item.start;
  }

  function pairKey(type, a, b) {
    return type + ":" + [identity(a), identity(b)].sort().join("|");
  }

  function compareItems(a, b) {
    return String(a.date).localeCompare(String(b.date)) ||
      toMinutes(a.start) - toMinutes(b.start) ||
      String(a.id).localeCompare(String(b.id));
  }

  function targetFor(a, b) {
    if (a._new && !b._new) return { item: a, other: b };
    if (b._new && !a._new) return { item: b, other: a };
    return { item: b, other: a };
  }

  function overlapHint(a, b) {
    var aStart = toMinutes(a.start);
    var bStart = toMinutes(b.start);
    var aEnd = endMinutes(a);
    var bEnd = endMinutes(b);
    if (aStart == null || bStart == null || aEnd <= bStart || bEnd <= aStart) return null;

    var target = targetFor(a, b);
    return {
      type: "overlap",
      key: pairKey("overlap", a, b),
      itemId: target.item.id,
      otherId: target.other.id,
      message: target.other.start + " の「" + target.other.title + "」と重なります"
    };
  }

  function travelHint(previous, next) {
    var gap = toMinutes(next.start) - endMinutes(previous);
    if (gap < 0 || gap >= TRAVEL_MINUTES || !previous.place || !next.place || previous.place === next.place) return null;

    var target = targetFor(previous, next);
    var message;
    if (target.item === next) {
      message = "前の予定（" + previous.title + "、" + previous.place + "）から " + gap + " 分しかありません";
    } else {
      message = "次の予定（" + next.title + "、" + next.place + "）まで " + gap + " 分しかありません";
    }
    return {
      type: "travel",
      key: pairKey("travel", previous, next),
      itemId: target.item.id,
      otherId: target.other.id,
      message: message
    };
  }

  function scheduleHints(items, newOnly) {
    var byDate = {};
    items.forEach(function (item) {
      if (toMinutes(item.start) == null) return;
      (byDate[item.date] || (byDate[item.date] = [])).push(item);
    });

    var hints = [];
    Object.keys(byDate).sort().forEach(function (date) {
      var day = byDate[date].sort(compareItems);

      // 長い予定に複数の予定が重なる場合も見落とさないよう、重複は全組合せを見る。
      for (var i = 0; i < day.length; i++) {
        for (var j = i + 1; j < day.length; j++) {
          if (newOnly && !day[i]._new && !day[j]._new) continue;
          var overlap = overlapHint(day[i], day[j]);
          if (overlap) hints.push(overlap);
        }
      }

      // 移動時間は、開始時刻の順で隣り合う予定だけを見る。
      for (var k = 1; k < day.length; k++) {
        if (newOnly && !day[k - 1]._new && !day[k]._new) continue;
        var travel = travelHint(day[k - 1], day[k]);
        if (travel) hints.push(travel);
      }
    });
    return hints;
  }

  function dateParts(value) {
    var m = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    var year = Number(m[1]);
    var month = Number(m[2]);
    var day = Number(m[3]);
    var date = new Date(Date.UTC(year, month - 1, day));
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
    return { year: year, month: month, day: day, date: date };
  }

  function weekdayHint(item) {
    var parts = dateParts(item.date);
    var text = String(item.rawText || "").replace(/[（]/g, "(").replace(/[）]/g, ")");
    if (!parts || !text) return null;

    var re = /(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*\(([日月火水木金土])(?:曜(?:日)?)?\)|(\d{1,2})\s*\/\s*(\d{1,2})\s*\(([日月火水木金土])(?:曜(?:日)?)?\)/g;
    var match;
    while ((match = re.exec(text))) {
      var month = Number(match[1] || match[4]);
      var day = Number(match[2] || match[5]);
      var written = match[3] || match[6];
      if (month !== parts.month || day !== parts.day) continue;
      var actual = WEEKDAYS[parts.date.getUTCDay()];
      if (written === actual) return null;
      return {
        type: "weekday",
        key: "weekday:" + item.id + "@" + item.date,
        itemId: item.id,
        otherId: "",
        message: month + "/" + day + " は" + actual + "曜ですが、通知には" + written + "曜とあります"
      };
    }
    return null;
  }

  function check(newItems, existingItems) {
    var fresh = (newItems || []).map(function (item) { return Object.assign({ _new: true }, item); });
    var existing = (existingItems || []).map(function (item) { return Object.assign({ _new: false }, item); });
    var hints = scheduleHints(existing.concat(fresh), true);
    fresh.forEach(function (item) {
      var hint = weekdayHint(item);
      if (hint) hints.push(hint);
    });
    return hints;
  }

  function upcoming(items, today, days) {
    var start = dateParts(today);
    if (!start) return [];
    var period = days == null ? 30 : Number(days);
    var end = new Date(start.date.getTime());
    end.setUTCDate(end.getUTCDate() + period);
    var selected = (items || []).filter(function (item) {
      var parts = dateParts(item.date);
      return parts && parts.date >= start.date && parts.date <= end;
    }).map(function (item) { return Object.assign({ _new: true }, item); });
    return scheduleHints(selected, false);
  }

  global.Suggest = {
    check: check,
    upcoming: upcoming,
    TRAVEL_MINUTES: TRAVEL_MINUTES
  };
})(typeof window !== "undefined" ? window : this);
