/*
 * メッセージの中継サーバー。
 *
 * このサーバーがすることは「暗号文の入った封筒を、宛先の人が取りに来るまで預かる」ことだけ。
 * 封筒の中身（本文・写真）は端末の中で暗号化されており、ここでは開けない。開ける鍵も持たない。
 * 中継役として次のものは扱う（＝運営者には見える）ことを、利用者に必ず伝えること。
 *   - 誰から誰へ送られたか（公開鍵から機械的に決まる32文字の宛先番号）
 *   - 送られた時刻と、暗号文の大きさ
 *
 * 外部ライブラリは使わない。Node.js だけで動く。
 *   node server/server.mjs
 *
 * 環境変数
 *   PORT        待ち受けポート（既定 8787）
 *   DATA_FILE   預かり中の封筒を保存する場所（既定 server/data/relay.json）
 *   RETAIN_DAYS 受け取られないまま消すまでの日数（既定 7）
 *   ORIGIN      許可する接続元（既定 * ＝どこからでも。署名で本人確認するため広くてよい）
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8787);
const DATA_FILE = process.env.DATA_FILE || path.join(HERE, "data", "relay.json");
const RETAIN_MS = Number(process.env.RETAIN_DAYS || 7) * 24 * 60 * 60 * 1000;
const ORIGIN = process.env.ORIGIN || "*";

const MAX_BODY = 2 * 1024 * 1024;   // 受け付ける本文の上限（写真1枚を見込んで2MB）
const MAX_QUEUE = 500;              // 1人あたり預かれる通数
const CLOCK_SKEW_MS = 5 * 60 * 1000; // 署名の有効時間（端末の時計のずれを見込む）
const SEND_PER_MINUTE = 120;        // 1人あたりの送信数の上限

const subtle = globalThis.crypto.subtle;

/* ---------------- 保存（受け取られるまで預かるだけ） ---------------- */

const db = { users: {}, queues: {} };   // users[id] = {signPub, dhPub, at} / queues[id] = [封筒...]
let dirty = false;

function load() {
  try {
    const saved = JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));
    Object.assign(db.users, saved.users || {});
    Object.assign(db.queues, saved.queues || {});
    log(`保存されていたデータを読み込みました（利用者 ${Object.keys(db.users).length} 人）`);
  } catch (e) {
    if (e.code !== "ENOENT") log("保存ファイルを読めませんでした: " + e.message);
  }
}

function save() {
  if (!dirty) return;
  dirty = false;
  try {
    fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
    const tmp = DATA_FILE + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(db));
    fs.renameSync(tmp, DATA_FILE);   // 書き込み途中で落ちても壊れないように差し替える
  } catch (e) {
    log("保存に失敗しました: " + e.message);
    dirty = true;
  }
}

/* ---------------- 本人確認（公開鍵による署名） ---------------- */

function unb64(text) {
  return new Uint8Array(Buffer.from(String(text).replace(/-/g, "+").replace(/_/g, "/"), "base64"));
}
function b64(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// 宛先番号は公開鍵から機械的に決まる。別人が同じ番号を名乗ることはできない
// （apps/messenger/crypto.js の idFromKeys と同じ計算。apps/tests/relay.test.mjs で一致を確認している）
async function idFromKeys(signPub, dhPub) {
  const material = Buffer.concat([unb64(signPub), unb64(dhPub)]);
  return b64(new Uint8Array(await subtle.digest("SHA-256", material))).slice(0, 32);
}

async function verifySignature(signPub, text, signature) {
  try {
    const key = await subtle.importKey("raw", unb64(signPub), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
    return await subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, unb64(signature), Buffer.from(text, "utf8"));
  } catch (e) {
    return false;
  }
}

async function sha256b64(text) {
  return b64(new Uint8Array(await subtle.digest("SHA-256", Buffer.from(text, "utf8"))));
}

// 署名を確かめる。宛先番号が登録済みで、時刻が近く、署名が合っていることの3点
async function authenticate(id, ts, sig, text) {
  const user = db.users[id];
  if (!user) return "この宛先番号は登録されていません";
  if (!Number.isFinite(ts) || Math.abs(Date.now() - ts) > CLOCK_SKEW_MS) return "時刻がずれています";
  if (typeof sig !== "string" || !sig) return "署名がありません";
  if (!(await verifySignature(user.signPub, text, sig))) return "署名が確かめられません";
  return null;
}

/* ---------------- 配送 ---------------- */

const streams = new Map();   // 宛先番号 → 受信待ちしている接続の集合
const sendCounts = new Map(); // 宛先番号 → [分, 件数]

function overSendLimit(id) {
  const minute = Math.floor(Date.now() / 60000);
  const seen = sendCounts.get(id);
  if (!seen || seen[0] !== minute) {
    sendCounts.set(id, [minute, 1]);
    return false;
  }
  seen[1] += 1;
  return seen[1] > SEND_PER_MINUTE;
}

function push(id, item) {
  const queue = db.queues[id] || (db.queues[id] = []);
  queue.push(item);
  while (queue.length > MAX_QUEUE) queue.shift();   // 古いものから捨てる
  dirty = true;

  for (const res of streams.get(id) || []) {
    writeEvent(res, "message", item);
  }
}

function writeEvent(res, event, data) {
  try {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  } catch (e) { /* 切断済み。次の掃除で取り除かれる */ }
}

function sweep() {
  const limit = Date.now() - RETAIN_MS;
  let removed = 0;
  for (const id of Object.keys(db.queues)) {
    const before = db.queues[id].length;
    db.queues[id] = db.queues[id].filter((m) => m.at > limit);
    removed += before - db.queues[id].length;
    if (db.queues[id].length === 0) delete db.queues[id];
  }
  if (removed) {
    dirty = true;
    log(`${removed} 通を保存期限（${RETAIN_MS / 86400000}日）で削除しました`);
  }
}

/* ---------------- HTTP ---------------- */

function log(message) {
  console.log(new Date().toISOString() + "  " + message);
}

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", ORIGIN);
  res.setHeader("Access-Control-Allow-Headers", "content-type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Max-Age", "86400");
}

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": Buffer.byteLength(text) });
  res.end(text);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new Error("大きすぎます"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
      catch (e) { reject(new Error("JSON として読めません")); }
    });
    req.on("error", reject);
  });
}

const routes = {
  async "GET /health"(req, res) {
    const queued = Object.values(db.queues).reduce((n, q) => n + q.length, 0);
    json(res, 200, { ok: true, users: Object.keys(db.users).length, queued, retainDays: RETAIN_MS / 86400000 });
  },

  // 宛先番号の登録。番号は公開鍵から決まるので、他人になりすますことはできない
  async "POST /register"(req, res) {
    const body = await readJson(req);
    if (typeof body.signPub !== "string" || typeof body.dhPub !== "string") {
      return json(res, 400, { error: "公開鍵がありません" });
    }
    if (unb64(body.signPub).length !== 65 || unb64(body.dhPub).length !== 65) {
      return json(res, 400, { error: "公開鍵の形式が違います" });
    }
    const id = await idFromKeys(body.signPub, body.dhPub);
    if (id !== body.id) return json(res, 400, { error: "宛先番号が公開鍵と一致しません" });

    const known = db.users[id];
    if (known && (known.signPub !== body.signPub || known.dhPub !== body.dhPub)) {
      return json(res, 409, { error: "登録済みの鍵と違います" });
    }
    if (!known) {
      db.users[id] = { signPub: body.signPub, dhPub: body.dhPub, at: Date.now() };
      dirty = true;
      log(`登録: ${id}`);
    }
    json(res, 200, { ok: true, id });
  },

  // 封筒を預ける。中身（e）は文字列のまま扱い、サーバーでは開かない
  async "POST /send"(req, res) {
    const body = await readJson(req);
    const { to, from, ts, sig, e } = body;
    if (typeof to !== "string" || typeof e !== "string" || !e) {
      return json(res, 400, { error: "宛先または本文がありません" });
    }
    if (e.length > MAX_BODY) return json(res, 413, { error: "大きすぎます" });

    const bad = await authenticate(from, Number(ts), sig, `send|${to}|${ts}|${await sha256b64(e)}`);
    if (bad) return json(res, 401, { error: bad });
    if (!db.users[to]) return json(res, 404, { error: "宛先が登録されていません" });
    if (overSendLimit(from)) return json(res, 429, { error: "送信が多すぎます。しばらく待ってください" });

    const item = { id: b64(globalThis.crypto.getRandomValues(new Uint8Array(12))), from, at: Date.now(), e };
    push(to, item);
    json(res, 200, { ok: true, id: item.id });
  },

  // 受け取り。つないでいる間、届いた封筒がそのまま流れてくる（Server-Sent Events）
  async "GET /inbox"(req, res, url) {
    const id = url.searchParams.get("id") || "";
    const ts = Number(url.searchParams.get("ts"));
    const sig = url.searchParams.get("sig") || "";
    const bad = await authenticate(id, ts, sig, `inbox|${id}|${ts}`);
    if (bad) return json(res, 401, { error: bad });

    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      "connection": "keep-alive",
      "x-accel-buffering": "no",
      "access-control-allow-origin": ORIGIN
    });
    res.write("retry: 3000\n\n");

    if (!streams.has(id)) streams.set(id, new Set());
    streams.get(id).add(res);

    for (const item of db.queues[id] || []) writeEvent(res, "message", item);
    writeEvent(res, "ready", { at: Date.now() });

    const beat = setInterval(() => { try { res.write(": keepalive\n\n"); } catch (err) {} }, 25000);
    const close = () => {
      clearInterval(beat);
      const set = streams.get(id);
      if (set) {
        set.delete(res);
        if (set.size === 0) streams.delete(id);
      }
    };
    req.on("close", close);
    req.on("error", close);
  },

  // 受け取り終えた封筒を消す
  async "POST /ack"(req, res) {
    const body = await readJson(req);
    const { id, ts, sig } = body;
    const ids = Array.isArray(body.ids) ? body.ids.map(String) : [];
    const bad = await authenticate(id, Number(ts), sig, `ack|${id}|${ts}|${ids.join(",")}`);
    if (bad) return json(res, 401, { error: bad });

    const queue = db.queues[id] || [];
    const drop = new Set(ids);
    const kept = queue.filter((m) => !drop.has(m.id));
    const removed = queue.length - kept.length;
    if (kept.length) db.queues[id] = kept; else delete db.queues[id];
    if (removed) dirty = true;
    json(res, 200, { ok: true, removed });
  }
};

const server = http.createServer(async (req, res) => {
  cors(res);
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }

  const url = new URL(req.url, "http://localhost");
  if (req.method === "GET" && url.pathname === "/") {
    res.writeHead(200, { "content-type": "text/plain; charset=utf-8" });
    return res.end(
      "暗号化メッセージの中継サーバーです。\n" +
      "預かっているのは端末側で暗号化された封筒だけで、本文や写真をこのサーバーで開くことはできません。\n" +
      `受け取られないままの封筒は ${RETAIN_MS / 86400000} 日で削除します。\n`);
  }

  const handler = routes[`${req.method} ${url.pathname}`];
  if (!handler) return json(res, 404, { error: "そのような窓口はありません" });
  try {
    await handler(req, res, url);
  } catch (err) {
    if (!res.headersSent) json(res, 400, { error: err.message });
  }
});

load();
sweep();
setInterval(sweep, 10 * 60 * 1000).unref();
setInterval(save, 1000).unref();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => { save(); log("終了します"); process.exit(0); });
}

if (process.env.NODE_ENV !== "test") {
  server.listen(PORT, () => log(`中継サーバーを起動しました: http://localhost:${PORT}`));
}

export { server, db, idFromKeys, PORT };
