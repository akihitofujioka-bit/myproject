"""賛否一覧表（VoteTable）を Word の表にする。

表は、様式の「別添１：…議案・発議案と賛否」の文字枠の中に入れる。
この枠は横書きなので、表は Excel と同じ向き（議案が上から下、議員名が
左から右）のまま組める。縦書きの本文に直接置くと 90 度倒れてしまう。

gikai_editor で実際に起きた不具合を避けるため、次を守っている。
  * 升目の段落は行グリッドから外す（snapToGrid=0）。外さないと 1 行に入る字数が
    半分になって字が切れる
  * 表の幅は枠より数 mm 狭くする。同じ幅だと中の字が早く折り返して行が重なる
"""

from __future__ import annotations

import math
from xml.etree import ElementTree as ET

from xlsx_vote import VoteTable

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FONT_MINCHO = "ＭＳ 明朝"
FONT_GOTHIC = "ＭＳ ゴシック"
BODY_PT = 8          # 表の中の字（実物の別添の表と同じくらい）
TITLE_PT = 11
MEMBER_COL_MM = 7.5      # 6.5mm では「議長」が 2 行に割れた
CAT_COL_MM = 13
RESULT_COL_MM = 10
LINE_MM = BODY_PT * 25.4 / 72 * 1.35      # 表の 1 行の高さの目安


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def mm2tw(mm: float) -> int:
    return int(round(mm * 1440 / 25.4))


def _sub(parent: ET.Element, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, w(tag), {w(k): v for k, v in attrs.items()})


def _para(text: str, *, pt: float = BODY_PT, font: str = FONT_MINCHO, bold: bool = False,
          jc: str = "left") -> ET.Element:
    p = ET.Element(w("p"))
    ppr = _sub(p, "pPr")
    _sub(ppr, "snapToGrid", val="0")
    _sub(ppr, "spacing", line="240", lineRule="auto")
    _sub(ppr, "jc", val=jc)
    if text:
        r = _sub(p, "r")
        rpr = _sub(r, "rPr")
        _sub(rpr, "rFonts", ascii=font, eastAsia=font, hAnsi=font)
        if bold:
            _sub(rpr, "b")
        _sub(rpr, "sz", val=str(int(pt * 2)))
        _sub(rpr, "szCs", val=str(int(pt * 2)))
        t = _sub(r, "t")
        t.text = text
    return p


def _cell(tr: ET.Element, width_mm: float, lines: list[str], *, vertical: bool = False,
          font: str = FONT_MINCHO, jc: str = "center", shade: str = "") -> None:
    tc = _sub(tr, "tc")
    pr = _sub(tc, "tcPr")
    _sub(pr, "tcW", w=str(mm2tw(width_mm)), type="dxa")
    if shade:
        _sub(pr, "shd", val="clear", color="auto", fill=shade)
    if vertical:
        _sub(pr, "textDirection", val="tbRlV")
    _sub(pr, "vAlign", val="center")
    for line in lines or [""]:
        tc.append(_para(line, font=font, jc=jc))


def _widths(vote: VoteTable, width_mm: float) -> list[float]:
    n = len(vote.members)
    item = width_mm - CAT_COL_MM - RESULT_COL_MM - MEMBER_COL_MM * n
    return [CAT_COL_MM, max(30.0, item)] + [MEMBER_COL_MM] * n + [RESULT_COL_MM]


def build_vote_blocks(vote: VoteTable, width_mm: float) -> list[ET.Element]:
    """文字枠の中身（表題・凡例・表）を段落と表の並びで返す。"""
    out = []
    widths = _widths(vote, width_mm)
    out.append(_para(vote.title or "議案・発議案と賛否", pt=TITLE_PT, font=FONT_GOTHIC,
                     bold=True))
    if vote.legend:
        out.append(_para(vote.legend, jc="right"))

    tbl = ET.Element(w("tbl"))
    pr = _sub(tbl, "tblPr")
    _sub(pr, "tblW", w=str(mm2tw(sum(widths))), type="dxa")
    borders = _sub(pr, "tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        _sub(borders, side, val="single", sz="4", space="0", color="000000")
    _sub(pr, "tblLayout", type="fixed")
    cm = _sub(pr, "tblCellMar")
    for side in ("left", "right"):
        _sub(cm, side, w=str(mm2tw(0.6)), type="dxa")
    grid = _sub(tbl, "tblGrid")
    for wd in widths:
        _sub(grid, "gridCol", w=str(mm2tw(wd)))

    # 見出しの行: 議員名は縦書き。高さは名前の字数に合わせる
    head = _sub(tbl, "tr")
    trpr = _sub(head, "trPr")
    _sub(trpr, "trHeight", val=str(mm2tw(_head_mm(vote))), hRule="atLeast")
    _sub(trpr, "tblHeader")
    gray = "E7E6E6"
    _cell(head, widths[0], ["区　分"], font=FONT_GOTHIC, shade=gray)
    _cell(head, widths[1], ["議案・発議案"], font=FONT_GOTHIC, shade=gray)
    for k, name in enumerate(vote.members):
        _cell(head, widths[2 + k], [name], vertical=True, font=FONT_GOTHIC, shade=gray)
    _cell(head, widths[-1], ["議決結果"], vertical=True, font=FONT_GOTHIC, shade=gray)

    for row in vote.rows:
        tr = _sub(tbl, "tr")
        _sub(_sub(tr, "trPr"), "cantSplit")
        _cell(tr, widths[0], [row.category])
        _cell(tr, widths[1], row.items, jc="left")
        for v in row.votes:
            _cell(tr, MEMBER_COL_MM, [v])
        _cell(tr, widths[-1], [row.result])
    out.append(tbl)
    # 枠の中身は段落で終わらなければならない（表で終わると Word が直そうとする）
    out.append(_para(""))
    return out


def _head_mm(vote: VoteTable) -> float:
    longest = max([len(m.replace("　", "")) for m in vote.members] + [4])
    return longest * BODY_PT * 25.4 / 72 * 1.1 + 3


def vote_table_height_mm(vote: VoteTable, width_mm: float) -> float:
    """枠の高さの目安（表題・凡例・見出し・各行）。"""
    widths = _widths(vote, width_mm)
    per_line = max(1, int((widths[1] - 1.5) / (BODY_PT * 25.4 / 72)))
    h = TITLE_PT * 25.4 / 72 * 1.4 + (LINE_MM if vote.legend else 0) + _head_mm(vote)
    for row in vote.rows:
        lines = sum(max(1, math.ceil(len(t) / per_line)) for t in row.items)
        h += max(lines, 1) * LINE_MM + 1
    return h + LINE_MM
