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

PHOTO_WIDTH_MM = {"大": 80.0, "中": 55.0, "小": 38.0, "顔": 26.0}
PHOTO_SMALLER = {"大": "中", "中": "小", "小": None, "顔": None}


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


def _heading_lines(text: str, per_line: int, max_lines: int = 2) -> List[str]:
    """見出しを行に分ける。per_line（1 行に入る字数）に収まれば 1 行のまま、
    収まらなければ最大 max_lines 行へほぼ均等に分ける。文字自体は削らない。"""
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
    if section == layout.IPPAN and kind == "答弁":
        return dx.MINCHO, 11.0, 17.0
    return dx.GOTHIC, 11.0, 17.0


def _same_text_style(a: dx.TextBox, b: dx.TextBox) -> bool:
    return (a.font, a.pt, a.pitch_pt, a.border, a.center, bool(a.line_runs)) == (
        b.font, b.pt, b.pitch_pt, b.border, b.center, bool(b.line_runs))


def _add_text(page: dx.Page, g: Geometry, rect: Rect, lines: List[str], *,
              font: str, pt: float, pitch: float, name: str,
              border: bool = False, center: bool = False,
              line_runs: Optional[List[List[Tuple[str, str]]]] = None) -> None:
    """同じ段で同じ書式が続く枠は、Word 上の 1 枠へまとめる。"""
    item = dx.TextBox(to_box(g, rect), lines, font, pt, pitch, border, center, name,
                      line_runs=line_runs)
    if page.items and isinstance(page.items[-1], dx.TextBox):
        previous = page.items[-1]
        previous_rect = getattr(previous, "_grid_rect", None)
        if (previous_rect and previous_rect.dan == rect.dan
                and previous_rect.line + previous_rect.line_span == rect.line
                and _same_text_style(previous, item)):
            merged = Rect(rect.dan, previous_rect.line, 1,
                          previous_rect.line_span + rect.line_span)
            previous.box = to_box(g, merged)
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
    page.items.append(dx.Picture(picture_box, data, ext, caption, f"写真{number}"))


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
    if title_index is not None and not overrides.get(title_index, {}).get("removed"):
        reserve_space(title_index)
        title = parts[title_index]
        rect = manual.get(title_index, Rect(0, 0, 2, 4))
        if title_index in manual or _fits(g, rect, occupied):
            if title_index not in manual:
                occupied.append(rect)
            placements.append(Placement(title, rect, title_index))
            _add_text(page, g, rect, _heading_lines(title.text, _per_line(g, rect, 18.0)), font=dx.GOTHIC, pt=18.0,
                      pitch=34.0, border=True, center=True, name="大見出し")
        else:
            warnings.append("大見出しの決まった位置が、区分の固定枠と重なります")
            overflow_by_index[title_index] = title

    photo_indices = [n for n, p in enumerate(parts) if p.kind == "写真"]
    first_face = photo_indices[0] if section == layout.IPPAN and photo_indices else None
    skip = {title_index} if title_index is not None else set()
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
            rect = manual.get(first_face, photo_rect(g, size, 0, 4))
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
        if flow_stopped:
            overflow_by_index[index] = part
            overflow += max(0, int(overrides.get(index, {}).get("space_before") or 0))
            if part.kind == "大見出し":
                overflow += 8
            elif part.kind == "中見出し":
                sample = Rect(0, 0, 1, 2)
                overflow += 2 if len(_heading_lines(
                    part.text, _per_line(g, sample, 16.0))) == 1 else 3
            elif part.kind == "写真":
                size = overrides.get(index, {}).get("size") or part.photo_size or "中"
                overflow += photo_rect(g, size, 0, 0).line_span
            else:
                overflow += len(split_lines(part.text, g.chars_per_line,
                                            indent=part.reason != "前ページからの続き"))
            continue
        reserve_space(index)
        if part.kind == "大見出し":
            rect = manual.get(index)
            if rect is None:
                for target in free_runs(g, whole_page(g), occupied):
                    candidate = Rect(target.dan, target.line, 2, 4)
                    if target.line_span >= 4 and _fits(g, candidate, occupied):
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
            _add_text(page, g, rect,
                      _heading_lines(part.text, _per_line(g, rect, 18.0)),
                      font=dx.GOTHIC, pt=18.0, pitch=34.0, border=True,
                      center=True, name="大見出し")
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
            sample = Rect(0, 0, 1, 2)
            heading_lines = _heading_lines(part.text, _per_line(g, sample, 16.0))
            span = 2 if len(heading_lines) == 1 else 3
            target = next((r for r in free_runs(g, whole_page(g), occupied)
                           if r.line_span >= span), None)
            if target is None:
                overflow += span
                overflow_by_index[index] = part
                flow_stopped = True
                continue
            rect = Rect(target.dan, target.line, 1, span)
            occupied.append(rect)
            placements.append(Placement(part, rect, index))
            pitch = rect.line_span * g.line_pitch_pt / len(heading_lines)
            _add_text(page, g, rect, heading_lines, font=dx.GOTHIC,
                      pt=16.0, pitch=pitch, center=True, name="中見出し")
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
    """人が直した種類を、元の読み取り結果を変えずに部品へ反映する。"""
    overrides = overrides or {}
    if not any(change.get("kind") for change in overrides.values()):
        return parts
    out = []
    for index, part in enumerate(parts):
        kind = overrides.get(index, {}).get("kind")
        out.append(replace(part, kind=kind, sure=True, reason="人が直した")
                   if kind else part)
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
