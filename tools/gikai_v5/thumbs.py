"""画面表示用の縮小 PNG を、標準ライブラリだけで用意する。"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_LOCK = threading.Lock()


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """RGB 画素列を、フィルターなしの PNG として保存する。"""
    if width < 1 or height < 1 or len(pixels) != width * height * 3:
        raise ValueError("PNG の大きさと画素数が合いません")

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    rows = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3]
                    for y in range(height))
    data = (PNG_SIGNATURE
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6))
            + chunk(b"IEND", b""))
    Path(path).write_bytes(data)


def read_png(path: Path) -> Tuple[int, int, bytes]:
    """8 bit の標準的な PNG を読み、RGB 画素列を返す。"""
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("PNG ではありません")
    pos = len(PNG_SIGNATURE)
    width = height = color = bit_depth = None
    palette = b""
    transparency = b""
    compressed = bytearray()
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        value = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", value)
            if bit_depth != 8 or compression or filtering or interlace:
                raise ValueError("対応していない PNG です")
        elif kind == b"PLTE":
            palette = value
        elif kind == b"tRNS":
            transparency = value
        elif kind == b"IDAT":
            compressed.extend(value)
        elif kind == b"IEND":
            break
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if not width or not height or channels is None:
        raise ValueError("PNG の情報を読めません")
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    rows: List[bytearray] = []
    offset = 0
    previous = bytearray(stride)
    for _y in range(height):
        filter_type = raw[offset]
        source = raw[offset + 1:offset + 1 + stride]
        offset += stride + 1
        row = bytearray(stride)
        for x, value in enumerate(source):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                p = left + up - upper_left
                distances = (abs(p - left), abs(p - up), abs(p - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            else:
                raise ValueError("PNG のフィルターを読めません")
            row[x] = (value + predictor) & 255
        rows.append(row)
        previous = row
    rgb = bytearray()
    for row in rows:
        for x in range(width):
            base = x * channels
            if color == 0 or color == 4:
                rgb.extend((row[base],) * 3)
            elif color == 2 or color == 6:
                rgb.extend(row[base:base + 3])
            else:
                index = row[base]
                start = index * 3
                if start + 3 > len(palette):
                    raise ValueError("PNG の色表を読めません")
                rgb.extend(palette[start:start + 3])
    return width, height, bytes(rgb)


def _scaled(width: int, height: int, pixels: bytes, max_px: int) -> Tuple[int, int, bytes]:
    scale = max(width / max_px, height / max_px, 1.0)
    new_w = max(1, int(width / scale))
    new_h = max(1, int(height / scale))
    if (new_w, new_h) == (width, height):
        return width, height, pixels
    output = bytearray(new_w * new_h * 3)
    for y in range(new_h):
        source_y = min(height - 1, y * height // new_h)
        for x in range(new_w):
            source_x = min(width - 1, x * width // new_w)
            source = (source_y * width + source_x) * 3
            target = (y * new_w + x) * 3
            output[target:target + 3] = pixels[source:source + 3]
    return new_w, new_h, bytes(output)


def orient_pixels(width: int, height: int, pixels: bytes,
                  orientation: int) -> Tuple[int, int, bytes]:
    """EXIF Orientation に従って RGB 画素を回転・反転する。"""
    if orientation not in range(2, 9):
        return width, height, pixels
    new_w, new_h = ((height, width) if orientation >= 5 else (width, height))
    output = bytearray(new_w * new_h * 3)
    for y in range(height):
        for x in range(width):
            if orientation == 2:
                nx, ny = width - 1 - x, y
            elif orientation == 3:
                nx, ny = width - 1 - x, height - 1 - y
            elif orientation == 4:
                nx, ny = x, height - 1 - y
            elif orientation == 5:
                nx, ny = y, x
            elif orientation == 6:
                nx, ny = height - 1 - y, x
            elif orientation == 7:
                nx, ny = height - 1 - y, width - 1 - x
            else:
                nx, ny = y, width - 1 - x
            source = (y * width + x) * 3
            target = (ny * new_w + nx) * 3
            output[target:target + 3] = pixels[source:source + 3]
    return new_w, new_h, bytes(output)


def exif_orientation(data: bytes) -> int:
    """JPEG の APP1 から Orientation を読む。見つからなければ 1。"""
    if not data.startswith(b"\xff\xd8"):
        return 1
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xff:
            break
        marker = data[pos + 1]
        pos += 2
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        value = data[pos + 2:pos + length]
        pos += length
        if marker != 0xe1 or not value.startswith(b"Exif\x00\x00"):
            continue
        tiff = value[6:]
        if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
            return 1
        endian = "<" if tiff[:2] == b"II" else ">"
        try:
            ifd = struct.unpack(endian + "I", tiff[4:8])[0]
            count = struct.unpack(endian + "H", tiff[ifd:ifd + 2])[0]
            for index in range(count):
                entry = tiff[ifd + 2 + index * 12:ifd + 14 + index * 12]
                tag, kind, amount = struct.unpack(endian + "HHI", entry[:8])
                if tag == 0x0112 and kind == 3 and amount == 1:
                    return struct.unpack(endian + "H", entry[8:10])[0]
        except (struct.error, IndexError):
            return 1
    return 1


class _Huffman:
    def __init__(self, counts: bytes, symbols: bytes) -> None:
        self.codes: Dict[Tuple[int, int], int] = {}
        code = 0
        offset = 0
        for length, count in enumerate(counts, 1):
            for _ in range(count):
                self.codes[(length, code)] = symbols[offset]
                offset += 1
                code += 1
            code <<= 1

    def read(self, reader: "_Bits") -> int:
        code = 0
        for length in range(1, 17):
            code = (code << 1) | reader.bits(1)
            if (length, code) in self.codes:
                return self.codes[(length, code)]
        raise ValueError("JPEG のハフマン符号を読めません")


class _Bits:
    def __init__(self, data: bytes, pos: int) -> None:
        self.data = data
        self.pos = pos
        self.buffer = 0
        self.count = 0

    def _byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("JPEG の画像データが途中で終わっています")
        value = self.data[self.pos]
        self.pos += 1
        if value == 0xff:
            while self.pos < len(self.data) and self.data[self.pos] == 0xff:
                self.pos += 1
            if self.pos >= len(self.data) or self.data[self.pos] != 0x00:
                raise ValueError("JPEG のマーカーが予期しない位置にあります")
            self.pos += 1
        return value

    def bits(self, amount: int) -> int:
        while self.count < amount:
            self.buffer = (self.buffer << 8) | self._byte()
            self.count += 8
        self.count -= amount
        return (self.buffer >> self.count) & ((1 << amount) - 1)

    def restart(self) -> None:
        self.buffer = self.count = 0
        if self.pos >= len(self.data) or self.data[self.pos] != 0xff:
            raise ValueError("JPEG のリスタートマーカーがありません")
        while self.pos < len(self.data) and self.data[self.pos] == 0xff:
            self.pos += 1
        if self.pos >= len(self.data) or not 0xd0 <= self.data[self.pos] <= 0xd7:
            raise ValueError("JPEG のリスタートマーカーを読めません")
        self.pos += 1


def _receive(reader: _Bits, size: int) -> int:
    if size == 0:
        return 0
    value = reader.bits(size)
    return value if value >= 1 << (size - 1) else value - (1 << size) + 1


def decode_jpeg_dc(data: bytes) -> Tuple[int, int, bytes]:
    """ベースライン JPEG を DC 成分だけで 1/8 大の RGB にする。"""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG ではありません")
    pos = 2
    quant: Dict[int, int] = {}
    huffman: Dict[Tuple[int, int], _Huffman] = {}
    components = {}
    width = height = 0
    restart_interval = 0
    scan = None
    while pos + 1 < len(data):
        if data[pos] != 0xff:
            raise ValueError("JPEG のマーカーを読めません")
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker == 0xd9:
            break
        if marker in (0xd8,) or 0xd0 <= marker <= 0xd7:
            continue
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        value = data[pos + 2:pos + length]
        pos += length
        if marker == 0xdb:
            offset = 0
            while offset < len(value):
                info = value[offset]
                offset += 1
                precision, table = info >> 4, info & 15
                step = 128 if precision else 64
                table_data = value[offset:offset + step]
                if len(table_data) != step:
                    raise ValueError("JPEG の量子化表を読めません")
                quant[table] = struct.unpack(">H", table_data[:2])[0] if precision else table_data[0]
                offset += step
        elif marker == 0xc0:
            if len(value) < 6 or value[0] != 8:
                raise ValueError("対応していない JPEG です")
            height, width, count = struct.unpack(">HHB", value[1:6])
            offset = 6
            for _ in range(count):
                ident, sampling, table = value[offset:offset + 3]
                components[ident] = {"h": sampling >> 4, "v": sampling & 15,
                                     "q": table, "dc": 0, "blocks": []}
                offset += 3
            factors = sorted((c["h"], c["v"]) for c in components.values())
            max_h = max(c["h"] for c in components.values())
            max_v = max(c["v"] for c in components.values())
            if len(components) not in (1, 3) or max_h not in (1, 2) or max_v not in (1, 2):
                raise ValueError("対応していない JPEG の色形式です")
            if len(components) == 3:
                sampling = [(c["h"], c["v"]) for c in components.values()]
                if sampling not in ([(1, 1), (1, 1), (1, 1)],
                                     [(2, 2), (1, 1), (1, 1)]):
                    raise ValueError("対応していない JPEG のサンプリングです")
        elif marker == 0xc2:
            raise ValueError("プログレッシブ JPEG には対応していません")
        elif marker == 0xc4:
            offset = 0
            while offset < len(value):
                info = value[offset]
                counts = value[offset + 1:offset + 17]
                size = sum(counts)
                symbols = value[offset + 17:offset + 17 + size]
                if len(counts) != 16 or len(symbols) != size:
                    raise ValueError("JPEG のハフマン表を読めません")
                huffman[(info >> 4, info & 15)] = _Huffman(counts, symbols)
                offset += 17 + size
        elif marker == 0xdd:
            restart_interval = struct.unpack(">H", value)[0]
        elif marker == 0xda:
            scan_count = value[0]
            offset = 1
            scan = []
            for _ in range(scan_count):
                ident, tables = value[offset:offset + 2]
                scan.append((ident, tables >> 4, tables & 15))
                offset += 2
            if value[offset:offset + 3] != b"\x00\x3f\x00":
                raise ValueError("対応していない JPEG スキャンです")
            break
    if not scan or not width or not height or len(scan) != len(components):
        raise ValueError("JPEG の画像情報を読めません")
    max_h = max(c["h"] for c in components.values())
    max_v = max(c["v"] for c in components.values())
    mcus_x = (width + max_h * 8 - 1) // (max_h * 8)
    mcus_y = (height + max_v * 8 - 1) // (max_v * 8)
    for component in components.values():
        component["blocks"] = [0] * (mcus_x * component["h"] * mcus_y * component["v"])
    reader = _Bits(data, pos)
    for mcu in range(mcus_x * mcus_y):
        if restart_interval and mcu and mcu % restart_interval == 0:
            reader.restart()
            for component in components.values():
                component["dc"] = 0
        mcu_x, mcu_y = mcu % mcus_x, mcu // mcus_x
        for ident, dc_table, ac_table in scan:
            component = components[ident]
            dc_huff = huffman[(0, dc_table)]
            ac_huff = huffman[(1, ac_table)]
            for block_y in range(component["v"]):
                for block_x in range(component["h"]):
                    category = dc_huff.read(reader)
                    component["dc"] += _receive(reader, category)
                    value = component["dc"] * quant[component["q"]] / 8.0 + 128.0
                    bx = mcu_x * component["h"] + block_x
                    by = mcu_y * component["v"] + block_y
                    blocks_w = mcus_x * component["h"]
                    component["blocks"][by * blocks_w + bx] = max(0, min(255, round(value)))
                    coefficient = 1
                    while coefficient < 64:
                        symbol = ac_huff.read(reader)
                        if symbol == 0:
                            break
                        run, size = symbol >> 4, symbol & 15
                        if size == 0 and run == 15:
                            coefficient += 16
                        else:
                            coefficient += run + 1
                            _receive(reader, size)
    output_w = (width + 7) // 8
    output_h = (height + 7) // 8
    order = list(components)
    rgb = bytearray()
    for y in range(output_h):
        values = []
        for x in range(output_w):
            values.clear()
            for ident in order:
                component = components[ident]
                cx = min(mcus_x * component["h"] - 1, x * component["h"] // max_h)
                cy = min(mcus_y * component["v"] - 1, y * component["v"] // max_v)
                values.append(component["blocks"][cy * mcus_x * component["h"] + cx])
            if len(values) == 1:
                red = green = blue = values[0]
            else:
                luminance, cb, cr = values
                red = luminance + 1.402 * (cr - 128)
                green = luminance - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
                blue = luminance + 1.772 * (cb - 128)
            rgb.extend(max(0, min(255, round(value))) for value in (red, green, blue))
    return output_w, output_h, bytes(rgb)


def _tk_thumbnail(source: Path, target: Path, max_px: int) -> bool:
    try:
        import tkinter as tk
        # PhotoImage は作成済みの Tk と同じメインスレッドでだけ安全に使える。
        # 一覧の作業スレッドでは、直後の標準ライブラリ処理へ進む。
        master = getattr(tk, "_default_root", None)
        if master is None or threading.current_thread() is not threading.main_thread():
            return False
        photo = tk.PhotoImage(master=master, file=str(source))
        sample = max(1, (max(photo.width(), photo.height()) + max_px - 1) // max_px)
        if sample > 1:
            photo = photo.subsample(sample, sample)
        photo.write(str(target), format="png")
        return True
    except Exception:
        return False


def _plain_png_thumbnail(source: Path, target: Path, max_px: int) -> bool:
    try:
        width, height, pixels = read_png(source)
        width, height, pixels = _scaled(width, height, pixels, max_px)
        write_png(target, width, height, pixels)
        return True
    except (OSError, ValueError, zlib.error):
        return False


def _powershell_thumbnail(source: Path, target: Path, max_px: int) -> bool:
    script = r"""
Add-Type -AssemblyName System.Drawing
$image = [System.Drawing.Image]::FromFile($env:GIKAI_THUMB_SOURCE)
try {
  $scale = [Math]::Min($env:GIKAI_THUMB_MAX / $image.Width, $env:GIKAI_THUMB_MAX / $image.Height)
  $scale = [Math]::Min(1.0, $scale)
  $width = [Math]::Max(1, [int][Math]::Round($image.Width * $scale))
  $height = [Math]::Max(1, [int][Math]::Round($image.Height * $scale))
  $bitmap = New-Object System.Drawing.Bitmap($width, $height)
  try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
      $graphics.DrawImage($image, 0, 0, $width, $height)
    } finally { $graphics.Dispose() }
    $bitmap.Save($env:GIKAI_THUMB_TARGET, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally { $bitmap.Dispose() }
} finally { $image.Dispose() }
"""
    env = os.environ.copy()
    env.update(GIKAI_THUMB_SOURCE=str(source), GIKAI_THUMB_TARGET=str(target),
               GIKAI_THUMB_MAX=str(max_px))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script], env=env, timeout=30, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode == 0 and target.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _sips_thumbnail(source: Path, target: Path, max_px: int) -> bool:
    try:
        result = subprocess.run(
            ["sips", "-Z", str(max_px), "-s", "format", "png", str(source),
             "--out", str(target)], timeout=30, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0 and target.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _fix_external_orientation(source: Path, target: Path, max_px: int) -> bool:
    try:
        width, height, pixels = read_png(target)
        orientation = exif_orientation(source.read_bytes())
        width, height, pixels = orient_pixels(width, height, pixels, orientation)
        width, height, pixels = _scaled(width, height, pixels, max_px)
        write_png(target, width, height, pixels)
        return True
    except (OSError, ValueError, zlib.error):
        return False


def thumbnail(path: Path, max_px: int) -> Optional[Path]:
    """一辺 max_px 以下の画面用 PNG を作り、キャッシュ先を返す。"""
    source = Path(path)
    if max_px < 1 or not source.is_file():
        return None
    try:
        stat = source.stat()
    except OSError:
        return None
    cache = source.parent / ".縮小"
    digest = hashlib.sha256(source.name.encode("utf-8")).hexdigest()[:16]
    target = cache / f"{digest}_{stat.st_size}_{stat.st_mtime_ns}_{max_px}.png"
    with _LOCK:
        if target.is_file():
            return target
        try:
            cache.mkdir(exist_ok=True)
        except OSError:
            return None
        suffix = source.suffix.lower()
        if suffix in (".png", ".gif"):
            if _tk_thumbnail(source, target, max_px):
                return target
            if suffix == ".png" and _plain_png_thumbnail(source, target, max_px):
                return target
        made = False
        if sys.platform.startswith("win"):
            made = _powershell_thumbnail(source, target, max_px)
        elif sys.platform == "darwin":
            made = _sips_thumbnail(source, target, max_px)
        if made:
            if _fix_external_orientation(source, target, max_px):
                return target
            return None
        if suffix in (".jpg", ".jpeg"):
            try:
                data = source.read_bytes()
                width, height, pixels = decode_jpeg_dc(data)
                width, height, pixels = orient_pixels(width, height, pixels,
                                                      exif_orientation(data))
                width, height, pixels = _scaled(width, height, pixels, max_px)
                write_png(target, width, height, pixels)
                return target
            except (OSError, ValueError, KeyError, struct.error):
                return None
    return None
