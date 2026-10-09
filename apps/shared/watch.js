/*
 * Apple Watch へ送る一覧を組み立て、iPhone アプリ側のプラグインに渡す。
 *
 * 送るのは次の3つだけで、どれも「手首を見て動けるか」を基準に選んでいる。
 *   今日と明日の会議 / 期限が近い書類 / 買い物リスト
 *
 * アプリはどれも同じ場所（localStorage）に保存しているため、どのアプリを開いていても
 * 全体をまとめて作れる（inbox.js と同じ考え方）。
 *
 * 通信について: 送り先は Apple Watch（WatchConnectivity）だけで、外部のサーバーには
 * 一切送らない。iPhone と Apple Watch の間の直接通信であり、インターネットを経由しない。
 *
 * ブラウザで開いているときは push() が何もせずに終わる（プラグインが無いため）。
 */
(function (global) {
  "use strict";

  var PLUGIN = "WatchBridge";
  var MEETING_DAYS = 7;      // 会議は1週間先まで
  var DEADLINE_DAYS = 14;    // 期限は2週間先まで
  var SHOPPING_DAYS = 14;    // 使い切ってから買い足すまでの目安
  var MAX = 20;              // 手首で追える件数の上限。これ以上は送らない

  var OPEN_STATUSES = ["未着手", "対応中", "提出済"];

  function pad(n) { return String(n).padStart(2, "0"); }

  function ymd(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function read(key) {
    try {
      var raw = global.localStorage.getItem(key);
      if (!raw) return null;
      var data = JSON.parse(raw);
      return data && typeof data === "object" ? data : null;
    } catch (e) {
      // 壊れたデータでも Apple Watch への送信だけは止めない（そのぶんを空にする）
      return null;
    }
  }

  function daysUntil(today, dateStr) {
    if (!dateStr) return null;
    var a = new Date(today + "T00:00:00");
    var b = new Date(dateStr + "T00:00:00");
    if (isNaN(a) || isNaN(b)) return null;
    return Math.round((b - a) / 86400000);
  }

  // 会議のメモから開始時刻と懇親会の有無を取り出す（書式は docs-tracker の meetingNote）
  function meetingDetail(note) {
    var time = "", social = "";
    String(note || "").split("\n").forEach(function (line) {
      var t = line.trim();
      if (/^\d{1,2}:\d{2}/.test(t)) time = t.replace(/\s*開始$/, "");
      else if (/懇親会/.test(t)) social = t;
    });
    return { time: time, social: social };
  }

  function isOpen(item) { return OPEN_STATUSES.indexOf(item && item.status) >= 0; }

  function docsLists(today) {
    var data = read("docs-tracker.v1");
    var items = (data && data.items) || [];
    var meetings = [], deadlines = [];
    items.forEach(function (it) {
      if (!isOpen(it)) return;
      var days = daysUntil(today, it.dueOn);
      if (days === null) return;
      // 手帳から入れた「予定」も、会議と同じく日時のある予定として扱う（過ぎたら出さない）
      if (it.kind === "会議" || it.kind === "予定") {
        if (days < 0 || days > MEETING_DAYS) return;
        var d = meetingDetail(it.note);
        meetings.push({
          id: it.id,
          title: it.title,
          date: it.dueOn,
          days: days,
          time: d.time,
          place: it.dest || "",
          social: d.social
        });
        return;
      }
      if (days > DEADLINE_DAYS) return;   // 期限切れ（マイナス）は残す。まだ終わっていないため
      deadlines.push({
        id: it.id,
        title: it.title,
        date: it.dueOn,
        days: days,
        kind: it.kind || "",
        dest: it.dest || "",
        status: it.status || ""
      });
    });
    var byDays = function (a, b) { return a.days - b.days; };
    return { meetings: meetings.sort(byDays).slice(0, MAX), deadlines: deadlines.sort(byDays).slice(0, MAX) };
  }

  // 冷蔵庫：直近に使い切り、いま在庫に無いもの（廃棄したものは買い直すとは限らないため入れない）
  function fridgeShopping(now) {
    var data = read("fridge.v1");
    if (!data) return [];
    var since = now - SHOPPING_DAYS * 86400000;
    var inStock = {};
    (data.items || []).forEach(function (it) { inStock[it.name] = true; });
    var seen = {}, out = [];
    (data.log || []).slice().reverse().forEach(function (l) {
      if (!l || l.action !== "consume" || !l.name) return;
      if (new Date(l.at).getTime() < since) return;
      if (inStock[l.name] || seen[l.name]) return;
      seen[l.name] = true;
      out.push({ name: l.name, from: "冷蔵庫" });
    });
    return out;
  }

  // 備蓄：最低在庫数を下回ったもの（最低在庫数が未設定でも、残り0なら対象）
  function stockShopping() {
    var data = read("stock.v1");
    if (!data) return [];
    var out = [];
    (data.items || []).forEach(function (it) {
      var have = Number(it.qty);
      if (isNaN(have)) have = 0;
      var min = it.minQty === null || it.minQty === undefined || it.minQty === "" ? null : Number(it.minQty);
      var gap = 0;
      if (min !== null && !isNaN(min) && have < min) gap = min - have;
      else if (have === 0) gap = 1;
      if (gap <= 0) return;
      out.push({
        name: it.name + (min !== null && !isNaN(min) ? " あと" + gap + (it.unit || "") : ""),
        from: "備蓄"
      });
    });
    return out;
  }

  /**
   * Apple Watch に送る一覧を作る。
   * options: { today: "YYYY-MM-DD", now: ミリ秒 }（テスト用。省略すると今の時刻）
   */
  function snapshot(options) {
    var opts = options || {};
    var now = opts.now || Date.now();
    var today = opts.today || ymd(new Date(now));
    var lists = docsLists(today);
    return {
      version: 1,
      today: today,
      updatedAt: new Date(now).toISOString(),
      meetings: lists.meetings,
      deadlines: lists.deadlines,
      shopping: fridgeShopping(now).concat(stockShopping()).slice(0, MAX)
    };
  }

  function available() {
    try {
      var cap = global.Capacitor;
      return !!(cap &&
                typeof cap.isNativePlatform === "function" && cap.isNativePlatform() &&
                typeof cap.nativePromise === "function");
    } catch (e) {
      return false;
    }
  }

  /**
   * 今の一覧を Apple Watch へ送る。
   * ブラウザで開いているときや、Apple Watch を持っていないときは何もしない。
   * 戻り値: { ok, reason }（失敗しても画面には出さない。送れないこと自体は不具合ではないため）
   */
  function push(options) {
    if (!available()) return Promise.resolve({ ok: false, reason: "not-native" });
    var data;
    try {
      data = snapshot(options);
    } catch (e) {
      return Promise.resolve({ ok: false, reason: "snapshot-failed" });
    }
    return global.Capacitor.nativePromise(PLUGIN, "sync", { payload: JSON.stringify(data) })
      .then(function (res) {
        return { ok: !!(res && res.ok), reason: (res && res.reason) || "" };
      }, function (e) {
        return { ok: false, reason: (e && e.message) || "sync-failed" };
      });
  }

  function readBlob(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new global.FileReader();
      reader.onload = function () {
        var result = String(reader.result || "");
        var comma = result.indexOf(",");
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.onerror = function () { reject(reader.error || new Error("background-read-failed")); };
      reader.readAsDataURL(blob);
    });
  }

  /**
   * キャラクター写真を Apple Watch の背景へ送る。
   * blob が null のときは、Watch に保存されている背景を消す。
   */
  function setBackground(blob) {
    if (!available()) return Promise.resolve({ ok: false, reason: "not-supported" });
    var args = blob === null ? Promise.resolve({ clear: true }) : readBlob(blob).then(function (data) {
      return { data: data };
    });
    return args.then(function (value) {
      return global.Capacitor.nativePromise(PLUGIN, "setBackground", value);
    }).then(function (res) {
      return { ok: !!(res && res.ok), reason: (res && res.reason) || "" };
    }, function (e) {
      return { ok: false, reason: (e && e.message) || "background-failed" };
    });
  }

  global.Watch = {
    snapshot: snapshot,
    push: push,
    available: available
  };

  global.WatchSync = {
    setBackground: setBackground
  };

  // 画面を開いたときと閉じるときに送る。アプリ内の保存時は各アプリの save() から呼ぶ
  if (global.addEventListener) {
    global.addEventListener("load", function () { push(); });
    global.addEventListener("pagehide", function () { push(); });
  }
})(typeof window !== "undefined" ? window : this);
