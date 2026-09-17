/*
 * レシートの文字認識結果から、合計・日付・店名を取り出す。
 *
 * 入力は ReceiptScanner プラグイン（iOS の Vision）が返す「行の断片」の配列:
 *   [{ text, x, y, width, height, confidence }]   位置は画像の左上を原点とする 0〜1 の割合
 *
 * Vision は「合計」と「¥1,280」のように、同じ行でも離れていると別の断片として返す。
 * そこでまず縦位置が近い断片を1行にまとめ、そのうえで規則を当てる。
 *
 * 通信は行わない。テストは apps/tests/receipt.test.mjs（ブラウザ不要）。
 */
(function (global) {
  "use strict";

  /* ---------- 文字の正規化 ---------- */

  // 全角の数字・記号を半角にし、空白を整える
  function normalize(text) {
    return String(text || "")
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/[，、]/g, ",")
      .replace(/[．]/g, ".")
      .replace(/[：]/g, ":")
      .replace(/[－―‐]/g, "-")
      .replace(/[／]/g, "/")
      .replace(/￥/g, "¥")
      .replace(/[\u3000\t]+/g, " ")
      .replace(/ +/g, " ")
      .trim();
  }

  /* ---------- 断片を行にまとめる ---------- */

  function median(values) {
    var v = values.slice().sort(function (a, b) { return a - b; });
    return v.length ? v[Math.floor(v.length / 2)] : 0;
  }

  /**
   * 縦位置が近い断片を同じ行とみなして左から右へつなぐ。
   * 戻り値: [{ text, y, parts }]（上から順）
   */
  function rowsFromLines(lines) {
    var items = (lines || []).filter(function (l) { return l && String(l.text || "").trim(); }).map(function (l) {
      var h = Number(l.height) || 0.02;
      return { text: normalize(l.text), x: Number(l.x) || 0, y: Number(l.y) || 0, h: h, cy: (Number(l.y) || 0) + h / 2 };
    });
    if (!items.length) return [];
    var tol = Math.max(0.004, median(items.map(function (i) { return i.h; })) * 0.6);
    items.sort(function (a, b) { return a.cy - b.cy; });
    var rows = [];
    items.forEach(function (it) {
      var last = rows[rows.length - 1];
      if (last && Math.abs(it.cy - last.cy) <= tol) {
        last.parts.push(it);
        last.cy = (last.cy * (last.parts.length - 1) + it.cy) / last.parts.length;
      } else {
        rows.push({ parts: [it], cy: it.cy });
      }
    });
    return rows.map(function (r) {
      r.parts.sort(function (a, b) { return a.x - b.x; });
      return { text: r.parts.map(function (p) { return p.text; }).join(" "), y: r.cy, parts: r.parts };
    });
  }

  /* ---------- 金額 ---------- */

  // 電話番号・登録番号・日付など、金額ではない数字の並びを含む行
  var NOT_AMOUNT_LINE = /TEL|電話|℡|〒|登録番号|T\d{13}|No\.|NO\.|番号|レジ|担当|\d{2,4}-\d{2,4}-\d{3,4}|\d{4}[\/.年]\d{1,2}[\/.月]\d{1,2}/i;

  // 行に含まれる金額（整数・円）をすべて取り出す
  function amountsIn(text) {
    var t = normalize(text);
    var out = [];
    var re = /(?:¥|\\)?\s*(\d{1,3}(?:,\d{3})+|\d{1,7})\s*(円|-)?/g;
    var m;
    while ((m = re.exec(t)) !== null) {
      var raw = m[1];
      var hasSep = raw.indexOf(",") >= 0;
      var hasYen = /[¥\\]\s*$/.test(t.slice(0, m.index + 1)) || m[0].indexOf("¥") >= 0 || m[0].indexOf("\\") >= 0 || (m[2] === "円");
      var n = Number(raw.replace(/,/g, ""));
      if (!isFinite(n)) continue;
      // 区切りも通貨記号も無い4桁以上の数字は、番号の可能性が高いので弱い候補にする
      var weak = !hasSep && !hasYen && raw.length >= 4;
      // 割合（8%、10%）は金額ではない
      var after = t.slice(m.index + m[0].length, m.index + m[0].length + 1);
      if (after === "%" || after === "％") continue;
      out.push({ value: n, weak: weak, yen: hasYen || hasSep });
    }
    return out;
  }

  var TOTAL_LABEL = /合\s*計|お会計|ご請求|請求額|お支払|支払額|お買上げ?合計|お買い上げ合計|総合計|合計金額|TOTAL/i;
  var TOTAL_EXCLUDE = /小\s*計|お預|お預り|預り|お釣|釣銭|おつり|内税|外税|消費税|税率|対象|割引|値引|ポイント|残高|返金|税抜|税別/;

  /**
   * 合計額を探す。
   * 1) 「合計」などの語がある行（小計・お預り・お釣りは除く）の金額。同じ行に無ければ次の行
   * 2) 見つからなければ、通貨記号や桁区切りのある金額のうち最大のもの（確度は低い）
   */
  function findTotal(rows) {
    var labeled = [];
    for (var i = 0; i < rows.length; i++) {
      var text = rows[i].text;
      if (!TOTAL_LABEL.test(text) || TOTAL_EXCLUDE.test(text)) continue;
      var amounts = amountsIn(text.replace(TOTAL_LABEL, " ")).filter(function (a) { return !a.weak || a.value >= 10; });
      if (!amounts.length && rows[i + 1] && !TOTAL_EXCLUDE.test(rows[i + 1].text)) {
        amounts = amountsIn(rows[i + 1].text).filter(function (a) { return !a.weak; });
      }
      if (amounts.length) {
        // 同じ行に複数あれば大きいほう（「合計 3点 ¥1,280」の「3」を避ける）
        var best = amounts.reduce(function (p, c) { return c.value > p.value ? c : p; });
        labeled.push({ value: best.value, row: i, taxIncluded: /税込/.test(text) });
      }
    }
    if (labeled.length) {
      // 「税込」と明記された合計を優先し、無ければいちばん下の合計を使う（小計→合計の順に並ぶため）
      var taxed = labeled.filter(function (l) { return l.taxIncluded; });
      var pick = (taxed.length ? taxed : labeled).slice(-1)[0];
      return { value: pick.value, confidence: "high", row: pick.row };
    }
    // 見出しが読めなかったときの保険
    var candidates = [];
    rows.forEach(function (r, i) {
      if (NOT_AMOUNT_LINE.test(r.text)) return;
      amountsIn(r.text).forEach(function (a) {
        if (a.yen && a.value >= 10 && a.value < 10000000) candidates.push({ value: a.value, row: i });
      });
    });
    if (!candidates.length) return null;
    var max = candidates.reduce(function (p, c) { return c.value > p.value ? c : p; });
    return { value: max.value, confidence: "low", row: max.row };
  }

  /* ---------- 日付 ---------- */

  function pad(n) { return String(n).padStart(2, "0"); }

  function validDate(y, m, d) {
    if (m < 1 || m > 12 || d < 1 || d > 31) return false;
    var dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
  }

  /**
   * 日付を探す。2026/9/15、2026年9月15日、26.09.15、令和8年9月15日、R8.9.15 に対応。
   */
  function findDate(rows) {
    var patterns = [
      { re: /(20\d{2})\s*[\/.\-年]\s*(\d{1,2})\s*[\/.\-月]\s*(\d{1,2})/, year: function (m) { return Number(m[1]); } },
      { re: /(?:令和|R|Ｒ)\s*(\d{1,2})\s*[\/.\-年]\s*(\d{1,2})\s*[\/.\-月]\s*(\d{1,2})/, year: function (m) { return 2018 + Number(m[1]); } },
      { re: /(?:^|[^\d])(\d{2})\s*[\/.\-]\s*(\d{1,2})\s*[\/.\-]\s*(\d{1,2})(?!\d)/, year: function (m) { return 2000 + Number(m[1]); } }
    ];
    for (var i = 0; i < rows.length; i++) {
      var text = rows[i].text;
      for (var p = 0; p < patterns.length; p++) {
        var m = text.match(patterns[p].re);
        if (!m) continue;
        var y = patterns[p].year(m), mo = Number(m[2]), d = Number(m[3]);
        if (validDate(y, mo, d) && y >= 2015 && y <= 2099) {
          return { value: y + "-" + pad(mo) + "-" + pad(d), row: i };
        }
      }
    }
    return null;
  }

  /* ---------- 店名 ---------- */

  var NOT_STORE = /^(領収書|領収証|レシート|お買上げ?票|お買い上げ|ご利用明細|明細|ありがとう|またお越し|TEL|電話|〒|営業時間|登録番号|T\d{13})/;
  var NOISE_LINE = /TEL|電話|℡|〒|登録番号|T\d{13}|^\d[\d\s:\/.\-]*$|^[¥\\]?\d/;

  /**
   * 店名を推定する。上のほうの行のうち、日付・電話・住所・定型文でない最初の行。
   * knownStores（過去に入力した店名）に含まれる語が本文にあれば、それを優先する。
   */
  function findStore(rows, knownStores) {
    var known = (knownStores || []).map(function (s) { return normalize(s); }).filter(Boolean)
      .sort(function (a, b) { return b.length - a.length; });
    var joined = rows.map(function (r) { return r.text; }).join("\n");
    for (var k = 0; k < known.length; k++) {
      if (known[k].length >= 2 && joined.indexOf(known[k]) >= 0) return { value: known[k], confidence: "high", known: true };
    }
    var top = rows.slice(0, 6);
    for (var i = 0; i < top.length; i++) {
      var t = top[i].text.trim();
      if (t.length < 2 || t.length > 30) continue;
      if (NOT_STORE.test(t) || NOISE_LINE.test(t)) continue;
      if (/\d{4}[\/.年]/.test(t)) continue;
      if (/(県|市|区|町|村).*\d/.test(t) && /\d/.test(t)) continue;   // 住所らしい行
      return { value: t.replace(/\s*(様|御中)$/, ""), confidence: "medium", known: false };
    }
    return null;
  }

  /* ---------- 買ったもの（明細） ---------- */

  // 明細ではない行。支払い・税・店舗情報など
  var NOT_ITEM = /小\s*計|合\s*計|お会計|ご請求|請求額|お支払|支払|お預|預り|お釣|釣銭|おつり|内税|外税|消費税|税率|税込|税抜|税別|課税|対象|割引|値引|ポイント|残高|返金|現金|クレジット|カード|電子マネー|チャージ|レシート|領収|ありがとう|またお越し/i;

  /**
   * 買ったものを1行ずつ取り出す。
   *
   * レシートは「店舗情報 → 明細 → 小計・合計 → 支払い」の順に並ぶため、
   * 小計・合計の行が出たところで打ち切る。
   * 明細と見なすのは「品名らしい文字」と「通貨記号か『円』が付いた金額」が
   * 同じ行にあるもの。「牛乳 1000ml ¥248」の 1000 のような、
   * 通貨記号の無い数字は品名の一部として扱う。
   */
  function findItems(rows) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var text = normalize(rows[i].text).trim();
      if (!text) continue;
      // ここから下は合計と支払いの欄
      if (/小\s*計/.test(text) || TOTAL_LABEL.test(text)) break;
      if (NOT_ITEM.test(text)) continue;
      if (NOT_AMOUNT_LINE.test(text)) continue;

      // 通貨記号か「円」が付いた金額だけを値段とみなす
      var priced = amountsIn(text).filter(function (a) { return a.yen; });
      if (!priced.length) continue;
      var price = priced[priced.length - 1].value;
      if (price <= 0) continue;

      // 行末の値段を取り除いたものを品名とする
      var name = text
        .replace(/(?:¥|\\)?\s*\d{1,3}(?:,\d{3})*\s*(?:円)?\s*[*※＊]?\s*$/, "")
        .replace(/[\s　]+$/, "")
        .trim();
      // 品名に文字が残らないもの（値段だけの行）は明細にしない
      if (!name || !/[^\d\s.,:;\-–—()（）%％*※＊]/.test(name)) continue;

      out.push({ name: name, price: price });
    }
    return out;
  }

  /* ---------- まとめ ---------- */

  /**
   * 認識結果から合計・日付・店名を取り出す。
   * @param lines  プラグインが返す断片の配列
   * @param opts   { knownStores: [過去の店名] }
   * @return { total, date, store, rows }  各項目は見つからなければ null
   */
  function parse(lines, opts) {
    var rows = rowsFromLines(lines);
    return {
      total: findTotal(rows),
      date: findDate(rows),
      store: findStore(rows, opts && opts.knownStores),
      items: findItems(rows),
      rows: rows.map(function (r) { return r.text; })
    };
  }

  global.Receipt = {
    findItems: findItems,
    parse: parse,
    rowsFromLines: rowsFromLines,
    amountsIn: amountsIn,
    findTotal: findTotal,
    findDate: findDate,
    findStore: findStore,
    normalize: normalize
  };
})(typeof window !== "undefined" ? window : this);
