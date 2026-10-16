/*
 * 名刺から読み取った文字を端末内 AI で項目に振り分ける。
 * AI の回答は元の文字と照合し、確認できた値だけを返す。
 */
(function (global) {
  "use strict";

  var STRING_FIELDS = ["name", "company", "department", "title", "email", "address", "url"];

  function error(code, message) {
    var value = new Error(message);
    value.code = code;
    return value;
  }

  function lineTexts(lines) {
    if (!Array.isArray(lines)) return [];
    return lines.map(function (line) {
      return typeof line === "string" ? line : (line && line.text);
    }).filter(function (text) {
      return typeof text === "string" && text.trim() !== "";
    });
  }

  function normalized(text) {
    return String(text == null ? "" : text).normalize("NFKC").replace(/[\s　]+/g, " ").trim();
  }

  function extractJSON(text) {
    var source = String(text == null ? "" : text);
    var start = source.indexOf("{");
    var depth = 0;
    var quoted = false;
    var escaped = false;
    var index;
    var character;
    if (start === -1) throw error("invalid_json", "AI の回答に JSON がありません");
    for (index = start; index < source.length; index++) {
      character = source.charAt(index);
      if (quoted) {
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === '"') quoted = false;
        continue;
      }
      if (character === '"') quoted = true;
      else if (character === "{") depth++;
      else if (character === "}") {
        depth--;
        if (depth === 0) {
          try {
            return JSON.parse(source.slice(start, index + 1));
          } catch (parseError) {
            throw error("invalid_json", "AI の JSON を読めません");
          }
        }
      }
    }
    throw error("invalid_json", "AI の JSON が途中で終わっています");
  }

  function appearsInSource(value, source) {
    var checked = normalized(value).toLowerCase();
    return checked !== "" && source.indexOf(checked) !== -1;
  }

  function validPhone(value) {
    var checked = normalized(value);
    return /^\+?[0-9](?:[0-9 ()-]{4,}[0-9])$/.test(checked);
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized(value));
  }

  function validURL(value) {
    return /^https?:\/\/[^\s]+$/i.test(normalized(value));
  }

  function validate(value, lines) {
    var texts = lineTexts(lines);
    var source = normalized(texts.join(" ")).toLowerCase();
    var result = {
      name: "", company: "", department: "", title: "", phones: [],
      email: "", address: "", url: ""
    };
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw error("invalid_result", "AI の回答の形が正しくありません");
    }
    STRING_FIELDS.forEach(function (key) {
      var candidate = value[key];
      if (typeof candidate !== "string" || candidate === "") return;
      if (!appearsInSource(candidate, source)) return;
      if (key === "email" && !validEmail(candidate)) return;
      if (key === "url" && !validURL(candidate)) return;
      result[key] = normalized(candidate);
    });
    if (Array.isArray(value.phones)) {
      value.phones.forEach(function (phone) {
        var candidate;
        if (typeof phone !== "string") return;
        candidate = normalized(phone);
        if (!validPhone(candidate) || !appearsInSource(candidate, source)) return;
        if (result.phones.indexOf(candidate) === -1) result.phones.push(candidate);
      });
    }
    return result;
  }

  function withTimeout(request, milliseconds) {
    return new Promise(function (resolve, reject) {
      var finished = false;
      var timer = setTimeout(function () {
        if (finished) return;
        finished = true;
        reject(error("timeout", "端末内 AI が時間内に答えませんでした"));
      }, milliseconds);
      Promise.resolve(request).then(function (value) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        resolve(value);
      }, function (reason) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        reject(reason);
      });
    });
  }

  function suggest(lines) {
    var texts = lineTexts(lines);
    var ai = global.OnDeviceAI;
    var request;
    if (!texts.length) return Promise.reject(error("no_text", "読み取った文字がありません"));
    if (!ai || typeof ai.status !== "function" || typeof ai.respond !== "function") {
      return Promise.reject(error("unavailable", "端末内 AI を使えません"));
    }
    request = Promise.resolve().then(function () {
      return ai.status();
    }).then(function (status) {
      if (!status || !status.available) throw error("unavailable", "端末内 AI を使えません");
      return ai.respond({
        instructions: "名刺のOCR文字だけを、氏名・会社・部署・役職・電話・メール・住所・URLに分類します。推測や補完をせず、文字に無い値は空にしてください。JSONだけで答えてください。",
        prompt: "次の各行を分類してください。形式は {\"name\":\"\",\"company\":\"\",\"department\":\"\",\"title\":\"\",\"phones\":[],\"email\":\"\",\"address\":\"\",\"url\":\"\"} です。\n\n" + texts.join("\n")
      });
    }).then(function (answer) {
      if (!answer || typeof answer.text !== "string") throw error("invalid_result", "AI の回答がありません");
      return validate(extractJSON(answer.text), texts);
    });
    return withTimeout(request, 15000);
  }

  global.MeishiAI = {
    extractJSON: extractJSON,
    validate: validate,
    suggest: suggest
  };
})(typeof window !== "undefined" ? window : this);
