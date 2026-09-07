/*
 * apps/messenger/crypto.js（エンド・ツー・エンド暗号化）の単体テスト。ブラウザ不要。
 *
 *   node apps/tests/crypto.test.mjs
 */
import fs from "node:fs";
import path from "node:path";
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
const throws = async (fn, label) => {
  let threw = false;
  try { await fn(); } catch (e) { threw = true; }
  ok(threw, label);
};
const clone = (o) => JSON.parse(JSON.stringify(o));

/* ---------------- 身元と宛先番号 ---------------- */
console.log("== 身元（identity）==");
const alice = await MC.createIdentity("あきひと");
const bob = await MC.createIdentity("たろう");
ok(alice.id.length === 32 && bob.id.length === 32, "宛先番号は32文字");
ok(alice.id !== bob.id, "人が違えば宛先番号も違う");
ok(alice.id === await MC.idFromKeys(alice.sign.pub, alice.dh.pub), "宛先番号は公開鍵から機械的に決まる");
ok(MC.unb64(alice.dh.pub).length === 65 && MC.unb64(alice.sign.pub).length === 65, "公開鍵は65バイト（P-256）");
ok(JSON.parse(JSON.stringify(alice)).sign.priv.d === alice.sign.priv.d, "そのままJSONに保存できる");

/* ---------------- ペアリング ---------------- */
console.log("== ペアリング（招待コードの交換）==");
const invite = await MC.createInvite(alice, "https://relay.example.jp");
ok(invite.code.startsWith("MSG1.i."), "招待コードの目印");
ok(invite.code.length < 480, "招待コードは貼り付けられる長さ（" + invite.code.length + "文字）");
ok(MC.decodeCode(invite.code, "i").server === "https://relay.example.jp", "中継サーバーの場所も一緒に渡せる");
ok(!invite.code.includes(alice.sign.priv.d), "コードに秘密鍵は入らない");
ok(!invite.code.includes(invite.pending.ek.priv.d), "コードに使い捨ての秘密鍵も入らない");

const accepted = await MC.acceptInvite(bob, invite.code, "https://relay.example.jp");
ok(accepted.replyCode.startsWith("MSG1.r."), "返信コードの目印");
ok(accepted.peerServer === "https://relay.example.jp", "招待した側の中継サーバーを読み取れる");
const completed = await MC.completeInvite(alice, invite.pending, accepted.replyCode);
let sa = completed.session;   // あきひと側の会話状態
let sb = accepted.session;    // たろう側の会話状態

ok(sa.peer.id === bob.id && sb.peer.id === alice.id, "互いの宛先番号を覚える");
ok(sa.peer.name === "たろう" && sb.peer.name === "あきひと", "互いの表示名を覚える");
ok(sa.ad === sb.ad, "身元の結び付け（AD）が一致する");
ok(sa.rk === sb.rk, "根の鍵が一致する");
ok(sa.cks === sb.ckr && sa.cks !== null, "招待した側の送信鎖＝招待された側の受信鎖");
ok(sa.ckr === null && sb.cks === null, "逆向きの鎖は最初は空");

const fpA = await MC.safetyNumber(alice, sa);
const fpB = await MC.safetyNumber(bob, sb);
ok(fpA === fpB, "双方の安全番号が一致する");
ok(fpA.replace(/ /g, "").length === 60, "安全番号は60桁");
ok(/^\d{5}( \d{5}){11}$/.test(fpA), "5桁ずつ12組で表示される");

await throws(() => MC.acceptInvite(bob, accepted.replyCode), "返信コードを招待コードとして読ませない");
await throws(() => MC.completeInvite(alice, invite.pending, invite.code), "招待コードを返信コードとして読ませない");
await throws(() => MC.acceptInvite(bob, "MSG1.i.aaa.bbb.ccc.ddd"), "壊れたコードは受け付けない");
await throws(() => MC.acceptInvite(bob, "ただの文字列"), "コードでない文字列は受け付けない");

/* ---------------- メッセージの往復 ---------------- */
console.log("== メッセージの往復 ==");
const send = async (fromSession, toSession, payload) => {
  const e = await MC.encrypt(fromSession, payload);
  const d = await MC.decrypt(toSession, e.envelope);
  return { from: e.session, to: d.session, payload: d.payload, envelope: e.envelope };
};

let r = await send(sa, sb, { t: "おはようございます" });
sa = r.from; sb = r.to;
ok(r.payload.t === "おはようございます", "招待した側 → 招待された側");
ok(!r.envelope.c.includes("おはよう"), "暗号文に本文はそのまま入らない");
ok(JSON.stringify(r.envelope).indexOf("おはよう") === -1, "封筒全体にも本文は現れない");

r = await send(sb, sa, { t: "こちらこそ" });
sb = r.from; sa = r.to;
ok(r.payload.t === "こちらこそ", "招待された側 → 招待した側");

// 招待された側が先に送る場合も動く（別のペアで確認）
{
  const c = await MC.createIdentity("C");
  const d = await MC.createIdentity("D");
  const inv = await MC.createInvite(c);
  const acc = await MC.acceptInvite(d, inv.code);
  const com = await MC.completeInvite(c, inv.pending, acc.replyCode);
  const first = await send(acc.session, com.session, { t: "先に送ります" });
  ok(first.payload.t === "先に送ります", "招待された側から先に送っても届く");
  const back = await send(first.to, first.from, { t: "受け取りました" });
  ok(back.payload.t === "受け取りました", "その返事も届く");
}

console.log("== 連続送信と交互送信 ==");
for (let i = 0; i < 5; i++) {
  r = await send(sa, sb, { t: "連続" + i });
  sa = r.from; sb = r.to;
  ok(r.payload.t === "連続" + i, "同じ向きに続けて送れる（" + i + "）");
}
for (let i = 0; i < 3; i++) {
  r = await send(sb, sa, { t: "返信" + i });
  sb = r.from; sa = r.to;
  r = await send(sa, sb, { t: "応答" + i });
  sa = r.from; sb = r.to;
  ok(r.payload.t === "応答" + i, "交互に送り合える（" + i + "）");
}

/* ---------------- 順番が入れ替わって届く場合 ---------------- */
console.log("== 順番が入れ替わって届く場合 ==");
{
  const e1 = await MC.encrypt(sa, { t: "1通目" });
  const e2 = await MC.encrypt(e1.session, { t: "2通目" });
  const e3 = await MC.encrypt(e2.session, { t: "3通目" });
  sa = e3.session;

  let d = await MC.decrypt(sb, e3.envelope);
  ok(d.payload.t === "3通目", "3通目が先に届いても開ける");
  ok(d.session.skipped.length === 2, "飛ばした2通ぶんの鍵を取り置く");
  d = await MC.decrypt(d.session, e1.envelope);
  ok(d.payload.t === "1通目", "あとから1通目が届いても開ける");
  d = await MC.decrypt(d.session, e2.envelope);
  ok(d.payload.t === "2通目", "あとから2通目が届いても開ける");
  ok(d.session.skipped.length === 0, "取り置いた鍵は使ったら消える");
  await throws(() => MC.decrypt(d.session, e1.envelope), "同じメッセージは二度は開けない（鍵を捨てるため）");
  sb = d.session;
}

/* ---------------- 前方秘匿性・鍵の更新 ---------------- */
console.log("== 前方秘匿性（過去のメッセージが読めないこと）==");
{
  const before = clone(sb);
  const e = await MC.encrypt(sa, { t: "秘密の連絡" });
  sa = e.session;
  const d = await MC.decrypt(sb, e.envelope);
  sb = d.session;
  ok(d.payload.t === "秘密の連絡", "受け取れる");
  await throws(() => MC.decrypt(sb, e.envelope), "受け取ったあとの状態では同じ暗号文を開けない");
  ok(before.ckr !== sb.ckr, "受信のたびに鎖の鍵が変わる");
}

// 端末の中身を丸ごと盗まれても、そのあと相手向きの鍵が作り直されれば読めなくなる
// （Double Ratchet の「鍵の更新は往復のたびに起きる」性質。専用のペアで順序を固定して確かめる）
console.log("== 鍵の更新（盗まれた古い状態が使えなくなること）==");
{
  const c = await MC.createIdentity("C");
  const d = await MC.createIdentity("D");
  const inv = await MC.createInvite(c);
  const acc = await MC.acceptInvite(d, inv.code);
  const com = await MC.completeInvite(c, inv.pending, acc.replyCode);
  let sc = com.session, sd = acc.session;

  const m1 = await send(sc, sd, { t: "1通目" });
  sc = m1.from; sd = m1.to;
  const stolen = clone(sd);                        // ← ここで D の端末が盗まれたとする
  ok((await MC.decrypt(stolen, (await MC.encrypt(sc, { t: "追い" })).envelope)).payload.t === "追い",
    "盗まれた直後は、盗んだ側も同じ鍵で読めてしまう（前提の確認）");

  const m2 = await send(sd, sc, { t: "D から返信（ここで鍵を作り直す）" });
  sd = m2.from; sc = m2.to;
  ok(m2.envelope.h.dh !== stolen.dhs.pub, "返信のときに新しい鍵を作っている");

  const m3 = await MC.encrypt(sc, { t: "更新後のメッセージ" });
  sc = m3.session;
  const got = await MC.decrypt(sd, m3.envelope);
  ok(got.payload.t === "更新後のメッセージ", "本人は引き続き読める");
  await throws(() => MC.decrypt(stolen, m3.envelope), "盗まれた古い状態では、更新後のメッセージは読めない");
}

/* ---------------- 改ざんと他人 ---------------- */
console.log("== 改ざん・第三者 ==");
{
  const e = await MC.encrypt(sa, { t: "改ざんの検知" });
  sa = e.session;
  const flip = (b64text) => {
    const bytes = MC.unb64(b64text);
    bytes[0] ^= 1;
    return MC.b64(bytes);
  };
  await throws(() => MC.decrypt(sb, { h: e.envelope.h, c: flip(e.envelope.c) }), "暗号文を1ビット変えると開けない");
  await throws(() => MC.decrypt(sb, { h: { ...e.envelope.h, n: e.envelope.h.n + 7 }, c: e.envelope.c }),
    "見出しを書き換えると開けない");
  await throws(() => MC.decrypt(sb, { h: e.envelope.h }), "暗号文が無いと開けない");
  await throws(() => MC.decrypt(sb, { c: e.envelope.c }), "見出しが無いと開けない");

  // 第三者（サーバー運営者を含む）は、公開情報だけでは開けない
  const eve = await MC.createIdentity("第三者");
  const eveInvite = await MC.createInvite(eve);
  const eveAccepted = await MC.acceptInvite(eve, eveInvite.code);
  await throws(() => MC.decrypt(eveAccepted.session, e.envelope), "無関係な第三者は開けない");
  const d = await MC.decrypt(sb, e.envelope);
  sb = d.session;
  ok(d.payload.t === "改ざんの検知", "正規の相手は開ける");
}

/* ---------------- 写真の添付 ---------------- */
console.log("== 写真の添付 ==");
{
  const bytes = new Uint8Array(120 * 1024);
  for (let i = 0; i < bytes.length; i++) bytes[i] = (i * 31 + 7) & 0xff;
  const image = MC.b64(bytes);
  const e = await MC.encrypt(sa, { t: "写真です", img: image, mime: "image/jpeg" });
  sa = e.session;
  ok(!e.envelope.c.includes(image.slice(0, 64)), "画像の中身は暗号文からは読み取れない");
  const d = await MC.decrypt(sb, e.envelope);
  sb = d.session;
  ok(d.payload.img === image, "120KBの画像がそのまま復元される");
  ok(d.payload.t === "写真です" && d.payload.mime === "image/jpeg", "本文と種類も一緒に運べる");
}

/* ---------------- 中継サーバー向けの署名 ---------------- */
console.log("== 本人確認の署名 ==");
{
  const text = "inbox|" + alice.id + "|" + Date.now();
  const sig = await MC.sign(alice, text);
  ok(await MC.verify(alice.sign.pub, text, sig) === true, "自分の署名は検証できる");
  ok(await MC.verify(bob.sign.pub, text, sig) === false, "他人の公開鍵では検証に失敗する");
  ok(await MC.verify(alice.sign.pub, text + "x", sig) === false, "文面を変えると検証に失敗する");
}

/* ---------------- 状態の保存と復元 ---------------- */
console.log("== 会話状態の保存と復元 ==");
{
  const saved = JSON.parse(JSON.stringify(sa));
  const e = await MC.encrypt(saved, { t: "保存して復元しても続けられる" });
  sa = e.session;
  const d = await MC.decrypt(JSON.parse(JSON.stringify(sb)), e.envelope);
  sb = d.session;
  ok(d.payload.t === "保存して復元しても続けられる", "JSONに保存・復元しても会話が続く");
  ok(typeof sa.dhs.priv === "object" && !("d" in (sa.peer || {})), "保存されるのは自分の秘密鍵だけ");
}

console.log(failures ? "\n=> 失敗 " + failures + " 件" : "\n=> すべて通過");
process.exit(failures ? 1 : 0);
