/*
 * メッセージの暗号化（エンド・ツー・エンド暗号化）の中核。
 *
 * 考え方は Signal と同じ二段構え。
 *  1. 初回だけ「招待コード」と「返信コード」を交換し、双方だけが知る共通の秘密（SK）を作る（X3DH 相当）
 *  2. そのあとは、メッセージを1通送受信するたびに鍵を作り直す（Double Ratchet 相当）
 * これにより、万一いまの鍵が盗まれても、過去のメッセージは解読できない（前方秘匿性）。
 *
 * 使う暗号は、ブラウザと OS に最初から入っている Web Crypto API のみ。
 *  - 鍵交換 : ECDH  P-256
 *  - 鍵の導出: HKDF-SHA256 / HMAC-SHA256
 *  - 本文   : AES-256-GCM（改ざんも検知できる方式）
 *  - 署名   : ECDSA P-256（中継サーバーに「本人である」ことを示すためだけに使う）
 * 追加のライブラリは使わない。中身をすべて読んで確かめられるようにするため。
 *
 * ※重要：この実装は第三者の監査を受けていない。日常の連絡を他人に見られないようにする用途を想定しており、
 *   身の安全に関わるような重大な秘密には Signal 本体を使うこと。
 */
(function (global) {
  "use strict";

  var webcrypto = (typeof globalThis !== "undefined" && globalThis.crypto) ? globalThis.crypto : global.crypto;
  var subtle = webcrypto.subtle;

  var INFO_X3DH = "myproject-messenger-x3dh-v1";
  var INFO_ROOT = "myproject-messenger-root-v1";
  var INFO_MSG = "myproject-messenger-message-v1";
  var MAX_SKIP = 500;      // 1つの鎖で飛ばせるメッセージ数の上限（順序が入れ替わった配送への備え）
  var MAX_KEPT_SKIPPED = 400; // 取り置く鍵の総数の上限

  /* ---------------- 文字列とバイト列の相互変換 ---------------- */

  function toBytes(text) { return new TextEncoder().encode(text); }
  function fromBytes(bytes) { return new TextDecoder().decode(bytes); }

  function b64(bytes) {
    var arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    var s = "";
    for (var i = 0; i < arr.length; i++) s += String.fromCharCode(arr[i]);
    return btoaSafe(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function unb64(text) {
    var s = String(text).replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    var raw = atobSafe(s);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // Node には btoa/atob があるが、無い環境でも動くようにしておく
  function btoaSafe(s) {
    if (typeof btoa === "function") return btoa(s);
    return Buffer.from(s, "binary").toString("base64");
  }
  function atobSafe(s) {
    if (typeof atob === "function") return atob(s);
    return Buffer.from(s, "base64").toString("binary");
  }

  function concat() {
    var parts = Array.prototype.slice.call(arguments);
    var total = 0, i;
    for (i = 0; i < parts.length; i++) total += parts[i].length;
    var out = new Uint8Array(total);
    var at = 0;
    for (i = 0; i < parts.length; i++) { out.set(parts[i], at); at += parts[i].length; }
    return out;
  }

  function equalBytes(a, b) {
    if (a.length !== b.length) return false;
    var diff = 0;
    for (var i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
    return diff === 0;
  }

  /* ---------------- 鍵の生成・書き出し・読み込み ---------------- */

  function genDhPair() {
    return subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  }
  function genSignPair() {
    return subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  }

  async function exportPair(pair) {
    return {
      pub: b64(new Uint8Array(await subtle.exportKey("raw", pair.publicKey))),
      priv: await subtle.exportKey("jwk", pair.privateKey)
    };
  }

  function importDhPub(pub) {
    return subtle.importKey("raw", unb64(pub), { name: "ECDH", namedCurve: "P-256" }, false, []);
  }
  function importDhPriv(jwk) {
    return subtle.importKey("jwk", jwk, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
  }
  function importSignPub(pub) {
    return subtle.importKey("raw", unb64(pub), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  }
  function importSignPriv(jwk) {
    return subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  }

  /* ---------------- 基本の暗号処理 ---------------- */

  async function sha256(bytes) {
    return new Uint8Array(await subtle.digest("SHA-256", bytes));
  }

  // ECDH：自分の秘密鍵と相手の公開鍵から、両者で一致する32バイトを作る
  async function dh(privJwk, pubB64) {
    var priv = await importDhPriv(privJwk);
    var pub = await importDhPub(pubB64);
    return new Uint8Array(await subtle.deriveBits({ name: "ECDH", public: pub }, priv, 256));
  }

  async function hkdf(ikm, salt, info, length) {
    var key = await subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
    var bits = await subtle.deriveBits(
      { name: "HKDF", hash: "SHA-256", salt: salt, info: toBytes(info) }, key, length * 8);
    return new Uint8Array(bits);
  }

  async function hmac(keyBytes, dataBytes) {
    var key = await subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    return new Uint8Array(await subtle.sign("HMAC", key, dataBytes));
  }

  // 根の鍵（root key）を進める。戻り値は [新しい根の鍵, 鎖の鍵]
  async function kdfRoot(rk, dhOut) {
    var out = await hkdf(dhOut, rk, INFO_ROOT, 64);
    return [out.slice(0, 32), out.slice(32, 64)];
  }

  // 鎖の鍵（chain key）を1つ進める。戻り値は [次の鎖の鍵, このメッセージの鍵]
  async function kdfChain(ck) {
    var mk = await hmac(ck, new Uint8Array([1]));
    var next = await hmac(ck, new Uint8Array([2]));
    return [next, mk];
  }

  // メッセージ鍵から AES の鍵と初期化ベクトルを作る
  async function messageKeys(mk) {
    var out = await hkdf(mk, new Uint8Array(32), INFO_MSG, 44);
    var key = await subtle.importKey("raw", out.slice(0, 32), { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
    return { key: key, iv: out.slice(32, 44) };
  }

  /* ---------------- 本人確認用の署名（中継サーバー向け） ---------------- */

  async function sign(identity, text) {
    var key = await importSignPriv(identity.sign.priv);
    var sig = await subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, toBytes(text));
    return b64(new Uint8Array(sig));
  }

  async function verify(signPub, text, signature) {
    var key = await importSignPub(signPub);
    return subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, unb64(signature), toBytes(text));
  }

  /* ---------------- 自分の身元（identity） ---------------- */

  // 宛先として使う短い番号。公開鍵から機械的に決まるので、他人が名乗ることはできない
  async function idFromKeys(signPub, dhPub) {
    return b64(await sha256(concat(unb64(signPub), unb64(dhPub)))).slice(0, 32);
  }

  async function createIdentity(name) {
    var signPair = await exportPair(await genSignPair());
    var dhPair = await exportPair(await genDhPair());
    return {
      v: 1,
      name: String(name || "").slice(0, 40),
      sign: signPair,
      dh: dhPair,
      id: await idFromKeys(signPair.pub, dhPair.pub),
      createdAt: Date.now()
    };
  }

  /* ---------------- ペアリング（招待コードの交換） ---------------- */

  var PREFIX = "MSG1";

  // コードには公開鍵・使い捨ての公開鍵・表示名・中継サーバーの場所だけを入れる。
  // 秘密鍵は決して入れない。中継サーバーの場所を含めるのは、相手が設定を手入力せずに済むようにするため。
  function encodeCode(role, signPub, dhPub, ekPub, name, server) {
    return [PREFIX, role, signPub, dhPub, ekPub,
      b64(toBytes(String(name || ""))), b64(toBytes(String(server || "")))].join(".");
  }

  function decodeCode(code, expectedRole) {
    var parts = String(code || "").trim().replace(/\s+/g, "").split(".");
    if (parts.length !== 7 || parts[0] !== PREFIX) throw new Error("コードの形式が違います");
    if (parts[1] !== expectedRole) {
      throw new Error(expectedRole === "i" ? "これは招待コードではありません" : "これは返信コードではありません");
    }
    var name, server;
    try {
      name = fromBytes(unb64(parts[5]));
      server = fromBytes(unb64(parts[6]));
    } catch (e) { throw new Error("コードの形式が違います"); }
    for (var i = 2; i <= 4; i++) {
      if (unb64(parts[i]).length !== 65) throw new Error("コードが壊れています");
    }
    return { role: parts[1], sign: parts[2], dh: parts[3], ek: parts[4], name: name, server: server };
  }

  // 招待する側（initiator）が最初に作るコード。使い捨ての鍵（ek）を1つ添える
  async function createInvite(identity, server) {
    var ek = await exportPair(await genDhPair());
    return {
      code: encodeCode("i", identity.sign.pub, identity.dh.pub, ek.pub, identity.name, server),
      pending: { ek: ek, createdAt: Date.now() }
    };
  }

  // 双方が同じ値にたどり着く共通の秘密（SK）。X3DH と同じ3回の ECDH を束ねる
  async function sharedSecret(mine, peer, iAmInitiator) {
    var dh1, dh2, dh3;
    if (iAmInitiator) {
      dh1 = await dh(mine.identity.dh.priv, peer.ek);   // 自分の身元鍵 × 相手の使い捨て鍵
      dh2 = await dh(mine.ek.priv, peer.dh);            // 自分の使い捨て鍵 × 相手の身元鍵
      dh3 = await dh(mine.ek.priv, peer.ek);            // 使い捨て鍵どうし
    } else {
      dh1 = await dh(mine.ek.priv, peer.dh);
      dh2 = await dh(mine.identity.dh.priv, peer.ek);
      dh3 = await dh(mine.ek.priv, peer.ek);
    }
    return hkdf(concat(dh1, dh2, dh3), new Uint8Array(32), INFO_X3DH, 32);
  }

  // 会話の状態（session）を作る。
  // 招待した側が送信の鎖を、招待された側が受信の鎖を、同じ材料から作るので最初の1通から噛み合う。
  async function newSession(identity, peer, sk, myEk, iAmInitiator) {
    var initiatorDh = iAmInitiator ? identity.dh.pub : peer.dh;
    var responderDh = iAmInitiator ? peer.dh : identity.dh.pub;
    var ad = b64(concat(unb64(initiatorDh), unb64(responderDh)));

    var pair = await kdfRoot(sk, await dh(myEk.priv, peer.ek));
    return {
      v: 1,
      peer: { id: await idFromKeys(peer.sign, peer.dh), name: peer.name, sign: peer.sign, dh: peer.dh },
      ad: ad,
      rk: b64(pair[0]),
      cks: iAmInitiator ? b64(pair[1]) : null,
      ckr: iAmInitiator ? null : b64(pair[1]),
      dhs: myEk,
      dhr: peer.ek,
      ns: 0, nr: 0, pn: 0,
      skipped: []
    };
  }

  // 招待された側（responder）：招待コードを受け取り、返信コードを作る
  async function acceptInvite(identity, code, server) {
    var peer = decodeCode(code, "i");
    var ek = await exportPair(await genDhPair());
    var sk = await sharedSecret({ identity: identity, ek: ek }, peer, false);
    var session = await newSession(identity, peer, sk, ek, false);
    return {
      session: session,
      peerServer: peer.server,
      replyCode: encodeCode("r", identity.sign.pub, identity.dh.pub, ek.pub, identity.name, server)
    };
  }

  // 招待した側（initiator）：返ってきた返信コードを取り込んで会話を開始できる状態にする
  async function completeInvite(identity, pending, replyCode) {
    var peer = decodeCode(replyCode, "r");
    var sk = await sharedSecret({ identity: identity, ek: pending.ek }, peer, true);
    return { session: await newSession(identity, peer, sk, pending.ek, true), peerServer: peer.server };
  }

  /* ---------------- メッセージの暗号化・復号 ---------------- */

  function cloneSession(session) {
    return JSON.parse(JSON.stringify(session));
  }

  function headerBytes(header) {
    return toBytes(JSON.stringify(header));
  }

  async function encrypt(session, payload) {
    var s = cloneSession(session);

    // 送信の鎖がまだ無い場合（招待された側が最初に送るとき）は、ここで鍵を作り直す
    if (!s.cks) {
      var fresh = await exportPair(await genDhPair());
      var stepped = await kdfRoot(unb64(s.rk), await dh(fresh.priv, s.dhr));
      s.pn = s.ns;
      s.ns = 0;
      s.dhs = fresh;
      s.rk = b64(stepped[0]);
      s.cks = b64(stepped[1]);
    }

    var step = await kdfChain(unb64(s.cks));
    s.cks = b64(step[0]);
    var header = { dh: s.dhs.pub, pn: s.pn, n: s.ns };
    s.ns += 1;

    var mk = await messageKeys(step[1]);
    var aad = concat(headerBytes(header), unb64(s.ad));
    var body = await subtle.encrypt(
      { name: "AES-GCM", iv: mk.iv, additionalData: aad }, mk.key, toBytes(JSON.stringify(payload)));

    return { session: s, envelope: { h: header, c: b64(new Uint8Array(body)) } };
  }

  async function openWith(mkBytes, header, ad, cipher) {
    var mk = await messageKeys(mkBytes);
    var aad = concat(headerBytes(header), unb64(ad));
    var plain = await subtle.decrypt(
      { name: "AES-GCM", iv: mk.iv, additionalData: aad }, mk.key, unb64(cipher));
    return JSON.parse(fromBytes(new Uint8Array(plain)));
  }

  // 順番が入れ替わって届いた場合に備え、飛ばした番号の鍵を取り置く
  async function skipTo(s, until) {
    if (!s.ckr) return;
    if (until - s.nr > MAX_SKIP) throw new Error("届いていないメッセージが多すぎます");
    while (s.nr < until) {
      var step = await kdfChain(unb64(s.ckr));
      s.ckr = b64(step[0]);
      s.skipped.push({ dh: s.dhr, n: s.nr, mk: b64(step[1]) });
      s.nr += 1;
    }
    while (s.skipped.length > MAX_KEPT_SKIPPED) s.skipped.shift();
  }

  // 相手が鍵を更新したときに、こちらも根の鍵を進める
  async function turnRatchet(s, header) {
    s.pn = s.ns;
    s.ns = 0;
    s.nr = 0;
    s.dhr = header.dh;

    var recv = await kdfRoot(unb64(s.rk), await dh(s.dhs.priv, s.dhr));
    s.rk = b64(recv[0]);
    s.ckr = b64(recv[1]);

    var fresh = await exportPair(await genDhPair());
    var send = await kdfRoot(unb64(s.rk), await dh(fresh.priv, s.dhr));
    s.dhs = fresh;
    s.rk = b64(send[0]);
    s.cks = b64(send[1]);
  }

  async function decrypt(session, envelope) {
    var s = cloneSession(session);
    var header = envelope && envelope.h;
    if (!header || typeof header.dh !== "string" || !Number.isInteger(header.n) || !Number.isInteger(header.pn)) {
      throw new Error("メッセージの形式が違います");
    }

    // 取り置いてある鍵で開けられるか先に試す（順番が前後して届いた分）
    for (var i = 0; i < s.skipped.length; i++) {
      if (s.skipped[i].dh === header.dh && s.skipped[i].n === header.n) {
        var kept = s.skipped[i].mk;
        s.skipped.splice(i, 1);
        return { session: s, payload: await openWith(unb64(kept), header, s.ad, envelope.c) };
      }
    }

    if (header.dh !== s.dhr) {
      await skipTo(s, header.pn);
      await turnRatchet(s, header);
    } else if (!s.ckr) {
      throw new Error("この相手からの受信はまだ始まっていません");
    } else if (header.n < s.nr) {
      // 受信済みの番号。取り置きにも無いということは、鍵をすでに捨てている
      throw new Error("受信済みのメッセージです");
    }
    await skipTo(s, header.n);

    var step = await kdfChain(unb64(s.ckr));
    s.ckr = b64(step[0]);
    s.nr += 1;

    return { session: s, payload: await openWith(step[1], header, s.ad, envelope.c) };
  }

  /* ---------------- 安全番号（なりすまし確認用） ---------------- */

  // 双方の画面に同じ60桁が出れば、通信の途中で入れ替えられていないことを確認できる。
  // 電話や対面など、別の手段で読み合わせて使う。
  async function safetyNumber(identity, session) {
    var mine = concat(unb64(identity.sign.pub), unb64(identity.dh.pub));
    var theirs = concat(unb64(session.peer.sign), unb64(session.peer.dh));
    var first = b64(mine) < b64(theirs) ? mine : theirs;
    var second = first === mine ? theirs : mine;
    var digest = await sha256(concat(first, second));
    var digits = "";
    for (var i = 0; i < 30; i++) digits += String(digest[i] % 100).padStart(2, "0");
    return digits.replace(/(\d{5})(?=\d)/g, "$1 ");
  }

  global.MsgCrypto = {
    createIdentity: createIdentity,
    createInvite: createInvite,
    acceptInvite: acceptInvite,
    completeInvite: completeInvite,
    encrypt: encrypt,
    decrypt: decrypt,
    sign: sign,
    verify: verify,
    safetyNumber: safetyNumber,
    idFromKeys: idFromKeys,
    sha256: sha256,
    decodeCode: decodeCode,
    b64: b64,
    unb64: unb64,
    toBytes: toBytes,
    fromBytes: fromBytes,
    equalBytes: equalBytes
  };
})(typeof window !== "undefined" ? window : this);
