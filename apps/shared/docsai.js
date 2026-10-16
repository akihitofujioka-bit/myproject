/*
 * 書類の端末内 AI 提案を安全に読み取るための部品。
 * AI の回答から最初の JSON オブジェクトだけを取り出し、型と値を検査する。
 */
(function (global) {
  "use strict";

  var KINDS = ["申請", "回覧", "提出", "支払い", "やること", "その他"];

  function firstObject(text) {
    var source = String(text == null ? "" : text);
    var start = source.indexOf("{");
    if (start < 0) return "";
    var depth = 0;
    var quoted = false;
    var escaped = false;
    for (var i = start; i < source.length; i++) {
      var ch = source.charAt(i);
      if (quoted) {
        if (escaped) escaped = false;
        else if (ch === "\\") escaped = true;
        else if (ch === '"') quoted = false;
        continue;
      }
      if (ch === '"') quoted = true;
      else if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) return source.slice(start, i + 1);
      }
    }
    return "";
  }

  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var p = value.split("-").map(Number);
    var date = new Date(p[0], p[1] - 1, p[2]);
    return p[0] >= 1 && p[0] <= 9999 &&
      date.getFullYear() === p[0] && date.getMonth() === p[1] - 1 && date.getDate() === p[2];
  }

  function parse(text) {
    var json = firstObject(text);
    if (!json) return null;
    var value;
    try { value = JSON.parse(json); } catch (e) { return null; }
    if (!value || Array.isArray(value) || typeof value !== "object") return null;
    if (typeof value.title !== "string" || typeof value.dueOn !== "string" ||
        typeof value.kind !== "string" || typeof value.summary !== "string") return null;
    var title = value.title.trim();
    var dueOn = value.dueOn.trim();
    var summary = value.summary.trim();
    var sentences = summary.split(/[。！？!?]+/).filter(function (part) { return !!part.trim(); });
    if (!title || title.length > 100 || KINDS.indexOf(value.kind) < 0 ||
        (dueOn && !validDate(dueOn)) || !summary || summary.length > 400 || sentences.length > 2) return null;
    return { title: title, dueOn: dueOn, kind: value.kind, summary: summary };
  }

  global.DocsAI = {
    kinds: KINDS.slice(),
    firstObject: firstObject,
    extractFirstObject: firstObject,
    validDate: validDate,
    isValidDate: validDate,
    parse: parse,
    parseSuggestion: parse
  };
})(typeof window !== "undefined" ? window : this);
