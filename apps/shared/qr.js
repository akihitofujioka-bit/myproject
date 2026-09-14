/*
 * QRコードの生成。外部ライブラリを使わずに実装している
 * （オフラインでも動かすため、および依存を増やさないため）。
 *
 * 中身は「QRメール作成ツール」で使っている実装をそのまま持ってきたもの。
 * リード・ソロモン誤り訂正、マスクの自動選択、UTF-8 のバイトモードに対応する。
 *
 * 使い方:
 *   var qr = QRGen.encode("myproject://docs?id=xxx", "M");
 *   // qr.size … 一辺のマス数 / qr.modules[y][x] … true なら黒
 */
var QRGen = (function () {
  "use strict";

  /* ---- 表: RSブロック構成 (v1..v40 × [L,M,Q,H]) ---- */
  /* 各レベルは (ブロック数, 総符号語, データ符号語) の3つ組の並び */
  var RS_BLOCK_TABLE = [

[[1,26,19],[1,26,16],[1,26,13],[1,26,9]],
[[1,44,34],[1,44,28],[1,44,22],[1,44,16]],
[[1,70,55],[1,70,44],[2,35,17],[2,35,13]],
[[1,100,80],[2,50,32],[2,50,24],[4,25,9]],
[[1,134,108],[2,67,43],[2,33,15,2,34,16],[2,33,11,2,34,12]],
[[2,86,68],[4,43,27],[4,43,19],[4,43,15]],
[[2,98,78],[4,49,31],[2,32,14,4,33,15],[4,39,13,1,40,14]],
[[2,121,97],[2,60,38,2,61,39],[4,40,18,2,41,19],[4,40,14,2,41,15]],
[[2,146,116],[3,58,36,2,59,37],[4,36,16,4,37,17],[4,36,12,4,37,13]],
[[2,86,68,2,87,69],[4,69,43,1,70,44],[6,43,19,2,44,20],[6,43,15,2,44,16]],
[[4,101,81],[1,80,50,4,81,51],[4,50,22,4,51,23],[3,36,12,8,37,13]],
[[2,116,92,2,117,93],[6,58,36,2,59,37],[4,46,20,6,47,21],[7,42,14,4,43,15]],
[[4,133,107],[8,59,37,1,60,38],[8,44,20,4,45,21],[12,33,11,4,34,12]],
[[3,145,115,1,146,116],[4,64,40,5,65,41],[11,36,16,5,37,17],[11,36,12,5,37,13]],
[[5,109,87,1,110,88],[5,65,41,5,66,42],[5,54,24,7,55,25],[11,36,12,7,37,13]],
[[5,122,98,1,123,99],[7,73,45,3,74,46],[15,43,19,2,44,20],[3,45,15,13,46,16]],
[[1,135,107,5,136,108],[10,74,46,1,75,47],[1,50,22,15,51,23],[2,42,14,17,43,15]],
[[5,150,120,1,151,121],[9,69,43,4,70,44],[17,50,22,1,51,23],[2,42,14,19,43,15]],
[[3,141,113,4,142,114],[3,70,44,11,71,45],[17,47,21,4,48,22],[9,39,13,16,40,14]],
[[3,135,107,5,136,108],[3,67,41,13,68,42],[15,54,24,5,55,25],[15,43,15,10,44,16]],
[[4,144,116,4,145,117],[17,68,42],[17,50,22,6,51,23],[19,46,16,6,47,17]],
[[2,139,111,7,140,112],[17,74,46],[7,54,24,16,55,25],[34,37,13]],
[[4,151,121,5,152,122],[4,75,47,14,76,48],[11,54,24,14,55,25],[16,45,15,14,46,16]],
[[6,147,117,4,148,118],[6,73,45,14,74,46],[11,54,24,16,55,25],[30,46,16,2,47,17]],
[[8,132,106,4,133,107],[8,75,47,13,76,48],[7,54,24,22,55,25],[22,45,15,13,46,16]],
[[10,142,114,2,143,115],[19,74,46,4,75,47],[28,50,22,6,51,23],[33,46,16,4,47,17]],
[[8,152,122,4,153,123],[22,73,45,3,74,46],[8,53,23,26,54,24],[12,45,15,28,46,16]],
[[3,147,117,10,148,118],[3,73,45,23,74,46],[4,54,24,31,55,25],[11,45,15,31,46,16]],
[[7,146,116,7,147,117],[21,73,45,7,74,46],[1,53,23,37,54,24],[19,45,15,26,46,16]],
[[5,145,115,10,146,116],[19,75,47,10,76,48],[15,54,24,25,55,25],[23,45,15,25,46,16]],
[[13,145,115,3,146,116],[2,74,46,29,75,47],[42,54,24,1,55,25],[23,45,15,28,46,16]],
[[17,145,115],[10,74,46,23,75,47],[10,54,24,35,55,25],[19,45,15,35,46,16]],
[[17,145,115,1,146,116],[14,74,46,21,75,47],[29,54,24,19,55,25],[11,45,15,46,46,16]],
[[13,145,115,6,146,116],[14,74,46,23,75,47],[44,54,24,7,55,25],[59,46,16,1,47,17]],
[[12,151,121,7,152,122],[12,75,47,26,76,48],[39,54,24,14,55,25],[22,45,15,41,46,16]],
[[6,151,121,14,152,122],[6,75,47,34,76,48],[46,54,24,10,55,25],[2,45,15,64,46,16]],
[[17,152,122,4,153,123],[29,74,46,14,75,47],[49,54,24,10,55,25],[24,45,15,46,46,16]],
[[4,152,122,18,153,123],[13,74,46,32,75,47],[48,54,24,14,55,25],[42,45,15,32,46,16]],
[[20,147,117,4,148,118],[40,75,47,7,76,48],[43,54,24,22,55,25],[10,45,15,67,46,16]],
[[19,148,118,6,149,119],[18,75,47,31,76,48],[34,54,24,34,55,25],[20,45,15,61,46,16]],
];
  /* ---- 表: 位置合わせパターン中心座標 (v1..v40) ---- */
  var ALIGN_POS = [

[],
[6,18],
[6,22],
[6,26],
[6,30],
[6,34],
[6,22,38],
[6,24,42],
[6,26,46],
[6,28,50],
[6,30,54],
[6,32,58],
[6,34,62],
[6,26,46,66],
[6,26,48,70],
[6,26,50,74],
[6,30,54,78],
[6,30,56,82],
[6,30,58,86],
[6,34,62,90],
[6,28,50,72,94],
[6,26,50,74,98],
[6,30,54,78,102],
[6,28,54,80,106],
[6,32,58,84,110],
[6,30,58,86,114],
[6,34,62,90,118],
[6,26,50,74,98,122],
[6,30,54,78,102,126],
[6,26,52,78,104,130],
[6,30,56,82,108,134],
[6,34,60,86,112,138],
[6,30,58,86,114,142],
[6,34,62,90,118,146],
[6,30,54,78,102,126,150],
[6,24,50,76,102,128,154],
[6,28,54,80,106,132,158],
[6,32,58,84,110,136,162],
[6,26,54,82,110,138,166],
[6,30,58,86,114,142,170],
];

  var ECL = { L: 0, M: 1, Q: 2, H: 3 };
  /* 形式情報での誤り訂正レベルのビット表現 */
  var ECL_FORMAT_BITS = { 0: 1, 1: 0, 2: 3, 3: 2 };

  /* ---- GF(256) 原始多項式 0x11D ---- */
  var EXP = new Uint8Array(512);
  var LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();

  function gmul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  /* 生成多項式 (係数は高次→低次) */
  function rsGenPoly(degree) {
    var g = [1];
    for (var i = 0; i < degree; i++) {
      var next = new Array(g.length + 1);
      for (var k = 0; k < next.length; k++) next[k] = 0;
      for (var j = 0; j < g.length; j++) {
        next[j] ^= g[j];
        next[j + 1] ^= gmul(g[j], EXP[i]);
      }
      g = next;
    }
    return g;
  }

  /* データ符号語 → 誤り訂正符号語 */
  function rsEncode(data, ecLen) {
    var g = rsGenPoly(ecLen);
    var buf = new Uint8Array(data.length + ecLen);
    buf.set(data, 0);
    for (var i = 0; i < data.length; i++) {
      var coef = buf[i];
      if (coef !== 0) {
        for (var j = 0; j < g.length; j++) buf[i + j] ^= gmul(g[j], coef);
      }
    }
    return buf.subarray(data.length);
  }

  /* ---- ビットバッファ ---- */
  function BitBuf() {
    this.bytes = [];
    this.len = 0;
  }
  BitBuf.prototype.putBit = function (bit) {
    var i = this.len >>> 3;
    if (this.bytes.length <= i) this.bytes.push(0);
    if (bit) this.bytes[i] |= 0x80 >>> (this.len & 7);
    this.len++;
  };
  BitBuf.prototype.put = function (num, bits) {
    for (var i = bits - 1; i >= 0; i--) this.putBit(((num >>> i) & 1) === 1);
  };

  /* ---- バージョン情報 ---- */
  function rsBlocksFor(version, ecl) {
    var flat = RS_BLOCK_TABLE[version - 1][ecl];
    var blocks = [];
    for (var i = 0; i < flat.length; i += 3) {
      for (var n = 0; n < flat[i]; n++) {
        blocks.push({ total: flat[i + 1], data: flat[i + 2] });
      }
    }
    return blocks;
  }

  function dataCodewords(version, ecl) {
    var blocks = rsBlocksFor(version, ecl);
    var sum = 0;
    for (var i = 0; i < blocks.length; i++) sum += blocks[i].data;
    return sum;
  }

  function charCountBits(version) {
    return version <= 9 ? 8 : 16;
  }

  /* バイト列がそのバージョン/レベルに収まるか */
  function capacityBytes(version, ecl) {
    var bits = dataCodewords(version, ecl) * 8 - 4 - charCountBits(version);
    return bits >>> 3;
  }

  function remainderBits(version) {
    if (version === 1) return 0;
    if (version <= 6) return 7;
    if (version <= 13) return 0;
    if (version <= 20) return 3;
    if (version <= 27) return 4;
    if (version <= 34) return 3;
    return 0;
  }

  /* ---- データ符号語列の構築 (終端・パディング・ブロック分割・インターリーブ) ---- */
  function buildCodewords(bytes, version, ecl) {
    var bb = new BitBuf();
    bb.put(4, 4); // 8ビットバイトモード
    bb.put(bytes.length, charCountBits(version));
    for (var i = 0; i < bytes.length; i++) bb.put(bytes[i], 8);

    var capBits = dataCodewords(version, ecl) * 8;
    // 終端子 0000 (最大4ビット)
    var term = Math.min(4, capBits - bb.len);
    bb.put(0, term);
    // バイト境界まで 0 埋め
    bb.put(0, (8 - (bb.len & 7)) & 7);
    // 残りを 0xEC / 0x11 交互で埋める
    var pad = [0xec, 0x11];
    for (var p = 0; bb.len < capBits; p++) bb.put(pad[p & 1], 8);

    var dataArr = new Uint8Array(bb.bytes);

    // ブロックへ分割 + 誤り訂正符号語生成
    var blocks = rsBlocksFor(version, ecl);
    var dataBlocks = [];
    var ecBlocks = [];
    var off = 0;
    var maxData = 0;
    var maxEc = 0;
    for (var b = 0; b < blocks.length; b++) {
      var dLen = blocks[b].data;
      var eLen = blocks[b].total - dLen;
      var chunk = dataArr.subarray(off, off + dLen);
      off += dLen;
      dataBlocks.push(chunk);
      ecBlocks.push(rsEncode(chunk, eLen));
      if (dLen > maxData) maxData = dLen;
      if (eLen > maxEc) maxEc = eLen;
    }

    // インターリーブ
    var out = [];
    for (var i2 = 0; i2 < maxData; i2++) {
      for (var b2 = 0; b2 < dataBlocks.length; b2++) {
        if (i2 < dataBlocks[b2].length) out.push(dataBlocks[b2][i2]);
      }
    }
    for (var i3 = 0; i3 < maxEc; i3++) {
      for (var b3 = 0; b3 < ecBlocks.length; b3++) {
        if (i3 < ecBlocks[b3].length) out.push(ecBlocks[b3][i3]);
      }
    }
    return new Uint8Array(out);
  }

  /* ---- モジュール配置 ---- */
  function Grid(version) {
    this.version = version;
    this.size = version * 4 + 17;
    this.modules = [];
    this.isFunc = [];
    for (var y = 0; y < this.size; y++) {
      var r1 = [], r2 = [];
      for (var x = 0; x < this.size; x++) {
        r1.push(false);
        r2.push(false);
      }
      this.modules.push(r1);
      this.isFunc.push(r2);
    }
  }
  Grid.prototype.setFunc = function (x, y, dark) {
    this.modules[y][x] = dark;
    this.isFunc[y][x] = true;
  };

  function getBit(n, i) {
    return ((n >>> i) & 1) !== 0;
  }

  function drawFinder(g, cx, cy) {
    for (var dy = -4; dy <= 4; dy++) {
      for (var dx = -4; dx <= 4; dx++) {
        var dist = Math.max(Math.abs(dx), Math.abs(dy));
        var x = cx + dx, y = cy + dy;
        if (x >= 0 && x < g.size && y >= 0 && y < g.size) {
          g.setFunc(x, y, dist !== 2 && dist !== 4);
        }
      }
    }
  }

  function drawAlign(g, cx, cy) {
    for (var dy = -2; dy <= 2; dy++) {
      for (var dx = -2; dx <= 2; dx++) {
        g.setFunc(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    }
  }

  function drawFormatBits(g, ecl, mask) {
    var data = (ECL_FORMAT_BITS[ecl] << 3) | mask;
    var rem = data;
    for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    var bits = ((data << 10) | rem) ^ 0x5412;

    for (var j = 0; j <= 5; j++) g.setFunc(8, j, getBit(bits, j));
    g.setFunc(8, 7, getBit(bits, 6));
    g.setFunc(8, 8, getBit(bits, 7));
    g.setFunc(7, 8, getBit(bits, 8));
    for (var k = 9; k < 15; k++) g.setFunc(14 - k, 8, getBit(bits, k));

    for (var m = 0; m < 8; m++) g.setFunc(g.size - 1 - m, 8, getBit(bits, m));
    for (var n = 8; n < 15; n++) g.setFunc(8, g.size - 15 + n, getBit(bits, n));
    g.setFunc(8, g.size - 8, true); // 固定の暗モジュール
  }

  function drawVersionBits(g) {
    if (g.version < 7) return;
    var rem = g.version;
    for (var i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
    var bits = (g.version << 12) | rem;
    for (var j = 0; j < 18; j++) {
      var bit = getBit(bits, j);
      var a = g.size - 11 + (j % 3);
      var b = Math.floor(j / 3);
      g.setFunc(a, b, bit);
      g.setFunc(b, a, bit);
    }
  }

  function drawFunctionPatterns(g, ecl) {
    // タイミングパターン
    for (var i = 0; i < g.size; i++) {
      g.setFunc(6, i, i % 2 === 0);
      g.setFunc(i, 6, i % 2 === 0);
    }
    // 切り出しシンボル + 分離パターン
    drawFinder(g, 3, 3);
    drawFinder(g, g.size - 4, 3);
    drawFinder(g, 3, g.size - 4);
    // 位置合わせパターン
    var pos = ALIGN_POS[g.version - 1];
    var last = pos.length - 1;
    for (var a = 0; a <= last; a++) {
      for (var b = 0; b <= last; b++) {
        if ((a === 0 && b === 0) || (a === 0 && b === last) || (a === last && b === 0)) continue;
        drawAlign(g, pos[a], pos[b]);
      }
    }
    drawFormatBits(g, ecl, 0); // マスク確定前の仮置き
    drawVersionBits(g);
  }

  function drawCodewords(g, data) {
    var i = 0;
    for (var right = g.size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < g.size; vert++) {
        for (var j = 0; j < 2; j++) {
          var x = right - j;
          var upward = ((right + 1) & 2) === 0;
          var y = upward ? g.size - 1 - vert : vert;
          if (!g.isFunc[y][x] && i < data.length * 8) {
            g.modules[y][x] = getBit(data[i >>> 3], 7 - (i & 7));
            i++;
          }
        }
      }
    }
  }

  function maskFn(mask, x, y) {
    switch (mask) {
      case 0: return (x + y) % 2 === 0;
      case 1: return y % 2 === 0;
      case 2: return x % 3 === 0;
      case 3: return (x + y) % 3 === 0;
      case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
      case 5: return ((x * y) % 2) + ((x * y) % 3) === 0;
      case 6: return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0;
      case 7: return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0;
    }
    return false;
  }

  function applyMask(g, mask) {
    for (var y = 0; y < g.size; y++) {
      for (var x = 0; x < g.size; x++) {
        if (!g.isFunc[y][x] && maskFn(mask, x, y)) {
          g.modules[y][x] = !g.modules[y][x];
        }
      }
    }
  }

  /* 評価スコア (低いほど良い) */
  function penalty(g) {
    var size = g.size, m = g.modules, score = 0, x, y;

    // 規則1: 行/列に同色が5個以上連続
    for (y = 0; y < size; y++) {
      var run = 1;
      for (x = 1; x < size; x++) {
        if (m[y][x] === m[y][x - 1]) {
          run++;
          if (run === 5) score += 3;
          else if (run > 5) score += 1;
        } else run = 1;
      }
    }
    for (x = 0; x < size; x++) {
      var runc = 1;
      for (y = 1; y < size; y++) {
        if (m[y][x] === m[y - 1][x]) {
          runc++;
          if (runc === 5) score += 3;
          else if (runc > 5) score += 1;
        } else runc = 1;
      }
    }

    // 規則2: 2x2 の同色ブロック
    for (y = 0; y < size - 1; y++) {
      for (x = 0; x < size - 1; x++) {
        var c = m[y][x];
        if (c === m[y][x + 1] && c === m[y + 1][x] && c === m[y + 1][x + 1]) score += 3;
      }
    }

    // 規則3: 1:1:3:1:1 比率パターン (前後に4モジュールの明領域)
    var patA = [true, false, true, true, true, false, true, false, false, false, false];
    var patB = [false, false, false, false, true, false, true, true, true, false, true];
    function matches(get, i) {
      var okA = true, okB = true;
      for (var k = 0; k < 11; k++) {
        if (get(i + k) !== patA[k]) okA = false;
        if (get(i + k) !== patB[k]) okB = false;
      }
      return okA || okB;
    }
    for (y = 0; y < size; y++) {
      for (x = 0; x + 11 <= size; x++) {
        if (matches(function (i) { return m[y][i]; }, x)) score += 40;
      }
    }
    for (x = 0; x < size; x++) {
      for (y = 0; y + 11 <= size; y++) {
        if (matches(function (i) { return m[i][x]; }, y)) score += 40;
      }
    }

    // 規則4: 暗モジュール比率の偏り
    var dark = 0;
    for (y = 0; y < size; y++) for (x = 0; x < size; x++) if (m[y][x]) dark++;
    var total = size * size;
    var k2 = Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1;
    score += k2 * 10;
    return score;
  }

  /* ---- 公開API ---- */

  /* 文字列 → UTF-8 バイト列 */
  function utf8Bytes(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) {
        out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      } else if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        var c2 = str.charCodeAt(i + 1);
        var cp = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00);
        i++;
        out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
      } else {
        out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      }
    }
    return out;
  }

  /* 収まる最小バージョンを返す。収まらなければ 0 */
  function minVersion(byteLen, ecl) {
    for (var v = 1; v <= 40; v++) {
      if (byteLen <= capacityBytes(v, ecl)) return v;
    }
    return 0;
  }

  /* text: 文字列 / ecl: 'L'|'M'|'Q'|'H' / opts.version: 明示指定 / opts.mask: 明示指定
   * 戻り値: { size, modules(2次元boolean), version, mask, ecl } */
  function encode(text, eclName, opts) {
    opts = opts || {};
    var ecl = ECL[eclName];
    if (ecl === undefined) throw new Error("誤り訂正レベルが不正です: " + eclName);

    var bytes = utf8Bytes(text);
    var version = opts.version || minVersion(bytes.length, ecl);
    if (!version) throw new Error("情報量が多すぎてQRコードに収まりません");
    if (bytes.length > capacityBytes(version, ecl)) {
      throw new Error("指定バージョンに収まりません");
    }

    var codewords = buildCodewords(bytes, version, ecl);

    var best = null;
    var maskList = opts.mask !== undefined && opts.mask !== null ? [opts.mask] : [0, 1, 2, 3, 4, 5, 6, 7];
    for (var mi = 0; mi < maskList.length; mi++) {
      var mask = maskList[mi];
      var g = new Grid(version);
      drawFunctionPatterns(g, ecl);
      drawCodewords(g, codewords);
      applyMask(g, mask);
      drawFormatBits(g, ecl, mask);
      var s = penalty(g);
      if (best === null || s < best.score) best = { score: s, grid: g, mask: mask };
    }

    return {
      size: best.grid.size,
      modules: best.grid.modules,
      version: version,
      mask: best.mask,
      ecl: eclName,
      byteLength: bytes.length,
    };
  }

  return {
    encode: encode,
    minVersion: minVersion,
    capacityBytes: capacityBytes,
    utf8Bytes: utf8Bytes,
  };
})();
