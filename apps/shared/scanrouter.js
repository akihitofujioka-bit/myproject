/*
 * カメラで撮った書類が「レシート」「会議の通知」「手帳のページ」のどれかを判定し、
 * 適切なアプリへ振り分けるための橋渡し。
 *
 * 判定は Receipt.parse()（合計額が読み取れるか）、Meeting.parse()
 * （会議名・日付などが読み取れるか）、Planner.parse()（手帳の日付の並びが
 * 読み取れるか）の結果を使う。どれとも言えない、または複数に当てはまる場合は
 * 判定せず、呼び出し側（ホーム画面）で利用者に選んでもらう。自動では登録しない。
 *
 * アプリをまたぐ受け渡しは sessionStorage を使う（この端末・このタブの中だけ）。
 * 通信は行わない。テストは apps/tests/scanrouter.test.mjs（ブラウザ不要）。
 */
(function (global) {
  "use strict";

  var KEY = "pendingScan";
  var MAX_AGE_MS = 5 * 60 * 1000; // 古い受け渡しは事故防止のため使わない
  var DEST = { receipt: "kakeibo/index.html", meeting: "docs-tracker/index.html", planner: "docs-tracker/index.html" };

  // レシートにだけ出てくる語。「合計」の見出しが読めなかったときの裏付けに使う
  var RECEIPT_WORDS = /小\s*計|お預|預り|お釣|釣銭|おつり|領収|税込|内税|外税|消費税|税率|対象|レジ|\d+\s*点|お買上|お買い上げ|現金|クレジット|電子マネー/;

  /**
   * レシートらしいか。
   * 以前は「金額らしい数字が1つでもあればレシート」としていたため、
   * 手帳に「3,000円」と書いてあるだけでレシートと判定していた（2026-10-01 修正）。
   * 「合計」などの見出しで合計額が取れたとき、または金額に加えてレシート特有の語か
   * 明細が2行以上あるときだけレシートとみなす。
   */
  function looksLikeReceipt(receipt) {
    if (!receipt || !receipt.total) return false;
    if (receipt.total.confidence === "high") return true;
    var joined = (receipt.rows || []).join("\n");
    return RECEIPT_WORDS.test(joined) || (receipt.items || []).length >= 2;
  }

  /**
   * 撮影結果（Vision の行データ）から、レシート・会議の通知・手帳のどれかを判定する。
   * 戻り値: { type: "receipt"|"meeting"|"planner"|"ambiguous"|"unknown",
   *          lines, receipt, meetings, planner, candidates }
   *   candidates … 当てはまった種類（ambiguous のとき、選んでもらう候補に使う）
   */
  function classify(lines, opts) {
    var receipt = global.Receipt ? global.Receipt.parse(lines) : null;
    var rows = receipt ? receipt.rows : [];
    var meetings = global.Meeting ? global.Meeting.parse(rows, {}) : [];
    var planner = global.Planner ? global.Planner.parse(lines, opts) : null;
    var plannerStrength = global.Planner ? global.Planner.strength(planner) : "";

    var looksReceipt = looksLikeReceipt(receipt);
    // 日付だけでは会議とみなさない（レシートにも日付は載っているため）。
    // 会議名らしい見出し（TITLE_HINT）が取れているものだけを数える
    var looksMeeting = meetings.some(function (m) { return !!m.title; });

    var candidates = [];
    if (plannerStrength === "strong" && planner.kind === "month") {
      // 月間のマス目の格子は、レシートや通知では起こらない。マスに「会議」と
      // 書いてあっても、金額が書いてあっても手帳として扱う
      candidates = ["planner"];
    } else {
      if (looksReceipt) candidates.push("receipt");
      if (looksMeeting) candidates.push("meeting");
      if (plannerStrength) candidates.push("planner");
      // 日付の行が3つ以上並ぶ手帳は、会議名らしい語（「会議」と書いた予定）があっても手帳を先に出す
      if (plannerStrength === "strong" && candidates.length > 1 && !looksReceipt) candidates = ["planner"];
    }

    var type = "unknown";
    if (candidates.length === 1) type = candidates[0];
    else if (candidates.length > 1) type = "ambiguous";

    return { type: type, lines: lines, receipt: receipt, meetings: meetings, planner: planner, candidates: candidates };
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

  /** 振り分け先のアプリが、自分宛ての受け渡しを受け取る。一度取り出したら消える（古いものも消す） */
  function takeHandoff(expectedType) {
    try {
      var raw = global.sessionStorage.getItem(KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      // 宛先が違うものは消さずに残す。書類トラッカーは「会議」と「手帳」の両方を
      // 受け取るため、先に会議側が見たときに手帳宛てのものを消してしまわないように
      if (data && data.type !== expectedType && data.at && Date.now() - data.at <= MAX_AGE_MS) return null;
      global.sessionStorage.removeItem(KEY);
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
    destinationFor: destinationFor,
    looksLikeReceipt: looksLikeReceipt
  };
})(typeof window !== "undefined" ? window : this);
