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
PHOTO_WIDTH_MM = {"特大": 110.0, "大": 80.0, "中": 55.0, "小": 38.0, "顔": 26.0}
PITCH = Geometry().line_pitch_pt
PHOTO_SMALLER = {"特大": "大", "大": "中", "中": "小", "小": None, "顔": None}


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
    height = width * (4 / 3 if size == "顔" else 3 / 4)
    line_span = math.ceil(mm2pt(width) / g.line_pitch_pt)
    needed_h = mm2pt(height)
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
                per_line = _per_line(g, sample, pt)
                pieces = [piece.strip() for piece in text.split(HEADING_BREAK) if piece.strip()]
                lines = _heading_lines(text, per_line, 2)
                if len(lines) <= max_lines * len(pieces) and max(text_width(l) for l in lines) <= per_line:
                    return pt, lines, span(lines, pt)
    for pt in (float(value) for value in range(int(base_pt), 11, -1)):
        per_line = _per_line(g, sample, pt)
        for max_lines in (1, 2, 3):
            lines = _heading_lines(text, per_line, max_lines)
            if len(lines) <= max_lines and max(text_width(l) for l in lines) <= per_line:
                return pt, lines, span(lines, pt)
    per_line = _per_line(g, sample, 12.0)
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


def _per_line(g: Geometry, rect: Rect, pt: float) -> int:
    """見出しの枠の高さ（段をまたぐなら段の間も含む）に、pt の字が何字入るか。"""
    return max(1, int(to_box(g, rect).h // pt))


# 見出しの中の「｜」は、そこで行を変える印（一般質問の「大まかな質問｜それへの答」）。
# 「｜」より前の行は青い字にする。
HEADING_BREAK = "｜"
QUESTION_COLOR = "0070C0"


def _heading_lines(text: str, per_line: int, max_lines: int = 2) -> List[str]:
    """見出しを行に分ける。per_line（1 行に入る字数）に収まれば 1 行のまま、
    収まらなければ最大 max_lines 行へほぼ均等に分ける。文字自体は削らない。
    「｜」があれば、そこで必ず行を変え、それぞれを同じ決まりで分ける。"""
    if HEADING_BREAK in text:
        lines: List[str] = []
        for piece in text.split(HEADING_BREAK):
            if piece.strip():
                lines.extend(_heading_lines(piece.strip(), per_line, max_lines))
        return lines or [""]
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


def _heading_colors(text: str, lines: List[str]) -> Optional[List[Optional[str]]]:
    """「｜」の前（大まかな質問）の行を青、後の行を黒にする色の並び。「｜」がなければ None。"""
    if HEADING_BREAK not in text:
        return None
    first = text.split(HEADING_BREAK)[0].strip()
    colors: List[Optional[str]] = []
    taken = ""
    for line in lines:
        blue = len(taken) < len(first)
        colors.append(QUESTION_COLOR if blue else None)
        if blue:
            taken += line
    return colors


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
    per_line = max(1, int((to_box(g, rect).w - dx.SLACK_PT) / pt))
    if HEADING_BREAK in part.text:
        lines = []
        for piece in part.text.split(HEADING_BREAK):
            if piece.strip():
                lines.extend(split_lines(piece.strip(), per_line, indent=False))
        return lines or [""]
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
            page.items.append(dx.Placeholder(picture_box, "", f"写真{number}"))
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
                      border=True, center=title.vertical, name="大見出し",
                      vertical=title.vertical, align="中央")
        else:
            warnings.append("大見出しの決まった位置が、区分の固定枠と重なります")
            overflow_by_index[title_index] = title

    skip = {title_index} if title_index is not None else set()
    # 一般質問の最初のページは「一般質問に◯氏が立つ」の次に質問の題が続く。
    # 題もその左の定位置へ並べ、顔写真はさらにその左へ置く。
    if (section == layout.IPPAN and title_rect is not None and parts[title_index].vertical
            and len(parts) > 1 and parts[1].kind == "大見出し"
            and 1 not in manual and not overrides.get(1, {}).get("removed")):
        second = parts[1]
        second_pt = _heading_pt(section, "大見出し", second.text)
        rect = _heading_rect(g, second, 0, title_rect.line + title_rect.line_span, second_pt)
        if _fits(g, rect, occupied):
            occupied.append(rect)
            placements.append(Placement(second, rect, 1))
            second_lines = _heading_lines_for(g, second, rect, second_pt)
            _add_text(page, g, rect, second_lines, line_colors=_heading_colors(second.text, second_lines),
                      font=dx.GOTHIC, pt=second_pt,
                      pitch=max(34.0, second_pt * dx.AT_LEAST_RATIO) if second.vertical
                      else dx.effective_pitch(second_pt, PITCH),
                      border=True, center=second.vertical, name="大見出し",
                      vertical=second.vertical, align="中央")
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
            face_line = (title_rect.line + title_rect.line_span
                         if title_rect is not None and (1 in skip or not parts[title_index].vertical)
                         else 4)
            rect = manual.get(first_face, photo_rect(g, size, 0, face_line))
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
            else:
                overflow += len(split_lines(part.text, g.chars_per_line,
                                            indent=part.reason != "前ページからの続き"))
            continue
        reserve_space(index)
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
                      border=True, center=part.vertical, name="大見出し",
                      vertical=part.vertical, align="中央")
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

        if part.kind == "中見出し" and not standalone_role:
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
            _add_text(page, g, rect, heading_lines, font=dx.GOTHIC,
                      pt=heading_pt, pitch=pitch, center=part.vertical, name="中見出し",
                      line_colors=_heading_colors(part.text, heading_lines),
                      vertical=part.vertical, align="中央")
            last_rect = rect
            continue

        lines = split_lines(part.text, g.chars_per_line,
                            indent=part.reason != "前ページからの続き")
        pos = 0
        font, pt, pitch = _format(section, part.kind)
        if standalone_role:
            font = dx.GOTHIC
        styled_lines = (_answer_line_runs(lines)
                        if section == layout.IPPAN and part.kind == "答弁" else None)
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
                      name="答弁者名" if standalone_role else part.kind,
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
