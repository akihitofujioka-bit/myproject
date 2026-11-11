"""表紙・審議ページ・最終ページの書き込み式テンプレート。"""

from __future__ import annotations

import re
import copy
import math
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
    ],
    layout.YOSAN: [
        FormField("title", "題", "1ページ目の囲みの左に入ります。発行年から自動で入ります。", "令和８年度当初予算"),
        FormField("kinds", "会計の種類", "囲みの右に1行に1つ書きます。",
                  default="一般会計\n特別会計\n公営企業会計", multiline=True),
        FormField("chart_title", "円グラフの題", "1ページ目の円グラフの上の題です。", "令和８年度一般会計予算"),
        FormField("chart_note", "円グラフの指示", "楕円の囲みに入る、印刷所への指示です。",
                  default="一般会計（歳出）の円グラフは、ひだか広報のものを使用"),
        FormField("general_total", "一般会計の歳出総額", "円グラフの真ん中に入る総額です。", "54億1,139万円"),
        FormField("chart_items", "円グラフの横の主な事業", "費目・事業名・説明です。", []),
        FormField("accounts", "各会計予算", "公営企業会計・特別会計の金額です。", []),
        FormField("headline", "2ページ目の大見出し", "例: 日高村72億円でスタート", "日高村７２億円でスタート"),
        FormField("focus", "注目する事業", "事業名・金額・説明です。", []),
        FormField("previous_title", "前の年度の欄の見出し", "例: 令和７年度補正予算", ""),
        FormField("previous", "前の年度の事業", "事業名・金額・説明です。", []),
    ],
    layout.KESSAN: [
        FormField("title", "題", "囲みの左に入る題です。発行年から自動で入ります。", "令和７年度決算認定"),
        FormField("kinds", "会計の種類", "囲みの右に1行に1つ書きます。",
                  default="一般会計\n特別会計\n公営企業会計", multiline=True),
        FormField("photo", "写真", "幅いっぱいに入る写真です（決算審査の様子など）。"),
        FormField("chart_note", "円グラフの指示", "楕円の囲みに入る、印刷所への指示です。",
                  default="一般会計の円グラフはひだか広報１１月号のを使用"),
        FormField("accounts", "会計別決算額", "会計ごとの歳入・歳出です。", []),
        FormField("body", "決算の質疑", "【会計名】／問　…／答　… の形です。", multiline=True),
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
    pitch = dx.effective_pitch(pt, pt)
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
    capacity = max(1, int(box.w / dx.effective_pitch(pt, pitch) + 1e-9))
    if len(lines) > capacity:
        if warnings is not None:
            warnings.append(f"{name}が{len(lines) - capacity}行あふれています。文章または枠を見直してください。")
        lines = lines[:capacity]
    page.items.append(dx.TextBox(box, lines, font, pt, pitch, border, center, name))


def _one_line_box(text: str, pt: float, *, height_ratio: float = dx.AT_LEAST_RATIO) -> tuple[float, float]:
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


def default_opinion(settings: Settings) -> str:
    """最終ページの意見・提言の決まった文（入力欄が空のときに使う）。"""
    return f"{settings.committee}へのご意見・ご提言を、よろしくお願い申し上げます。"


def summary_text(counts, month: Optional[int] = None) -> str:
    """種類と件数から審議ページのまとめ文を作る。"""
    pairs = []
    for item in counts or []:
        if isinstance(item, dict):
            kind, count = item.get("kind", ""), item.get("count", 0)
        else:
            kind, count = item[0], item[1]
        if int(count or 0):   # 区分が空の件数も合計に入れる
            pairs.append((str(kind).strip(), int(count)))
    total = sum(count for _, count in pairs)
    named = [(kind, count) for kind, count in pairs if kind]
    detail = "、".join(f"{kind}{count}件" for kind, count in named)
    head = f"{month}月議会" if month else "議会"
    if not pairs:
        return ""
    # 横書きの文なので、数字はすべて全角にする（縦中横の決まりは縦書きだけ）。
    if not named:   # 区分の列が無いエクセルでも、件数だけは出す
        return _full_digits(f"{head}では、計{total}件の議案等が決まった。")
    return _full_digits(f"{head}では、{detail}の計{total}件の議案等が決まった。")


def _full_digits(text: str) -> str:
    return str(text).translate(layout.ZEN)


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
    warnings.extend(dx.page_textbox_warnings(page))
    return compose.PageResult(page, overflow, 0, warnings, [])


def _body_parts(text: str) -> List[ingest.Part]:
    parts = []
    # ほかの記事と同じく、2〜3 桁は縦中横、1 桁と 4 桁以上は全角にそろえる。
    for raw in ingest.normalize_numbers(str(text or "")).splitlines():
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


VOTE_ROW_PT = 17.0    # 賛否表の 1 行の高さ（11pt の字が欠けない高さ）


def vote_result(value) -> str:
    """議決結果は「可決」「否決」などだけを出す。「原案可決」の「原案」は付けない。"""
    text = str(value or "").strip()
    return text[2:] if text.startswith("原案") and len(text) > 2 else text


def _vote_table(form: dict, settings: Settings) -> tuple:
    """賛否表（Word の表）と、行ごとの高さ、見出し行の高さを返す。置く位置はあとで決める。"""
    members = list(settings.vote_members)
    # 区分は「条例など」「補正予算」の 4 字が 1 行に入る幅にする
    widths = [24.0, 72.0] + [max(10.0, 62.0 / len(members))] * len(members) + [22.0]
    scale = mm2pt(180) / sum(widths)
    widths = [width * scale for width in widths]
    # 左上は元の賛否のエクセルと同じく、区分と件名の列をつないだ 1 つのセルに斜めの線を引き、
    # 右上に「議員名」、左下に「議案・発議案」を入れる。
    rows = [["", ""] + members + ["議決結果"]]
    for item in form.get("votes", []) or []:
        marks = item.get("marks", {})
        rows.append([str(item.get("kind", "")), str(item.get("title", ""))]
                    + [str(marks.get(name, "")) for name in members]
                    + [vote_result(item.get("result", ""))])
    cell_pts = [[8.0] * len(rows[0])]
    # 件名は 9pt、区分と議決結果は 10pt にして、件数が多くても 1 ページに収まりやすくする。
    cell_pts.extend([[10.0, 9.0] + [8.0] * len(members) + [10.0] for _row in rows[1:]])
    # 見出し行の議員名は縦書き。いちばん長い名前が入る高さにする。
    longest = max(len(name) for name in members)
    header_pt = longest * 8.0 * 1.15 + 6.0
    vertical = {(0, 2 + index) for index in range(len(members))}
    # 長い件名は列の幅で改行を入れ、その行数に合わせて行を高くする（Word と紙面の見本で同じ高さ）。
    heights = [header_pt]
    for row in rows[1:]:
        line_counts = []
        for column, pt in ((0, 10.0), (1, 9.0), (len(row) - 1, 10.0)):
            units = max(1, int((widths[column] - 4) / pt))
            # 入っている改行（エクセルのセル内の改行や、画面で入れた改行）はそのまま生かす
            lines = _fit_lines(str(row[column]), units)
            row[column] = "\n".join(lines)
            line_counts.append(len(lines))
        heights.append(max(15.0, max(line_counts) * 9.0 * 1.4 + 4))
    table = dx.Table(_box(15, 200, 180, 80), widths, rows, 8.0, dx.GOTHIC, True, "賛否表",
                     cell_pts, vertical, heights, {(0, 0): 2}, None,
                     {(0, 0): ("議員名", "議　案・発議案")})
    return table, heights, header_pt


def _shingi(form: dict, issue: layout.Issue, settings: Settings, g: Geometry) -> compose.PageResult:
    page, warnings, placements = dx.Page(), [], []
    meeting = form.get("meeting") or meeting_name(issue)
    period = form.get("period", "")
    # 従来の紙面の形: 枠の中に「審議したこと」（左）と「決まったこと」（右）を階段状に置き、
    # 1 行目の右に定例会名、2 行目の左下に会期を小さく入れる。まとめ文は下の別の枠に入れる。
    page.items.append(dx.TextBox(_box(15, 15, 180, 36), [""], dx.GOTHIC, 11, 15.4,
                                 border=True, name="審議の囲み", vertical=False))
    _htext(page, _box(30, 16, 80, 18), "審議したこと", 36, font=dx.MINCHO,
           name="審議の題字1", warnings=warnings)
    _htext(page, _box(95, 32, 80, 18), "決まったこと", 36, font=dx.MINCHO,
           name="審議の題字2", warnings=warnings)
    _htext(page, _box(130, 23, 62, 7), _full_digits(meeting), 12, bold=True,
           name="定例会名", warnings=warnings)
    _htext(page, _box(19, 41, 70, 7), _full_digits(period), 12, bold=True,
           name="会期", warnings=warnings)
    summary = summary_text(form.get("counts", []), layout.TEIREIKAI.get(issue.month))
    _htext(page, _box(15, 54, 180, 14), "　" + summary if summary else "", 12, border=True,
           name="まとめ文", warnings=warnings)

    # 賛否表を先に組み、ページのいちばん下に寄せる。その上に残った段をすべて審議の本文（議案と質疑）に使う。
    title = f"第{str({3: 1, 6: 2, 9: 3, 12: 4}.get(layout.TEIREIKAI.get(issue.month), 0)).translate(layout.ZEN)}回定例会議案・発議案と賛否"
    page_bottom = g.page_h_mm - g.margin_bottom_mm
    summary_bottom = 70.0
    table_overflow = 0
    table = None
    if settings.vote_members:
        table, heights, header_pt = _vote_table(form, settings)
        table_h = (sum(heights) + 2) * 25.4 / 72
    else:
        table_h = 45.0
    # 表の見出し（13mm）を含めて、本文の 1 段ぶんは必ず残す
    lowest_top = to_box(g, Rect(1, 0, 1, 1))
    lowest_top = (lowest_top.y + lowest_top.h) * 25.4 / 72 + 2 + 13
    table_top = max(lowest_top, page_bottom - table_h)
    top = table_top - 13.0
    if table is not None:
        table.box = _box(15, table_top, 180, page_bottom - table_top)
        room = mm2pt(page_bottom - table_top) - header_pt
        fit_rows = 0
        for height in heights[1:]:
            if room < height:
                break
            room -= height
            fit_rows += 1
        table_overflow = max(0, len(heights) - 1 - fit_rows)
        if table_overflow:
            warnings.append(f"賛否表が{table_overflow}行（{table_overflow}件ぶん）ページに入りません。件名を短くするか、行を減らしてください。")

    dans = [d for d in range(1, g.dans)
            if (to_box(g, Rect(d, 0, 1, 1)).y + to_box(g, Rect(d, 0, 1, 1)).h) * 25.4 / 72 <= top - 2]
    used = 0
    capacity = g.lines_per_dan * len(dans)
    for index, part in enumerate(_body_parts(form.get("body", ""))):
        # 見出しは場所を取りすぎないよう本文に近い大きさにする。区分の囲みだけ 12pt で 2 行分、
        # 「◎件名」と「質疑」は本文と同じ 11pt の太字で、必要な行数だけ使う。
        boxed = part.kind == "中見出し" and part.reason == "【区分】の印"
        heading = part.kind in ("中見出し", "議案")
        pt = 12.0 if boxed else 11.0
        chars = max(1, int(g.dan_h_pt / pt))
        lines = split_lines(part.text, chars, indent=part.kind in ("本文", "答弁"))
        span = max(2, len(lines) + 1) if boxed else len(lines)
        if heading:
            remaining = g.lines_per_dan - used % g.lines_per_dan
            if span > remaining:
                used += remaining
        if used >= capacity or (heading and used + span > capacity):
            used += span
            continue
        if heading:
            dan, line = dans[used // g.lines_per_dan], used % g.lines_per_dan
            rect = Rect(dan, line, 1, span)
            page.items.append(dx.TextBox(to_box(g, rect), lines, dx.GOTHIC, pt, g.line_pitch_pt,
                                         boxed, boxed, part.kind, True, "左", not boxed))
            placements.append(compose.Placement(part, rect, index))
            used += span
            continue
        # 本文・問・答は、段の終わりで次の段へ続ける（1 つの段からはみ出さない）。入らない行は数えるだけ。
        rest = lines
        while rest:
            if used >= capacity:
                used += len(rest)
                break
            dan, line = dans[used // g.lines_per_dan], used % g.lines_per_dan
            take = min(len(rest), g.lines_per_dan - line)
            rect = Rect(dan, line, 1, take)
            page.items.append(dx.TextBox(to_box(g, rect), rest[:take], dx.GOTHIC, pt, g.line_pitch_pt,
                                         False, False, part.kind, True, "左", False))
            placements.append(compose.Placement(part, rect, index))
            used += take
            rest = rest[take:]
    overflow = max(0, used - capacity)

    _htext(page, _box(15, top, 180, 7), title, 11, font=dx.GOTHIC,
           align="中央", name="賛否表見出し", warnings=warnings)
    _htext(page, _box(15, top + 7, 180, 5), "○：賛成　　●：反対", 8,
           align="右", name="賛否凡例", warnings=warnings)
    if table is None:
        _htext(page, _box(15, table_top, 180, 45), "設定で議員名簿を入れてください", 12,
               align="中央", border=True, name="賛否表", warnings=warnings)
    else:
        page.items.append(table)
    if overflow:
        warnings.append(f"審議の本文（案件の説明・質疑）が{overflow}行（約{overflow * g.chars_per_line}字）入りません。"
                        "説明や質疑を短くしてください。")
    overflow += table_overflow
    warnings.extend(dx.page_textbox_warnings(page))
    return compose.PageResult(page, overflow, max(0, capacity - used), warnings, placements)


KESSAN_ROW_PT = 17.0   # 会計別決算額の 1 行の高さ


def kessan_title(issue: layout.Issue) -> str:
    """10 月号は前の年度の決算を載せる（令和８年１０月号 → 令和７年度決算認定）。"""
    match = re.search(r"令和\s*([0-9０-９]+)年", issue.date or "")
    if not match:
        return "決算認定"
    year = int(match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789"))) - 1
    return _full_digits(f"令和{year}年度決算認定")


def yosan_title(issue: layout.Issue) -> str:
    """4・5 月号はその年度の当初予算を載せる（令和８年５月号 → 令和８年度当初予算）。"""
    match = re.search(r"令和\s*([0-9０-９]+)年", issue.date or "")
    if not match:
        return "当初予算"
    year = int(match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    return _full_digits(f"令和{year}年度当初予算")


def _yosan(form: dict, issue: layout.Issue, g: Geometry) -> compose.PageResult:
    """当初予算の見開き（第202号の形）。1 ページ目は円グラフと各会計予算、2 ページ目は注目する事業。"""
    page, warnings = dx.Page(), []
    title = form.get("title") or yosan_title(issue)
    if int(form.get("page_index") or 1) == 1:
        overflow = _yosan_first(page, form, title, warnings)
    else:
        overflow = _yosan_second(page, form, title, warnings)
    warnings.extend(dx.page_textbox_warnings(page))
    return compose.PageResult(page, overflow, 0, warnings, [])


def _block(page, x, y, w, text, pt, bottom, name, warnings, *, bold=False, border=False,
           align="左") -> tuple:
    """横書きの文を y から下へ置き、次に置ける y と、入らなかった行数を返す。"""
    lines = _fit_lines(text, int(mm2pt(w) / pt))
    pitch_mm = dx.effective_pitch(pt, pt) * 25.4 / 72
    room = max(0, int((bottom - y) / pitch_mm + 1e-9))
    take = min(len(lines), room)
    if take:
        page.items.append(dx.TextBox(_box(x, y, w, take * pitch_mm + 0.5), lines[:take], dx.GOTHIC,
                                     pt, pt, border, False, name, False, align, bold))
    return y + take * pitch_mm, len(lines) - take


def _yosan_first(page, form, title, warnings) -> int:
    page.items.append(dx.TextBox(_box(18, 18, 174, 27), [""], dx.GOTHIC, 11, 15.4,
                                 border=True, name="当初予算の囲み", vertical=False))
    _htext(page, _box(28, 21, 90, 10), title, 20, name="当初予算の題", warnings=warnings)
    _htext(page, _box(118, 19, 64, 25), str(form.get("kinds", "")), 16, align="中央",
           name="会計の種類", warnings=warnings)
    chart_title = form.get("chart_title") or title.replace("当初予算", "一般会計予算")
    _htext(page, _box(15, 49, 180, 12), _full_digits(chart_title), 22, align="中央", bold=True,
           name="円グラフの題", warnings=warnings)
    lines = _fit_lines(_full_digits(form.get("chart_note", "")), 30)
    if form.get("general_total"):
        lines += ["", "歳出　" + str(form["general_total"])]
    note = dx.TextBox(_box(40, 63, 130, 52), [""] * max(1, (8 - len(lines)) // 2) + lines,
                      dx.GOTHIC, 11, 15.4, border=True, name="円グラフの指示", vertical=False,
                      align="中央", shape="ellipse")
    page.items.append(note)
    # 円グラフの横に入れる主な事業（費目ごと）。左右 2 列に並べる。
    items = [v for v in form.get("chart_items", []) or [] if any(str(v.get(k, "")).strip()
                                                                for k in ("item", "name", "text"))]
    overflow = 0
    if items:
        _htext(page, _box(18, 119, 174, 6), "円グラフの横に入れる主な事業", 10, bold=True,
               name="主な事業の見出し", warnings=warnings)
    columns = [(18.0, 125.0), (107.0, 125.0)]
    for number, value in enumerate(items):
        x, y = columns[number % 2]
        head = (f"【{value.get('item', '').strip()}】" if str(value.get("item", "")).strip() else "") + \
            "◉" + str(value.get("name", "")).strip()
        y, lost = _block(page, x, y, 85, head, 11, 215, "主な事業", warnings, bold=True)
        y, lost2 = _block(page, x + 3, y, 82, str(value.get("text", "")), 10, 215, "主な事業の説明", warnings)
        columns[number % 2] = (x, y + 2)
        overflow += lost + lost2
    if overflow:
        warnings.append(f"円グラフの横の主な事業が{overflow}行入りません。説明を短くしてください。")
    _htext(page, _box(18, 221, 174, 9), "　" + _full_digits(title.replace("当初予算", "各会計予算")), 15,
           bold=True, border=True, name="各会計予算の見出し", warnings=warnings)
    groups = {}
    for value in form.get("accounts", []) or []:
        groups.setdefault(str(value.get("group", "")).strip() or "その他", []).append(value)
    for column, (group, values) in enumerate(list(groups.items())[:2]):
        x = 20 if column == 0 else 108
        y, _lost = _block(page, x, 233, 82, group, 12, 285, "会計のまとめ", warnings, bold=True)
        for value in values:
            line = f"◉{str(value.get('name', '')).strip()}　{str(value.get('amount', '')).strip()}"
            y, lost = _block(page, x, y + 1, 82, line, 11, 285, "会計の金額", warnings)
            if str(value.get("note", "")).strip():
                y, lost2 = _block(page, x + 3, y, 79, str(value["note"]), 10, 285, "会計の注", warnings)
                lost += lost2
            overflow += lost
    if len(groups) > 2:
        warnings.append("各会計予算のまとめは2つまでです（公営企業会計・特別会計）。")
    return overflow


def _yosan_second(page, form, title, warnings) -> int:
    _htext(page, _box(15, 16, 180, 20), _full_digits(form.get("headline", "")), 30, align="中央",
           bold=True, name="当初予算の大見出し", warnings=warnings)
    year = title.replace("当初予算", "")
    _htext(page, _box(40, 40, 130, 13), f"{year}　注目する事業", 18, align="中央", bold=True,
           border=True, name="注目する事業の見出し", warnings=warnings)
    overflow, y = 0, 58.0
    bottom = 238.0 if form.get("previous") else 285.0
    for value in form.get("focus", []) or []:
        head = f"{str(value.get('name', '')).strip()}　{_full_digits(str(value.get('amount', '')).strip())}"
        y, lost = _block(page, 18, y, 174, head, 13, bottom, "注目する事業", warnings, bold=True)
        text = str(value.get("text", "")).strip()
        if text:
            y, lost2 = _block(page, 22, y + 1, 170, "◉" + text.lstrip("◉"), 11, bottom,
                              "注目する事業の説明", warnings)
            lost += lost2
        if y < bottom:
            _htext(page, _box(18, y + 1.5, 174, 1), "", 1, border=True, name="区切り線",
                   warnings=warnings)
        y += 5
        overflow += lost
    if form.get("previous"):
        heading = _full_digits(form.get("previous_title") or "前の年度の事業")
        _htext(page, _box(18, 242, 174, 9), "　" + heading, 14, bold=True, border=True,
               name="前の年度の見出し", warnings=warnings)
        y = 254.0
        for value in form.get("previous", []) or []:
            head = f"{str(value.get('name', '')).strip()}　{_full_digits(str(value.get('amount', '')).strip())}"
            y, lost = _block(page, 20, y, 172, head, 12, 285, "前の年度の事業", warnings, bold=True)
            if str(value.get("text", "")).strip():
                y, lost2 = _block(page, 24, y, 168, str(value["text"]), 10, 285, "前の年度の説明", warnings)
                lost += lost2
            y += 2
            overflow += lost
    if overflow:
        warnings.append(f"注目する事業などが{overflow}行入りません。説明を短くするか、件数を減らしてください。")
    return overflow


def _account_table(accounts) -> tuple:
    """会計別決算額の表を作る。まとめ（特別会計など）は縦につなぐ。

    列は 0: 短いまとめ（縦書き）、1〜2: 会計名、3: 歳入、4: 歳出。
    まとめが 4 字までなら列 0 に縦書き、長ければ（簡易水道事業会計など）列 0〜1 に横書きで入れる。
    """
    rows = [["会　計　名", "", "", "歳　入", "歳　出"]]
    spans = {(0, 0): 3}
    merges, vertical = {}, set()
    items = [a for a in accounts or [] if any(str(a.get(k, "")).strip()
                                                 for k in ("group", "name", "revenue", "expense"))]
    index = 0
    while index < len(items):
        group = str(items[index].get("group", "")).strip()
        count = 1
        while (group and index + count < len(items)
               and str(items[index + count].get("group", "")).strip() == group):
            count += 1
        short = len(group) <= 4
        for offset in range(count):
            account = items[index + offset]
            row = len(rows)
            name = str(account.get("name", "")).strip()
            values = ["", "", "", str(account.get("revenue", "")).strip(),
                      str(account.get("expense", "")).strip()]
            if not group:
                values[0] = name
                spans[(row, 0)] = 3
            elif short:
                values[0] = group if offset == 0 else ""
                values[1] = name
                spans[(row, 1)] = 2
                vertical.add((row, 0))
                if count > 1:
                    merges[(row, 0)] = "restart" if offset == 0 else "continue"
            else:
                # 長いまとめは半分で改行する（簡易水道事業会計 → 簡易水道／事業会計）
                half = (len(group) + 1) // 2
                values[0] = (group[:half] + "\n" + group[half:]) if offset == 0 else ""
                values[2] = name
                spans[(row, 0)] = 2
                if count > 1:
                    merges[(row, 0)] = "restart" if offset == 0 else "continue"
            rows.append(values)
        index += count
    return rows, spans, merges, vertical


def _kessan(form: dict, issue: layout.Issue, g: Geometry) -> compose.PageResult:
    """決算のページ（第204号の形）: 題の囲み・写真・円グラフの指示・会計別決算額・決算の質疑。"""
    page, warnings, placements = dx.Page(), [], []
    page.items.append(dx.TextBox(_box(18, 18, 174, 27), [""], dx.GOTHIC, 11, 15.4,
                                 border=True, name="決算の囲み", vertical=False))
    _htext(page, _box(28, 21, 90, 10), form.get("title") or kessan_title(issue), 20,
           name="決算の題", warnings=warnings)
    _htext(page, _box(118, 19, 64, 25), str(form.get("kinds", "")), 16, align="中央",
           name="会計の種類", warnings=warnings)
    _image(page, form.get("photo", ""), _box(18, 46, 174, 95), "決算写真", warnings)
    note = dx.TextBox(_box(42, 150, 130, 28), _fit_lines(_full_digits(form.get("chart_note", "")), 30),
                      dx.GOTHIC, 11, 15.4, border=True, name="円グラフの指示", vertical=False,
                      align="中央", shape="ellipse")
    note.lines = [""] * max(0, (4 - len(note.lines)) // 2 + 1) + note.lines   # 楕円の中ほどへ下げる
    page.items.append(note)
    _htext(page, _box(15, 183, 180, 6), "会　計　別　決　算　額", 11, align="中央",
           name="会計別決算額の見出し", warnings=warnings)
    rows, spans, merges, vertical = _account_table(form.get("accounts", []))
    widths = [mm2pt(value) for value in (8.0, 14.0, 43.0, 42.0, 40.0)]
    heights = [15.0] + [KESSAN_ROW_PT] * (len(rows) - 1)
    table_h = (sum(heights) + 6) * 25.4 / 72
    page.items.append(dx.Table(_box(35, 191, 147, table_h), widths, rows, 11.0, dx.GOTHIC, True,
                               "会計別決算額", None, vertical, heights, spans, merges))
    dan5_top = to_box(g, Rect(4, 0, 1, 1)).y * 25.4 / 72
    if 191 + table_h > dan5_top:
        warnings.append("会計別決算額の表が長く、下の決算の質疑に重なります。会計の行を減らしてください。")

    # 下の段（5 段目）: 右に「決算の質疑」の囲み、その左に【会計名】と問・答を縦書きで流す。
    dan = g.dans - 1
    heading_rect = Rect(dan, 0, 1, 3)
    page.items.append(dx.TextBox(to_box(g, heading_rect), ["決算の質疑"], dx.GOTHIC, 16,
                                 g.line_pitch_pt, True, True, "決算の質疑"))
    used, capacity = 3, g.lines_per_dan
    for index, part in enumerate(_body_parts(form.get("body", ""))):
        heading = part.kind == "中見出し"
        text = part.text if not heading else "【" + part.text.strip("【】") + "】"
        lines = split_lines(text, g.chars_per_line, indent=part.kind == "本文")
        take = min(len(lines), max(0, capacity - used))
        if take:
            rect = Rect(dan, used, 1, take)
            page.items.append(dx.TextBox(to_box(g, rect), lines[:take], dx.GOTHIC, 11.0,
                                         g.line_pitch_pt, False, False, part.kind))
            placements.append(compose.Placement(part, rect, index))
        used += len(lines)
    overflow = max(0, used - capacity)
    if overflow:
        warnings.append(f"決算の質疑が{overflow}行あふれています。問・答を短くしてください。")
    warnings.extend(dx.page_textbox_warnings(page))
    return compose.PageResult(page, overflow, max(0, capacity - used), warnings, placements)


def _last(form: dict, settings: Settings, g: Geometry) -> compose.PageResult:
    page, warnings = dx.Page(), []
    page.items.append(dx.TextBox(to_box(g, Rect(0, 0, 1, 4)), ["編　集", "後　記"],
                                 dx.GYOSHO, 20, 28, True, True, "編集後記"))
    editorial_lines = split_lines(str(form.get("editorial", "")), g.chars_per_line)
    editorial_capacity = max(0, g.lines_per_dan - 5)
    page.items.append(dx.TextBox(to_box(g, Rect(0, 5, 1, min(editorial_capacity, len(editorial_lines) or 1))),
                                 editorial_lines[:editorial_capacity], dx.GOTHIC, 11, g.line_pitch_pt,
                                 False, False, "編集後記本文"))
    photos = list(form.get("editorial_photos", []) or [])[:2]
    for index, photo in enumerate(photos):
        _image(page, photo, _box(20 + index * 42, 67, 38, 28), f"編集後記写真{index + 1}", warnings)

    # 自由欄に画像（写真や、Word の図形を画像にしたもの）があれば、2〜4 段目にそのまま置く。
    # 何枚かあるときは上から順に同じ高さで並べ、それぞれ縦横の割合を保って入るだけ大きくする。
    images = [value for value in (form.get("free_images") or []) if value]
    if images:
        area = to_box(g, Rect(1, 0, 3, g.lines_per_dan))
        band = area.h / len(images)
        for index, image in enumerate(images):
            _image(page, image, Box(area.x, area.y + index * band, area.w, band - (4 if len(images) > 1 else 0)),
                   f"自由欄の画像{index + 1}", warnings)
        if str(form.get("free", "")).strip():
            warnings.append("自由欄に字と画像の両方があります。画像を入れたときは、字は紙面に出ません")
    free_lines = []
    for paragraph in ("" if images else str(form.get("free", ""))).splitlines():
        free_lines.extend(split_lines(paragraph, g.chars_per_line))
    free_capacity = g.lines_per_dan * 3
    for dan in range(1, 4):
        start = (dan - 1) * g.lines_per_dan
        chunk = free_lines[start:start + g.lines_per_dan]
        if chunk:
            page.items.append(dx.TextBox(to_box(g, Rect(dan, 0, 1, len(chunk))), chunk,
                                         dx.GOTHIC, 11, g.line_pitch_pt, False, False, "自由欄"))

    fifth = to_box(g, Rect(4, 0, 1, g.lines_per_dan))
    hearing = Box(mm2pt(83), fifth.y, mm2pt(112), mm2pt(36))
    _htext(page, hearing, "", 1, border=True, name="傍聴案内の囲み", warnings=warnings)
    _htext(page, Box(mm2pt(86), fifth.y + mm2pt(2), mm2pt(106), mm2pt(9)),
           form.get("hearing_title") or "議会を傍聴してみませんか", 16,
           font=dx.GOTHIC, align="中央", name="傍聴案内見出し", warnings=warnings, bold=True)
    _htext(page, Box(mm2pt(86), fifth.y + mm2pt(12), mm2pt(106), mm2pt(12)),
           form.get("next_meeting", ""), 11,
           align="中央", name="次回定例会", warnings=warnings)
    _htext(page, Box(mm2pt(86), fifth.y + mm2pt(26), mm2pt(106), mm2pt(8)),
           form.get("invitation") or "お気軽に傍聴に、お越し下さい。", 14,
           font=dx.GOTHIC, align="中央", name="傍聴の呼びかけ", warnings=warnings)

    opinion = form.get("opinion") or default_opinion(settings)
    # 縦書きの 2 つは、ページ下端の再生紙のお知らせ（上端 279.8mm）の手前で止める。
    # 段の高さいっぱいにすると最後の行がお知らせに重なった（Mac の Word で確認）
    v_height = mm2pt(278.5) - fifth.y
    _vtext(page, Box(mm2pt(37), fifth.y, mm2pt(45), v_height), opinion, 11,
           name="意見・提言", warnings=warnings)
    _vtext(page, Box(mm2pt(20), fifth.y, mm2pt(14), v_height),
           f"発行責任者\n議　長　{settings.chair}", 11, name="発行責任者", warnings=warnings)
    _htext(page, _box(15, 279.8, 180, 5.2),
           "「日高村議会だより」は、資源保護のため再生紙を使用しています。", 10.5,
           align="中央", name="再生紙のお知らせ", warnings=warnings)
    overflow = max(0, len(editorial_lines) - editorial_capacity) + max(0, len(free_lines) - free_capacity)
    if overflow:
        warnings.append(f"編集後記・自由欄が{overflow}行あふれています。文章を短くするか、自由欄の構成を見直してください。")
    warnings.extend(dx.page_textbox_warnings(page))
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
    if section == layout.KESSAN:
        return _kessan(values, issue, g)
    if section == layout.YOSAN:
        return _yosan(values, issue, g)
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
