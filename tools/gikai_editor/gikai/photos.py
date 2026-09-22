"""写真の取り込み・トリミング・様式への差し込み。

議員から届く写真は、向きも大きさもばらばらで、そのままでは
紙面の枠に合わない。ここでは次の処理を行う。

  * EXIF の回転情報を反映して正しい向きにする
  * 枠の縦横比に合わせて中央を切り出す（洋服の裾上げと同じ考え方）
  * 印刷に必要な解像度が足りているかを判定する
  * 様式に入っている写真を、枠を崩さずに差し替える

Pillow が入っていない環境でも、差し替えだけはできるようにしている。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, asdict
from pathlib import Path

try:  # Pillow は任意。無い場合は機能を限定して動かす
    from PIL import Image, ImageOps, ExifTags  # type: ignore

    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

# 印刷に必要な解像度。議会だよりは 350dpi で刷ることが多い。
PRINT_DPI = 350
WEB_DPI = 150


@dataclass
class PhotoInfo:
    name: str
    width: int
    height: int
    bytes: int
    format: str = ""
    orientation: str = ""  # 横 / 縦 / 正方形
    print_ok: bool = True
    max_print_cm: tuple[float, float] = (0.0, 0.0)
    warning: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["max_print_cm"] = list(self.max_print_cm)
        return d


def inspect(data: bytes, name: str = "") -> PhotoInfo:
    """写真の大きさと、印刷に耐えるかどうかを調べる。"""
    if not HAS_PIL:
        return PhotoInfo(name=name, width=0, height=0, bytes=len(data),
                         warning="Pillow が入っていないため写真の情報を読めません")
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im) or im
        w, h = im.size
        fmt = im.format or ""
    orient = "正方形" if abs(w - h) < min(w, h) * 0.05 else ("横" if w > h else "縦")
    # 350dpi で刷れる最大サイズ（cm）
    max_w = w / PRINT_DPI * 2.54
    max_h = h / PRINT_DPI * 2.54
    info = PhotoInfo(
        name=name, width=w, height=h, bytes=len(data), format=fmt,
        orientation=orient, max_print_cm=(round(max_w, 1), round(max_h, 1)),
    )
    # 紙面でよく使う最小サイズ（横4cm）に満たなければ警告
    if max_w < 4.0 or max_h < 3.0:
        info.print_ok = False
        info.warning = (
            f"解像度が足りません（{w}×{h}px）。この写真は印刷すると"
            f"最大でも約{max_w:.1f}×{max_h:.1f}cm です。"
            "元データ（撮影したままのファイル）をもらってください。"
        )
    elif len(data) < 80 * 1024:
        info.warning = "ファイルサイズが小さめです。メールで圧縮された可能性があります。"
    return info


def crop_to_ratio(
    data: bytes,
    ratio: float,
    *,
    focus: tuple[float, float] = (0.5, 0.4),
    max_px: int = 3000,
    quality: int = 92,
) -> bytes:
    """枠の縦横比 ``ratio``（幅÷高さ）に合わせて切り出す。

    ``focus`` は残したい部分の中心（0〜1）。人物写真は顔が上寄りなので
    既定値は少し上を向けている。
    """
    if not HAS_PIL:
        return data
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        w, h = im.size
        cur = w / h
        if abs(cur - ratio) < 0.01:
            box = (0, 0, w, h)
        elif cur > ratio:  # 横に長い → 左右を切る
            new_w = int(round(h * ratio))
            cx = int(w * focus[0])
            left = max(0, min(w - new_w, cx - new_w // 2))
            box = (left, 0, left + new_w, h)
        else:  # 縦に長い → 上下を切る
            new_h = int(round(w / ratio))
            cy = int(h * focus[1])
            top = max(0, min(h - new_h, cy - new_h // 2))
            box = (0, top, w, top + new_h)
        out = im.crop(box)
        if max(out.size) > max_px:
            scale = max_px / max(out.size)
            out = out.resize(
                (max(1, int(out.width * scale)), max(1, int(out.height * scale))),
                Image.LANCZOS,
            )
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=quality, optimize=True, dpi=(PRINT_DPI, PRINT_DPI))
        return buf.getvalue()


def to_thumbnail(data: bytes, size: int = 320) -> bytes:
    """画面表示用の縮小画像。"""
    if not HAS_PIL:
        return data
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
        return buf.getvalue()


def match_format(data: bytes, target_name: str) -> bytes:
    """様式に入っている画像と同じ形式に変換する。

    Word は画像の形式と拡張子が食い違うと表示できないことがあるため、
    差し替え時は元の形式に合わせる。
    """
    ext = Path(target_name).suffix.lower()
    if not HAS_PIL:
        return data
    fmt = {
        ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
        ".gif": "GIF", ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF",
    }.get(ext)
    if not fmt:
        return data
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im) or im
        if fmt == "JPEG":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format=fmt)
        return buf.getvalue()


def aspect_of(data: bytes) -> float:
    """幅÷高さ。読めなければ 4/3 を返す。"""
    if not HAS_PIL:
        return 4 / 3
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im) or im
            return im.width / im.height
    except Exception:
        return 4 / 3


def prepare_for_slot(data: bytes, target_name: str, target_data: bytes | None) -> bytes:
    """様式の写真枠に差し込めるかたちに整える。

    枠の縦横比は、いま入っている画像の縦横比から推定する
    （Word の図はたいてい枠と画像の比が一致しているため）。
    """
    ratio = aspect_of(target_data) if target_data else None
    out = data
    if ratio:
        out = crop_to_ratio(out, ratio)
    return match_format(out, target_name)
