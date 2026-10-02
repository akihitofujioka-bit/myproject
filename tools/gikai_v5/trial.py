"""段階 1 の確かめ（設計図 §15）: ツールの計算どおりに Word で文字が並ぶか。

    python trial.py [出力先.docx]

2 ページの Word を作る。

1. **格子の確認** — 全部の段・全部の行に「行番号＋かな＋終」を 12 字ちょうどで入れる。
   Word で開いて、どの行も「終」が段の下の端にあり、1 段に 30 行並んでいれば計算どおり。
   1 字でも折り返されると「終」が次の行に落ちるので、すぐ分かる
2. **組みの見本** — 大見出し（囲み）・中見出し・写真の場所・本文の流し込み（禁則あり）

薄い灰色の線は段の輪郭（確かめ用）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import docx_out as dx
from grid import Geometry, Rect, flow, layout_text, to_box, whole_page

KANA = "あいうえおかきくけこさしすせそたちつてと"
ZEN = str.maketrans("0123456789", "０１２３４５６７８９")

SAMPLE = [
    "これは組みの見本です。本文は一段に十二字ずつ、右の行から左の行へ流れます。"
    "句読点や閉じ括弧（「」など）が行の頭に来ないよう、前の行の字を送っています。",
    "写真の場所を空けると、その段の本文は写真の右と左に分かれて続きます。"
    "見出しのある段も同じで、空いている行だけに本文が入ります。",
    "問　この見本の文章は、何度も繰り返して紙面を埋めていますか。",
    "答　そのとおりです。あふれた行の数は、作るときに画面へ表示します。",
]


def guides(g: Geometry) -> list:
    return [dx.Guide(to_box(g, Rect(d, 0, 1, g.lines_per_dan))) for d in range(g.dans)]


def page_grid_check(g: Geometry) -> dx.Page:
    page = dx.Page(guides(g))
    n = g.chars_per_line
    for d in range(g.dans):
        lines = []
        for ln in range(g.lines_per_dan):
            head = f"{d + 1}{ln + 1:02d}".translate(ZEN)       # 例: １０１ ＝ 1 段目の 1 行目
            lines.append((head + KANA)[: n - 1] + "終")
        page.items.append(dx.TextBox(to_box(g, Rect(d, 0, 1, g.lines_per_dan)), lines,
                                     pt=g.body_pt, pitch_pt=g.line_pitch_pt, name="check"))
    return page


def page_sample(g: Geometry) -> dx.Page:
    page = dx.Page(guides(g))
    big = Rect(0, 0, 2, 4)            # 1〜2 段目 × 右から 4 行
    mid = Rect(2, 0, 1, 2)
    photo = Rect(0, 12, 2, 10)
    occupied = [big, mid, photo]

    page.items.append(dx.TextBox(to_box(g, big), ["大見出しの見本", "囲み・ゴシック１８ポ"],
                                 font=dx.GOTHIC, pt=18, pitch_pt=g.line_pitch_pt * 4 / 2.5,
                                 border=True, center=True, name="h1"))
    page.items.append(dx.TextBox(to_box(g, mid), ["中見出し１６ポ"], font=dx.GOTHIC, pt=16,
                                 pitch_pt=g.line_pitch_pt * 2, center=True, name="h2"))
    page.items.append(dx.Placeholder(to_box(g, photo), "写真（大）の場所"))

    lines = layout_text(SAMPLE * 12, g.chars_per_line)
    result = flow(g, lines, whole_page(g), occupied)
    for run in result.runs:
        page.items.append(dx.TextBox(to_box(g, run.rect), run.lines, pt=g.body_pt,
                                     pitch_pt=g.line_pitch_pt, name="body"))
    print(f"見本ページ: 本文 {len(lines)} 行、あふれ {result.overflow_lines} 行、余り {result.free_lines} 行")
    return page


def main(argv: list[str]) -> int:
    g = Geometry()
    bad = g.check()
    if bad:
        print("\n".join(bad))
        return 1
    out = Path(argv[1]) if len(argv) > 1 else Path(__file__).parent / "試し出力" / "段階1_格子の確認.docx"
    dx.write_docx(out, g, [page_grid_check(g), page_sample(g)])
    print(f"1 段 {g.lines_per_dan} 行 × {g.chars_per_line} 字、段の間 {g.gap_pt:.1f}pt")
    print(f"書き出しました: {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
