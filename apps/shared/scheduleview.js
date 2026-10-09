/*
 * 予定アプリの一覧と月間カレンダーで使う日付計算。
 * 画面や保存先には触れず、ブラウザを使わないテストからも呼べるようにする。
 */
(function (global) {
  "use strict";

  var DAY_MS = 24 * 60 * 60 * 1000;

  function parseYmd(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
    if (!m) return null;
    var y = Number(m[1]), month = Number(m[2]) - 1, day = Number(m[3]);
    var date = new Date(y, month, day);
    if (date.getFullYear() !== y || date.getMonth() !== month || date.getDate() !== day) return null;
    return date;
  }

  function dayNumber(date) {
    return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_MS);
  }

  function timeOf(item) {
    var direct = String((item && (item.startTime || item.time)) || "");
    var found = /^(\d{1,2}:\d{2})/.exec(direct);
    if (found) return found[1].padStart(5, "0");
    found = /(?:^|\n)\s*(\d{1,2}:\d{2})/.exec(String((item && item.note) || ""));
    return found ? found[1].padStart(5, "0") : "";
  }

  function compareItems(a, b) {
    var dateCompare = String(a.dueOn || a.date || "").localeCompare(String(b.dueOn || b.date || ""));
    if (dateCompare) return dateCompare;
    var at = timeOf(a), bt = timeOf(b);
    if (!!at !== !!bt) return at ? -1 : 1;
    if (at !== bt) return at.localeCompare(bt);
    return String(a.title || "").localeCompare(String(b.title || ""), "ja");
  }

  function groupForList(items, today) {
    var base = today && typeof today.getTime === "function" && !isNaN(today.getTime()) ? today : new Date();
    var baseDay = dayNumber(base);
    var daysToSunday = (7 - base.getDay()) % 7;
    var buckets = {
      "今日": [], "明日": [], "今週": [], "それ以降": [], "過ぎた予定": []
    };

    (items || []).forEach(function (item) {
      var date = parseYmd(item && (item.dueOn || item.date));
      if (!date) return;
      var diff = dayNumber(date) - baseDay;
      if (diff === 0) buckets["今日"].push(item);
      else if (diff === 1) buckets["明日"].push(item);
      else if (diff >= 2 && diff <= daysToSunday) buckets["今週"].push(item);
      else if (diff > daysToSunday) buckets["それ以降"].push(item);
      else if (diff >= -7) buckets["過ぎた予定"].push(item);
    });

    var labels = ["今日", "明日", "今週", "それ以降", "過ぎた予定"];
    return labels.filter(function (label) { return buckets[label].length; }).map(function (label) {
      if (label === "過ぎた予定") {
        buckets[label].sort(function (a, b) {
          var dateCompare = String(b.dueOn || b.date || "").localeCompare(String(a.dueOn || a.date || ""));
          return dateCompare || compareItems(a, b);
        });
      } else {
        buckets[label].sort(compareItems);
      }
      return { label: label, items: buckets[label] };
    });
  }

  function monthGrid(year, month) {
    var first = new Date(year, month, 1);
    var mondayOffset = (first.getDay() + 6) % 7;
    var start = new Date(year, month, 1 - mondayOffset);
    var weeks = [];
    for (var row = 0; row < 6; row++) {
      var week = [];
      for (var col = 0; col < 7; col++) {
        week.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + row * 7 + col));
      }
      weeks.push(week);
    }
    return weeks;
  }

  function itemsOn(items, ymd) {
    return (items || []).filter(function (item) {
      return String((item && (item.dueOn || item.date)) || "") === ymd;
    }).slice().sort(compareItems);
  }

  global.ScheduleView = {
    groupForList: groupForList,
    monthGrid: monthGrid,
    itemsOn: itemsOn
  };
})(typeof window !== "undefined" ? window : this);
