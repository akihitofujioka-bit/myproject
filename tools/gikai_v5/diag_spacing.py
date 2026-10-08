"""Windows の Word で字が欠ける原因を見分けるための確かめ用 Word を作る。

    python diag_spacing.py [出力先.docx]

段ごとに行送りの指定のしかたを変えて、同じ「行番号＋かな＋終」を並べる。
役場のパソコンの Word で開き、**どの段なら「終」が欠けずに見えるか**を確かめる。
行の頭の字（Ａ〜Ｅ）がその段の指定を表す。

| 段 | 頭の字 | 指定 |
|---|---|---|
| 1 | Ａ | 今の作り（本文の行送り 最小値 17pt・枠の下の余裕 6pt。2026-10-08 に固定値から変更） |
| 2 | Ｂ | 行送り「最小値」17pt（今の作りと同じ） |
| 3 | Ｃ | 固定値 17pt、枠の下の余裕を 1 字半（17pt）に |
| 4 | Ｄ | 行送りを指定しない（1 行） |
| 5 | Ｅ | 固定値 20pt（行送りを広げる） |

2 ページ目は同じ並びを ＭＳ ゴシックで作る。
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import docx_out as dx
from grid import Geometry, Rect, to_box

KANA = "あいうえおかきくけこ"
ZEN = str.maketrans("0123456789", "０１２３４５６７８９")
LETTERS = "ＡＢＣＤＥ"
EMU = dx.EMU_PER_PT


def _page(g: Geometry, font: str) -> dx.Page:
    page = dx.Page([dx.Guide(to_box(g, Rect(d, 0, 1, g.lines_per_dan))) for d in range(g.dans)])
    for d in range(g.dans):
        lines = [(LETTERS[d] + f"{ln + 1:02d}".translate(ZEN) + KANA)[: g.chars_per_line - 1] + "終"
                 for ln in range(g.lines_per_dan)]
        page.items.append(dx.TextBox(to_box(g, Rect(d, 0, 1, g.lines_per_dan)), lines, font=font,
                                     pt=g.body_pt, pitch_pt=g.line_pitch_pt, name=f"diag{d}"))
    return page


def _vary(xml: str) -> str:
    """枠ごとに、頭の字（Ａ〜Ｅ）に合わせて行送りと枠の高さを書き換える。"""
    parts = xml.split("<w:r><w:drawing>")
    out = [parts[0]]
    for part in parts[1:]:
        letter = next((c for c in LETTERS if c in part), None)
        if letter == "Ｂ":
            part = re.sub(r'w:lineRule="\w+"', 'w:lineRule="atLeast"', part)
        elif letter == "Ｃ":
            part = re.sub(r'w:lineRule="\w+"', 'w:lineRule="exact"', part)
            extra = int(round((17 - dx.SLACK_PT) * EMU))
            part = re.sub(r'(<wp:extent cx="\d+" cy=")(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + extra), part)
            part = re.sub(r'(<a:ext cx="\d+" cy=")(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + extra), part)
        elif letter == "Ｄ":
            part = re.sub(r' w:line="\d+" w:lineRule="\w+"', "", part)
        elif letter == "Ｅ":
            part = re.sub(r'w:line="\d+" w:lineRule="\w+"', 'w:line="400" w:lineRule="exact"', part)
        out.append(part)
    return "<w:r><w:drawing>".join(out)


def main(argv: list) -> int:
    g = Geometry()
    out = Path(argv[1]) if len(argv) > 1 else Path(__file__).parent / "試し出力" / "行送りの確かめ.docx"
    dx.write_docx(out, g, [_page(g, dx.MINCHO), _page(g, dx.GOTHIC)])
    # 書き出した document.xml だけを書き換えて入れ直す
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(out) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                data = _vary(data.decode("utf-8")).encode("utf-8")
            dst.writestr(item, data)
    tmp.replace(out)
    print(f"書き出しました: {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
