/*
 * 会議の開催通知から「会議名・日付・時刻・場所・懇親会の有無」を取り出す。
 *
 * 入力は文字認識の結果を行にまとめたもの（文字列の配列）。
 * 呼び出し側で Receipt.rowsFromLines(lines).map(r => r.text) を渡す。
 *
 * 取り出したものは必ず人が確認してから登録する前提で作っている。
 * 通知の書き方は役所ごと・文書ごとに違うため、確実に読み取れる前提に立たない。
 */
(function (global) {
  "use strict";

  function normalize(text) {
    return String(text == null ? "" : text)
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/[（]/g, "(").replace(/[）]/g, ")")
      .replace(/[：]/g, ":").replace(/[～〜]/g, "~")
      .replace(/[　]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function pad(n) { return String(n).padStart(2, "0"); }

  function validDate(y, m, d) {
    if (!(y >= 2000 && y <= 2100 && m >= 1 && m <= 12 && d >= 1 && d <= 31)) return false;
    var dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
  }

  /**
   * 日付を取り出す。年が書かれていない場合は、今日以降でいちばん近い年にする
   * （通知は先の予定を知らせるものなので、過ぎた日付にはしない）。
   */
  function findDate(text, today) {
    var base = today || new Date();
    var m;

    m = text.match(/(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
    if (m && validDate(+m[1], +m[2], +m[3])) return { value: +m[1] + "-" + pad(m[2]) + "-" + pad(m[3]), confidence: "high" };

    m = text.match(/(?:令和|R)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
    if (m) {
      var y = 2018 + Number(m[1]);
      if (validDate(y, +m[2], +m[3])) return { value: y + "-" + pad(m[2]) + "-" + pad(m[3]), confidence: "high" };
    }

    m = text.match(/(20\d{2})\s*[\/.\-]\s*(\d{1,2})\s*[\/.\-]\s*(\d{1,2})/);
    if (m && validDate(+m[1], +m[2], +m[3])) return { value: +m[1] + "-" + pad(m[2]) + "-" + pad(m[3]), confidence: "high" };

    // 年の書かれていない「10月15日」「10/15」。今日以降でいちばん近い年にする
    m = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/) || text.match(/(?:^|[^\d\/])(\d{1,2})\s*\/\s*(\d{1,2})(?!\d)/);
    if (m) {
      var mo = Number(m[1]), da = Number(m[2]);
      for (var add = 0; add <= 1; add++) {
        var yy = base.getFullYear() + add;
        if (!validDate(yy, mo, da)) continue;
        var cand = new Date(yy, mo - 1, da);
        var todayMidnight = new Date(base.getFullYear(), base.getMonth(), base.getDate());
        if (cand >= todayMidnight) return { value: yy + "-" + pad(mo) + "-" + pad(da), confidence: "medium" };
      }
    }
    return null;
  }

  // 「午後1時30分」「13:30」「午前10時」を 24 時間表記にする
  function toTime(hour, minute, ampm) {
    var h = Number(hour);
    var mi = Number(minute || 0);
    if (ampm === "午後" && h < 12) h += 12;
    if (ampm === "午前" && h === 12) h = 0;
    if (!(h >= 0 && h <= 23 && mi >= 0 && mi <= 59)) return null;
    return pad(h) + ":" + pad(mi);
  }

  /** 開始時刻と、書かれていれば終了時刻を取り出す。 */
  function findTimes(text) {
    var range = text.match(/(\d{1,2})\s*:\s*(\d{2})\s*~\s*(\d{1,2})\s*:\s*(\d{2})/);
    if (range) {
      return { start: toTime(range[1], range[2]), end: toTime(range[3], range[4]) };
    }
    var rangeJa = text.match(/(午前|午後)?\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分?\s*~\s*(午前|午後)?\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分?/);
    if (rangeJa) {
      return {
        start: toTime(rangeJa[2], rangeJa[3], rangeJa[1]),
        end: toTime(rangeJa[5], rangeJa[6], rangeJa[4] || rangeJa[1])
      };
    }
    var ja = text.match(/(午前|午後)\s*(\d{1,2})\s*時\s*(\d{1,2})?\s*分?/);
    if (ja) return { start: toTime(ja[2], ja[3], ja[1]), end: null };
    var hm = text.match(/(?:^|[^\d])(\d{1,2})\s*:\s*(\d{2})(?!\d)/);
    if (hm) return { start: toTime(hm[1], hm[2]), end: null };
    var jaPlain = text.match(/(\d{1,2})\s*時\s*(\d{1,2})?\s*分?/);
    if (jaPlain) return { start: toTime(jaPlain[1], jaPlain[2]), end: null };
    return { start: null, end: null };
  }

  // 「会 場」のように字の間に空白が入る書き方が多いため、空白を許す
  var PLACE_LABEL = /^(場\s*所|会\s*場|開催\s*場所|開催\s*会場)\s*[:：]?\s*/;

  /** 「場所」「会場」の行から場所を取り出す。 */
  function findPlace(rows) {
    for (var i = 0; i < rows.length; i++) {
      var t = normalize(rows[i]);
      if (!PLACE_LABEL.test(t)) continue;
      var value = t.replace(PLACE_LABEL, "").trim();
      // ラベルだけの行なら、次の行を見る
      if (!value && rows[i + 1]) value = normalize(rows[i + 1]).trim();
      if (value) return { value: value, confidence: "high" };
    }
    return null;
  }

  var SOCIAL = /懇親会|懇談会|情報交換会|意見交換会|レセプション/;
  var SOCIAL_NONE = /(懇親会|懇談会|情報交換会|意見交換会)[^。\n]{0,10}(ありません|行いません|open|無し|なし|実施しません|予定しておりません)/;

  /** 懇親会の有無と会費を取り出す。 */
  function findSocial(rows) {
    var joined = rows.map(normalize).join("\n");
    if (!SOCIAL.test(joined)) return { has: false, fee: null, stated: false };
    if (SOCIAL_NONE.test(joined)) return { has: false, fee: null, stated: true };
    var fee = joined.match(/会費\s*[:：]?\s*(\d{1,3}(?:,\d{3})*|\d+)\s*円/);
    return { has: true, fee: fee ? Number(fee[1].replace(/,/g, "")) : null, stated: true };
  }

  var TITLE_HINT = /(委員会|協議会|審議会|連絡会|総会|理事会|会議|打合せ|打ち合わせ|説明会|研修会|同盟会)/;
  var TITLE_STRIP = /(の)?(開催)?(通知|案内|ご案内|について|のお知らせ|お知らせ)\s*$/;
  var NOT_TITLE = /^(日\s*時|場\s*所|会\s*場|議\s*題|内\s*容|記|標記|なお|※|備考|出席)/;

  /** 会議名らしい行を探す。ラベルの行や本文は避ける。 */
  function findTitle(rows) {
    for (var i = 0; i < rows.length; i++) {
      var t = normalize(rows[i]);
      if (!t || NOT_TITLE.test(t)) continue;
      if (!TITLE_HINT.test(t)) continue;
      // 日付や時刻を含む行は「日時」の行なので会議名ではない
      if (/\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*:\s*\d{2}/.test(t)) continue;
      var name = t.replace(TITLE_STRIP, "").replace(/^\d+\s*[.、]?\s*/, "").trim();
      if (name.length >= 3) return { value: name, confidence: "high" };
    }
    return null;
  }

  /**
   * 1つの書類から会議を取り出す。
   * 「1 〇〇委員会」のように番号付きで複数並ぶ場合は、それぞれを分けて返す。
   */
  function parse(rows, opts) {
    var options = opts || {};
    var lines = (rows || []).map(function (r) { return String(r == null ? "" : r); });

    // 番号付きの見出しで区切れるなら、会議ごとに分ける
    var blocks = splitBlocks(lines);
    var out = blocks.map(function (block) {
      return build(block, options.today);
    }).filter(function (m) { return m.date || m.title; });

    // 何も取れなければ、全体を1件として扱う
    if (!out.length) {
      var whole = build(lines, options.today);
      if (whole.date || whole.title) out.push(whole);
    }
    return out;
  }

  // 「1 〇〇委員会」「2 〇〇委員会」のような番号付きの見出しで区切る
  function splitBlocks(lines) {
    var heads = [];
    lines.forEach(function (line, i) {
      var t = normalize(line);
      if (/^\d+\s+\S/.test(t) && TITLE_HINT.test(t) && !/\d{1,2}\s*月\s*\d{1,2}\s*日/.test(t)) heads.push(i);
    });
    if (heads.length < 2) return [lines];
    return heads.map(function (start, idx) {
      var end = idx + 1 < heads.length ? heads[idx + 1] : lines.length;
      return lines.slice(start, end);
    });
  }

  function build(lines, today) {
    var joined = lines.map(normalize).join("\n");
    // 日時は「日時」の行を優先し、無ければ全体から探す
    var dateLine = lines.filter(function (l) { return /^(日\s*時|開催日|期日)/.test(normalize(l)); })[0];
    var target = dateLine ? normalize(dateLine) : joined;
    var date = findDate(target, today) || findDate(joined, today);
    var times = findTimes(dateLine ? normalize(dateLine) : joined);
    var title = findTitle(lines);
    var place = findPlace(lines);
    var social = findSocial(lines);
    return {
      title: title ? title.value : "",
      date: date ? date.value : "",
      dateConfidence: date ? date.confidence : null,
      startTime: times.start || "",
      endTime: times.end || "",
      place: place ? place.value : "",
      social: social,
      rows: lines.map(normalize).filter(Boolean)
    };
  }

  global.Meeting = {
    parse: parse,
    normalize: normalize,
    findDate: findDate,
    findTimes: findTimes,
    findPlace: findPlace,
    findSocial: findSocial,
    findTitle: findTitle
  };
})(typeof window !== "undefined" ? window : this);
