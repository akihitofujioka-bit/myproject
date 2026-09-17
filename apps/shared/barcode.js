/*
 * バーコードを「描く側」（エンコーダ）。ポイントカードの番号を画面に表示し、
 * 店のスキャナで読んでもらうために使う。
 *
 * 対応形式
 *   - EAN-13 / JAN-13（13桁）、UPC-A（12桁）、EAN-8（8桁）: チェックディジット付きの数字
 *   - Code128: 英数字・記号。会員証・ポイントカードで最も多い形式。
 *     数字が続く部分は C セット（2桁を1文字に圧縮）、それ以外は B セットで符号化する
 *
 * 戻り値はどの形式も「モジュール列」（1=黒, 0=白 の配列）。描画は toCanvas() が行う。
 * 外部ライブラリも通信も使わない。
 */
(function (global) {
  "use strict";

  /* ---------- EAN / UPC ---------- */
  var L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
  var R = L.map(function (s) { return s.replace(/[01]/g, function (c) { return c === "0" ? "1" : "0"; }); });
  var G = R.map(function (s) { return s.split("").reverse().join(""); });
  // EAN-13 の先頭1桁は、左側6桁の L/G の並びで表す
  var PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];

  function checkDigit(digits) {
    var sum = 0;
    for (var i = 0; i < digits.length; i++) {
      var fromRight = digits.length - i;
      sum += Number(digits[i]) * (fromRight % 2 === 0 ? 1 : 3);
    }
    return String((10 - (sum % 10)) % 10);
  }

  function checksumOk(code) {
    return /^\d+$/.test(code) && checkDigit(code.slice(0, -1)) === code.slice(-1);
  }

  function bitsToModules(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) out.push(str.charAt(i) === "1" ? 1 : 0);
    return out;
  }

  function ean13(code) {
    if (!/^\d{13}$/.test(code) || !checksumOk(code)) throw new Error("EAN-13 として正しくありません");
    var parity = PARITY[Number(code.charAt(0))];
    var s = "101";
    for (var i = 1; i <= 6; i++) {
      var d = Number(code.charAt(i));
      s += parity.charAt(i - 1) === "L" ? L[d] : G[d];
    }
    s += "01010";
    for (var j = 7; j <= 12; j++) s += R[Number(code.charAt(j))];
    s += "101";
    return bitsToModules(s);
  }

  function ean8(code) {
    if (!/^\d{8}$/.test(code) || !checksumOk(code)) throw new Error("EAN-8 として正しくありません");
    var s = "101";
    for (var i = 0; i < 4; i++) s += L[Number(code.charAt(i))];
    s += "01010";
    for (var j = 4; j < 8; j++) s += R[Number(code.charAt(j))];
    s += "101";
    return bitsToModules(s);
  }

  // UPC-A は先頭に 0 を付けた EAN-13 と同じ縞模様になる
  function upca(code) {
    if (!/^\d{12}$/.test(code) || !checksumOk(code)) throw new Error("UPC-A として正しくありません");
    return ean13("0" + code);
  }

  /* ---------- Code128 ---------- */
  // 各文字の「バー・スペースの幅」（6本、合計11モジュール）。106 番の STOP だけ 7 本・13 モジュール
  var C128 = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112"
  ];
  var START_B = 104, START_C = 105, CODE_B = 100, CODE_C = 99, STOP = 106;

  function code128Ok(text) {
    // B セットで表せるのは ASCII の空白〜チルダ（0x20〜0x7E）
    return typeof text === "string" && text.length > 0 && text.length <= 80 && /^[\x20-\x7E]+$/.test(text);
  }

  // 位置 i から数字が何桁続くか
  function digitRun(text, i) {
    var n = 0;
    while (i + n < text.length && text.charAt(i + n) >= "0" && text.charAt(i + n) <= "9") n++;
    return n;
  }

  function code128(text) {
    if (!code128Ok(text)) throw new Error("Code128 で表せない文字が含まれています");
    var codes = [];
    var i = 0;
    // 先頭から4桁以上（または全体が偶数桁の数字）なら C セットで始める
    var run = digitRun(text, 0);
    var set = (run >= 4 || (run === text.length && run % 2 === 0 && run >= 2)) ? "C" : "B";
    codes.push(set === "C" ? START_C : START_B);
    while (i < text.length) {
      run = digitRun(text, i);
      if (set === "C") {
        if (run >= 2) {
          codes.push(Number(text.substr(i, 2)));
          i += 2;
        } else {
          codes.push(CODE_B);
          set = "B";
        }
      } else {
        // 4桁以上の数字が続くなら C セットに切り替えたほうが短い
        if (run >= 4) {
          // 奇数桁なら先頭1桁を B で出してから偶数桁にそろえる
          if (run % 2 === 1) {
            codes.push(text.charCodeAt(i) - 32);
            i++;
          }
          codes.push(CODE_C);
          set = "C";
        } else {
          codes.push(text.charCodeAt(i) - 32);
          i++;
        }
      }
    }
    var sum = codes[0];
    for (var k = 1; k < codes.length; k++) sum += codes[k] * k;
    codes.push(sum % 103);
    codes.push(STOP);

    var modules = [];
    codes.forEach(function (c) {
      var widths = C128[c];
      for (var w = 0; w < widths.length; w++) {
        var n = Number(widths.charAt(w));
        var bar = w % 2 === 0 ? 1 : 0;
        for (var m = 0; m < n; m++) modules.push(bar);
      }
    });
    return modules;
  }

  /* ---------- 形式の判定と描画 ---------- */

  /** 文字列からもっとも自然な形式を選ぶ。表せなければ null */
  function guessFormat(text) {
    var t = String(text || "").trim();
    if (/^\d{13}$/.test(t) && checksumOk(t)) return "ean13";
    if (/^\d{8}$/.test(t) && checksumOk(t)) return "ean8";
    if (/^\d{12}$/.test(t) && checksumOk(t)) return "upca";
    if (code128Ok(t)) return "code128";
    if (t.length > 0 && t.length <= 300) return "qr";
    return null;
  }

  function encode(text, format) {
    var t = String(text || "").trim();
    switch (format) {
      case "ean13": return ean13(t);
      case "ean8": return ean8(t);
      case "upca": return upca(t);
      case "code128": return code128(t);
      default: throw new Error("対応していない形式です: " + format);
    }
  }

  /**
   * 1次元バーコードを canvas に描く。左右に静止域（白）を 10 モジュール置く。
   * @param {number} opts.width  表示幅の上限（CSS px）。省略時は canvas の幅
   * @param {number} opts.height 表示高さ（CSS px）
   * @param {number} opts.dpr    端末の画素密度（省略時は 1）。Retina では 2〜3
   *
   * 1 モジュールが端末の整数画素になるように描き、CSS では等倍に縮めて表示する
   * （半端な幅だと縞がにじんで、スキャナで読めなくなるため）。
   */
  function toCanvas(canvas, text, format, opts) {
    opts = opts || {};
    var modules = encode(text, format);
    var quiet = 10;
    var total = modules.length + quiet * 2;
    var width = opts.width || canvas.width || 320;
    var height = opts.height || canvas.height || 120;
    var dpr = Math.max(1, Math.round(opts.dpr || 1));
    var scale = Math.max(1, Math.floor(width * dpr / total));
    canvas.width = total * scale;
    canvas.height = Math.round(height * dpr);
    canvas.style.width = (canvas.width / dpr) + "px";
    canvas.style.height = height + "px";
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000";
    for (var i = 0; i < modules.length; i++) {
      if (modules[i]) ctx.fillRect((quiet + i) * scale, 0, scale, canvas.height);
    }
    return { modules: modules.length, scale: scale };
  }

  global.Barcode = {
    encode: encode,
    guessFormat: guessFormat,
    checkDigit: checkDigit,
    checksumOk: checksumOk,
    code128Ok: code128Ok,
    toCanvas: toCanvas,
    FORMAT_LABEL: { ean13: "JAN/EAN-13", ean8: "EAN-8", upca: "UPC-A", code128: "Code128", qr: "QRコード" }
  };
})(typeof window !== "undefined" ? window : this);
