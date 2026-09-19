/*
 * 買い物リストを iPhone の「リマインダー」に送る。
 *
 * ねらいは Apple Watch での買い物である。Apple Watch にはリマインダー App が
 * 最初から入っているため、リマインダーに入れておけば店先で iPhone を出さずに
 * 手首だけで消し込める。
 *
 * Web のアプリからリマインダーへ直接書き込む方法は用意されていないので、
 * iPhone の「ショートカット」App を経由する（利用者が一度だけショートカットを作る）。
 * 手順は docs/apple-watch-shopping-list.md にまとめてある。
 *
 * ショートカットが使えない環境（パソコンのブラウザなど）では、文字として
 * コピーするだけにする。どちらの経路でも外部への通信は行わない。
 */
(function (global) {
  "use strict";

  var SHORTCUT_NAME = "買い物リストに追加";

  // ショートカットに文字を渡すための URL（Apple が定めている書き方）
  function url(text, name) {
    return "shortcuts://run-shortcut?name=" + encodeURIComponent(name || SHORTCUT_NAME) +
      "&input=text&text=" + encodeURIComponent(text);
  }

  // ショートカット App がある端末か
  function onIOS() {
    var cap = global.Capacitor;
    if (cap && typeof cap.isNativePlatform === "function" && cap.isNativePlatform()) return true;
    var nav = global.navigator || {};
    var ua = nav.userAgent || "";
    if (/iPad|iPhone|iPod/.test(ua)) return true;
    // iPadOS はパソコン版 Safari を名乗るため、画面に触れるかどうかで見分ける
    return /Macintosh/.test(ua) && Number(nav.maxTouchPoints) > 1;
  }

  function copy(text) {
    var nav = global.navigator;
    if (nav && nav.clipboard && nav.clipboard.writeText) {
      return nav.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  }

  function clean(names) {
    var seen = {};
    var out = [];
    (names || []).forEach(function (n) {
      var t = String(n == null ? "" : n).replace(/\s+/g, " ").trim();
      if (!t || seen[t]) return;
      seen[t] = true;
      out.push(t);
    });
    return out;
  }

  /**
   * 買い物リストを送る。
   * names: 品名の配列（重複と空白は取り除く）
   * options: { shortcutName: "...", forceCopy: true }
   * 戻り値: { ok, how, count }
   *   how = "shortcut"（ショートカットへ渡した）/ "copied"（コピーした）
   *       / "failed"（コピーもできなかった）/ "empty"（送るものが無い）
   */
  function send(names, options) {
    var opts = options || {};
    var list = clean(names);
    if (!list.length) return Promise.resolve({ ok: false, how: "empty", count: 0 });

    var text = list.join("\n");
    if (onIOS() && !opts.forceCopy) {
      // ショートカットが未作成のときは「見つかりません」と出るだけで、害はない
      global.location.href = url(text, opts.shortcutName);
      return Promise.resolve({ ok: true, how: "shortcut", count: list.length });
    }
    return copy(text).then(function (done) {
      return { ok: done, how: done ? "copied" : "failed", count: list.length };
    });
  }

  global.Reminders = {
    send: send,
    url: url,
    onIOS: onIOS,
    clean: clean,
    shortcutName: SHORTCUT_NAME
  };
})(typeof window !== "undefined" ? window : this);
