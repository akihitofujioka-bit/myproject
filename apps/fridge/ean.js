/*
 * EAN-13 / JAN-13 / UPC-A / EAN-8 バーコードの読み取り。
 *
 * 外部ライブラリを使わずに実装している（オフラインでも動かすため、
 * および依存を増やさないため）。読み取りの考え方は一般的な1次元バーコード
 * リーダーと同じで、画像の横1行から明暗の「連続する長さ」を数え、
 * 数字ごとに決められた幅の並びと突き合わせる。
 *
 * 端末が BarcodeDetector API に対応している場合はそちらの方が精度が高いので、
 * 呼び出し側（index.html）はそちらを優先し、非対応のとき（iOS など）に
 * このモジュールを使う。
 */
(function (global) {
  "use strict";

  // L符号の各数字を「白黒の連続長」で表したもの（4つの区間の幅）
  var L_PATTERNS = [
    [3, 2, 1, 1], [2, 2, 2, 1], [2, 1, 2, 2], [1, 4, 1, 1], [1, 1, 3, 2],
    [1, 2, 3, 1], [1, 1, 1, 4], [1, 3, 1, 2], [1, 2, 1, 3], [3, 1, 1, 2]
  ];
  // G符号は L符号の並びを逆にしたもの。左半分は L と G が混ざり、その並びで先頭桁が決まる
  var L_AND_G_PATTERNS = L_PATTERNS.concat(L_PATTERNS.map(function (p) {
    return p.slice().reverse();
  }));
  var START_END_PATTERN = [1, 1, 1];
  var MIDDLE_PATTERN = [1, 1, 1, 1, 1];
  // 左半分のL/Gの並び（ビットが立っている位置がG）から先頭桁を決める表
  var FIRST_DIGIT_ENCODINGS = [0x00, 0x0B, 0x0D, 0x0E, 0x13, 0x19, 0x1C, 0x15, 0x16, 0x1A];

  var MAX_AVG_VARIANCE = 0.48;
  var MAX_INDIVIDUAL_VARIANCE = 0.7;

  function NotFound() { return null; }

  // 実測した幅の並びが、基準パターンにどれだけ近いか。小さいほど良い。合わないときは Infinity
  function patternMatchVariance(counters, pattern, maxIndividual) {
    var total = 0, patternLength = 0, i;
    for (i = 0; i < counters.length; i++) { total += counters[i]; patternLength += pattern[i]; }
    if (total < patternLength) return Infinity;
    var unit = total / patternLength;
    var maxIndividualScaled = maxIndividual * unit;
    var totalVariance = 0;
    for (i = 0; i < counters.length; i++) {
      var variance = Math.abs(counters[i] - pattern[i] * unit);
      if (variance > maxIndividualScaled) return Infinity;
      totalVariance += variance;
    }
    return totalVariance / total;
  }

  // start位置から counters.length 区間ぶんの連続長を数える
  function recordPattern(bits, start, counters) {
    var numCounters = counters.length, end = bits.length;
    for (var c = 0; c < numCounters; c++) counters[c] = 0;
    if (start >= end) return false;
    var isWhite = bits[start] === 0;
    var counterPosition = 0;
    var i = start;
    while (i < end) {
      if ((bits[i] === 1) !== isWhite) {
        counters[counterPosition]++;
      } else {
        counterPosition++;
        if (counterPosition === numCounters) break;
        counters[counterPosition] = 1;
        isWhite = !isWhite;
      }
      i++;
    }
    return counterPosition === numCounters || (counterPosition === numCounters - 1 && i === end);
  }

  // pattern に一致する区切り（ガードバー）を探す。戻り値は [開始位置, 終了位置]
  function findGuardPattern(bits, rowOffset, whiteFirst, pattern) {
    var width = bits.length;
    var patternLength = pattern.length;
    var counters = new Array(patternLength);
    for (var c = 0; c < patternLength; c++) counters[c] = 0;

    // 探し始める位置を、期待する色の画素まで進める
    while (rowOffset < width && (bits[rowOffset] === 1) === whiteFirst) rowOffset++;
    if (rowOffset >= width) return NotFound();

    var counterPosition = 0;
    var patternStart = rowOffset;
    var isWhite = whiteFirst;
    for (var x = rowOffset; x < width; x++) {
      if ((bits[x] === 1) !== isWhite) {
        counters[counterPosition]++;
      } else {
        if (counterPosition === patternLength - 1) {
          if (patternMatchVariance(counters, pattern, MAX_INDIVIDUAL_VARIANCE) < MAX_AVG_VARIANCE) {
            return [patternStart, x];
          }
          patternStart += counters[0] + counters[1];
          for (var k = 2; k < patternLength; k++) counters[k - 2] = counters[k];
          counters[patternLength - 2] = 0;
          counters[patternLength - 1] = 0;
          counterPosition--;
        } else {
          counterPosition++;
        }
        counters[counterPosition] = 1;
        isWhite = !isWhite;
      }
    }
    return NotFound();
  }

  function decodeDigit(bits, counters, rowOffset, patterns) {
    if (!recordPattern(bits, rowOffset, counters)) return -1;
    var bestVariance = MAX_AVG_VARIANCE;
    var bestMatch = -1;
    for (var i = 0; i < patterns.length; i++) {
      var variance = patternMatchVariance(counters, patterns[i], MAX_INDIVIDUAL_VARIANCE);
      if (variance < bestVariance) { bestVariance = variance; bestMatch = i; }
    }
    return bestMatch;
  }

  function sumCounters(counters) {
    var s = 0;
    for (var i = 0; i < counters.length; i++) s += counters[i];
    return s;
  }

  // チェックディジット（末尾1桁）の検証
  function checksumOk(code) {
    if (!/^\d+$/.test(code) || (code.length !== 13 && code.length !== 8 && code.length !== 12)) return false;
    var sum = 0;
    var digits = code.split("").map(Number);
    var check = digits.pop();
    // 右から数えて奇数番目に重み3
    for (var i = 0; i < digits.length; i++) {
      var fromRight = digits.length - i; // 1始まり
      sum += digits[i] * (fromRight % 2 === 1 ? 3 : 1);
    }
    return (10 - (sum % 10)) % 10 === check;
  }

  // 先頭桁を左半分のL/Gの並びから決める
  function firstDigit(lgPattern) {
    for (var d = 0; d < 10; d++) if (FIRST_DIGIT_ENCODINGS[d] === lgPattern) return d;
    return -1;
  }

  // EAN-13（JAN-13）/ UPC-A の読み取り
  function decodeEan13(bits, startRange) {
    var counters = [0, 0, 0, 0];
    var rowOffset = startRange[1];
    var end = bits.length;
    var digits = "";
    var lgPattern = 0;
    var x;

    for (x = 0; x < 6; x++) {
      if (rowOffset >= end) return null;
      var m = decodeDigit(bits, counters, rowOffset, L_AND_G_PATTERNS);
      if (m < 0) return null;
      digits += String(m % 10);
      rowOffset += sumCounters(counters);
      if (m >= 10) lgPattern |= 1 << (5 - x);
    }
    var first = firstDigit(lgPattern);
    if (first < 0) return null;

    var middle = findGuardPattern(bits, rowOffset, true, MIDDLE_PATTERN);
    if (!middle) return null;
    rowOffset = middle[1];

    for (x = 0; x < 6; x++) {
      if (rowOffset >= end) return null;
      var m2 = decodeDigit(bits, counters, rowOffset, L_PATTERNS);
      if (m2 < 0) return null;
      digits += String(m2);
      rowOffset += sumCounters(counters);
    }

    if (!findGuardPattern(bits, rowOffset, false, START_END_PATTERN)) return null;
    var code = String(first) + digits;
    return checksumOk(code) ? code : null;
  }

  // EAN-8（JAN-8）の読み取り。左4桁はすべてL符号
  function decodeEan8(bits, startRange) {
    var counters = [0, 0, 0, 0];
    var rowOffset = startRange[1];
    var end = bits.length;
    var digits = "";
    var x, m;

    for (x = 0; x < 4; x++) {
      if (rowOffset >= end) return null;
      m = decodeDigit(bits, counters, rowOffset, L_PATTERNS);
      if (m < 0) return null;
      digits += String(m);
      rowOffset += sumCounters(counters);
    }
    var middle = findGuardPattern(bits, rowOffset, true, MIDDLE_PATTERN);
    if (!middle) return null;
    rowOffset = middle[1];

    for (x = 0; x < 4; x++) {
      if (rowOffset >= end) return null;
      m = decodeDigit(bits, counters, rowOffset, L_PATTERNS);
      if (m < 0) return null;
      digits += String(m);
      rowOffset += sumCounters(counters);
    }
    if (!findGuardPattern(bits, rowOffset, false, START_END_PATTERN)) return null;
    return checksumOk(digits) ? digits : null;
  }

  // 1行ぶんの白黒データ（1=黒）から読み取る
  function decodeRow(bits) {
    var offset = 0;
    // 開始ガードの候補を順に試す（背景の縞模様を誤検出しても次の候補へ進める）
    for (var attempt = 0; attempt < 12 && offset < bits.length; attempt++) {
      var startRange = findGuardPattern(bits, offset, false, START_END_PATTERN);
      if (!startRange) return null;
      var code = decodeEan13(bits, startRange) || decodeEan8(bits, startRange);
      if (code) return code;
      offset = startRange[1];
    }
    return null;
  }

  // 画像の1行を白黒データに変換する。コントラストが低い行は null を返す
  function rowToBits(data, width, y) {
    var bits = new Uint8Array(width);
    var lum = new Uint8Array(width);
    var min = 255, max = 0;
    for (var x = 0; x < width; x++) {
      var i = (y * width + x) * 4;
      var v = (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) / 1000;
      lum[x] = v;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (max - min < 24) return null; // ほぼ一様な行は読み取れない
    var threshold = (min + max) / 2;
    for (var j = 0; j < width; j++) bits[j] = lum[j] < threshold ? 1 : 0;
    return bits;
  }

  function reversed(bits) {
    var out = new Uint8Array(bits.length);
    for (var i = 0; i < bits.length; i++) out[i] = bits[bits.length - 1 - i];
    return out;
  }

  /**
   * ImageData からバーコードを読み取る。読めなければ null。
   * 画像の上下中央付近を何本かの水平線で走査し、上下逆さまの場合も試す。
   */
  function decodeImageData(imageData, options) {
    var opts = options || {};
    var lines = opts.lines || 15;
    var width = imageData.width, height = imageData.height;
    var data = imageData.data;
    for (var n = 0; n < lines; n++) {
      // 中央から上下に広がる順に走査する（バーコードは中央に写りやすい）
      var ratio = 0.5 + (n % 2 === 0 ? 1 : -1) * Math.ceil(n / 2) * (0.4 / lines);
      var y = Math.max(0, Math.min(height - 1, Math.round(height * ratio)));
      var bits = rowToBits(data, width, y);
      if (!bits) continue;
      var code = decodeRow(bits) || decodeRow(reversed(bits));
      if (code) return code;
    }
    return null;
  }

  global.EAN = {
    decodeImageData: decodeImageData,
    decodeRow: decodeRow,
    checksumOk: checksumOk,
    L_PATTERNS: L_PATTERNS,
    FIRST_DIGIT_ENCODINGS: FIRST_DIGIT_ENCODINGS
  };
})(typeof window !== "undefined" ? window : this);
