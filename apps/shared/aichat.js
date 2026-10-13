/*
 * 秘書・壁打ち・ブレストで、端末内 AI へ渡す指示と会話を組み立てる。
 * 長すぎる場合は会話と資料を減らし、1 回だけ自動でやり直す。
 */
(function (global) {
  "use strict";

  var MODES = {
    secretary: "秘書",
    sparring: "壁打ち",
    brainstorm: "ブレスト"
  };
  var DAY_NAMES = ["日", "月", "火", "水", "木", "金", "土"];

  function weekday(today) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(today || ""));
    if (!match) return "";
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var date = new Date(year, month - 1, day, 12);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return "";
    return DAY_NAMES[date.getDay()];
  }

  function sourceText(source) {
    if (!source) return "";
    var title = String(source.title == null ? "" : source.title);
    var body = String(source.body == null ? "" : source.body);
    return "資料: " + title + "\n" + body;
  }

  function instructions(mode, options) {
    options = options || {};
    var text;
    if (mode === "secretary" || !MODES[mode]) {
      var dayName = weekday(options.today);
      text = "あなたは議員の秘書。渡した一覧だけを根拠に、短く日本語で答える。一覧に無いことは『分かりません』と言う。今日は " +
        String(options.today || "") + (dayName ? "（" + dayName + "）" : "");
      if (options.context) text += "\n一覧:\n" + String(options.context);
    } else if (mode === "sparring") {
      text = "相手の考えを深める聞き役。まず要点を 1〜2 行で言い直し、弱いところ・抜けている視点を 1〜3 個指摘し、最後に問いを 1 つ返す。結論を押しつけない";
    } else if (mode === "brainstorm") {
      text = "案をたくさん出す役。番号付きで 8〜10 個、1 案 1〜2 行。似た案は避け、意外な案も混ぜる";
    } else {
      text = "";
    }

    var attached = sourceText(options.source);
    if (attached) text += (text ? "\n" : "") + attached;
    return text;
  }

  function recent(messages, turns) {
    var count = Math.max(0, Math.floor(Number(turns) || 0) * 2);
    if (!Array.isArray(messages) || count === 0) return [];
    return messages.slice(-count);
  }

  function clip(text, limit) {
    var characters = Array.from(String(text == null ? "" : text));
    var max = Math.max(0, Math.floor(Number(limit) || 0));
    return {
      text: characters.slice(0, max).join(""),
      cut: characters.length > max
    };
  }

  function sourceNotice(cut) {
    return cut ? "資料が長いため先頭 3,000 字だけ渡しています" : "";
  }

  function clippedSource(source, limit) {
    if (!source) return null;
    return {
      title: String(source.title == null ? "" : source.title),
      body: clip(source.body, limit).text
    };
  }

  function prompt(mode, messages, question, turns) {
    var aiName = mode === "secretary" || !MODES[mode] ? "秘書" : "相手";
    function speech(name, value) {
      return name + ": " + String(value == null ? "" : value).replace(/\r?\n/g, "\n  ");
    }
    var lines = recent(messages, turns).map(function (message) {
      var name = message && message.role === "user" ? "利用者" : aiName;
      return speech(name, message && message.text != null ? message.text : "");
    });
    lines.push(speech("利用者", question));
    return lines.join("\n");
  }

  function asCodedError(error) {
    if (error instanceof Error && error.code) return error;
    var code = error && error.code ? error.code : "failed";
    var result = error instanceof Error ? error : new Error(code);
    result.code = code;
    return result;
  }

  function respond(ai, options, turns, sourceLimit, context) {
    var request = {
      instructions: instructions(options.mode, {
        today: options.today,
        context: context,
        source: clippedSource(options.source, sourceLimit)
      }),
      prompt: prompt(options.mode, options.messages, options.question, turns)
    };
    return Promise.resolve().then(function () {
      return ai.respond(request);
    });
  }

  function ask(ai, options) {
    options = options || {};
    return respond(ai, options, 6, 3000, options.context).then(function (answer) {
      return { text: String(answer && answer.text != null ? answer.text : ""), retried: false };
    }).catch(function (error) {
      var firstError = asCodedError(error);
      if (firstError.code !== "tooLong") throw firstError;
      var retryContext = typeof options.retryContext === "string" ? options.retryContext : options.context;
      return respond(ai, options, 2, 1500, retryContext).then(function (answer) {
        return { text: String(answer && answer.text != null ? answer.text : ""), retried: true };
      }).catch(function (retryError) {
        throw asCodedError(retryError);
      });
    });
  }

  function errorMessage(code) {
    if (code === "unsupported" || code === "unavailable") {
      return "この端末では端末内 AI を使えません（iOS 26 以降の Apple Intelligence 対応機が必要です）";
    }
    if (code === "oldOS") return "iOS 26 以降にすると使えます";
    if (code === "disabled") return "設定 → Apple Intelligence と Siri でオンにしてください";
    if (code === "notReady") return "AI の準備中です。しばらくしてからもう一度お試しください";
    if (code === "tooLong") return "長くなったため答えられません。新しい会話を始めてください";
    if (code === "refused" || code === "failed") return "答えを作れませんでした。言い方を変えてみてください";
    return "";
  }

  global.AIChat = {
    MODES: MODES,
    instructions: instructions,
    recent: recent,
    clip: clip,
    sourceNotice: sourceNotice,
    ask: ask,
    errorMessage: errorMessage
  };
})(typeof window !== "undefined" ? window : this);
