/*
 * 通知文から電話番号・メールアドレス・URLを取り出す。
 * 取り出した内容は、必ず人が確認してから使う前提で作っている。
 */
(function (global) {
  "use strict";

  function normalize(text) {
    return String(text == null ? "" : text)
      .replace(/[０-９]/g, function (c) {
        return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
      })
      // 長音の「ー」は、数字にはさまれたとき（電話番号の区切り）だけハイフンにする
      .replace(/(\d)\s*[－‐ー―−]\s*(?=\d)/g, "$1-");
  }

  function uniqueMatches(text, pattern, format) {
    var found = [];
    var seen = Object.create(null);
    var match;
    while ((match = pattern.exec(text)) !== null) {
      var value = format ? format(match[0]) : match[0];
      if (!seen[value]) {
        seen[value] = true;
        found.push(value);
      }
    }
    return found;
  }

  function findPhones(text) {
    var pattern = /内線\s*\d{2,5}|0\d{1,4}-\d{1,4}-\d{3,4}|0\d{9,10}/g;
    var found = [];
    var seen = Object.create(null);
    var match;

    while ((match = pattern.exec(text)) !== null) {
      var raw = match[0];
      if (raw.charAt(0) === "0") {
        var before = text.charAt(match.index - 1);
        var after = text.charAt(match.index + raw.length);
        if (/\d/.test(before) || /\d/.test(after)) continue;
      }
      var value = raw.indexOf("内線") === 0
        ? "内線 " + raw.replace(/^内線\s*/, "")
        : raw;
      if (!seen[value]) {
        seen[value] = true;
        found.push(value);
      }
    }
    return found;
  }

  function find(text) {
    var normalized = normalize(text);
    return {
      phones: findPhones(normalized),
      emails: uniqueMatches(normalized, /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi),
      urls: uniqueMatches(normalized, /https?:\/\/[^\s<>"']+/gi)
    };
  }

  function noteLine(found) {
    var parts = [];
    var phones = found && Array.isArray(found.phones) ? found.phones : [];
    var emails = found && Array.isArray(found.emails) ? found.emails : [];
    if (phones.length) parts.push("電話 " + phones.join(" / "));
    if (emails.length) parts.push("メール " + emails.join(" / "));
    return parts.length ? "問い合わせ: " + parts.join(" / ") : "";
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/\r\n|\r|\n/g, "<br>");
  }

  function linkify(text) {
    var normalized = normalize(text);
    var pattern = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|0\d{1,4}-\d{1,4}-\d{3,4}|0\d{9,10}/gi;
    var html = "";
    var last = 0;
    var match;

    while ((match = pattern.exec(normalized)) !== null) {
      var value = match[0];
      var before = normalized.charAt(match.index - 1);
      var after = normalized.charAt(match.index + value.length);
      if (value.charAt(0) === "0" && (/\d/.test(before) || /\d/.test(after))) continue;

      html += escapeHtml(normalized.slice(last, match.index));
      if (value.indexOf("@") !== -1) {
        html += '<a href="mailto:' + escapeHtml(value) + '">' + escapeHtml(value) + "</a>";
      } else {
        html += '<a href="tel:' + value.replace(/\D/g, "") + '">' + escapeHtml(value) + "</a>";
      }
      last = match.index + value.length;
    }
    return html + escapeHtml(normalized.slice(last));
  }

  global.Contacts = {
    find: find,
    noteLine: noteLine,
    linkify: linkify
  };
})(typeof window !== "undefined" ? window : this);
