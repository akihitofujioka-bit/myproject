/*
 * カメラで撮った書類が「レシート」か「会議の通知」かを判定し、
 * 適切なアプリへ振り分けるための橋渡し。
 *
 * 判定は Receipt.parse()（合計額が読み取れるか）と Meeting.parse()
 * （会議名・日付などが読み取れるか）の結果を使う。どちらとも言えない、
 * または両方に当てはまる場合は判定せず、呼び出し側（ホーム画面）で
 * 利用者に選んでもらう。自動では登録しない。
 *
 * アプリをまたぐ受け渡しは sessionStorage を使う（この端末・このタブの中だけ）。
 * 通信は行わない。テストは apps/tests/scanrouter.test.mjs（ブラウザ不要）。
 */
(function (global) {
  "use strict";

  var KEY = "pendingScan";
  var MAX_AGE_MS = 5 * 60 * 1000; // 古い受け渡しは事故防止のため使わない
  var DEST = { receipt: "kakeibo/index.html", meeting: "docs-tracker/index.html" };

  /**
   * 撮影結果（Vision の行データ）から、レシートか会議の通知かを判定する。
   * 戻り値: { type: "receipt"|"meeting"|"ambiguous"|"unknown", lines, receipt, meetings }
   */
  function classify(lines) {
    var receipt = global.Receipt ? global.Receipt.parse(lines) : null;
    var rows = receipt ? receipt.rows : [];
    var meetings = global.Meeting ? global.Meeting.parse(rows, {}) : [];

    var looksReceipt = !!(receipt && receipt.total);
    // 日付だけでは会議とみなさない（レシートにも日付は載っているため）。
    // 会議名らしい見出し（TITLE_HINT）が取れているものだけを数える
    var looksMeeting = meetings.some(function (m) { return !!m.title; });

    var type = "unknown";
    if (looksReceipt && looksMeeting) type = "ambiguous";
    else if (looksReceipt) type = "receipt";
    else if (looksMeeting) type = "meeting";

    return { type: type, lines: lines, receipt: receipt, meetings: meetings };
  }

  /** 振り分け先に渡すデータを控える。呼び出し側は、この後で利用者の操作により移動すること */
  function handoff(type, lines) {
    if (!DEST[type]) return false;
    try {
      global.sessionStorage.setItem(KEY, JSON.stringify({ type: type, lines: lines, at: Date.now() }));
      return true;
    } catch (e) {
      return false;
    }
  }

  /** 振り分け先のアプリが、自分宛ての受け渡しを受け取る。一度取り出したら消える */
  function takeHandoff(expectedType) {
    try {
      var raw = global.sessionStorage.getItem(KEY);
      if (!raw) return null;
      global.sessionStorage.removeItem(KEY);
      var data = JSON.parse(raw);
      if (!data || data.type !== expectedType) return null;
      if (!data.at || Date.now() - data.at > MAX_AGE_MS) return null;
      return data.lines;
    } catch (e) {
      return null;
    }
  }

  function destinationFor(type) { return DEST[type] || null; }

  global.ScanRouter = {
    classify: classify,
    handoff: handoff,
    takeHandoff: takeHandoff,
    destinationFor: destinationFor
  };
})(typeof window !== "undefined" ? window : this);
