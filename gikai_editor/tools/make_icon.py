#!/usr/bin/env python3
"""起動用アイコンを作る。

    python tools/make_icon.py

議会だより＝縦書きの広報紙、というイメージで、
緑の角丸の上に白い紙面（赤の題字帯と縦組みの本文）を置いている。

小さい表示（16px）でも形が潰れないよう、大きさごとに描き込みの
細かさを変えている。4倍で描いてから縮小して輪郭をなめらかにする。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

GREEN = (31, 111, 74)        # 表紙の地色（画面の配色と同じ）
GREEN_DARK = (22, 84, 55)
PAPER = (255, 255, 255)
BAND = (178, 58, 72)         # 題字の帯
TEXT = (95, 105, 120)        # 本文を表す線
SEAL = (200, 90, 60)

OUT = Path(__file__).resolve().parents[1]
SS = 4  # 描画時の拡大率（縮小して輪郭をなめらかにする）


def draw_icon(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(v: float) -> float:
        return v * s

    # 小さいときは、緑の余白を削って紙面を大きく取る。
    # そうしないと 16px で本文の線が潰れて読めなくなる。
    small = size < 32
    frame_r = 0.16 if small else 0.22
    margin_x = 0.13 if small else 0.22
    margin_t = 0.10 if small else 0.145
    margin_b = 0.90 if small else 0.855

    # --- 地の角丸四角
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=px(frame_r), fill=GREEN)
    # 下側をわずかに沈めて立体感を出す（32px 以上のときだけ）
    if size >= 32:
        d.rounded_rectangle((0, px(0.52), s - 1, s - 1), radius=px(frame_r), fill=GREEN_DARK)
        d.rounded_rectangle((0, 0, s - 1, px(0.62)), radius=px(frame_r), fill=GREEN)

    # --- 紙面
    pl, pt, pr, pb = px(margin_x), px(margin_t), px(1 - margin_x), px(margin_b)
    d.rounded_rectangle((pl, pt, pr, pb), radius=px(0.02 if small else 0.035), fill=PAPER)

    # --- 題字の帯
    band_h = (pb - pt) * (0.20 if size >= 24 else 0.24)
    d.rounded_rectangle(
        (pl, pt, pr, pt + band_h), radius=px(0.035), fill=BAND
    )
    d.rectangle((pl, pt + band_h - px(0.03), pr, pt + band_h), fill=BAND)

    # --- 縦組みの本文を表す線
    body_top = pt + band_h + (pb - pt) * 0.10
    body_bottom = pb - (pb - pt) * 0.09
    body_h = body_bottom - body_top

    if size >= 48:
        ratios, lw = [0.92, 0.74, 0.98, 0.62, 0.86], 0.036
    elif size >= 32:
        ratios, lw = [0.92, 0.70, 0.96, 0.64], 0.045
    else:
        ratios, lw = [0.92, 0.68, 0.96], 0.062

    n = len(ratios)
    left, right = pl + (pr - pl) * 0.13, pr - (pr - pl) * 0.13
    span = right - left
    step = span / n
    w = px(lw)
    # 縦書きは右から左へ読むので、右端から並べる
    for i, r in enumerate(ratios):
        cx = right - step * (i + 0.5)
        h = body_h * r
        d.rounded_rectangle(
            (cx - w / 2, body_top, cx + w / 2, body_top + h),
            radius=w / 2, fill=TEXT,
        )

    # --- 朱印（大きいときだけ）
    if size >= 64:
        r = px(0.052)
        cx, cy = pr - px(0.075), pb - px(0.075)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SEAL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw_icon(s) for s in sizes]

    # Windows のショートカット用
    images[-1].save(OUT / "icon.ico", format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=images[:-1])
    # ブラウザのタブ用
    (OUT / "gikai" / "static").mkdir(parents=True, exist_ok=True)
    images[-1].save(OUT / "gikai" / "static" / "favicon.ico", format="ICO",
                    sizes=[(16, 16), (32, 32), (48, 48)])
    # macOS / Linux 用
    draw_icon(512).save(OUT / "gikai" / "static" / "icon.png")
    draw_icon(512).save(OUT / "icon.png")

    print("作成しました:")
    for p in ("icon.ico", "icon.png", "gikai/static/favicon.ico", "gikai/static/icon.png"):
        f = OUT / p
        print(f"  {p:32s} {f.stat().st_size:>7,} バイト")


if __name__ == "__main__":
    main()
