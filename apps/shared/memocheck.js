/* メモ本文の行頭にあるチェック印を読み取り、安全に書き換える。 */
(function (global) {
  "use strict";

  function parseLine(line, index) {
    var raw = String(line == null ? "" : line);
    var checked = /^(?:-\s*\[[xX]\]|[☑✓✔■])\s*(.*)$/.exec(raw);
    if (checked) return { index: index, raw: raw, text: checked[1], marked: true, checked: true };
    var unchecked = /^(?:-\s*\[\s\]|[□・*\-])\s*(.*)$/.exec(raw);
    if (unchecked) return { index: index, raw: raw, text: unchecked[1], marked: true, checked: false };
    return { index: index, raw: raw, text: raw, marked: false, checked: false };
  }

  function parse(text) {
    return String(text == null ? "" : text).split(/\r\n|\n|\r/).map(function (line, index) {
      return parseLine(line, index);
    });
  }

  function mapLines(text, change) {
    var parts = String(text == null ? "" : text).split(/(\r\n|\n|\r)/);
    for (var index = 0, lineIndex = 0; index < parts.length; index += 2, lineIndex++) {
      parts[index] = change(parts[index], lineIndex);
    }
    return parts.join("");
  }

  function toggle(text, lineIndex, checked) {
    return mapLines(text, function (line, index) {
      if (index !== Number(lineIndex)) return line;
      var parsed = parseLine(line, index);
      if (!parsed.marked) return line;
      return (checked ? "☑ " : "□ ") + parsed.text;
    });
  }

  function strip(text) {
    return mapLines(text, function (line, index) {
      var parsed = parseLine(line, index);
      return parsed.marked ? parsed.text : line;
    });
  }

  global.MemoCheck = { parse: parse, toggle: toggle, strip: strip };
})(typeof window !== "undefined" ? window : this);
