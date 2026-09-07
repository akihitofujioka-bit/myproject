/*
 * 「ふたりのメッセージ」のアイコンを作る。
 *
 *   node tools/make-icons.mjs
 *
 * 出力先
 *   apps/messenger/icon-{180,192,512}.png            … Web・ホーム画面に追加したとき用
 *   mobile-messenger/android の res/mipmap-各密度/ic_launcher ほか … Android アプリ用
 *
 * 依存ライブラリなしで PNG を書き出す（zlib と CRC だけで足りるため）。
 * 図柄は「吹き出しの中に南京錠」。青地に白の吹き出し、錠は地の色で抜く。
 */
import zlib from "node:zlib";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/* ---------------- PNG の書き出し ---------------- */

const crcTable = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function writePng(file, size, pixel) {
  const raw = Buffer.alloc(size * (size * 4 + 1));
  let at = 0;
  for (let y = 0; y < size; y++) {
    raw[at++] = 0;   // 行ごとのフィルタ種別（0 = なし）
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x, y);
      raw[at++] = r; raw[at++] = g; raw[at++] = b; raw[at++] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;   // 1色あたり8ビット
  ihdr[9] = 6;   // RGBA
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0))
  ]));
  return file;
}

/* ---------------- 図柄 ---------------- */

const ACCENT = [47, 111, 237];
const WHITE = [255, 255, 255];
const BLACK = [0, 0, 0];
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

// 角の丸い四角形の内側かどうか
function inRoundRect(x, y, x0, y0, x1, y1, r) {
  if (x < x0 || x > x1 || y < y0 || y > y1) return false;
  if ((x >= x0 + r && x <= x1 - r) || (y >= y0 + r && y <= y1 - r)) return true;
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

/**
 * @param size  出力する一辺の画素数
 * @param opts.shape  "rounded"（角丸の四角）｜"circle"（丸）｜"none"（地なし）
 * @param opts.inset  図柄を内側に寄せる割合。Android の可変アイコンは外周が切られるため使う
 * @param opts.mono   単色の影絵にする（Android 13 以降のテーマ対応アイコン用）
 */
function draw(size, opts) {
  const shape = opts.shape || "rounded";
  const inset = opts.inset || 0;
  const SUB = 4;   // 縁をなめらかにするための細かい標本化

  // 図柄を描く正方形（画面全体のうち inset ぶん内側）
  const span = size * (1 - inset * 2);
  const origin = size * inset;
  const u = (v) => origin + v * span;

  return (px, py) => {
    let ground = 0, bubble = 0, lock = 0;
    for (let sy = 0; sy < SUB; sy++) {
      for (let sx = 0; sx < SUB; sx++) {
        const x = px + (sx + 0.5) / SUB;
        const y = py + (sy + 0.5) / SUB;

        if (shape === "rounded") {
          if (inRoundRect(x, y, 0, 0, size, size, size * 0.22)) ground++;
        } else if (shape === "circle") {
          const d = (x - size / 2) ** 2 + (y - size / 2) ** 2;
          if (d <= (size / 2) ** 2) ground++;
        }

        // 吹き出し（本体としっぽ）
        const body = inRoundRect(x, y, u(0.2), u(0.24), u(0.8), u(0.63), span * 0.11);
        const tailX = (x - u(0.29)) / (span * 0.14);
        const tailY = (y - u(0.6)) / (span * 0.16);
        const tail = tailY >= 0 && tailY <= 1 && tailX >= tailY * 0.15 && tailX <= 1 - tailY;
        if (body || tail) bubble++;

        // 南京錠（つる＋本体）
        const shackleR = span * 0.075;
        const dx = x - u(0.5), dy = y - u(0.395);
        const d = Math.sqrt(dx * dx + dy * dy);
        const shackle = dy <= 0 && d <= shackleR && d >= shackleR - span * 0.028;
        const box = inRoundRect(x, y, u(0.412), u(0.392), u(0.588), u(0.535), span * 0.022);
        if (shackle || box) lock++;
      }
    }

    const total = SUB * SUB;
    if (opts.mono) {
      // 影絵：吹き出しの形だけを黒で描き、錠は抜く
      const alpha = Math.max(0, bubble - lock) / total;
      return [...BLACK, Math.round(alpha * 255)];
    }

    if (shape === "none") {
      // 地なし（可変アイコンの前景）。吹き出しの部分だけを白で描き、錠は青で抜く
      const alpha = bubble / total;
      if (alpha === 0) return [0, 0, 0, 0];
      return [...mix(WHITE, ACCENT, Math.min(1, lock / total)), Math.round(alpha * 255)];
    }

    const alpha = ground / total;
    if (alpha === 0) return [0, 0, 0, 0];
    let color = mix(ACCENT, WHITE, bubble / total);
    color = mix(color, ACCENT, lock / total);
    return [...color, Math.round(alpha * 255)];
  };
}

/* ---------------- 書き出し ---------------- */

const made = [];
const emit = (file, size, opts) => made.push(writePng(file, size, draw(size, opts)));

// Web・ホーム画面に追加したとき用
for (const size of [180, 192, 512]) {
  emit(path.join(ROOT, `apps/messenger/icon-${size}.png`), size, { shape: "rounded" });
}

// Android アプリ用
const RES = path.join(ROOT, "mobile-messenger/android/app/src/main/res");
const DENSITIES = [
  ["mdpi", 1], ["hdpi", 1.5], ["xhdpi", 2], ["xxhdpi", 3], ["xxxhdpi", 4]
];
if (fs.existsSync(path.dirname(RES))) {
  for (const [name, scale] of DENSITIES) {
    const dir = path.join(RES, "mipmap-" + name);
    // 古い端末向けの四角・丸アイコン（48dp）
    emit(path.join(dir, "ic_launcher.png"), Math.round(48 * scale), { shape: "rounded" });
    emit(path.join(dir, "ic_launcher_round.png"), Math.round(48 * scale), { shape: "circle" });
    // 可変アイコン（108dp）。外周が切り取られるため、図柄は内側66%に収める
    emit(path.join(dir, "ic_launcher_foreground.png"), Math.round(108 * scale), { shape: "none", inset: 0.17 });
    emit(path.join(dir, "ic_launcher_monochrome.png"), Math.round(108 * scale), { mono: true, inset: 0.17 });
  }
  // 起動画面に出す図柄（144dp 相当）
  emit(path.join(RES, "drawable-xxhdpi/splash_logo.png"), 432, { shape: "rounded" });
}

console.log(`アイコンを ${made.length} 個作りました。`);
for (const file of made) console.log("  " + path.relative(ROOT, file));
