/*
 * 中継サーバーとのやりとり。
 *
 * 送るのは「宛先番号・時刻・署名・暗号文」だけで、本文や写真はすでに暗号化されている。
 * サーバーに自分だと示すため、送信・受信・削除のたびに自分の署名鍵で短い文面に署名する
 * （合言葉やパスワードは使わない。使い回されない仕組みにするため時刻を必ず含める）。
 */
(function (global) {
  "use strict";

  var RETRY_MIN = 1000;
  var RETRY_MAX = 30000;

  function trimUrl(url) {
    return String(url || "").trim().replace(/\/+$/, "");
  }

  async function request(server, route, options) {
    var res = await fetch(trimUrl(server) + route, options);
    var body = null;
    try { body = await res.json(); } catch (e) { /* 本文なし */ }
    if (!res.ok) {
      var reason = (body && body.error) || ("サーバーが " + res.status + " を返しました");
      var err = new Error(reason);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function postJson(server, route, payload) {
    return request(server, route, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });
  }

  // 自分の宛先番号を中継サーバーに知らせる（相手が自分宛てに預けられるようにするため）
  function register(server, identity) {
    return postJson(server, "/register", {
      id: identity.id, signPub: identity.sign.pub, dhPub: identity.dh.pub
    });
  }

  function health(server) {
    return request(server, "/health", { method: "GET" });
  }

  async function send(server, identity, to, envelope) {
    var e = JSON.stringify(envelope);
    var ts = Date.now();
    var digest = global.MsgCrypto.b64(await global.MsgCrypto.sha256(global.MsgCrypto.toBytes(e)));
    var sig = await global.MsgCrypto.sign(identity, "send|" + to + "|" + ts + "|" + digest);
    return postJson(server, "/send", { to: to, from: identity.id, ts: ts, sig: sig, e: e });
  }

  // 受け取り済みとして中継サーバーから消す。これを呼ばないとサーバーに残り続ける
  async function ack(server, identity, ids) {
    if (!ids.length) return { ok: true, removed: 0 };
    var ts = Date.now();
    var sig = await global.MsgCrypto.sign(identity, "ack|" + identity.id + "|" + ts + "|" + ids.join(","));
    return postJson(server, "/ack", { id: identity.id, ts: ts, sig: sig, ids: ids });
  }

  async function inboxUrl(server, identity) {
    var ts = Date.now();
    var sig = await global.MsgCrypto.sign(identity, "inbox|" + identity.id + "|" + ts);
    return trimUrl(server) + "/inbox?id=" + encodeURIComponent(identity.id) +
      "&ts=" + ts + "&sig=" + encodeURIComponent(sig);
  }

  /**
   * 受信を続ける。回線が切れても自動でつなぎ直す。
   * handlers = { onMessage(item), onStatus("connecting"|"online"|"offline", detail) }
   * 戻り値の close() で止める。
   */
  function connect(server, identity, handlers) {
    var source = null;
    var timer = null;
    var wait = RETRY_MIN;
    var stopped = false;

    function status(state, detail) {
      if (handlers.onStatus) handlers.onStatus(state, detail);
    }

    function scheduleRetry(detail) {
      if (stopped) return;
      status("offline", detail);
      timer = global.setTimeout(start, wait);
      wait = Math.min(wait * 2, RETRY_MAX);
    }

    async function start() {
      if (stopped) return;
      status("connecting");
      var url;
      try {
        url = await inboxUrl(server, identity);
      } catch (e) {
        return scheduleRetry(e.message);
      }
      if (stopped) return;

      // 署名には有効時間があるため、EventSource 任せの自動再接続は使わず、毎回作り直す
      source = new global.EventSource(url);
      source.addEventListener("ready", function () {
        wait = RETRY_MIN;
        status("online");
      });
      source.addEventListener("message", function (ev) {
        try { handlers.onMessage(JSON.parse(ev.data)); } catch (e) { /* 壊れた通知は捨てる */ }
      });
      source.onerror = function () {
        if (source) { source.close(); source = null; }
        scheduleRetry("接続が切れました");
      };
    }

    start();
    return {
      close: function () {
        stopped = true;
        if (timer) global.clearTimeout(timer);
        if (source) { source.close(); source = null; }
      },
      // 画面に戻ってきたときなど、すぐつなぎ直したいとき
      refresh: function () {
        if (stopped) return;
        wait = RETRY_MIN;
        if (timer) global.clearTimeout(timer);
        if (source) { source.close(); source = null; }
        start();
      }
    };
  }

  global.MsgNet = {
    register: register,
    health: health,
    send: send,
    ack: ack,
    connect: connect,
    inboxUrl: inboxUrl,
    trimUrl: trimUrl
  };
})(typeof window !== "undefined" ? window : this);
