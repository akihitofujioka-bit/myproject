/* TODO の小さな項目を安全に変換・検査する純粋関数。 */
(function (global) {
  "use strict";

  function cleanText(value) {
    return String(value == null ? "" : value).trim().slice(0, 60);
  }

  function normalize(value) {
    if (!Array.isArray(value)) return [];
    return value.filter(function (item) {
      return item && typeof item === "object" && typeof item.id === "string" && !!item.id &&
        typeof item.text === "string" && !!item.text.trim() && item.text.trim().length <= 60 &&
        typeof item.done === "boolean";
    }).slice(0, 30).map(function (item) {
      return { id: item.id, text: item.text.trim(), done: item.done };
    });
  }

  function toLines(checklist) {
    return normalize(checklist).map(function (item) { return item.text; }).join("\n");
  }

  function fromLines(text, previous, makeId) {
    var old = normalize(previous);
    var used = {};
    return String(text == null ? "" : text).split(/\r\n|\n|\r/).map(cleanText)
      .filter(function (line) { return !!line; }).slice(0, 30).map(function (line) {
        var found = null;
        for (var i = 0; i < old.length; i++) {
          if (!used[i] && old[i].text === line) { found = old[i]; used[i] = true; break; }
        }
        return found ? { id: found.id, text: line, done: found.done } : {
          id: String(makeId()), text: line, done: false
        };
      });
  }

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

  function parseAI(text) {
    var json = firstObject(text);
    var value;
    if (!json) return null;
    try { value = JSON.parse(json); } catch (e) { return null; }
    if (!value || Array.isArray(value) || typeof value !== "object" || !Array.isArray(value.items)) return null;
    var seen = {};
    var items = [];
    for (var i = 0; i < value.items.length && items.length < 15; i++) {
      if (typeof value.items[i] !== "string") continue;
      var item = cleanText(value.items[i]);
      if (!item || seen[item]) continue;
      seen[item] = true;
      items.push(item);
    }
    return items;
  }

  function fromMemo(text, parsed, makeId) {
    var lines = Array.isArray(parsed) ? parsed : [];
    var marked = lines.filter(function (line) { return line && line.marked && cleanText(line.text); });
    var titleLine = lines.find(function (line) {
      return line && !line.marked && cleanText(line.text);
    });
    var fallback = String(text == null ? "" : text).split(/\r\n|\n|\r/).map(cleanText)
      .filter(function (line) { return !!line; })[0] || "";
    // 印の行が 1 つだけで件名にする行が無いときは、その行を件名にする（小さな項目にはしない）
    if (!titleLine && marked.length === 1) return { title: cleanText(marked[0].text).slice(0, 40), checklist: [] };
    return {
      title: cleanText(titleLine ? titleLine.text : (marked.length ? "" : fallback)).slice(0, 40),
      checklist: marked.slice(0, 30).map(function (line) {
        return { id: String(makeId()), text: cleanText(line.text), done: line.checked === true };
      })
    };
  }

  global.TodoChecklist = {
    normalize: normalize,
    toLines: toLines,
    fromLines: fromLines,
    firstObject: firstObject,
    parseAI: parseAI,
    fromMemo: fromMemo
  };
})(typeof window !== "undefined" ? window : this);
