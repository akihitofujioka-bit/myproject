/*
 * トップ画面の「次の予定」欄。次の予定がある日に会議が2件以上あるとき、
 * 10秒ごとに1件ずつ順に出す（iPhone のロック画面ウィジェットと同じ並び）。
 *
 * 一覧は watch.js の Watch.snapshot() をそのまま使う（Watch・ウィジェットと同じ中身にするため）。
 * 選び方は Swift 側の nextDayMeetings（mobile/ios/App/WatchAppSources/Snapshot.swift）と合わせている。
 *  - 始まった会議は外す（終日の会議はその日が終わるまで残す）
 *  - いちばん近い日の会議だけを、時刻の早い順・終日は後ろに並べる
 *  - その日より前に書類の期限があるときは空にする（ウィジェットはその期限を出すため）
 *
 * 端末の中のデータを読むだけで、どこにも送らない。
 */
(function (global) {
  "use strict";

  var INTERVAL = 10000;   // 切り替えの間隔（ミリ秒）

  function startMinutes(time) {
    var m = /^(\d{1,2}):(\d{2})/.exec(String(time || ""));
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }

  /**
   * snapshot: Watch.snapshot() の戻り値。nowMinutes: 今の時刻（0時からの分）
   * 戻り値: [{ id, title, days, time }]。会議が2件未満でも、見つかった分を返す
   */
  function pick(snapshot, nowMinutes) {
    var open = ((snapshot && snapshot.meetings) || []).filter(function (m) {
      if (typeof m.days !== "number" || m.days < 0) return false;
      var start = startMinutes(m.time);
      return !(m.days === 0 && start !== null && start <= nowMinutes);
    });
    if (!open.length) return [];
    var day = Math.min.apply(null, open.map(function (m) { return m.days; }));
    var earlierDeadline = ((snapshot && snapshot.deadlines) || []).some(function (d) {
      return typeof d.days === "number" && d.days >= 0 && d.days < day;
    });
    if (earlierDeadline) return [];
    return open.filter(function (m) { return m.days === day; })
      .map(function (m) { return { id: m.id, title: m.title || "（会議）", days: m.days, time: m.time || "" }; })
      .sort(function (a, b) {
        var x = startMinutes(a.time), y = startMinutes(b.time);
        return (x === null ? 9999 : x) - (y === null ? 9999 : y);
      });
  }

  function dayLabel(d) {
    if (d === 0) return "今日";
    if (d === 1) return "明日";
    return "あと" + d + "日";
  }

  /** 時刻から何件目を出すか決める（開き直しても続きから進む。Watch の画面と同じ考え方） */
  function indexAt(count, nowMs) {
    return count ? Math.floor(nowMs / INTERVAL) % count : 0;
  }

  /** ラベルの文（「明日 終日　1/2」）。時刻は「13:00〜14:00」のように終わりまで出す */
  function detail(item, index, count) {
    return dayLabel(item.days) + " " + (startMinutes(item.time) === null ? "終日" : item.time) + "　" + (index + 1) + "/" + count;
  }

  /**
   * 欄を表示し、10秒ごとに切り替える。会議が2件未満なら欄を隠す。
   * els: { card, title, detail }
   */
  function mount(els) {
    var timer = null;
    function render() {
      var now = new Date();
      var list = [];
      try {
        list = pick(global.Watch.snapshot(), now.getHours() * 60 + now.getMinutes());
      } catch (e) {
        list = [];   // 一覧が読めなくても、トップ画面のほかの部分は動かす
      }
      if (list.length < 2) {
        els.card.hidden = true;
        return;
      }
      var i = indexAt(list.length, now.getTime());
      els.card.hidden = false;
      els.title.textContent = list[i].title;
      els.detail.textContent = detail(list[i], i, list.length);
    }
    function start() {
      if (timer) clearInterval(timer);
      render();
      timer = setInterval(render, INTERVAL);
    }
    start();
    // 画面に戻ったときは、そのとき時点の一覧で作り直す
    global.addEventListener("pageshow", start);
    global.document.addEventListener("visibilitychange", function () {
      if (!global.document.hidden) start();
    });
  }

  global.NextUp = { pick: pick, indexAt: indexAt, detail: detail, mount: mount, INTERVAL: INTERVAL };
})(typeof window !== "undefined" ? window : this);
