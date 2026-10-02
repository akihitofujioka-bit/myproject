/*
 * 手帳のページ（手書きの予定）から、日付ごとの予定を取り出す。
 *
 * 2つの書き方に対応する。
 *   月間のマス目  … 「1〜31」の日付の数字が格子状に並び、マスの中に手書きで予定を書くもの
 *   日付ごとのメモ … 「10/3(金)」「3日(金)」「10月3日」のような日付の行のあとに、
 *                   その日の予定やメモが続くもの（ウィークリー・日記・縦に並んだ月間など）
 *
 * 入力は ReceiptScanner プラグイン（iOS の Vision）が返す断片の配列:
 *   [{ text, x, y, width, height, confidence }]   位置は画像の左上を原点とする 0〜1 の割合
 *
 * 月間のマス目は、文字だけを見ても「どのマスに書かれたか」が分からない。
 * そこで日付の数字の位置から格子（列の幅・段の高さ・1日の位置）を割り出し、
 * 手書きの断片をその位置のマスの日付に振り分ける。
 *
 * 手書きの読み取りは間違いが多いため、取り出したものは必ず人が確認してから
 * 登録する前提で作っている。通信は行わない。テストは apps/tests/planner.test.mjs。
 */
(function (global) {
  "use strict";

  /* ---------- 文字の正規化 ---------- */

  function normalize(text) {
    return String(text == null ? "" : text)
      .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/[Ａ-Ｚａ-ｚ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); })
      .replace(/[（]/g, "(").replace(/[）]/g, ")")
      .replace(/[：]/g, ":").replace(/[～〜]/g, "~")
      .replace(/[／]/g, "/").replace(/[－―‐ー](?=\d)/g, "-")
      // 手書きの横棒は、漢字の「一」・長音「ー」・マイナス「−」・ダッシュとして読まれることが多い。
      // 数字と数字の間にあるものは「-」とみなす（「14一15 会議」→「14-15 会議」）
      .replace(/(\d)\s*[－―‐ー一−–—]\s*(?=\d)/g, "$1-")
      .replace(/[　\t]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function pad(n) { return String(n).padStart(2, "0"); }

  function daysIn(y, m) { return new Date(y, m, 0).getDate(); }

  function ymd(y, m, d) { return y + "-" + pad(m) + "-" + pad(d); }

  function median(values) {
    var v = values.slice().sort(function (a, b) { return a - b; });
    return v.length ? v[Math.floor(v.length / 2)] : 0;
  }

  function percentile(values, p) {
    var v = values.slice().sort(function (a, b) { return a - b; });
    if (!v.length) return 0;
    return v[Math.min(v.length - 1, Math.floor(v.length * p))];
  }

  /* ---------- 印刷された文字（予定ではないもの） ---------- */

  // 手帳に最初から印刷されている祝日・六曜・月の満ち欠けなど。予定として拾わない
  var PRINTED = /^(元日|元旦|成人の日|建国記念の日|天皇誕生日|春分の日|昭和の日|憲法記念日|みどりの日|こどもの日|海の日|山の日|敬老の日|秋分の日|スポーツの日|体育の日|文化の日|勤労感謝の日|振替休日|国民の休日|休日|祝日|大安|仏滅|友引|先勝|先負|赤口|新月|満月|上弦|下弦|節分|彼岸|立春|立夏|立秋|立冬|夏至|冬至|七夕|母の日|父の日|クリスマス|大晦日|旧暦.*|六曜|祝|休|NOTE|MEMO|メモ|TO ?DO|Week|WEEK|週)$/i;

  var WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"];
  var WEEKDAYS_EN = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  var MONTHS_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  /** 「月」「(火)」「MON」「Tuesday」などを曜日番号（0=日）にする。当てはまらなければ -1 */
  function weekdayOf(token) {
    var t = String(token || "").replace(/[()\[\]\s.]/g, "");
    var ja = t.match(/^(日|月|火|水|木|金|土)(曜日?|曜)?$/);
    if (ja) return WEEKDAYS_JA.indexOf(ja[1]);
    var en = t.toUpperCase().match(/^(SUN|MON|TUE|WED|THU|FRI|SAT)/);
    if (en && /^[A-Z]+$/.test(t.toUpperCase()) && t.length <= 9) return WEEKDAYS_EN.indexOf(en[1]);
    return -1;
  }

  /* ---------- 時刻 ---------- */

  function toTime(hour, minute, ampm) {
    var h = Number(hour);
    var mi = Number(minute || 0);
    if (/午後|PM|pm/.test(ampm || "") && h < 12) h += 12;
    if (/午前|AM|am/.test(ampm || "") && h === 12) h = 0;
    if (!(h >= 0 && h <= 23 && mi >= 0 && mi <= 59)) return null;
    return pad(h) + ":" + pad(mi);
  }

  var AMPM = "(午前|午後|AM|PM|am|pm)?\\s*";
  var HM = "(\\d{1,2})\\s*(?::\\s*(\\d{2})|時\\s*(?:(\\d{1,2})\\s*分?|半)?)";
  // 「10:00~12:00」「10時~11時半」「午後2時」「14:30」「10~12」（範囲の数字だけ）
  var RANGE_RE = new RegExp("^" + AMPM + HM + "\\s*[~\\-]\\s*" + AMPM + "(\\d{1,2})\\s*(?::\\s*(\\d{2})|時\\s*(?:(\\d{1,2})\\s*分?|半)?)?");
  var SINGLE_RE = new RegExp("^" + AMPM + HM + "\\s*(?:~|から|より)?");
  var BARE_RANGE_RE = /^(\d{1,2})\s*[~\-]\s*(\d{1,2})(?!\d)(?!\s*[\/日月])/;
  // 「9会議」「9 会議」のように、行頭の数字のすぐ後ろに件名が続く書き方は、その時刻から始まる予定とみなす
  // （手帳では「9」だけで9時を表すことが多い。利用者の書き方: 2026-10-02）。
  // 「2人」「3回」「5kg」「500円」のような数量は時刻にしない
  var BARE_HOUR_RE = /^(\d{1,2})(?!\d)\s*(?![\d.,:\/~\-%]|人|名|個|回|件|枚|本|冊|円|日|月|年|歳|才|週|分|秒|号|番|階|点|位|台|社|部|班|組|割|度|時|k|K|g|m|c|L|l|F)(?=\S)/;

  /**
   * 行の先頭（または途中）の時刻を取り出し、残りを件名にする。
   * 戻り値: { start, end, rest }
   */
  function splitTime(text) {
    var t = normalize(text);
    // 先頭の記号（・ - ○ □ ☆ など）を外す
    var lead = t.replace(/^[・\-*•○◯●□■☆★◎→>]+\s*/, "");
    var m = lead.match(RANGE_RE);
    if (m) {
      // 「10時半~11時」の「半」は前側、「10時~11時半」の「半」は後ろ側だけに効かせる
      var start = toTime(m[2], m[3] || m[4] || (/^[^~\-]*時\s*半/.test(m[0]) ? 30 : 0), m[1]);
      var endAmpm = m[5] || m[1];
      var end = toTime(m[6], m[7] || m[8] || (/[~\-][^~\-]*時\s*半\s*$/.test(m[0]) ? 30 : 0), endAmpm);
      // 「1~3」のような範囲で後ろが小さいときは午後とみなす（13:00~15:00）
      if (start && end && end < start && Number(m[6]) < 12) end = toTime(Number(m[6]) + 12, m[7] || m[8] || 0);
      if (start) return { start: start, end: end || "", rest: lead.slice(m[0].length).trim() };
    }
    m = lead.match(SINGLE_RE);
    if (m) {
      var s = toTime(m[2], m[3] || m[4] || (/時\s*半/.test(m[0]) ? 30 : 0), m[1]);
      if (s) return { start: s, end: "", rest: lead.slice(m[0].length).trim() };
    }
    m = lead.match(BARE_HOUR_RE);
    if (m && Number(m[1]) >= 6 && Number(m[1]) <= 23 && lead.slice(m[0].length).trim()) {
      return { start: toTime(m[1], 0), end: "", rest: lead.slice(m[0].length).trim() };
    }
    m = lead.match(BARE_RANGE_RE);
    if (m && Number(m[1]) >= 6 && Number(m[1]) <= 22 && Number(m[2]) > Number(m[1]) && Number(m[2]) <= 23) {
      return { start: toTime(m[1], 0), end: toTime(m[2], 0), rest: lead.slice(m[0].length).trim() };
    }
    // 行の途中に「14:00」がある書き方（「歯医者 14:00」）
    var mid = lead.match(/(?:^|\s)(\d{1,2}):(\d{2})(?:\s*~\s*(\d{1,2}):(\d{2}))?(?=\s|$)/);
    if (mid && toTime(mid[1], mid[2])) {
      return {
        start: toTime(mid[1], mid[2]),
        end: mid[3] ? (toTime(mid[3], mid[4]) || "") : "",
        rest: (lead.slice(0, mid.index) + " " + lead.slice(mid.index + mid[0].length)).replace(/\s+/g, " ").trim()
      };
    }
    return { start: "", end: "", rest: lead };
  }

  /** 予定として意味のある文字か（数字・記号だけ、印刷物の語だけのものは除く） */
  function meaningful(text) {
    var t = normalize(text);
    if (!t) return false;
    if (PRINTED.test(t)) return false;
    if (!/[^\d\s.,:;~\-–—()\/%*※・|_=+ー一]/.test(t)) return false;
    // 曜日だけ
    if (weekdayOf(t) >= 0) return false;
    return true;
  }

  /* ---------- 月と年 ---------- */

  /**
   * ページの見出しから年と月を探す。いちばん大きく書かれたものを優先する。
   * 戻り値: { year: 数値|null, month: 数値|null }
   */
  function findMonthHeading(frags) {
    var best = null;
    frags.forEach(function (f) {
      var t = normalize(f.text);
      var y = null, m = null, mm;
      if ((mm = t.match(/(20\d{2})\s*[年.\/\-]\s*(\d{1,2})(?:\s*月)?(?![\d\/.])/))) { y = +mm[1]; m = +mm[2]; }
      else if ((mm = t.match(/(?:令和|R)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月/))) { y = 2018 + +mm[1]; m = +mm[2]; }
      else if ((mm = t.match(/^(\d{1,2})\s*月(?:\s|$|[A-Za-z(])/)) || (mm = t.match(/^(\d{1,2})\s*月$/))) { m = +mm[1]; }
      else {
        var en = t.toUpperCase().match(/(?:^|\s)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?(?:\s+(20\d{2}))?(?:\s|$)/);
        if (en && t.length <= 20) { m = MONTHS_EN.indexOf(en[1]) + 1; if (en[2]) y = +en[2]; }
        var ey = t.match(/^(20\d{2})$/);
        if (ey) y = +ey[1];
      }
      if (m != null && !(m >= 1 && m <= 12)) { m = null; }
      if (m == null && y == null) return;
      var size = Number(f.height) || 0;
      if (!best || (m != null && best.month == null) || (((m != null) === (best.month != null)) && size > best.size)) {
        best = { year: y != null ? y : (best && best.year), month: m, size: size };
      } else if (y != null && best.year == null) {
        best.year = y;
      }
    });
    return best ? { year: best.year || null, month: best.month || null } : { year: null, month: null };
  }

  /** 年が分からないとき、今日にいちばん近い年を当てる（先月より前なら来年とみなす） */
  function guessYear(month, today) {
    var base = today || new Date();
    var y = base.getFullYear();
    var diff = (month - 1) - base.getMonth();
    if (diff < -1) return y + 1;   // 例: 12月に 1月のページを撮った
    if (diff > 10) return y - 1;   // 例: 1月に 12月のページを撮った
    return y;
  }

  /**
   * 1日の曜日（0=日）と最終日から、当てはまる年月を今日の近くで探す。
   * 先月〜11か月先の順に探し、最初に合ったものを返す。
   */
  function guessMonthByWeekday(firstWeekday, maxDay, today) {
    var base = today || new Date();
    for (var add = -1; add <= 11; add++) {
      var d = new Date(base.getFullYear(), base.getMonth() + add, 1);
      if (d.getDay() !== firstWeekday) continue;
      if (daysIn(d.getFullYear(), d.getMonth() + 1) < maxDay) continue;
      return { year: d.getFullYear(), month: d.getMonth() + 1 };
    }
    return null;
  }

  /* ---------- 月間のマス目 ---------- */

  /**
   * 断片の中の日付の数字（1〜31）を拾う。
   * 「5 6 7」のように隣の日付と1つにつながった断片は、幅を等分して分ける。
   * 「15 敬老の日」「3 歯医者」のように数字の後ろに文字が続くものは、
   * 数字を日付、残りをそのマスの書き込みとして扱う。
   */
  function collectAnchors(frags) {
    var anchors = [];
    var rest = [];
    frags.forEach(function (f, idx) {
      var t = normalize(f.text);
      var x = Number(f.x) || 0, y = Number(f.y) || 0, w = Number(f.width) || 0, h = Number(f.height) || 0.02;
      if (/^\d{1,2}(\s+\d{1,2})+$/.test(t)) {
        var nums = t.split(" ");
        if (nums.every(function (n) { return +n >= 1 && +n <= 31; })) {
          nums.forEach(function (n, i) {
            anchors.push({ value: +n, x: x + w * i / nums.length, y: y, w: w / nums.length, h: h, src: idx });
          });
          return;
        }
      }
      var m = t.match(/^(\d{1,2})(?:\s+|(?=[^\d:時\/.\-~月日,円%]))(.*)$/) || t.match(/^(\d{1,2})$/);
      if (m && +m[1] >= 1 && +m[1] <= 31 && !/^\d{1,2}\s*[:時~\-\/.,円%]/.test(t)) {
        var digitsW = Math.min(w, Math.max(h * 0.6 * m[1].length, w * m[1].length / Math.max(1, t.length)));
        anchors.push({ value: +m[1], x: x, y: y, w: digitsW, h: h, src: idx });
        var tail = (m[2] || "").trim();
        if (tail) rest.push({ text: tail, x: x + digitsW, y: y, width: Math.max(0, w - digitsW), height: h, src: idx, inline: true });
        return;
      }
      rest.push({ text: t, x: x, y: y, width: w, height: h, src: idx });
    });
    return { anchors: anchors, rest: rest };
  }

  /**
   * 日付の数字の位置から格子を割り出す。
   * 「となりの日（+1）」の横の間隔を列の幅、「1週間後（+7）」の縦の間隔を段の高さとし、
   * いちばん多くの数字と矛盾しない並びを採る。手書きの数字などの紛れ込みはここで外れる。
   */
  function fitGrid(anchors) {
    if (anchors.length < 8) return null;
    // 余白に印刷された小さな前月・翌月のカレンダーを外すため、大きい数字を中心にする
    var hs = anchors.map(function (a) { return a.h; });
    var big = percentile(hs, 0.9);
    var cand = anchors.filter(function (a) { return a.h >= big * 0.6; });
    if (cand.length < 8) cand = anchors;

    var hMed = median(cand.map(function (a) { return a.h; }));
    var dxs = [], dys = [];
    cand.forEach(function (a) {
      cand.forEach(function (b) {
        if (b.value === a.value + 1 && b.x > a.x && Math.abs(b.y - a.y) < hMed * 1.2) dxs.push(b.x - a.x);
        if (b.value === a.value + 7 && b.y > a.y) dys.push(b.y - a.y);
      });
    });
    if (dxs.length < 2 || dys.length < 1) return null;
    var colW = median(dxs);
    var rowH = median(dys);
    if (!(colW > 0.02 && rowH > hMed)) return null;
    // 縦方向の +7 は、同じ列（横のずれが列幅の半分未満）だけを数え直して精度を上げる
    var dys2 = [];
    cand.forEach(function (a) {
      cand.forEach(function (b) {
        if (b.value === a.value + 7 && b.y > a.y && Math.abs(b.x - a.x) < colW * 0.5) dys2.push(b.y - a.y);
      });
    });
    if (dys2.length) rowH = median(dys2);

    // 日付の数字を、横位置の近いもの同士で「列」に、縦位置の近いもの同士で「段」にまとめ、番号を振る。
    // 列の間隔は一定と決めつけない。見開きの手帳は綴じ目のところだけ間隔が広く、
    // 一定とみなすと綴じ目より右のマスを1つずれた日に振り分けてしまう（2026-10-01 実物の手帳で確認）。
    // 間隔が列幅の約2倍あれば、その間の列は数字を読み落としたとみなして番号を飛ばす。
    function clusters(values, pitch) {
      var sorted = values.slice().sort(function (p, q) { return p - q; });
      var groups = [];
      sorted.forEach(function (v) {
        var last = groups[groups.length - 1];
        if (last && v - last.items[last.items.length - 1] <= pitch * 0.45) last.items.push(v);
        else groups.push({ items: [v] });
      });
      var idx = 0;
      groups.forEach(function (g, i) {
        g.center = median(g.items);
        // 間隔が列幅（段の高さ）の半分に満たないまとまりは、同じ番号にする。
        // マスの中の手書きの数字（「9会議」の「9」など）が別のまとまりになっても、後ろの番号がずれないように
        if (i > 0) idx += Math.round((g.center - groups[i - 1].center) / pitch);
        g.idx = idx;
      });
      return groups;
    }
    function indexIn(groups, v) {
      var best = null;
      groups.forEach(function (g) { if (!best || Math.abs(g.center - v) < Math.abs(best.center - v)) best = g; });
      return best;
    }
    var colGroups = clusters(cand.map(function (a) { return a.x; }), colW);
    var rowGroups = clusters(cand.map(function (a) { return a.y; }), rowH);

    // 「日付 − 列番号 − 7×段番号」がいちばん多くそろう値を採り、それに合う数字だけを格子とする。
    // 手書きの数字や余白の小さなカレンダーの数字は、ここで外れる
    var votes = {};
    var placed = cand.map(function (a) {
      var c = indexIn(colGroups, a.x).idx, r = indexIn(rowGroups, a.y).idx;
      var base = a.value - c - 7 * r;
      votes[base] = (votes[base] || 0) + 1;
      return { a: a, c: c, r: r, base: base };
    });
    var bestBase = null, n = 0;
    Object.keys(votes).forEach(function (k) { if (votes[k] > n) { n = votes[k]; bestBase = +k; } });
    var set = placed.filter(function (p) { return p.base === bestBase; });
    if (set.length < 6) return null;
    var cs = set.map(function (p) { return p.c; });
    var minC = Math.min.apply(null, cs), maxC = Math.max.apply(null, cs);
    if (maxC - minC > 6) return null;   // 1週は7列まで

    // 列・段ごとの数字の位置（格子に乗った数字の中央値）。数字が1つも無い列・段は、隣から列幅ぶんずらして補う
    function positions(key, idxKey, pitch, lo, hi) {
      var known = {};
      set.forEach(function (p) { (known[p[idxKey]] = known[p[idxKey]] || []).push(p.a[key]); });
      var out = {};
      Object.keys(known).forEach(function (k) { out[k] = median(known[k]); });
      var ks = Object.keys(out).map(Number);
      for (var i = lo; i <= hi; i++) {
        if (out[i] != null) continue;
        var near = ks.reduce(function (p, q) { return Math.abs(q - i) < Math.abs(p - i) ? q : p; });
        out[i] = out[near] + (i - near) * pitch;
      }
      return out;
    }
    var ref = set[0].a;
    var cRef = set[0].c, rRef = set[0].r;
    var rs = set.map(function (p) { return p.r; });
    var colX = positions("x", "c", colW, minC - 1, minC + 7);
    var rowY = positions("y", "r", rowH, Math.min.apply(null, rs) - 1, Math.max.apply(null, rs) + 6);

    return {
      ref: ref, colW: colW, rowH: rowH,
      // 列・段の番号は、基準の数字（ref）からの差で扱う
      minDc: minC - cRef, maxDc: maxC - cRef,
      minDr: Math.min.apply(null, rs) - rRef, maxDr: Math.max.apply(null, rs) - rRef,
      colX: function (dc) { return colX[dc + cRef]; },
      rowY: function (dr) { return rowY[dr + rRef]; },
      members: set.map(function (p) { return p.a; }),
      hMed: hMed
    };
  }

  /**
   * 曜日の見出し（日 月 火 … / SUN MON …）を探し、列ごとの曜日と中心の位置を返す。
   * 見つからなければ null。
   */
  function findWeekdayHeader(frags, grid) {
    var labels = [];
    frags.forEach(function (f) {
      var t = normalize(f.text);
      var tokens = t.split(" ");
      var wds = tokens.map(weekdayOf);
      if (!tokens.length || wds.some(function (w) { return w < 0; })) return;
      tokens.forEach(function (tok, i) {
        var w = (Number(f.width) || 0) / tokens.length;
        labels.push({ wd: wds[i], cx: (Number(f.x) || 0) + w * (i + 0.5), y: Number(f.y) || 0 });
      });
    });
    // 格子より上にあるものだけ（本文中の「(月)」などを避ける）
    var top = Math.min.apply(null, grid.members.map(function (a) { return a.y; }));
    labels = labels.filter(function (l) { return l.y < top; });
    if (labels.length < 3) return null;

    // 見出しは列の中央、日付の数字は列の端にあることが多い。見出しの中心が数字の位置から
    // 列幅の何倍ずれているか（全部の見出しで共通のはず）を多数決で決め、各見出しの列を割り出す
    // 見出しと数字の組み合わせは「同じ列の右寄り」とも「右隣の列の左寄り」とも取れる。
    // 見出しがすべて、数字のある列（minDc〜maxDc）に収まる組み合わせを選ぶ。同点なら、ずれの小さい方
    var dcs = [];
    for (var dc = grid.minDc; dc <= grid.maxDc; dc++) dcs.push(dc);
    var offsets = [];
    labels.forEach(function (l) {
      dcs.forEach(function (dc) {
        var o = (l.cx - grid.colX(dc)) / grid.colW;
        if (o > -0.95 && o < 0.95) offsets.push(o);
      });
    });
    var bestO = 0, bestN = 0;
    offsets.forEach(function (o) {
      var k = labels.filter(function (l) {
        return dcs.some(function (dc) { return Math.abs((l.cx - grid.colX(dc)) / grid.colW - o) < 0.15; });
      }).length;
      if (k > bestN || (k === bestN && Math.abs(o) < Math.abs(bestO))) { bestN = k; bestO = o; }
    });
    var near = offsets.filter(function (q) { return Math.abs(q - bestO) < 0.15; });
    var offset = near.length ? median(near) : bestO;

    var refVote = {};
    labels.forEach(function (l) {
      var hit = null;
      dcs.forEach(function (dc) {
        var o = (l.cx - grid.colX(dc)) / grid.colW;
        if (Math.abs(o - offset) < 0.2 && (hit == null || Math.abs(o - offset) < Math.abs((l.cx - grid.colX(hit)) / grid.colW - offset))) hit = dc;
      });
      if (hit == null) return;
      l.dc = hit;
      var wdAtRef = ((l.wd - l.dc) % 7 + 7) % 7;
      refVote[wdAtRef] = (refVote[wdAtRef] || 0) + 1;
    });
    var wdRef = -1, n = 0;
    Object.keys(refVote).forEach(function (k) { if (refVote[k] > n) { n = refVote[k]; wdRef = +k; } });
    if (n < 3) return null;
    var agreed = labels.filter(function (l) { return l.dc != null && ((l.wd - l.dc) % 7 + 7) % 7 === wdRef; });
    return {
      weekdayAtRefColumn: wdRef,
      // 列の中心が、その列の数字の左端からどれだけ右にあるか（列幅の何倍か）
      centerOffset: offset,
      firstDc: Math.min.apply(null, agreed.map(function (l) { return l.dc; })),
      count: agreed.length
    };
  }

  /**
   * 手帳を少し斜めに撮ると、同じ段の日付が右へ行くほど上下にずれ、段や列の判定を誤る。
   * 「となりの日（+1）」の縦のずれと「1週間後（+7）」の横のずれから傾きを見積もり、
   * 全部の断片の位置をまっすぐに直す（撮影時に四隅を補正できなかった場合の保険）。
   */
  function deskew(collected) {
    var a = collected.anchors;
    var row = [], col = [];
    a.forEach(function (p) {
      a.forEach(function (q) {
        var dx = q.x - p.x, dy = q.y - p.y;
        if (q.value === p.value + 1 && dx > 0.02 && dx < 0.3 && Math.abs(dy) < dx * 0.5) row.push(dy / dx);
        if (q.value === p.value + 7 && dy > 0.02 && dy < 0.4 && Math.abs(dx) < dy * 0.5) col.push(dx / dy);
      });
    });
    var k1 = row.length >= 3 ? median(row) : 0;   // 横に進むと縦にずれる割合
    var k2 = col.length >= 2 ? median(col) : 0;   // 縦に進むと横にずれる割合
    if (Math.abs(k1) < 0.01 && Math.abs(k2) < 0.01) return collected;
    function fix(f) {
      var x = Number(f.x) || 0, y = Number(f.y) || 0;
      var out = {};
      Object.keys(f).forEach(function (k) { out[k] = f[k]; });
      out.x = x - k2 * y;
      out.y = y - k1 * x;
      return out;
    }
    return { anchors: collected.anchors.map(fix), rest: collected.rest.map(fix) };
  }

  function parseMonthGrid(frags, today) {
    var collected = deskew(collectAnchors(frags));
    var grid = fitGrid(collected.anchors);
    if (!grid) return null;

    var ref = grid.ref;
    // 曜日の見出しは、傾きを直したあとの位置（collected.rest）で探す
    var header = findWeekdayHeader(collected.rest, grid);

    // マスの左端。曜日の見出しがあれば、その中心から割り出す（数字が左寄せでも右寄せでも合う）。
    // 無ければ、右端の列の数字のすぐ右が紙の外かどうかで、数字が右寄せかを判断する
    var cellLeftRef;
    if (header) {
      cellLeftRef = ref.x + (header.centerOffset - 0.5) * grid.colW;
      // 見出しが列の中央からずれて印刷されている手帳や、写真の遠近で上のほうがずれた場合でも、
      // 日付の数字そのものは自分のマスの中に入るようにする
      cellLeftRef = Math.min(cellLeftRef, ref.x - grid.colW * 0.02);
      cellLeftRef = Math.max(cellLeftRef, ref.x + ref.w - grid.colW * 0.98);
    } else {
      var maxX = Math.max.apply(null, grid.members.map(function (a) { return a.x + a.w; }));
      var minX = Math.min.apply(null, grid.members.map(function (a) { return a.x; }));
      var rightAligned = maxX + grid.colW * 0.6 > 1.02 && minX - grid.colW * 0.6 > -0.02;
      cellLeftRef = rightAligned ? (ref.x + ref.w) - grid.colW * 0.92 : ref.x - grid.colW * 0.08;
    }
    var cellTopRef = ref.y - grid.rowH * 0.08;
    // いちばん左の列（基準の列から数えて何列目か）。見出しが7つ揃っていればそれを使う
    var leftDc = header && header.count >= 7 ? header.firstDc : grid.minDc;

    var maxDay = Math.max.apply(null, grid.members.map(function (a) { return a.value; }));
    // 1日の曜日（見出しが無ければ分からない）
    var firstWeekday = header ? ((header.weekdayAtRefColumn + (1 - ref.value)) % 7 + 7) % 7 : -1;

    var heading = findMonthHeading(collected.rest);
    var year = heading.year, month = heading.month, monthConfidence = "high";
    if (month && !year) {
      year = guessYear(month, today);
      // 曜日の見出しがあれば、年の候補（前後1年）を曜日で確かめる
      if (firstWeekday >= 0 && new Date(year, month - 1, 1).getDay() !== firstWeekday) {
        [year + 1, year - 1].some(function (y) {
          if (new Date(y, month - 1, 1).getDay() === firstWeekday) { year = y; return true; }
          return false;
        });
      }
      monthConfidence = "medium";
    }
    if (!month) {
      var g = null;
      if (firstWeekday >= 0) g = guessMonthByWeekday(firstWeekday, maxDay, today);
      if (!g) {
        // 曜日も分からないときは、日曜始まり・月曜始まりのどちらかと仮定して近い月を探す
        var col1 = ((1 - ref.value - leftDc) % 7 + 7) % 7;   // 左端の列から数えた1日の列
        g = guessMonthByWeekday(col1, maxDay, today) || guessMonthByWeekday((col1 + 1) % 7, maxDay, today);
      }
      if (!g) return null;
      year = g.year; month = g.month; monthConfidence = "low";
    }
    var dim = daysIn(year, month);

    // マス（列番号 dc・段番号 dr）を日付に変える。範囲外（前月・翌月のマス、欄外）は 0
    function dayAt(dc, dr) {
      if (dc < leftDc || dc > leftDc + 6) return 0;
      var d = ref.value + dc + 7 * dr;
      return d >= 1 && d <= dim ? d : 0;
    }

    // 日付の数字そのもの（格子に乗ったもの）は書き込みではない。
    // 格子に乗らなかった数字（手書きの「2」など）は書き込みに戻す
    var memberSet = grid.members;
    // 「9役員会議」のように数字と文字が1つの断片だったものは、切り分けた後ろの文字とつなぎ直す
    var leftovers = [];
    collected.anchors.filter(function (a) { return memberSet.indexOf(a) < 0; }).forEach(function (a) {
      var tail = collected.rest.filter(function (f) { return f.inline && f.src === a.src; })[0];
      if (tail) {
        tail.text = a.value + tail.text;
        tail.width += tail.x - a.x;
        tail.x = a.x;
        tail.inline = false;
        return;
      }
      leftovers.push({ text: String(a.value), x: a.x, y: a.y, width: a.w, height: a.h, src: a.src });
    });
    // 見出しの年月・曜日の行は外す
    var content = collected.rest.concat(leftovers).filter(function (f) {
      // 時刻だけの断片（「13:30」）は、次の行の予定に引き継ぐため残す
      if (!meaningful(f.text) && !splitTime(f.text).start) return false;
      var t = normalize(f.text);
      if (findMonthHeading([f]).month && t.length <= 12) return false;
      if (t.split(" ").every(function (tok) { return weekdayOf(tok) >= 0; })) return false;
      return true;
    });

    // マスの境目は、列・段ごとの数字の位置から求める（間隔が一定でない手帳に合わせるため）
    var shiftX = cellLeftRef - ref.x;
    var shiftY = cellTopRef - ref.y;
    function colOf(px) {
      for (var dc = leftDc; dc <= leftDc + 6; dc++) {
        var left = grid.colX(dc) + shiftX;
        var right = dc < leftDc + 6 ? grid.colX(dc + 1) + shiftX : left + grid.colW;
        if (px >= left && px < right) return dc;
      }
      return null;
    }
    function rowOf(py) {
      for (var dr = grid.minDr - 1; dr <= grid.maxDr + 1; dr++) {
        var top = grid.rowY(dr) + shiftY;
        var bottom = grid.rowY(dr + 1) != null ? grid.rowY(dr + 1) + shiftY : top + grid.rowH;
        if (py >= top && py < bottom) return dr;
      }
      return null;
    }

    // 断片をマスに振り分ける。断片の書き出し（左端付近）と縦の中心で判断する
    var cells = {};
    content.forEach(function (f) {
      var px = f.x + Math.min(f.width / 2, grid.colW * 0.3);
      var py = f.y + f.height / 2;
      var dc = colOf(px);
      var dr = rowOf(py);
      if (dc == null || dr == null) return;
      var d = dayAt(dc, dr);
      if (!d) return;
      (cells[d] = cells[d] || []).push(f);
    });

    var entries = [];
    Object.keys(cells).map(Number).sort(function (a, b) { return a - b; }).forEach(function (d) {
      entries = entries.concat(entriesFrom(linesOf(cells[d]), ymd(year, month, d)));
    });

    return {
      kind: "month",
      year: year,
      month: month,
      monthConfidence: monthConfidence,
      anchors: grid.members.length,
      entries: entries
    };
  }

  /** 同じマスの断片を、縦位置の近いもの同士で1行にまとめる（上から順） */
  function linesOf(frags) {
    var items = frags.slice().sort(function (a, b) { return (a.y + a.height / 2) - (b.y + b.height / 2); });
    var tol = Math.max(0.004, median(items.map(function (f) { return f.height; })) * 0.6);
    var rows = [];
    items.forEach(function (f) {
      var cy = f.y + f.height / 2;
      var last = rows[rows.length - 1];
      if (last && Math.abs(cy - last.cy) <= tol) { last.parts.push(f); }
      else rows.push({ cy: cy, parts: [f] });
    });
    return rows.map(function (r) {
      r.parts.sort(function (a, b) { return a.x - b.x; });
      return normalize(r.parts.map(function (p) { return p.text; }).join(" "));
    }).filter(Boolean);
  }

  /**
   * 1日ぶんの書き込み（行の配列）を予定にする。
   * 1行を1件とする。時刻だけの行（「10:00」の次の行に「歯医者」）は、時刻を次の行へ引き継ぐ。
   */
  function entriesFrom(lines, date) {
    var out = [];
    var pending = null;
    lines.forEach(function (text) {
      var t = splitTime(text);
      var title = t.rest.replace(/^[・\-*•○◯●□■☆★◎→>:]+\s*/, "").trim();
      if (!meaningful(title)) {
        if (t.start) pending = t;
        return;
      }
      var time = t.start ? t : (pending || t);
      pending = null;
      out.push({ date: date, startTime: time.start || "", endTime: time.end || "", title: title });
    });
    return out;
  }

  /* ---------- 日付ごとのメモ ---------- */

  /** 断片を行にまとめる（上から順）。各行は { text, y } */
  function rowsOf(frags) {
    var items = frags.map(function (f) {
      var h = Number(f.height) || 0.02;
      return { text: normalize(f.text), x: Number(f.x) || 0, y: Number(f.y) || 0, h: h, cy: (Number(f.y) || 0) + h / 2 };
    }).filter(function (i) { return i.text; });
    if (!items.length) return [];
    var tol = Math.max(0.004, median(items.map(function (i) { return i.h; })) * 0.6);
    items.sort(function (a, b) { return a.cy - b.cy; });
    var rows = [];
    items.forEach(function (it) {
      var last = rows[rows.length - 1];
      if (last && Math.abs(it.cy - last.cy) <= tol) {
        last.parts.push(it);
        last.cy = (last.cy * (last.parts.length - 1) + it.cy) / last.parts.length;
      } else rows.push({ parts: [it], cy: it.cy });
    });
    return rows.map(function (r) {
      r.parts.sort(function (a, b) { return a.x - b.x; });
      return { text: r.parts.map(function (p) { return p.text; }).join(" "), y: r.cy };
    });
  }

  /**
   * 日付の直後の曜日を読む。読めたら { wd, len }。
   * 「月」は月の意味と紛らわしいため、括弧付き「(月)」か「月曜」の形のときだけ曜日とみなす。
   */
  function readWeekday(s) {
    var m;
    if ((m = s.match(/^\s*\(\s*(日|月|火|水|木|金|土)\s*(?:曜日?)?\s*\)\s*/))) return { wd: WEEKDAYS_JA.indexOf(m[1]), len: m[0].length };
    if ((m = s.match(/^\s*\(\s*(SUN|MON|TUE|WED|THU|FRI|SAT)[A-Z]*\.?\s*\)\s*/i))) return { wd: WEEKDAYS_EN.indexOf(m[1].toUpperCase()), len: m[0].length };
    if ((m = s.match(/^\s*(日|月|火|水|木|金|土)曜日?\s*/))) return { wd: WEEKDAYS_JA.indexOf(m[1]), len: m[0].length };
    if ((m = s.match(/^\s*(SUN(?:DAY)?|MON(?:DAY)?|TUE(?:S|SDAY)?|WED(?:NESDAY)?|THU(?:R|RS|RSDAY)?|FRI(?:DAY)?|SAT(?:URDAY)?)\.?(?![A-Za-z])\s*/i))) {
      return { wd: WEEKDAYS_EN.indexOf(m[1].slice(0, 3).toUpperCase()), len: m[0].length };
    }
    // 括弧なしの漢字1字は、月・日以外で、後ろが空白か行末のときだけ
    if ((m = s.match(/^\s+(火|水|木|金|土)(?=\s|$)\s*/))) return { wd: WEEKDAYS_JA.indexOf(m[1]), len: m[0].length };
    return null;
  }

  /**
   * 行の先頭にある日付を読む。読めたら { year, month, day, weekday, rest } を返す。
   * month が null のものは「3日(金)」のように日だけが書かれたもの。
   */
  /**
   * 手書きの日付に多い読み違いを、行頭の日付の部分だけ直す。
   * 数字の隣にある「O」「〇」は0、「l」「I」「|」は1、数字にはさまれた「ノ」「\」は「/」とみなす。
   */
  function fixDateChars(t) {
    var head = t.slice(0, 12), tail = t.slice(12);
    head = head
      .replace(/(\d)\s*[ノﾉ\\∕⁄]\s*(?=\d)/g, "$1/")
      .replace(/[OoＯｏ〇○◯](?=\s*[\d\/月日])|(\d)[OoＯｏ〇○◯]/g, function (all, d) { return (d || "") + "0"; })
      .replace(/[lI|｜!ｌ](?=\d)|(\d)[lI|｜!ｌ](?![A-Za-z])/g, function (all, d) { return (d || "") + "1"; });
    return head + tail;
  }

  /**
   * 「/」を読み落として「1013(金)」のように1つの数字になった日付の分け方の候補。
   * 曜日が付いているときだけ使う（ただの番号と区別するため）。
   * 例: 1013 → 10/13・10/3（間の「1」は「/」の読み違い）、113 → 1/13・11/3・1/3
   */
  function splitMergedDate(digits) {
    var out = [];
    for (var i = 1; i <= 2 && i < digits.length; i++) {
      var mo = Number(digits.slice(0, i)), rest = digits.slice(i);
      if (!(mo >= 1 && mo <= 12)) continue;
      if (rest.length <= 2 && Number(rest) >= 1 && Number(rest) <= 31) out.push({ month: mo, day: Number(rest) });
      if (rest.length >= 2 && /[17]/.test(rest[0]) && rest.length - 1 <= 2) {
        var d2 = Number(rest.slice(1));
        if (d2 >= 1 && d2 <= 31) out.push({ month: mo, day: d2 });
      }
    }
    return out;
  }

  function dateHead(text) {
    var t = fixDateChars(normalize(text));
    var m, w, after;
    function done(year, month, day, needWeekday) {
      after = t.slice(m[0].length);
      w = readWeekday(after);
      if (needWeekday && !w) return null;
      return { year: year, month: month, day: day, weekday: w ? w.wd : -1, rest: (w ? after.slice(w.len) : after).trim() };
    }
    if ((m = t.match(/^(20\d{2})\s*[年\/.\-]\s*(\d{1,2})\s*[月\/.\-]\s*(\d{1,2})(?!\d)\s*日?/))) return done(+m[1], +m[2], +m[3]);
    if ((m = t.match(/^(?:令和|R)\s*(\d{1,2})\s*[年.]\s*(\d{1,2})\s*[月.]\s*(\d{1,2})(?!\d)\s*日?/))) return done(2018 + +m[1], +m[2], +m[3]);
    if ((m = t.match(/^(\d{1,2})\s*月\s*(\d{1,2})\s*日/))) return done(null, +m[1], +m[2]);
    // 「10/3」「10/3(金)」。時刻（10:30）や分数・番号と取り違えないよう、直後は数字・記号以外
    if ((m = t.match(/^(\d{1,2})\s*\/\s*(\d{1,2})(?![\d:\/.])/))) return done(null, +m[1], +m[2]);
    // 「10.3(金)」は曜日が付くときだけ（「1.5L」のような量と区別するため）
    if ((m = t.match(/^(\d{1,2})\.(\d{1,2})(?![\d.])/))) return done(null, +m[1], +m[2], true);
    // 「1013(金)」— 「/」を読み落としたもの。曜日が付いているときだけ、分け方の候補を全部持たせる
    if ((m = t.match(/^(\d{3,4})(?!\d)/))) {
      var parts = splitMergedDate(m[1]);
      var hm = parts.length ? done(null, parts[0].month, parts[0].day, true) : null;
      if (hm) { hm.alts = parts; return hm; }
    }
    // 「3日(金)」「3(金)」「3 FRI」— 曜日が付いているものだけ（ただの数字と区別するため）
    if ((m = t.match(/^(\d{1,2})(?!\d)\s*日?/))) return done(null, null, +m[1], true);
    // 「FRI 3」
    if ((m = t.match(/^(SUN|MON|TUE|WED|THU|FRI|SAT)[A-Za-z]*\.?\s*(\d{1,2})(?!\d)\s*/i))) {
      return { year: null, month: null, day: +m[2], weekday: WEEKDAYS_EN.indexOf(m[1].toUpperCase()), rest: t.slice(m[0].length).trim() };
    }
    return null;
  }

  function validDate(y, m, d) {
    if (!(y >= 2000 && y <= 2100 && m >= 1 && m <= 12 && d >= 1 && d <= 31)) return false;
    var dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
  }

  function dayDiff(a, b) {
    var pa = a.split("-").map(Number), pb = b.split("-").map(Number);
    return Math.round((new Date(pb[0], pb[1] - 1, pb[2]) - new Date(pa[0], pa[1] - 1, pa[2])) / 86400000);
  }
  function addDays(date, n) {
    var p = date.split("-").map(Number);
    var d = new Date(p[0], p[1] - 1, p[2] + n);
    return ymd(d.getFullYear(), d.getMonth() + 1, d.getDate());
  }
  function weekdayOfDate(date) {
    var p = date.split("-").map(Number);
    return new Date(p[0], p[1] - 1, p[2]).getDay();
  }

  /**
   * 手書きの日付の読み違いを、前後の日付と曜日で直す。
   * 日付ごとのメモは上から順に日付が進むので、並びから外れたものや曜日と合わないものは読み違いとみなす。
   *   1) 分け方の候補（1013 → 10/13・10/3）があれば、曜日と前後の並びに合うものを選ぶ
   *   2) 曜日と合わなければ、前後の日付の間で曜日が合う日にする
   *   3) 曜日が無く、前後がちょうど2日違いなら、その間の日にする
   * 直した日付には guessed を付け、確認欄で知らせる。
   */
  function fixSequence(list) {
    function wdOk(s, date) { return s.weekday < 0 || weekdayOfDate(date) === s.weekday; }
    // 正しく読めたとみなす日付を決める。曜日が合うものを候補にし、
    // 並び順と矛盾する組（後ろの行なのに前の日付、または離れすぎ）がなくなるまで、
    // 矛盾をいちばん多く作っているものから外していく
    var good = list.map(function (s) { return wdOk(s, s.date); });
    function conflict(i, j) {   // i < j
      var d = dayDiff(list[i].date, list[j].date);
      return d <= 0 || d > 7 * (j - i);
    }
    for (;;) {
      var worst = -1, worstN = 0, worstCost = -1;
      list.forEach(function (s, i) {
        if (!good[i]) return;
        var n = 0, cost = 0;
        list.forEach(function (t, j) {
          if (i === j || !good[j]) return;
          var a = Math.min(i, j), b = Math.max(i, j);
          if (conflict(a, b)) n++;
          cost += Math.abs(dayDiff(list[a].date, list[b].date) - (b - a));
        });
        if (n > worstN || (n === worstN && n > 0 && cost > worstCost)) { worst = i; worstN = n; worstCost = cost; }
      });
      if (worst < 0) break;
      good[worst] = false;
    }
    list.forEach(function (s, i) {
      if (good[i]) {
        // 分け方が複数考えられたが、前後とつながる方に決まったもの
        if (s.alts.length > 1) s.guessed = false;
        return;
      }
      var pi = i - 1; while (pi >= 0 && !good[pi]) pi--;
      var ni = i + 1; while (ni < list.length && !good[ni]) ni++;
      var lo = pi >= 0 ? list[pi].date : null, hi = ni < list.length ? list[ni].date : null;
      function between(d) {
        return (!lo || dayDiff(lo, d) > 0) && (!hi || dayDiff(d, hi) > 0) && wdOk(s, d);
      }
      var pick = s.alts.filter(between)[0];
      if (!pick && (lo || hi)) {
        // 正しい日付から、並び順どおりに数えた位置を中心に、曜日が合う日を探す
        var expect = lo ? addDays(lo, i - pi) : addDays(hi, -(ni - i));
        for (var k = 0; k <= 6 && !pick; k++) {
          [addDays(expect, k), addDays(expect, -k)].some(function (c) {
            if (between(c)) { pick = c; return true; }
            return false;
          });
        }
      }
      if (pick && pick !== s.date) { s.date = pick; s.guessed = true; }
    });
  }

  /**
   * 見開きの手帳（左右のページそれぞれに日付が縦に並ぶもの）は、行をそのまま横につなぐと
   * 左右の別の日の書き込みが混ざる。日付の書き出しの横位置が離れて2か所以上にあれば、
   * その位置で縦に区切って、それぞれを別に読む。
   */
  function splitColumns(frags) {
    var xs = frags.filter(function (f) { return dateHead(f.text); })
      .map(function (f) { return Number(f.x) || 0; })
      .sort(function (a, b) { return a - b; });
    var starts = [];
    xs.forEach(function (x) {
      if (!starts.length || x - starts[starts.length - 1].last > 0.2) starts.push({ first: x, last: x });
      else starts[starts.length - 1].last = x;
    });
    if (starts.length < 2) return [frags];
    var cuts = starts.slice(1).map(function (s) { return s.first - 0.02; });
    var cols = cuts.map(function () { return []; }).concat([[]]);
    frags.forEach(function (f) {
      var x = Number(f.x) || 0;
      var i = 0;
      while (i < cuts.length && x >= cuts[i]) i++;
      cols[i].push(f);
    });
    return cols;
  }

  function parseDaily(frags, today) {
    var base = today || new Date();
    var heading = findMonthHeading(frags.filter(function (f) { return !dateHead(f.text); }));
    var sections = [];
    var lowConfidence = false;

    // 日付の行を、年・月を補って "YYYY-MM-DD" にする。読めなければ null
    function resolve(h, day, monthIn) {
      var month = monthIn || heading.month;
      var year = h.year || heading.year;
      if (!month) {
        // 月が書かれていない。曜日が分かれば、今日に近い月のうち曜日が合うものを探す
        for (var add = -1; add <= 11 && h.weekday >= 0; add++) {
          var d = new Date(base.getFullYear(), base.getMonth() + add, day);
          if (d.getDate() === day && d.getDay() === h.weekday) {
            lowConfidence = true;
            return ymd(d.getFullYear(), d.getMonth() + 1, day);
          }
        }
        return null;   // 日付として扱えない（ただの番号の可能性）
      }
      if (!year) {
        year = guessYear(month, base);
        // 曜日が書かれていれば、それに合う年を前後1年で探す
        if (h.weekday >= 0 && validDate(year, month, day) && new Date(year, month - 1, day).getDay() !== h.weekday) {
          [year + 1, year - 1].some(function (y) {
            if (validDate(y, month, day) && new Date(y, month - 1, day).getDay() === h.weekday) { year = y; return true; }
            return false;
          });
        }
      }
      return validDate(year, month, day) ? ymd(year, month, day) : null;
    }

    splitColumns(frags).forEach(function (colFrags) {
      var current = null;
      rowsOf(colFrags).forEach(function (row) {
        var h = dateHead(row.text);
        if (h && h.day >= 1 && h.day <= 31) {
          var date = resolve(h, h.day, h.month);
          var alts = (h.alts || []).map(function (c) { return resolve(h, c.day, c.month); }).filter(Boolean);
          if (!date && alts.length) date = alts[0];
          if (!date) { current = null; return; }
          current = { date: date, lines: [], weekday: h.weekday, alts: alts, guessed: alts.length > 1 };
          sections.push(current);
          if (h.rest) current.lines.push(h.rest);
          return;
        }
        if (current) current.lines.push(row.text);
      });
    });

    fixSequence(sections);

    // 同じ日付が別々に出てきた場合はまとめ、日付の順に並べる
    var byDate = {}, guessed = {};
    sections.forEach(function (s) {
      byDate[s.date] = (byDate[s.date] || []).concat(s.lines);
      if (s.guessed) guessed[s.date] = true;
    });
    var order = Object.keys(byDate).sort();

    var entries = [];
    order.forEach(function (date) {
      entriesFrom(byDate[date], date).forEach(function (e) {
        if (guessed[date]) e.dateGuess = true;   // 確認欄で「推測した日付」と分かるようにする
        entries.push(e);
      });
    });
    return {
      kind: "daily",
      sections: order.length,
      monthConfidence: lowConfidence ? "low" : (heading.month ? "high" : "medium"),
      entries: entries
    };
  }

  /* ---------- まとめ ---------- */

  /**
   * 手帳のページから予定を取り出す。
   * @param lines  プラグインが返す断片の配列
   * @param opts   { today: Date }（テスト用。省略時は今日）
   * @return { kind: "month"|"daily"|null, entries: [{ date, startTime, endTime, title }], ... }
   *         月間のマス目として読めればそちらを優先し、読めなければ日付ごとのメモとして読む。
   */
  function parse(lines, opts) {
    var today = opts && opts.today;
    var frags = (lines || []).filter(function (l) { return l && String(l.text || "").trim(); });
    var month = parseMonthGrid(frags, today);
    if (month) return month;
    var daily = parseDaily(frags, today);
    if (daily.sections) return daily;
    return { kind: null, entries: [] };
  }

  /**
   * 手帳のページらしさ。振り分け（scanrouter.js）で使う。
   *   "strong" … 月間のマス目の格子が取れた（レシート・通知では起こらない）
   *   "weak"   … 日付の行が2つ以上ある（日付ごとのメモ）
   *   ""       … 手帳とは言えない
   */
  function strength(result) {
    if (!result || !result.kind) return "";
    if (result.kind === "month") return "strong";
    if (result.kind === "daily" && result.sections >= 3) return "strong";
    if (result.kind === "daily" && result.sections >= 2) return "weak";
    return "";
  }

  global.Planner = {
    parse: parse,
    strength: strength,
    splitTime: splitTime,
    dateHead: dateHead,
    findMonthHeading: findMonthHeading,
    normalize: normalize
  };
})(typeof window !== "undefined" ? window : this);
