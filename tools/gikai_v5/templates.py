"""表紙・審議ページ・最終ページの書き込み式テンプレート。"""

from __future__ import annotations

import re
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import compose
import docx_out as dx
import ingest
import layout
from grid import Box, Geometry, Rect, mm2pt, split_lines, text_width, to_box
from settings import Settings


@dataclass(frozen=True)
class FormField:
    """画面へ出す入力欄の説明。"""

    name: str
    label: str
    description: str
    example: str = ""
    default: object = ""
    multiline: bool = False


FIELDS = {
    layout.COVER: [
        FormField("photo", "表紙写真", "中央へ置く写真を選びます。"),
        FormField("photo_caption", "写真の説明", "表紙写真の短い説明です。", "見本行事の様子"),
        FormField("feature_titles", "特集の題名", "複数あるときは1行に1件書きます。", "暮らしの特集", multiline=True),
    ],
    layout.SHINGI: [
        FormField("meeting", "定例会名", "発行月から自動で入ります。必要なときだけ直します。"),
        FormField("period", "会期", "帯の2行目に入る期間です。", "Ｒ８．９．４～９．１１"),
        FormField("counts", "議案等の種類と件数", "種類と件数を一覧で入力します。", []),
        FormField("body", "審議本文", "印を付けて1つの欄へ書きます。", "【区分】予算\n◎見本条例\n質疑\n問　質問文\n答　答弁文", multiline=True),
        FormField("votes", "議案・発議案と賛否", "行ごとに区分・件名・結果・各議員の印を入れます。", []),
        FormField("attachment", "表の下の案内", "表の下へ入れる文です。"),
    ],
    layout.LAST: [
        FormField("editorial", "編集後記", "1段目に入る本文です。", multiline=True),
        FormField("editorial_photos", "編集後記の写真", "0～2枚の写真と説明を選びます。", []),
        FormField("free", "自由欄", "2～4段目へ入れる記事です。原稿の内容を貼り付けても構いません。", multiline=True),
        FormField("hearing_title", "傍聴案内の見出し", "5段目の見出しです。", default="議会を傍聴してみませんか"),
        FormField("next_meeting", "次回定例会", "開会予定を入力します。", "次の定例会は１２月４日（金）午前１０時に開会の予定です。"),
        FormField("invitation", "呼びかけ", "傍聴の呼びかけです。", default="お気軽に傍聴に、お越し下さい。"),
        FormField("opinion", "意見・提言の案内", "委員会への案内です。"),
    ],
}

FORM_SECTIONS = tuple(FIELDS)


def default_form(section: str) -> dict:
    """入力欄の既定値を新しい辞書で返す。"""
    form = {field.name: copy.deepcopy(field.default) for field in FIELDS.get(section, [])}
    return form


def _box(x: float, y: float, w: float, h: float) -> Box:
    return Box(mm2pt(x), mm2pt(y), mm2pt(w), mm2pt(h))


def _fit_lines(text: str, units_per_line: int) -> List[str]:
    """入力済みの改行を保ちつつ、枠寸法に合わせて明示改行する。"""
    lines = []
    for paragraph in str(text or "").splitlines() or [""]:
        lines.extend(split_lines(paragraph, max(1, units_per_line), indent=False))
    return lines


def _htext(page: dx.Page, box: Box, text: str, pt: float, *, font: str = dx.GOTHIC,
           align: str = "左", border: bool = False, name: str = "text",
           warnings: Optional[List[str]] = None, bold: bool = False) -> None:
    """横書き文字を枠幅で分け、枠高に入らない分は警告する。"""
    pitch = max(pt * 1.35, pt)
    lines = _fit_lines(text, int(box.w / pt))
    capacity = max(1, int(box.h / pitch + 1e-9))
    if len(lines) > capacity:
        if warnings is not None:
            warnings.append(f"{name}が{len(lines) - capacity}行あふれています。文章または枠を見直してください。")
        lines = lines[:capacity]
    page.items.append(dx.TextBox(box, lines, font, pt, pitch, border,
                                 False, name, False, align, bold))


def _vtext(page: dx.Page, box: Box, text: str, pt: float, *, font: str = dx.GOTHIC,
           pitch: float = 17.0, border: bool = False, center: bool = False,
           name: str = "text", warnings: Optional[List[str]] = None) -> None:
    """縦書き文字を枠高で分け、枠幅に入らない分は警告する。"""
    lines = _fit_lines(text, int(box.h / pt))
    capacity = max(1, int(box.w / max(pitch, pt) + 1e-9))
    if len(lines) > capacity:
        if warnings is not None:
            warnings.append(f"{name}が{len(lines) - capacity}行あふれています。文章または枠を見直してください。")
        lines = lines[:capacity]
    page.items.append(dx.TextBox(box, lines, font, pt, pitch, border, center, name))


def _one_line_box(text: str, pt: float, *, height_ratio: float = 1.35) -> tuple[float, float]:
    """横書き1行を Word に折り返させない幅・高さを返す。"""
    return text_width(text) * pt + dx.SLACK_PT, max(pt * height_ratio, pt) + dx.SLACK_PT


def _image(page: dx.Page, value, box: Box, label: str, warnings: List[str]) -> None:
    """フォームで選ばれた画像を置く。読めないときは場所を残す。"""
    path_value = value.get("path", "") if isinstance(value, dict) else value
    caption = value.get("caption", "") if isinstance(value, dict) else ""
    if not path_value:
        page.items.append(dx.Placeholder(box, label, label))
        return
    path = Path(path_value)
    try:
        data = path.read_bytes()
        ext = compose._image_ext(path.name, data)
        dx.image_size(data, ext)
    except (OSError, ValueError) as error:
        page.items.append(dx.Placeholder(box, label + "（読み取り不可）", label))
        warnings.append(f"{label}を読み取れません: {error}")
        return
    page.items.append(dx.Picture(box, data, ext, caption, label))


def _feature_lines(form: dict, issue: layout.Issue, plan: layout.Plan) -> List[str]:
    raw = form.get("feature_titles") or issue.feature_title
    titles = [line.strip() for line in str(raw).splitlines() if line.strip()]
    page_range = plan.page_range(layout.TOKUSHU)
    if not titles or not page_range:
        return []
    first, last = page_range
    if len(titles) == 1:
        ranges = [(first, last)]
    else:
        ranges = []
        for index, _title in enumerate(titles):
            start = min(first + index, last)
            end = last if index == len(titles) - 1 else start
            ranges.append((start, end))
    lines = []
    for index, (title, pages) in enumerate(zip(titles, ranges)):
        prefix = "特集　" if index == 0 else "　　　"
        lines.append(f"{prefix}{title}……{layout.page_label(*pages)}")
    return lines


def meeting_name(issue: layout.Issue) -> str:
    """発行月から、掲載する定例会名を求める。"""
    match = re.search(r"令和\s*([0-9０-９]+)年", issue.date)
    year = int(match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))) if match else 0
    meeting_month = layout.TEIREIKAI.get(issue.month, issue.month)
    if issue.month == 1:
        year -= 1
    number = {3: 1, 6: 2, 9: 3, 12: 4}.get(meeting_month, 0)
    return f"令和{str(year).translate(layout.ZEN)}年第{str(number).translate(layout.ZEN)}回定例会"


def summary_text(counts, month: Optional[int] = None) -> str:
    """種類と件数から審議ページのまとめ文を作る。"""
    pairs = []
    for item in counts or []:
        if isinstance(item, dict):
            kind, count = item.get("kind", ""), item.get("count", 0)
        else:
            kind, count = item[0], item[1]
        if str(kind).strip() and int(count or 0):
            pairs.append((str(kind).strip(), int(count)))
    total = sum(count for _, count in pairs)
    detail = "、".join(f"{kind}{count}件" for kind, count in pairs)
    head = f"{month}月議会" if month else "議会"
    return ingest.normalize_numbers(f"{head}では、{detail}の計{total}件の議案等が決まった。") if pairs else ""


def _cover(form: dict, issue: layout.Issue, plan: layout.Plan, g: Geometry) -> compose.PageResult:
    page, warnings = dx.Page(), []
    issue_no = f"第{str(issue.number).translate(layout.ZEN)}号"
    issue_date = str(issue.date).translate(layout.ZEN)
    no_w, no_h = _one_line_box(issue_no, 20)
    date_w, date_h = _one_line_box(issue_date, 16)
    kana_w, kana_h = _one_line_box("ひだか", 36)
    title_w, title_h = _one_line_box("議会だより", 55)
    # 字の幅ちょうどの枠だと、Windows の Word や画面の見本では字の幅がわずかに違い、
    # 最後の字が欠ける（役場のパソコンで確認）。右上の 2 つは 80mm、題字は 120mm の幅をとり、
    # 寄せ方（右・左）で位置を決める。発行日に曜日などを書き足しても入る
    no_w = max(no_w, mm2pt(80))
    date_w = max(date_w, mm2pt(80))
    kana_w = max(kana_w, mm2pt(60))
    title_w = max(title_w, mm2pt(120))
    right = mm2pt(195)
    _htext(page, Box(right - no_w, mm2pt(15), no_w, no_h), issue_no, 20,
           align="右", name="号数", warnings=warnings)
    _htext(page, Box(right - date_w, mm2pt(25), date_w, date_h), issue_date, 16,
           align="右", name="発行日", warnings=warnings)
    _htext(page, Box(mm2pt(22), mm2pt(15), kana_w, kana_h), "ひだか", 36,
           name="題字（ひだか）", warnings=warnings)
    _htext(page, Box(mm2pt(22), mm2pt(34), title_w, title_h), "議会だより", 55,
           name="題字（議会だより）", warnings=warnings)
    _image(page, form.get("photo"), _box(20, 62, 170, 150), "表紙写真", warnings)
    _htext(page, _box(20, 213, 170, 8), form.get("photo_caption", ""), 10,
           align="中央", name="写真説明", warnings=warnings)
    _htext(page, _box(20, 225, 170, 1), "", 1, border=True, name="横線", warnings=warnings)
    toc = _feature_lines(form, issue, plan)
    _htext(page, _box(20, 229, 170, 22), "\n".join(toc), 12,
           name="特集目次", warnings=warnings)
    publisher = "発行　高知県日高村議会　編集　議会広報発行調査特別委員会　日高村本郷６１－１"
    contact = "〒７８１－２１９４　　℡０８８９－２４－７７７７"
    _htext(page, _box(15, 267, 180, 14), publisher + "\n" + contact, 12,
           align="中央", name="発行元", warnings=warnings)
    overflow = max(0, len(toc) - 3)
    if overflow:
        warnings.append(f"特集の目次が{overflow}行あふれています。題名をまとめてください。")
    return compose.PageResult(page, overflow, 0, warnings, [])


def _body_parts(text: str) -> List[ingest.Part]:
    parts = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("【区分】"):
            parts.append(ingest.Part("中見出し", line[4:].strip(), True, "【区分】の印"))
        elif line.startswith("◎"):
            parts.append(ingest.Part("議案", line, True, "◎の印"))
        elif line == "質疑":
            parts.append(ingest.Part("中見出し", line, True, "質疑の印"))
        elif line.startswith("問　"):
            parts.append(ingest.Part("質問", line, True, "問の印"))
        elif line.startswith("答　"):
            parts.append(ingest.Part("答弁", line, True, "答の印"))
        else:
            parts.append(ingest.Part("本文", line, True, "書き込み欄"))
    return parts


def _shingi(form: dict, issue: layout.Issue, settings: Settings, g: Geometry) -> compose.PageResult:
    page, warnings, placements = dx.Page(), [], []
    meeting = form.get("meeting") or meeting_name(issue)
    period = form.get("period", "")
    _htext(page, _box(15, 15, 180, 20), f"審議したこと　　{meeting}\n{period}　　決まったこと",
           14, font=dx.GOTHIC, align="中央", border=True, name="審議の帯", warnings=warnings)
    summary = summary_text(form.get("counts", []), layout.TEIREIKAI.get(issue.month))
    _htext(page, _box(15, 36, 180, 10), summary, 12, name="まとめ文", warnings=warnings)

    used = 0
    capacity = g.lines_per_dan * 2
    for index, part in enumerate(_body_parts(form.get("body", ""))):
        heading = part.kind in ("中見出し", "議案")
        pt = 14.0 if heading else 11.0
        chars = max(1, int(g.dan_h_pt / pt))
        lines = split_lines(part.text, chars, indent=part.kind in ("本文", "答弁"))
        span = max(2, len(lines)) if heading else len(lines)
        if used >= capacity:
            used += span
            continue
        take_span = min(span, capacity - used)
        take = min(len(lines), take_span)
        dan, line = 1 + used // g.lines_per_dan, used % g.lines_per_dan
        rect = Rect(dan, line, 1, take_span)
        font = dx.GOTHIC
        page.items.append(dx.TextBox(to_box(g, rect), lines[:take], font, pt, 17.0,
                                     part.kind == "中見出し" and part.reason == "【区分】の印",
                                     heading, part.kind))
        placements.append(compose.Placement(part, rect, index))
        used += span
    overflow = max(0, used - capacity)

    title = f"第{str({3: 1, 6: 2, 9: 3, 12: 4}.get(layout.TEIREIKAI.get(issue.month), 0)).translate(layout.ZEN)}回定例会議案・発議案と賛否"
    _htext(page, _box(15, 168, 180, 7), title, 11, font=dx.GOTHIC,
           align="中央", name="賛否表見出し", warnings=warnings)
    _htext(page, _box(15, 175, 180, 5), "○：賛成　　●：反対", 8,
           align="右", name="賛否凡例", warnings=warnings)
    if not settings.members:
        _htext(page, _box(15, 181, 180, 45), "設定で議員名簿を入れてください", 12,
               align="中央", border=True, name="賛否表", warnings=warnings)
    else:
        members = list(settings.members)
        widths = [18.0, 75.0] + [max(10.0, 65.0 / len(members))] * len(members) + [22.0]
        scale = mm2pt(180) / sum(widths)
        widths = [width * scale for width in widths]
        rows = [["区分", "議案・発議案"] + members + ["議決結果"]]
        for item in form.get("votes", []) or []:
            marks = item.get("marks", {})
            rows.append([str(item.get("kind", "")), str(item.get("title", ""))]
                        + [str(marks.get(name, "")) for name in members]
                        + [str(item.get("result", ""))])
        cell_pts = [[8.0] * len(rows[0])]
        cell_pts.extend([[11.0, 11.0] + [8.0] * len(members) + [11.0]
                         for _row in rows[1:]])
        page.items.append(dx.Table(_box(15, 181, 180, 55), widths, rows, 8.0,
                                   dx.GOTHIC, True, "賛否表", cell_pts))
        table_overflow = max(0, len(rows) - 8)
        if table_overflow:
            warnings.append(f"賛否表が{table_overflow}行あふれています。件名をまとめるか、行を減らしてください。")
            overflow += table_overflow
    attachment = form.get("attachment") or ("別添　" + title)
    _htext(page, _box(15, 239, 180, 12), attachment, 16,
           align="中央", name="別添案内", warnings=warnings)
    if overflow:
        warnings.append(f"審議本文が{overflow}行あふれています。本文を短くするか、表現をまとめてください。")
    return compose.PageResult(page, overflow, max(0, capacity - used), warnings, placements)


def _last(form: dict, settings: Settings, g: Geometry) -> compose.PageResult:
    page, warnings = dx.Page(), []
    page.items.append(dx.TextBox(to_box(g, Rect(0, 0, 1, 4)), ["編　集", "後　記"],
                                 dx.GOTHIC, 20, 22, True, True, "編集後記"))
    editorial_lines = split_lines(str(form.get("editorial", "")), g.chars_per_line)
    editorial_capacity = max(0, g.lines_per_dan - 5)
    page.items.append(dx.TextBox(to_box(g, Rect(0, 5, 1, min(editorial_capacity, len(editorial_lines) or 1))),
                                 editorial_lines[:editorial_capacity], dx.GOTHIC, 11, 17,
                                 False, False, "編集後記本文"))
    photos = list(form.get("editorial_photos", []) or [])[:2]
    for index, photo in enumerate(photos):
        _image(page, photo, _box(20 + index * 42, 67, 38, 28), f"編集後記写真{index + 1}", warnings)

    free_lines = []
    for paragraph in str(form.get("free", "")).splitlines():
        free_lines.extend(split_lines(paragraph, g.chars_per_line))
    free_capacity = g.lines_per_dan * 3
    for dan in range(1, 4):
        start = (dan - 1) * g.lines_per_dan
        chunk = free_lines[start:start + g.lines_per_dan]
        if chunk:
            page.items.append(dx.TextBox(to_box(g, Rect(dan, 0, 1, len(chunk))), chunk,
                                         dx.GOTHIC, 11, 17, False, False, "自由欄"))

    fifth = to_box(g, Rect(4, 0, 1, g.lines_per_dan))
    hearing = Box(mm2pt(20), fifth.y, mm2pt(112), mm2pt(36))
    _htext(page, hearing, "", 1, border=True, name="傍聴案内の囲み", warnings=warnings)
    _htext(page, Box(mm2pt(23), fifth.y + mm2pt(2), mm2pt(106), mm2pt(9)),
           form.get("hearing_title") or "議会を傍聴してみませんか", 16,
           font=dx.GOTHIC, align="中央", name="傍聴案内見出し", warnings=warnings, bold=True)
    _htext(page, Box(mm2pt(23), fifth.y + mm2pt(12), mm2pt(106), mm2pt(12)),
           form.get("next_meeting", ""), 11,
           align="中央", name="次回定例会", warnings=warnings)
    _htext(page, Box(mm2pt(23), fifth.y + mm2pt(26), mm2pt(106), mm2pt(8)),
           form.get("invitation") or "お気軽に傍聴に、お越し下さい。", 14,
           font=dx.GOTHIC, align="中央", name="傍聴の呼びかけ", warnings=warnings)

    opinion = (form.get("opinion")
               or f"{settings.committee}へのご意見・ご提言を、よろしくお願い申し上げます。")
    _vtext(page, Box(mm2pt(150), fifth.y, mm2pt(45), fifth.h), opinion, 11,
           name="意見・提言", warnings=warnings)
    _vtext(page, Box(mm2pt(135), fifth.y, mm2pt(14), fifth.h),
           f"発行責任者\n議　長　{settings.chair}", 11, name="発行責任者", warnings=warnings)
    _htext(page, _box(15, 279.9, 180, 5.1),
           "「日高村議会だより」は、資源保護のため再生紙を使用しています。", 10.5,
           align="中央", name="再生紙のお知らせ", warnings=warnings)
    overflow = max(0, len(editorial_lines) - editorial_capacity) + max(0, len(free_lines) - free_capacity)
    if overflow:
        warnings.append(f"編集後記・自由欄が{overflow}行あふれています。文章を短くするか、自由欄の構成を見直してください。")
    return compose.PageResult(page, overflow, max(0, editorial_capacity + free_capacity - len(editorial_lines) - len(free_lines)), warnings, [])


def build(section: str, form: dict, issue: layout.Issue, plan: layout.Plan,
          settings: Settings, g: Geometry) -> compose.PageResult:
    """書き込み内容から、紙面見本と Word で共用する1ページを作る。"""
    values = dict(default_form(section))
    values.update(form or {})
    if section == layout.COVER:
        return _cover(values, issue, plan, g)
    if section == layout.SHINGI:
        return _shingi(values, issue, settings, g)
    if section == layout.LAST:
        return _last(values, settings, g)
    raise ValueError("書き込み式ではない区分です: " + section)


def copied_form(section: str, form: dict) -> dict:
    """前号から残す欄だけを写し、号ごとの内容を空に戻す。"""
    copied = dict(form or {})
    if section == layout.COVER:
        for key in ("photo", "photo_caption"):
            copied[key] = ""
    elif section == layout.SHINGI:
        for key in ("meeting", "period", "counts", "body", "attachment"):
            copied[key] = [] if key == "counts" else ""
        copied["votes"] = [dict(row, marks={}) for row in copied.get("votes", [])]
    elif section == layout.LAST:
        copied["editorial"] = ""
        copied["editorial_photos"] = []
        copied["next_meeting"] = ""
    return copied
