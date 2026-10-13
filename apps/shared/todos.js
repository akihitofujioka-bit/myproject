/*
 * 通知の文章からやること候補を見つけ、確認後に書類トラッカーへ足す。
 * 読めない保存データは上書きせず、既存の項目やほかの鍵も残す。
 */
(function (global) {
  "use strict";

  var STORAGE_KEY = "docs-tracker.v1";
  var KEYWORDS = ["持参", "資料", "提出", "締切", "締め切り", "期限", "用意", "準備", "持ち物", "必要"];

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function validDate(year, month, day) {
    var date = new Date(year, month - 1, day);
    return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
  }

  // 年のない期限は、今日以降で最初に来る同じ月日にする。
  function closestDate(month, day, today) {
    var base = String(today || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!base) return "";
    var startYear = Number(base[1]);
    for (var add = 0; add <= 8; add++) {
      var year = startYear + add;
      if (!validDate(year, month, day)) continue;
      var value = year + "-" + pad(month) + "-" + pad(day);
      if (value >= today) return value;
    }
    return "";
  }

  function dueDate(sentence, today) {
    var normalized = sentence
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/／/g, "/");
    var match = normalized.match(/(?:(\d{1,2})\s*\/\s*(\d{1,2})|(\d{1,2})\s*月\s*(\d{1,2})\s*日)\s*(?:[（(][^）)]*[）)])?\s*まで/);
    return match ? closestDate(Number(match[1] || match[3]), Number(match[2] || match[4]), today) : "";
  }

  function candidates(text, eventDate, today) {
    return String(text == null ? "" : text)
      .split(/[。\r\n]+/)
      .map(function (sentence) { return sentence.replace(/^[\s・※]+|[\s・※]+$/g, ""); })
      .filter(function (sentence) {
        return sentence && KEYWORDS.some(function (keyword) { return sentence.indexOf(keyword) >= 0; });
      })
      .map(function (sentence) {
        return {
          title: sentence.slice(0, 40),
          dueOn: dueDate(sentence, today) || String(eventDate || "")
        };
      });
  }

  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function monthDay(date) {
    var match = String(date || "").match(/^\d{4}-(\d{2})-(\d{2})$/);
    return match ? Number(match[1]) + "/" + Number(match[2]) : "";
  }

  function add(storage, list) {
    var data;
    try {
      var raw = storage.getItem(STORAGE_KEY);
      data = raw ? JSON.parse(raw) : { v: 1, items: [], calIds: {} };
    } catch (e) {
      return { ok: false, added: 0 };
    }

    if (!data || typeof data !== "object" || Array.isArray(data) || !Array.isArray(data.items)) {
      return { ok: false, added: 0 };
    }

    var entries = (list || []).filter(function (item) {
      return item && String(item.title || "").trim();
    });
    var now = new Date().toISOString();
    entries.forEach(function (item) {
      data.items.push({
        id: uid(),
        title: String(item.title).trim(),
        kind: "やること",
        dest: "",
        dueOn: String(item.dueOn || ""),
        status: "未着手",
        priority: "中",
        note: "予定: " + String(item.scheduleTitle || "") + "（" + monthDay(item.scheduleDate) + "）",
        createdAt: now,
        doneAt: "",
        icsSeq: 0,
        planKey: "",
        scheduleId: String(item.scheduleId || "")
      });
    });

    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      return { ok: false, added: 0 };
    }
    return { ok: true, added: entries.length };
  }

  global.Todos = { KEYWORDS: KEYWORDS, candidates: candidates, add: add };
})(typeof window !== "undefined" ? window : this);
