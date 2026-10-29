"""原稿の部品を 1 ページへ自動配置する（設計図 §7、段階 4）。

    python compose.py 原稿ファイル [区分名] [出力.docx]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import docx_out as dx
import ingest as I
import layout
from grid import Geometry, Rect, free_runs, mm2pt, split_lines, text_width, to_box, whole_page

# 特大は従来の紙面にある幅 105〜110mm の写真に合わせる。
PHOTO_WIDTH_MM = {"特大": 110.0, "大": 80.0, "中": 55.0, "小": 38.0, "顔": 26.0,
                  "顔小": 22.0, "顔大": 30.0, "顔特大": 38.0}   # 顔写真は縦長（幅:高さ = 3:4）。顔特大は 2 段
# 紙面を見るで「大きく」「小さく」するときの順（顔写真は縦長のまま大きさだけ変える）
PHOTO_STEPS = (("小", "中", "大", "特大"), ("顔小", "顔", "顔大", "顔特大"))
PITCH = Geometry().line_pitch_pt
PHOTO_SMALLER = {"特大": "大", "大": "中", "中": "小", "小": None, "顔": None,
                 "顔小": None, "顔大": None, "顔特大": None}


@dataclass
class Placement:
    """1 つの部品が占めた格子上の場所。長い本文は複数になる。"""

    part: I.Part
    rect: Rect
    index: int


@dataclass
class PageResult:
    page: dx.Page
    overflow_lines: int
    free_lines: int
    warnings: List[str] = field(default_factory=list)
    placements: List[Placement] = field(default_factory=list)
    overflow_parts: List[I.Part] = field(default_factory=list)


def photo_rect(g: Geometry, size: str, dan: int, line: int) -> Rect:
    """写真の mm 寸法を格子へ切り上げる。段の間も写真の高さに使う。"""
    width = PHOTO_WIDTH_MM[size]
    height = width * (4 / 3 if size.startswith("顔") else 3 / 4)
    line_span = math.ceil(mm2pt(width) / g.line_pitch_pt)
    needed_h = mm2pt(height) + (16.0 if size.startswith("顔") and size != "顔" else 0.0)   # 顔写真の下の議員名の分
    dan_span = 1
    while dan_span * g.dan_h_pt + (dan_span - 1) * g.gap_pt < needed_h:
        dan_span += 1
    return Rect(dan, line, dan_span, line_span)


def _mid_heading(g: Geometry, text: str, base_pt: float = 16.0) -> Tuple[float, List[str], int]:
    """中見出しの (字の大きさ, 行, 格子の行数) を決める。16pt で 1〜3 行に
    収め、収まらない長さなら字を小さくする。文字は削らない。
    格子の行数は 行数 + 1 以上にし、行送りが 字×1.4 を下回らないようにする。"""

    def span(lines: List[str], pt: float) -> int:
        need = math.ceil(len(lines) * dx.effective_pitch(pt, PITCH) / g.line_pitch_pt - 1e-6)
        return max(len(lines) + 1, need)
    sample = Rect(0, 0, 1, 2)
    if HEADING_BREAK in text:
        # 「大まかな質問｜答」は、それぞれを 1〜2 行にして並べる
        # まず字を小さくしてでも、それぞれ 1 行に収める。無理なら 2 行ずつにする
        for max_lines in (1, 2):
            for pt in (float(value) for value in range(int(base_pt), 11, -1)):
                per_line = _per_line(g, sample, pt, inset=False)
                pieces = [piece.strip() for piece in text.split(HEADING_BREAK) if piece.strip()]
                lines = _heading_lines(text, per_line, 2)
                if len(lines) <= max_lines * len(pieces) and max(text_width(l) for l in lines) <= per_line:
                    return pt, lines, span(lines, pt)
    for pt in (float(value) for value in range(int(base_pt), 11, -1)):
        per_line = _per_line(g, sample, pt, inset=False)
        for max_lines in (1, 2, 3):
            lines = _heading_lines(text, per_line, max_lines)
            if len(lines) <= max_lines and max(text_width(l) for l in lines) <= per_line:
                return pt, lines, span(lines, pt)
    per_line = _per_line(g, sample, 12.0, inset=False)
    lines = split_lines(text, per_line, indent=False) or [""]
    return 12.0, lines, span(lines, 12.0)


def _caption(parts: List[I.Part], index: int) -> str:
    if index + 1 < len(parts) and parts[index + 1].kind == "写真説明":
        return parts[index + 1].text.lstrip("▲△").strip()
    return ""


def _image_ext(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    if ext == "jpg":
        return "jpeg"
    if ext in ("png", "jpeg"):
        return ext
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    raise ValueError(f"画像の形式を判定できません: {name}")


def _fits(g: Geometry, rect: Rect, occupied: List[Rect]) -> bool:
    return (rect.dan >= 0 and rect.line >= 0
            and rect.dan + rect.dan_span <= g.dans
            and rect.line + rect.line_span <= g.lines_per_dan
            and not any(rect.overlaps(other) for other in occupied))


def _table_size(g: Geometry, part: I.Part, width: Optional[float] = None):
    """表の (行, 列の幅, 行の高さ, 要る段の数)。width を省くとページの幅いっぱい。中身が読めなければ None。"""
    import tables
    decoded = tables.decode(part.text)
    if decoded is None or not decoded[1]:
        return None
    rows = decoded[1]
    width = width or to_box(g, Rect(0, 0, 1, g.lines_per_dan)).w
    word = tables.decode_word(part.text)
    if word:
        # Word の表は元の列の幅と字の大きさで並ぶので、高さはそれで見積もる
        fitted, _word_pt = tables.fit_word_xml(word, width)
        widths, heights = tables.word_heights(fitted)
    else:
        widths, heights = tables.layout(rows, width)
    needed = sum(heights)
    dans = 1
    while dans < g.dans and dans * g.dan_h_pt + (dans - 1) * g.gap_pt < needed:
        dans += 1
    return rows, widths, heights, dans


def _table_dans(g: Geometry, part: I.Part) -> int:
    size = _table_size(g, part)
    return size[3] if size else 1


TABLE_MIN_RATIO = 0.6   # 段の一部が大見出しなどでふさがっていても、この割合の幅があれば表を置く


def _place_table(page, g: Geometry, part: I.Part, occupied: List[Rect], warnings: List[str]) -> Optional[Rect]:
    """表を、本文の続きの次の段から、空いている幅いっぱいに置く（横書きの表）。

    大見出しなどで段の一部がふさがっていても、ページの幅の 6 割以上空いていれば、その幅に縮めて置く。
    本文が途中まで入った段の残りは空けておく（表のあとの本文が表より前に読まれないように）。
    """
    import tables
    runs = free_runs(g, whole_page(g), occupied)
    start = runs[0].dan if runs else g.dans
    if runs and runs[0].line != 0:
        start += 1          # 本文が途中まで入った段には置かず、次の段から
    for dan in range(start, g.dans):
        for dans in range(1, g.dans - dan + 1):
            # この段から dans 段ぶん、どの段でも空いている行のうち、いちばん長く続く所
            free = [line for line in range(g.lines_per_dan)
                    if not any(Rect(d, line, 1, 1).overlaps(o) for d in range(dan, dan + dans) for o in occupied)]
            best, run_start, previous = (0, 0), None, None
            for line in free + [None]:
                if line is not None and previous is not None and line == previous + 1:
                    previous = line
                    continue
                if run_start is not None and previous - run_start + 1 > best[1]:
                    best = (run_start, previous - run_start + 1)
                run_start = previous = line
            if best[1] < g.lines_per_dan * TABLE_MIN_RATIO:
                break
            rect = Rect(dan, best[0], dans, best[1])
            size = _table_size(g, part, to_box(g, rect).w)
            if size is None or size[3] > dans:
                continue          # この幅だと段が足りない。段を増やして試す
            rows, widths, heights, _dans = size
            box = to_box(g, rect)
            box = type(box)(box.x, box.y, box.w, min(box.h, sum(heights) + 2))
            word = tables.decode_word(part.text)
            page.items.append(dx.Table(box, widths, rows, tables.CELL_PT, dx.GOTHIC, True, "表",
                                       None, None, heights,
                                       word_xml=tables.fit_word_xml(word, box.w)[0] if word else ""))
            for run in runs:
                if run.dan < dan:
                    occupied.append(run)   # 表より上の段の残りは空ける
            return rect
    if _table_size(g, part) and _table_size(g, part)[3] >= g.dans:
        warnings.append("表が長く、ページに入りきりません。行を減らすか、2つの表に分けてください")
    return None


def _per_line(g: Geometry, rect: Rect, pt: float, inset: bool = True) -> int:
    """見出しの枠の高さ（段をまたぐなら段の間も含む）に、pt の字が何字入るか。
    inset が真なら、大見出しの囲みの内側の余白を除く（中見出しは囲まないので除かない）。"""
    return max(1, int((to_box(g, rect).h - (2 * dx.HEADING_INSET_PT if inset else 0)) // pt))


# 見出しの中の「｜」は、そこで行を変える印（一般質問の「大まかな質問｜それへの答」）。
# 「｜」より前の行は青い字にする。
HEADING_BREAK = "｜"
# 大見出しの字は、横書きなら左づめ、縦書きなら上づめ（枠の中で行のかたまりは真ん中に置く）
BIG_HEADING_ALIGN = "左"
QUESTION_COLOR = "0070C0"


def _heading_lines(text: str, per_line: int, max_lines: int = 2) -> List[str]:
    """見出しを行に分ける。per_line（1 行に入る字数）に収まれば 1 行のまま、
    収まらなければ最大 max_lines 行へほぼ均等に分ける。文字自体は削らない。
    「｜」があれば、そこで必ず行を変え、それぞれを同じ決まりで分ける。"""
    if HEADING_BREAK in text:
        return _split_pieces(text, lambda piece: _heading_lines(piece, per_line, max_lines))
    if not text:
        return [""]
    if text_width(text) <= per_line:
        return [text]
    width = max(1, math.ceil(text_width(text) / math.ceil(text_width(text) / per_line)))
    lines = split_lines(text, width, indent=False)
    if len(lines) <= max_lines:
        return lines
    # 半角を含む長い見出しでも、最後の行へ残りをつないで全文を保つ。
    return lines[:max_lines - 1] + ["".join(lines[max_lines - 1:])]


class HeadingLines(list):
    """見出しの行。blue は、先頭から何行が大まかな質問（青字）か。"""
    blue = 0


def _split_pieces(text: str, split) -> List[str]:
    """「大まかな質問｜答」を、それぞれ split で行に分けて並べる。質問の行の数を覚えておく。"""
    lines = HeadingLines()
    pieces = [piece.strip() for piece in text.split(HEADING_BREAK)]
    for number, piece in enumerate(pieces):
        if piece:
            lines.extend(split(piece))
        if number == 0:
            lines.blue = len(lines)
    if not lines:
        lines.append("")
    return lines


def _heading_colors(text: str, lines: List[str]) -> Optional[List[Optional[str]]]:
    """「｜」の前（大まかな質問）の行を青、後の行（見出しの答）を黒にする色の並び。「｜」がなければ None。

    行に分けたときに覚えた質問の行の数で決める（字数を数え直すと、空きなどで食い違うことがあった）。
    """
    if HEADING_BREAK not in text:
        return None
    blue = getattr(lines, "blue", None)
    if blue is None:   # 行の数を覚えていないとき（字数で数える。空きは数えない）
        first = re.sub(r"\s", "", text.split(HEADING_BREAK)[0])
        blue, taken = 0, ""
        for line in lines:
            if len(taken) >= len(first):
                break
            taken += re.sub(r"\s", "", line)
            blue += 1
    return [QUESTION_COLOR if index < blue else None for index in range(len(lines))]


ROLE_ENDINGS = ("長", "参事", "主幹", "室長", "所長", "局長")
ANSWER_START = re.compile(r"^(?P<head>[ \u3000]*答)(?P<gap>[ \u3000]*)(?P<rest>.*)$", re.S)


def _is_role(text: str) -> bool:
    value = text.strip()
    return bool(value and len(value) <= 12 and value.endswith(ROLE_ENDINGS))


def _answer_line_runs(lines: List[str]) -> Optional[List[List[Tuple[str, str]]]]:
    """一般質問の答弁を、答・役職名と答弁本文の書体に分ける。"""
    joined = "".join(lines)
    match = ANSWER_START.match(joined)
    if not match:
        return None
    prefix = match.group("head")
    rest = match.group("rest")
    role, separator, _body = rest.partition("　")
    if _is_role(role) and (separator or not _body):
        prefix += match.group("gap") + role
    prefix_left = len(prefix)
    styled = []
    for line in lines:
        gothic_count = min(prefix_left, len(line))
        runs = []
        if gothic_count:
            runs.append((line[:gothic_count], dx.GOTHIC))
        if gothic_count < len(line):
            runs.append((line[gothic_count:], dx.MINCHO))
        styled.append(runs)
        prefix_left -= gothic_count
    return styled


QUESTION_START = re.compile(r"^[ \u3000]*問[ \u3000]*(?P<rest>.*)$", re.S)


def _ippan_lines(part: I.Part, g: Geometry, role_before: str = ""):
    """一般質問の問・答を「質問　本文」「答弁　答弁者」の形にする。

    質問は「質問」の後に全角の空きを入れて、そのまま質問の本文を続ける（行は変えない）。
    答弁は「答弁」の後に全角の空きと答弁者を入れ、行を変えて答弁の本文を入れる（本文は明朝）。
    行と、行ごとの書体を返す。問・答の形でなければ None。
    """
    if part.reason == "前ページからの続き":
        return None
    if part.kind == "質問":
        match = QUESTION_START.match(part.text)
        if not match:
            return None
        return split_lines("質問　" + match.group("rest").strip(), g.chars_per_line, indent=False), None
    if part.kind == "答弁":
        match = ANSWER_START.match(part.text)
        if not match:
            return None
        rest = match.group("rest").strip()
        role, separator, body = rest.partition("　")
        if not (_is_role(role) and (separator or not body)):
            role, body = role_before, rest
        if role:
            head = split_lines("答弁　" + role, g.chars_per_line, indent=False)
            lines = head + split_lines(body.strip(), g.chars_per_line, indent=True)
            runs = [[(line, dx.GOTHIC if index < len(head) else dx.MINCHO)] for index, line in enumerate(lines)]
            return lines, runs
        # 答弁者が分からないときは「答弁　」のあとにそのまま本文を続ける
        lines = split_lines("答弁　" + body.strip(), g.chars_per_line, indent=False)
        runs = [[(line[:3], dx.GOTHIC), (line[3:], dx.MINCHO)] if index == 0 else [(line, dx.MINCHO)]
                for index, line in enumerate(lines)]
        return lines, runs
    return None


def _format(section: str, kind: str) -> Tuple[str, float, float]:
    # 一般質問だけ、答弁の本文を明朝にする。その他の本文はすべてゴシック。
    if section == layout.IPPAN and kind == "答弁":
        return dx.MINCHO, 11.0, PITCH
    return dx.GOTHIC, 11.0, PITCH


def _heading_pt(section: str, kind: str, text: str = "") -> float:
    title = text.replace(" ", "").replace("　", "")
    if kind == "大見出し":
        if section == layout.GYOSEI and title.startswith("行政報告"):
            return 28.0
        if section == layout.IINKAI and title.startswith("閉会中の委員会"):
            return 22.0
        if section in (layout.YOSAN, layout.KESSAN) and title.startswith(("当初予算", "決算")):
            return 20.0
        if section == layout.IPPAN and title.startswith("一般質問に"):
            return 26.0
        if section == layout.TOKUSHU and title.startswith("特集"):
            return 24.0
        return 14.0 if section in (layout.GYOSEI, layout.IINKAI) else 18.0
    if section == layout.GYOSEI and title in ("（要旨）", "(要旨)"):
        return 24.0
    if section == layout.KESSAN:
        return 18.0 if title in ("一般会計", "特別会計", "公営企業会計") else 14.0
    if section == layout.SHINGI:
        return 14.0
    return 14.0 if section in (layout.GYOSEI, layout.IINKAI) else 16.0


def _horizontal_heading_span(g: Geometry, text: str, pt: float) -> int:
    """横見出しは同じ段の横幅を使い、長ければ枠内で折り返す。"""
    if HEADING_BREAK in text:
        # 「大まかな質問｜答」は、長い方が 1 行に入る幅を取る（入らなければ枠の中で折り返す）
        widest = max(text_width(piece.strip()) for piece in text.split(HEADING_BREAK))
        needed = math.ceil((widest * pt + dx.SLACK_PT) / g.line_pitch_pt) + 1
        return min(g.lines_per_dan, max(8, needed))
    needed = math.ceil(text_width(text) * pt / (2 * g.line_pitch_pt))
    return min(g.lines_per_dan, max(8, min(22, needed)))


def _heading_rect(g: Geometry, part: I.Part, dan: int, line: int, pt: float) -> Rect:
    if not part.vertical:
        return Rect(dan, line, 1, _horizontal_heading_span(g, part.text, pt))
    # 大見出しの行送りは max(34pt, 字×1.4)。実際の行数ぶんの幅を取る（2 行の「大まかな質問｜答」も欠けないように）
    count = len(_heading_lines(part.text, _per_line(g, Rect(dan, line, 2, 4), pt)))
    pitch = max(34.0, pt * dx.AT_LEAST_RATIO)
    span = max(4, math.ceil(count * pitch / g.line_pitch_pt - 1e-6))
    return Rect(dan, line, 2, span)


def _heading_lines_for(g: Geometry, part: I.Part, rect: Rect, pt: float) -> List[str]:
    if part.vertical:
        return _heading_lines(part.text, _per_line(g, rect, pt))
    per_line = max(1, int((to_box(g, rect).w - dx.SLACK_PT - 2 * dx.HEADING_INSET_PT) / pt))
    if HEADING_BREAK in part.text:
        return _split_pieces(part.text, lambda piece: split_lines(piece, per_line, indent=False))
    return split_lines(part.text, per_line, indent=False) or [""]


def _same_text_style(a: dx.TextBox, b: dx.TextBox) -> bool:
    return (a.font, a.pt, a.pitch_pt, a.border, a.center, a.vertical, a.align,
            bool(a.line_runs)) == (b.font, b.pt, b.pitch_pt, b.border, b.center,
                                   b.vertical, b.align, bool(b.line_runs))


def _add_text(page: dx.Page, g: Geometry, rect: Rect, lines: List[str], *,
              font: str, pt: float, pitch: float, name: str,
              border: bool = False, center: bool = False,
              line_runs: Optional[List[List[Tuple[str, str]]]] = None,
              vertical: bool = True, align: str = "左",
              line_colors: Optional[List[Optional[str]]] = None) -> None:
    """同じ段で同じ書式が続く枠は、Word 上の 1 枠へまとめる。"""
    item = dx.TextBox(to_box(g, rect), lines, font, pt, pitch, border, center, name,
                      vertical=vertical, align=align, line_runs=line_runs, line_colors=line_colors)
    if page.items and isinstance(page.items[-1], dx.TextBox):
        previous = page.items[-1]
        previous_rect = getattr(previous, "_grid_rect", None)
        if (previous_rect and previous_rect.dan == rect.dan
                and previous_rect.line + previous_rect.line_span == rect.line
                and _same_text_style(previous, item)):
            merged = Rect(rect.dan, previous_rect.line, 1,
                          previous_rect.line_span + rect.line_span)
            previous.box = to_box(g, merged)
            if previous.line_colors is not None or line_colors is not None:
                previous.line_colors = ((previous.line_colors or [None] * len(previous.lines))
                                        + (line_colors or [None] * len(lines)))
            previous.lines.extend(lines)
            if previous.line_runs is not None and line_runs is not None:
                previous.line_runs.extend(line_runs)
            previous._grid_rect = merged
            return
    item._grid_rect = rect
    page.items.append(item)


def _place_picture(page: dx.Page, g: Geometry, part: I.Part, rect: Rect,
                   images: Dict[str, bytes], caption: str, number: int, size: str,
                   warnings: List[str]) -> None:
    name = part.image or f"写真{number}"
    data = images.get(name)
    grid_box = to_box(g, rect)
    width = min(grid_box.w, mm2pt(PHOTO_WIDTH_MM[size]))
    picture_box = dx.Box(grid_box.x + (grid_box.w - width) / 2,
                         grid_box.y, width, grid_box.h)
    if data is None:
        if part.reason == "印刷所が入れる顔写真の空欄":
            # 顔写真の空欄の下に、議員名（▲見本 太郎議員 の行）を横書きで入れる
            name_h = 16.0 if caption else 0.0
            # 顔写真の枠は縦長（幅:高さ = 3:4）。議員名はそのすぐ下
            frame_h = min(picture_box.w * 4 / 3, picture_box.h - name_h)
            frame = dx.Box(picture_box.x, picture_box.y, picture_box.w, frame_h)
            page.items.append(dx.Placeholder(frame, "", f"写真{number}"))
            if caption:
                pt = min(9.0, max(6.0, (picture_box.w - dx.SLACK_PT) / max(1.0, text_width(caption))))
                page.items.append(dx.TextBox(dx.Box(picture_box.x, frame.y + frame.h, picture_box.w, name_h),
                                             [caption], dx.GOTHIC, pt, dx.effective_pitch(pt, PITCH),
                                             False, True, "顔写真の議員名", vertical=False, align="中央"))
            return
        page.items.append(dx.Placeholder(picture_box, f"写真{number}: {name}", f"写真{number}"))
        warnings.append(f"写真{number}（{name}）の画像データがありません")
        return
    try:
        ext = _image_ext(name, data)
        # 書き出す前にヘッダーを確かめ、壊れた画像は分かる形で残す。
        dx.image_size(data, ext)
    except ValueError as e:
        page.items.append(dx.Placeholder(picture_box, f"写真{number}: 読み取り不可", f"写真{number}"))
        warnings.append(str(e))
        return
    object_name = Path(name).stem if Path(name).stem.startswith("写真_") else f"写真{number}"
    page.items.append(dx.Picture(picture_box, data, ext, caption, object_name))


def _compose(section: str, parts: List[I.Part], images: Dict[str, bytes], g: Geometry,
             photo_sizes: Optional[Dict[int, Optional[str]]] = None,
             overrides: Optional[Dict[int, dict]] = None) -> PageResult:
    page = dx.Page()
    fixed = layout.fixed_areas(section, g)
    occupied: List[Rect] = list(fixed.values())
    placements: List[Placement] = []
    warnings: List[str] = []
    overflow = 0
    overflow_by_index: Dict[int, I.Part] = {}
    photo_sizes = photo_sizes or {}
    overrides = overrides or {}
    manual: Dict[int, Rect] = {}
    flow_stopped = False
    for name, rect in fixed.items():
        page.items.append(dx.Placeholder(to_box(g, rect), name, name))

    def reserve_space(index: int) -> None:
        """部品の直前に指定された空き行を、本文と同じ読む順で確保する。"""
        nonlocal overflow
        count = max(0, int(overrides.get(index, {}).get("space_before") or 0))
        left = count
        for run in free_runs(g, whole_page(g), occupied):
            if left <= 0:
                break
            take = min(left, run.line_span)
            occupied.append(Rect(run.dan, run.line, 1, take))
            left -= take
        overflow += left

    # 人が場所を決めた写真・大見出しを先に確保する。置けない指定だけを
    # 退け、後の自動配置へ戻す。
    for index, part in enumerate(parts):
        change = overrides.get(index, {})
        rect = change.get("rect")
        if part.kind not in ("写真", "大見出し") or rect is None or change.get("removed"):
            continue
        if not isinstance(rect, Rect) or not _fits(g, rect, occupied):
            warnings.append(f"部品{index + 1}は重なるか版面の外にあるため、自動の位置に戻しました")
            continue
        occupied.append(rect)
        manual[index] = rect

    # ページ先頭の大見出しだけを定位置へ置く。前ページからの続きが先にある場合、
    # このページ自身の大見出しは本文の順番どおり後で置く。
    title_index = 0 if parts and parts[0].kind == "大見出し" else None
    title_rect = None
    if title_index is not None and not overrides.get(title_index, {}).get("removed"):
        reserve_space(title_index)
        title = parts[title_index]
        title_pt = _heading_pt(section, "大見出し", title.text)
        rect = manual.get(title_index, _heading_rect(g, title, 0, 0, title_pt))
        if title_index in manual or _fits(g, rect, occupied):
            title_rect = rect
            if title_index not in manual:
                occupied.append(rect)
            placements.append(Placement(title, rect, title_index))
            title_lines = _heading_lines_for(g, title, rect, title_pt)
            _add_text(page, g, rect, title_lines, line_colors=_heading_colors(title.text, title_lines),
                      font=dx.GOTHIC, pt=title_pt,
                      pitch=max(34.0, title_pt * dx.AT_LEAST_RATIO) if title.vertical
                      else dx.effective_pitch(title_pt, PITCH),
                      border=True, center=True, name="大見出し",
                      vertical=title.vertical, align=BIG_HEADING_ALIGN)
        else:
            warnings.append("大見出しの決まった位置が、区分の固定枠と重なります")
            overflow_by_index[title_index] = title

    skip = {title_index} if title_index is not None else set()
    # 一般質問の最初のページは「一般質問に◯氏が立つ」→ 1 人目の顔写真（と議員名）→ 1 人目の題、の順。
    # 顔写真の入る幅を空けて、その左へ題を並べる。
    face_at = None
    if (section == layout.IPPAN and title_rect is not None and parts[title_index].vertical
            and len(parts) > 1 and parts[1].kind == "大見出し"
            and 1 not in manual and not overrides.get(1, {}).get("removed")):
        second = parts[1]
        second_pt = _heading_pt(section, "大見出し", second.text)
        section_end = title_rect.line + title_rect.line_span
        # 1 人目の顔写真の大きさ（紙面を見るで変えていればその大きさ）の幅を空ける
        face_index = next((n for n, p in enumerate(parts) if p.kind == "写真"), None)
        face_size = (overrides.get(face_index, {}).get("size") if face_index is not None else None) or "顔"
        face_span = photo_rect(g, face_size if face_size in PHOTO_WIDTH_MM else "顔", 0, 0).line_span
        rect = _heading_rect(g, second, 0, section_end + face_span, second_pt)
        if not second.vertical:
            # 横書きの題が長いときは、ページの左の端までの幅に収めて、枠の中で折り返す
            room = g.lines_per_dan - rect.line
            if room >= 8 and rect.line_span > room:
                rect = Rect(rect.dan, rect.line, rect.dan_span, room)
        if _fits(g, rect, occupied):
            face_at = section_end
            occupied.append(rect)
            placements.append(Placement(second, rect, 1))
            second_lines = _heading_lines_for(g, second, rect, second_pt)
            _add_text(page, g, rect, second_lines, line_colors=_heading_colors(second.text, second_lines),
                      font=dx.GOTHIC, pt=second_pt,
                      pitch=max(34.0, second_pt * dx.AT_LEAST_RATIO) if second.vertical
                      else dx.effective_pitch(second_pt, PITCH),
                      border=True, center=True, name="大見出し",
                      vertical=second.vertical, align=BIG_HEADING_ALIGN)
            skip.add(1)
            title_rect = rect

    photo_indices = [n for n, p in enumerate(parts) if p.kind == "写真"]
    first_face = photo_indices[0] if section == layout.IPPAN and photo_indices else None
    if first_face is not None:
        reserve_space(first_face)
        change = overrides.get(first_face, {})
        size = photo_sizes.get(first_face, change.get("size") or
                               parts[first_face].photo_size or "顔")
        if change.get("removed"):
            size = None
        skip.add(first_face)
        if first_face + 1 < len(parts) and parts[first_face + 1].kind == "写真説明":
            skip.add(first_face + 1)
        if size is not None:
            face_line = (face_at if face_at is not None else
                         title_rect.line + title_rect.line_span
                         if title_rect is not None and not parts[title_index].vertical else 4)
            rect = manual.get(first_face, photo_rect(g, size, 0, face_line))
            if first_face not in manual and not _fits(g, rect, occupied):
                # 大見出しが長くて決まった所に入らないときは、いちばん近い空いた所へ置く（顔写真と議員名をなくさない）
                candidates = sorted(((abs(dan) * g.lines_per_dan + abs(line - face_line), dan, line)
                                     for dan in range(g.dans) for line in range(g.lines_per_dan)))
                rect = next((photo_rect(g, size, dan, line) for _d, dan, line in candidates
                             if _fits(g, photo_rect(g, size, dan, line), occupied)), rect)
            if first_face in manual or _fits(g, rect, occupied):
                if first_face not in manual:
                    occupied.append(rect)
                placements.append(Placement(parts[first_face], rect, first_face))
                _place_picture(page, g, parts[first_face], rect, images,
                               _caption(parts, first_face), 1, size, warnings)
            else:
                warnings.append("顔写真を大見出しの左へ置けませんでした")
                overflow_by_index[first_face] = parts[first_face]

    last_rect: Optional[Rect] = None
    photo_number = 0
    pending_role = ""
    for index, part in enumerate(parts):
        if part.kind == "写真":
            photo_number += 1
        if index in skip or part.kind == "写真説明":
            continue
        if overrides.get(index, {}).get("removed"):
            continue
        # 人が場所を決めた写真は場所を確保済みなので、本文があふれても次ページへ送らない。
        if flow_stopped and not (part.kind == "写真" and index in manual):
            overflow_by_index[index] = part
            overflow += max(0, int(overrides.get(index, {}).get("space_before") or 0))
            if part.kind == "空き行":
                overflow += int(part.text)
            elif part.kind == "次段":
                overflow += g.lines_per_dan
            elif part.kind == "大見出し":
                overflow += 8
            elif part.kind == "中見出し":
                overflow += (_horizontal_heading_span(g, part.text, _heading_pt(section, part.kind, part.text))
                             if not part.vertical else _mid_heading(
                                 g, part.text, _heading_pt(section, part.kind, part.text))[2])
            elif part.kind == "写真":
                size = overrides.get(index, {}).get("size") or part.photo_size or "中"
                overflow += photo_rect(g, size, 0, 0).line_span
            elif part.kind == "表":
                overflow += _table_dans(g, part) * g.lines_per_dan
            else:
                shaped = _ippan_lines(part, g) if section == layout.IPPAN else None
                overflow += len(shaped[0]) if shaped else len(split_lines(
                    part.text, g.chars_per_line, indent=part.reason != "前ページからの続き"))
            continue
        reserve_space(index)
        if part.kind == "表":
            if _table_size(g, part) is None:
                warnings.append("表の中身が見つかりません。特集の手順の『表』に、本文の【表】と同じ名前の表があるか確かめてください")
                continue
            rect = _place_table(page, g, part, occupied, warnings)
            if rect is None:
                overflow += _table_dans(g, part) * g.lines_per_dan
                overflow_by_index[index] = part
                flow_stopped = True
                continue
            occupied.append(rect)
            placements.append(Placement(part, rect, index))
            last_rect = rect
            continue
        if part.kind in ("空き行", "次段"):
            runs = free_runs(g, whole_page(g), occupied)
            if part.kind == "次段" and runs:
                count = sum(run.line_span for run in runs if run.dan == runs[0].dan)
            else:
                count = int(part.text) if part.kind == "空き行" else g.lines_per_dan
            left = count
            for run in runs:
                if left <= 0:
                    break
                take = min(left, run.line_span)
                rect = Rect(run.dan, run.line, 1, take)
                occupied.append(rect)
                placements.append(Placement(part, rect, index))
                last_rect = rect
                left -= take
            if left:
                overflow += left
                if part.kind == "空き行":
                    overflow_by_index[index] = replace(part, text=str(left))
                flow_stopped = True
            continue
        if part.kind == "大見出し":
            heading_pt = _heading_pt(section, part.kind, part.text)
            rect = manual.get(index)
            if rect is None:
                for target in free_runs(g, whole_page(g), occupied):
                    candidate = _heading_rect(g, part, target.dan, target.line, heading_pt)
                    if target.line_span >= candidate.line_span and _fits(g, candidate, occupied):
                        rect = candidate
                        break
            if rect is None:
                overflow += 8
                overflow_by_index[index] = part
                flow_stopped = True
                continue
            if index not in manual:
                occupied.append(rect)
            placements.append(Placement(part, rect, index))
            big_lines = _heading_lines_for(g, part, rect, heading_pt)
            _add_text(page, g, rect, big_lines, line_colors=_heading_colors(part.text, big_lines),
                      font=dx.GOTHIC, pt=heading_pt,
                      pitch=max(34.0, heading_pt * dx.AT_LEAST_RATIO) if part.vertical
                      else dx.effective_pitch(heading_pt, PITCH),
                      border=True, center=True, name="大見出し",
                      vertical=part.vertical, align=BIG_HEADING_ALIGN)
            last_rect = rect
            continue
        if part.kind == "写真":
            change = overrides.get(index, {})
            size = photo_sizes.get(index, change.get("size") or part.photo_size or "中")
            if change.get("removed"):
                size = None
            if index + 1 < len(parts) and parts[index + 1].kind == "写真説明":
                skip.add(index + 1)
            if size is None:
                continue
            if index in manual:
                rect = manual[index]
                placements.append(Placement(part, rect, index))
                _place_picture(page, g, part, rect, images, _caption(parts, index),
                               photo_number, size, warnings)
                last_rect = rect
                continue
            line_span = photo_rect(g, size, 0, 0).line_span
            start_dan = last_rect.dan if last_rect else 0
            rect = None
            for dan in range(start_dan, g.dans):
                candidate = photo_rect(g, size, dan, g.lines_per_dan - line_span)
                if _fits(g, candidate, occupied):
                    rect = candidate
                    break
            if rect is None:
                warnings.append(f"写真{photo_number}を置ける空きがありません")
                overflow_by_index[index] = part
                flow_stopped = True
                continue
            occupied.append(rect)
            placements.append(Placement(part, rect, index))
            _place_picture(page, g, part, rect, images, _caption(parts, index),
                           photo_number, size, warnings)
            last_rect = rect
            continue

        # 答弁者名が独立した短い 1 行なら、中見出し扱いになっていても
        # 一般質問の答弁者名としてゴシック 11pt で置く。
        standalone_role = (section == layout.IPPAN and _is_role(part.text)
                           and index + 1 < len(parts) and parts[index + 1].kind == "答弁")
        # 一般質問は「答弁」の行の次に答弁者を入れるので、別の行の答弁者は次の答弁へ渡す
        if standalone_role and _ippan_lines(parts[index + 1], g) is not None:
            pending_role = part.text.strip()
            continue

        # 委員会報告で報告する課長などの名前は、見出しにせず 1 行に置き、次の行から説明を始める
        reporter = (section == layout.IINKAI and part.kind == "中見出し" and _is_role(part.text))

        if part.kind == "中見出し" and not standalone_role and not reporter:
            base_pt = _heading_pt(section, part.kind, part.text)
            if part.vertical:
                heading_pt, heading_lines, span = _mid_heading(g, part.text, base_pt)
            else:
                heading_pt = base_pt
                span = _horizontal_heading_span(g, part.text, heading_pt)
            target = next((r for r in free_runs(g, whole_page(g), occupied)
                           if r.line_span >= span), None)
            if target is None:
                overflow += span
                overflow_by_index[index] = part
                flow_stopped = True
                continue
            rect = Rect(target.dan, target.line, 1, span)
            if not part.vertical:
                heading_lines = _heading_lines_for(g, part, rect, heading_pt)
            occupied.append(rect)
            placements.append(Placement(part, rect, index))
            pitch = (rect.line_span * g.line_pitch_pt / len(heading_lines)
                     if part.vertical else dx.effective_pitch(heading_pt, PITCH))
            align = "中央"
            if (section == layout.IINKAI and part.vertical and len(heading_lines) == 2
                    and part.text.strip().endswith("委員会")):
                # 委員会名が 1 行に入らないときは、1 行目を上づめ、2 行目を下づめにする
                per_line = _per_line(g, Rect(0, 0, 1, 2), heading_pt, inset=False)
                gap = max(0, int(per_line - text_width(heading_lines[1])))
                heading_lines = [heading_lines[0], "　" * gap + heading_lines[1]]
                align = "左"
            _add_text(page, g, rect, heading_lines, font=dx.GOTHIC,
                      pt=heading_pt, pitch=pitch, center=True, name="中見出し",
                      line_colors=_heading_colors(part.text, heading_lines),
                      vertical=part.vertical, align=align)
            last_rect = rect
            continue

        lines = split_lines(part.text, g.chars_per_line,
                            indent=part.reason != "前ページからの続き" and not reporter)
        pos = 0
        font, pt, pitch = _format(section, part.kind)
        if standalone_role or reporter:
            font = dx.GOTHIC
        styled_lines = (_answer_line_runs(lines)
                        if section == layout.IPPAN and part.kind == "答弁" else None)
        shaped = _ippan_lines(part, g, pending_role) if section == layout.IPPAN else None
        pending_role = ""
        if shaped:   # 一般質問は「質問」「答弁（の次に答弁者）」の行のあとで行を変える
            lines, styled_lines = shaped
        for run in free_runs(g, whole_page(g), occupied):
            if pos >= len(lines):
                break
            take = min(run.line_span, len(lines) - pos)
            rect = Rect(run.dan, run.line, 1, take)
            chunk = lines[pos:pos + take]
            chunk_runs = styled_lines[pos:pos + take] if styled_lines is not None else None
            occupied.append(rect)
            placements.append(Placement(part, rect, index))
            _add_text(page, g, rect, chunk, font=font, pt=pt, pitch=pitch,
                      name="答弁者名" if standalone_role else ("報告者" if reporter else part.kind),
                      line_runs=chunk_runs)
            last_rect = rect
            pos += take
        overflow += len(lines) - pos
        if pos < len(lines):
            overflow_by_index[index] = (part if pos == 0 else replace(
                part, text="".join(lines[pos:]), reason="前ページからの続き"))
            flow_stopped = True

    capacity = g.dans * g.lines_per_dan
    used = len({cell for rect in occupied for cell in rect.cells()})
    warnings.extend(dx.page_textbox_warnings(page))
    overflow_parts = []
    for index, part in enumerate(parts):
        pending = overflow_by_index.get(index)
        if pending is not None:
            overflow_parts.append(pending)
            if (part.kind == "写真" and index + 1 < len(parts)
                    and parts[index + 1].kind == "写真説明"):
                overflow_parts.append(parts[index + 1])
    return PageResult(page, overflow, max(0, capacity - used), warnings, placements,
                      overflow_parts)


def apply_kind_overrides(parts: List[I.Part],
                         overrides: Optional[Dict[int, dict]] = None) -> List[I.Part]:
    """人が直した種類と見出しの向きを、元の読み取り結果を変えずに反映する。"""
    overrides = overrides or {}
    if not any(change.get("kind") or change.get("vertical") is not None
               for change in overrides.values()):
        return parts
    out = []
    for index, part in enumerate(parts):
        change = overrides.get(index, {})
        kind = change.get("kind")
        vertical = change.get("vertical")
        if kind or vertical is not None:
            out.append(replace(part, kind=kind or part.kind,
                               vertical=part.vertical if vertical is None else vertical,
                               sure=True, reason="人が直した"))
        else:
            out.append(part)
    return out


def compose_page(section: str, parts: List[I.Part], images: Dict[str, bytes],
                 g: Geometry, overrides: Optional[Dict[int, dict]] = None) -> PageResult:
    """部品を 1 ページへ配置し、あふれ・余りと写真変更の提案を返す。"""
    parts = apply_kind_overrides(parts, overrides)
    result = _compose(section, parts, images, g, overrides=overrides)
    if result.overflow_lines:
        photos = [n for n, p in enumerate(parts) if p.kind == "写真"]
        for number, index in enumerate(photos, 1):
            current = "顔" if section == layout.IPPAN and number == 1 else "中"
            smaller = PHOTO_SMALLER[current]
            changed = _compose(section, parts, images, g, {index: smaller}, overrides)
            gain = result.overflow_lines - changed.overflow_lines
            if gain > 0:
                action = f"{smaller}にする" if smaller else "外す"
                result.warnings.append(f"写真{number} を{action}と あと {gain} 行入ります")
            removed = _compose(section, parts, images, g, {index: None}, overrides)
            gain = result.overflow_lines - removed.overflow_lines
            if smaller is not None and gain > 0:
                result.warnings.append(f"写真{number} を外すと あと {gain} 行入ります")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="原稿を 1 ページへ自動配置します")
    parser.add_argument("source", type=Path, help=".docx / .doc / .txt の原稿")
    parser.add_argument("section", nargs="?", default=layout.IPPAN, help="区分名（既定: 一般質問）")
    parser.add_argument("output", nargs="?", type=Path, help="出力する .docx")
    parser.add_argument("--no-guide", action="store_true", help="段の輪郭を出さない")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or Path("試し出力") / f"段階4_{args.source.stem}.docx"
    try:
        source = I.ingest(args.source)
        g = Geometry()
        result = compose_page(args.section, source.parts, source.images, g)
        if not args.no_guide:
            result.page.items.extend(dx.Guide(to_box(g, Rect(d, 0, 1, g.lines_per_dan)),
                                              f"段{d + 1}") for d in range(g.dans))
        dx.write_docx(output, g, [result.page])
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        print(f"作れませんでした: {e}", file=sys.stderr)
        return 1
    print(f"作りました: {output.resolve()}")
    print(f"あふれ: {result.overflow_lines} 行 / 余り: {result.free_lines} 行")
    for warning in source.warnings + (I.check_ippan(source.parts) if args.section == layout.IPPAN else []) + result.warnings:
        print(f"・{warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
