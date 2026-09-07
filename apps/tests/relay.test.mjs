/*
 * server/server.mjs（中継サーバー）と apps/messenger/net.js の通信部分のテスト。
 * 実際にサーバーを起動し、2人ぶんの端末を模して暗号化メッセージをやりとりする。
 *
 *   node apps/tests/relay.test.mjs
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const fake = {};
new Function("window", fs.readFileSync(path.join(ROOT, "apps/messenger/crypto.js"), "utf8"))(fake);
const MC = fake.MsgCrypto;

let failures = 0;
const ok = (cond, label) => {
  console.log((cond ? "  PASS  " : "  FAIL  ") + label);
  if (!cond) failures++;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ---------------- サーバーの起動 ---------------- */

const PORT = 8900 + Math.floor(Math.random() * 200);
const BASE = `http://127.0.0.1:${PORT}`;
const DATA_FILE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "relay-test-")), "relay.json");

function startServer() {
  const child = spawn(process.execPath, [path.join(ROOT, "server/server.mjs")], {
    env: { ...process.env, PORT: String(PORT), DATA_FILE, RETAIN_DAYS: "7" },
    stdio: ["ignore", "pipe", "pipe"]
  });
  child.stderr.on("data", (b) => console.error("  [server] " + String(b).trim()));
  return child;
}

async function waitForHealth(timeoutMs = 8000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try {
      const res = await fetch(BASE + "/health");
      if (res.ok) return res.json();
    } catch (e) { /* まだ起動中 */ }
    await sleep(100);
  }
  throw new Error("サーバーが起動しませんでした");
}

let server = startServer();
const health = await waitForHealth();

/* ---------------- 端末側のふるまい ---------------- */

const post = (route, body) =>
  fetch(BASE + route, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

const register = (identity) =>
  post("/register", { id: identity.id, signPub: identity.sign.pub, dhPub: identity.dh.pub });

async function sendEnvelope(identity, to, envelope) {
  const e = JSON.stringify(envelope);
  const ts = Date.now();
  const digest = MC.b64(await MC.sha256(MC.toBytes(e)));
  const sig = await MC.sign(identity, `send|${to}|${ts}|${digest}`);
  return post("/send", { to, from: identity.id, ts, sig, e });
}

async function ack(identity, ids) {
  const ts = Date.now();
  const sig = await MC.sign(identity, `ack|${identity.id}|${ts}|${ids.join(",")}`);
  return post("/ack", { id: identity.id, ts, sig, ids });
}

// 受信の口を開き、届いた封筒を配列にためる（ブラウザの EventSource と同じ形式を自前で読む）
async function openInbox(identity) {
  const ts = Date.now();
  const sig = await MC.sign(identity, `inbox|${identity.id}|${ts}`);
  const controller = new AbortController();
  const res = await fetch(`${BASE}/inbox?id=${identity.id}&ts=${ts}&sig=${encodeURIComponent(sig)}`,
    { signal: controller.signal });
  const inbox = { status: res.status, items: [], ready: false, close: () => controller.abort() };
  if (!res.ok) { inbox.error = await res.json(); return inbox; }

  (async () => {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const event = (block.match(/^event: (.*)$/m) || [])[1];
          const data = (block.match(/^data: (.*)$/m) || [])[1];
          if (event === "message") inbox.items.push(JSON.parse(data));
          if (event === "ready") inbox.ready = true;
        }
      }
    } catch (e) { /* close() による中断 */ }
  })();

  for (let i = 0; i < 100 && !inbox.ready; i++) await sleep(20);
  return inbox;
}

const waitFor = async (fn, ms = 3000) => {
  const until = Date.now() + ms;
  while (Date.now() < until) { if (fn()) return true; await sleep(20); }
  return false;
};

/* ---------------- 登録 ---------------- */
console.log("== 起動と登録 ==");
ok(health.ok === true, "/health が応答する");
ok(health.retainDays === 7, "保存期限が7日と表示される");

const alice = await MC.createIdentity("あきひと");
const bob = await MC.createIdentity("たろう");
ok((await register(alice)).status === 200, "登録できる");
ok((await register(bob)).status === 200, "相手も登録できる");
ok((await register(alice)).status === 200, "同じ内容の登録は何度でも通る");

const wrongId = await post("/register", { id: bob.id, signPub: alice.sign.pub, dhPub: alice.dh.pub });
ok(wrongId.status === 400, "他人の宛先番号では登録できない（なりすまし防止）");
ok((await post("/register", { id: "x", signPub: "AA", dhPub: "BB" })).status === 400, "壊れた公開鍵は受け付けない");

const serverId = await (await fetch(BASE + "/health")).json();
ok(serverId.users === 2, "登録者数が数えられている");

/* ---------------- 署名の確認 ---------------- */
console.log("== 本人確認（署名）==");
{
  const envelope = { h: { dh: "x", pn: 0, n: 0 }, c: "AAAA" };
  const e = JSON.stringify(envelope);
  const digest = MC.b64(await MC.sha256(MC.toBytes(e)));
  const ts = Date.now();

  const good = await sendEnvelope(alice, bob.id, envelope);
  ok(good.status === 200, "正しい署名なら預かってもらえる");

  const forged = await post("/send", { to: bob.id, from: alice.id, ts, sig: await MC.sign(bob, `send|${bob.id}|${ts}|${digest}`), e });
  ok(forged.status === 401, "他人になりすました署名は拒まれる");

  const stale = Date.now() - 20 * 60 * 1000;
  const old = await post("/send", { to: bob.id, from: alice.id, ts: stale, sig: await MC.sign(alice, `send|${bob.id}|${stale}|${digest}`), e });
  ok(old.status === 401, "古い署名は拒まれる（使い回し防止）");

  const tampered = await post("/send", { to: bob.id, from: alice.id, ts, sig: await MC.sign(alice, `send|${bob.id}|${ts}|${digest}`), e: e + " " });
  ok(tampered.status === 401, "本文をすり替えると拒まれる");

  const stranger = await MC.createIdentity("未登録");
  ok((await sendEnvelope(stranger, bob.id, envelope)).status === 401, "登録していない人は送れない");
  ok((await sendEnvelope(alice, "存在しない宛先番号", envelope)).status === 404, "宛先が無ければ預からない");

  const noSig = await post("/ack", { id: alice.id, ts: Date.now(), ids: [] });
  ok(noSig.status === 401, "署名なしの削除は拒まれる");
}

/* ---------------- 受け取りと削除 ---------------- */
console.log("== 受け取り（預かった順に流れてくる）==");
const inbox = await openInbox(bob);
ok(inbox.status === 200, "受信の口を開ける");
ok(await waitFor(() => inbox.items.length >= 1), "つないだ時点で預かり分が流れてくる");
ok(inbox.items[0].from === alice.id, "差出人がわかる");
ok(JSON.parse(inbox.items[0].e).c === "AAAA", "封筒の中身がそのまま届く");

await sendEnvelope(alice, bob.id, { h: { dh: "y", pn: 0, n: 1 }, c: "BBBB" });
ok(await waitFor(() => inbox.items.length >= 2), "つないでいる間は届いた分がすぐ流れてくる");

{
  const badInbox = await openInbox({ ...bob, sign: alice.sign });
  ok(badInbox.status === 401, "他人の受信の口は開けない");
}

const removed = await (await ack(bob, inbox.items.map((m) => m.id))).json();
ok(removed.removed === 2, "受け取り済みとして消せる");
inbox.close();
await sleep(100);

{
  const again = await openInbox(bob);
  ok(again.items.length === 0, "消したあとは同じものが再送されない");
  again.close();
}

/* ---------------- サーバーには暗号文しか残らない ---------------- */
console.log("== サーバーに残るもの ==");
{
  await sendEnvelope(alice, bob.id, { h: { dh: "z", pn: 0, n: 2 }, c: "秘密ではない目印" });
  await sleep(1300);   // 保存の間隔（1秒）を待つ
  const saved = fs.readFileSync(DATA_FILE, "utf8");
  ok(saved.includes(bob.id), "宛先は残る（配送に必要なため）");
  ok(!saved.includes(alice.sign.priv.d) && !saved.includes(bob.dh.priv.d), "秘密鍵はサーバーに存在しない");
  const parsed = JSON.parse(saved);
  ok(Object.keys(parsed.users[bob.id]).sort().join(",") === "at,dhPub,signPub", "利用者について持つのは公開鍵と登録日時だけ");
  ok(Object.keys(parsed.queues[bob.id][0]).sort().join(",") === "at,e,from,id", "封筒について持つのは差出人・時刻・暗号文だけ");
}

/* ---------------- 再起動しても預かり分は残る ---------------- */
console.log("== 再起動 ==");
{
  server.kill("SIGTERM");
  await sleep(400);
  server = startServer();
  await waitForHealth();
  const after = await openInbox(bob);
  ok(after.items.length === 1, "再起動しても預かり中の封筒は消えない");
  await ack(bob, after.items.map((m) => m.id));
  after.close();
}

/* ---------------- 大きすぎる封筒 ---------------- */
console.log("== 大きさの上限 ==");
{
  const huge = "x".repeat(3 * 1024 * 1024);
  const res = await post("/send", { to: bob.id, from: alice.id, ts: Date.now(), sig: "AA", e: huge })
    .catch(() => ({ status: 0 }));
  ok(res.status === 400 || res.status === 413 || res.status === 0, "大きすぎる封筒は受け付けない");
  ok((await fetch(BASE + "/health")).ok, "そのあともサーバーは動き続ける");
}

/* ---------------- 端から端までの往復 ---------------- */
console.log("== 端から端まで（暗号化したまま中継する）==");
{
  const invite = await MC.createInvite(alice);
  const accepted = await MC.acceptInvite(bob, invite.code);
  const completed = await MC.completeInvite(alice, invite.pending, accepted.replyCode);
  let sa = completed.session, sb = accepted.session;

  const bobInbox = await openInbox(bob);
  const photo = MC.b64(new Uint8Array(80 * 1024).fill(7));
  const enc = await MC.encrypt(sa, { t: "写真を送ります", img: photo, mime: "image/jpeg" });
  sa = enc.session;
  ok((await sendEnvelope(alice, bob.id, enc.envelope)).status === 200, "暗号化した写真つきメッセージを預けられる");
  ok(await waitFor(() => bobInbox.items.length >= 1, 5000), "相手の端末に届く");

  const received = bobInbox.items[0];
  ok(!received.e.includes("写真を送ります"), "中継の途中では本文が読めない");
  const dec = await MC.decrypt(sb, JSON.parse(received.e));
  sb = dec.session;
  ok(dec.payload.t === "写真を送ります", "受け取った端末では本文が読める");
  ok(dec.payload.img === photo, "写真もそのまま復元される");

  const aliceInbox = await openInbox(alice);
  const back = await MC.encrypt(sb, { t: "受け取りました" });
  sb = back.session;
  await sendEnvelope(bob, alice.id, back.envelope);
  ok(await waitFor(() => aliceInbox.items.length >= 1), "返事も届く");
  const decBack = await MC.decrypt(sa, JSON.parse(aliceInbox.items[0].e));
  ok(decBack.payload.t === "受け取りました", "返事を読める");

  bobInbox.close();
  aliceInbox.close();
}

server.kill("SIGTERM");
await sleep(200);
console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
