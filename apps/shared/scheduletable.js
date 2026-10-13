/*
 * 行事予定表の各行から、日付・時刻・件名・場所を取り出す。
 * 取り出した内容は、必ず人が確認してから登録する前提で使う。
 */
(function (global) {
  "use strict";

  var DATE_HEADINGS = ["日付", "月日", "日", "開催日"];
  var TIME_HEADINGS = ["時間", "時刻", "開始"];
  var TITLE_HEADINGS = ["行事", "件名", "内容", "会議名", "名称"];
  var PLACE_HEADINGS = ["場所", "会場"];
  var VERTICAL_HEADINGS = ["日時", "日付", "月日", "日", "開催日", "時間", "時刻", "開始", "行事", "件名", "内容", "会議名", "名称", "場所", "会場"];

  function normalize(text) {
    return String(text == null ? "" : text)
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/[（]/g, "(").replace(/[）]/g, ")")
      .replace(/[：]/g, ":").replace(/[／]/g, "/")
      .replace(/[～〜]/g, "~")
      .replace(/[　]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function validDate(year, month, day) {
    if (!(year >= 1 && year <= 9999 && month >= 1 && month <= 12 && day >= 1 && day <= 31)) return false;
    var date = new Date(year, month - 1, day);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
  }

  function baseDate(today) {
    var match = normalize(today).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match && validDate(Number(match[1]), Number(match[2]), Number(match[3]))) {
      return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    }
    var now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  }

  function findDate(text, today) {
    var value = normalize(text);
    var match = value.match(/(?:^|[^\d])(\d{4})\s*[-\/]\s*(\d{1,2})\s*[-\/]\s*(\d{1,2})(?!\d)/);
    if (match) {
      var year = Number(match[1]);
      var month = Number(match[2]);
      var day = Number(match[3]);
      return validDate(year, month, day) ? year + "-" + pad(month) + "-" + pad(day) : null;
    }

    match = value.match(/(?:^|[^\d\/])(\d{1,2})\s*\/\s*(\d{1,2})(?!\s*\/|\d)/) ||
      value.match(/(?:^|[^\d])(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
    if (!match) return null;

    var base = baseDate(today);
    var monthWithoutYear = Number(match[1]);
    var dayWithoutYear = Number(match[2]);
    for (var add = 0; add <= 8; add++) {
      var candidateYear = base.getFullYear() + add;
      if (!validDate(candidateYear, monthWithoutYear, dayWithoutYear)) continue;
      var candidate = new Date(candidateYear, monthWithoutYear - 1, dayWithoutYear);
      if (candidate >= base) return candidateYear + "-" + pad(monthWithoutYear) + "-" + pad(dayWithoutYear);
    }
    return null;
  }

  function toTime(hour, minute) {
    var h = Number(hour);
    var m = Number(minute || 0);
    if (!(h >= 0 && h <= 23 && m >= 0 && m <= 59)) return null;
    return pad(h) + ":" + pad(m);
  }

  function findTimes(text) {
    var value = normalize(text);
    var range = value.match(/(\d{1,2})\s*:\s*(\d{2})\s*~\s*(\d{1,2})\s*:\s*(\d{2})/);
    if (range) return { start: toTime(range[1], range[2]), end: toTime(range[3], range[4]) };

    var japaneseRange = value.match(/(\d{1,2})\s*時\s*(\d{1,2})?\s*分?\s*~\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分?/);
    if (japaneseRange) {
      return { start: toTime(japaneseRange[1], japaneseRange[2]), end: toTime(japaneseRange[3], japaneseRange[4]) };
    }

    var colon = value.match(/(?:^|[^\d])(\d{1,2})\s*:\s*(\d{2})(?!\d)/);
    if (colon) return { start: toTime(colon[1], colon[2]), end: null };
    var japanese = value.match(/(?:^|[^\d])(\d{1,2})\s*時\s*(\d{1,2})?\s*分?/);
    if (japanese) return { start: toTime(japanese[1], japanese[2]), end: null };
    return { start: null, end: null };
  }

  function headingIndex(row, headings) {
    for (var i = 0; i < row.length; i++) {
      if (headings.indexOf(normalize(row[i]).replace(/\s/g, "")) !== -1) return i;
    }
    return -1;
  }

  function isVerticalNotice(table) {
    return table.length > 0 && table.every(function (row) {
      return row.length === 2 && VERTICAL_HEADINGS.indexOf(normalize(row[0]).replace(/\s/g, "")) !== -1;
    });
  }

  function longestColumn(rows, excluded) {
    var width = rows.reduce(function (max, row) { return Math.max(max, row.length); }, 0);
    var best = -1;
    var bestLength = -1;
    for (var column = 0; column < width; column++) {
      if (excluded.indexOf(column) !== -1) continue;
      var length = rows.reduce(function (sum, row) { return sum + normalize(row[column]).length; }, 0);
      if (length > bestLength) {
        best = column;
        bestLength = length;
      }
    }
    return best;
  }

  function analyze(table, today) {
    if (!Array.isArray(table) || !table.length || isVerticalNotice(table)) return null;

    var headerRow = -1;
    var dateColumn = -1;
    for (var rowIndex = 0; rowIndex < table.length; rowIndex++) {
      var found = headingIndex(table[rowIndex], DATE_HEADINGS);
      if (found !== -1) {
        headerRow = rowIndex;
        dateColumn = found;
        break;
      }
    }

    var dataRows;
    var titleColumn = -1;
    var timeColumn = -1;
    var placeColumn = -1;
    if (headerRow !== -1) {
      var header = table[headerRow];
      titleColumn = headingIndex(header, TITLE_HEADINGS);
      timeColumn = headingIndex(header, TIME_HEADINGS);
      placeColumn = headingIndex(header, PLACE_HEADINGS);
      dataRows = table.slice(headerRow + 1);
    } else {
      dataRows = table.slice();
      var width = dataRows.reduce(function (max, row) { return Math.max(max, row.length); }, 0);
      var mostDates = 0;
      for (var column = 0; column < width; column++) {
        var count = dataRows.reduce(function (sum, row) {
          return sum + (findDate(row[column], today) ? 1 : 0);
        }, 0);
        if (count > mostDates) {
          mostDates = count;
          dateColumn = column;
        }
      }
    }

    if (dateColumn === -1) return null;
    var datedRows = dataRows.filter(function (row) { return !!findDate(row[dateColumn], today); });
    if (datedRows.length < 2) return null;

    if (titleColumn === -1) titleColumn = longestColumn(datedRows, [dateColumn, timeColumn, placeColumn]);
    return {
      rows: datedRows,
      dateColumn: dateColumn,
      titleColumn: titleColumn,
      timeColumn: timeColumn,
      placeColumn: placeColumn
    };
  }

  function isSchedule(tables) {
    return (Array.isArray(tables) ? tables : []).some(function (table) {
      return !!analyze(table);
    });
  }

  function parse(tables, today) {
    var meetings = [];
    (Array.isArray(tables) ? tables : []).forEach(function (table) {
      var info = analyze(table, today);
      if (!info) return;
      info.rows.forEach(function (row) {
        var times = info.timeColumn === -1 ? { start: null, end: null } : findTimes(row[info.timeColumn]);
        meetings.push({
          title: info.titleColumn === -1 ? "" : normalize(row[info.titleColumn]),
          date: findDate(row[info.dateColumn], today),
          dateConfidence: null,
          startTime: times.start || "",
          endTime: times.end || "",
          place: info.placeColumn === -1 ? "" : normalize(row[info.placeColumn]),
          social: { has: false, fee: null },
          rows: [row.map(function (cell) { return String(cell == null ? "" : cell); }).join(" ")],
          source: "file"
        });
      });
    });
    return meetings;
  }

  global.ScheduleTable = {
    isSchedule: isSchedule,
    parse: parse
  };
})(typeof window !== "undefined" ? window : this);
