"""紙面を自動で組む（自動組版）。

前号の様式に流し込む方式では、枠の数と大きさが前号のままなので、
記事が増えたり写真が変わったりすると入りきらない。

こちらは反対に、**紙面の決まりごと（判型・段数・縦書き・文字の大きさ）
だけを固定して、中身に合わせて Word に組ませる**方式。
段送りと改ページは Word 自身が行うので、原稿が増えればページが増え、
写真を入れればその分だけ本文が押し出される。

決まりごと（LayoutSpec）:
  * A4 縦・5段・縦書き — 議会だよりの基本の形
  * 余白、段間、文字の大きさ、行送り
これらは画面から変えられるが、既定値は第203号の紙面に合わせてある。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from xml.sax.saxutils import escape

from .photos import HAS_PIL, aspect_of, crop_to_ratio
from .textutil import count_chars

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

# 色は第203号の実物から採った。日高村議会だよりは青系で、緑ではない。
# 変えるときは実物の紙面から採り直すこと（勘で決めない）
INK_ACCENT = "0076A3"      # 見出しの文字・罫線（濃い青）
INK_BAND = "9DDCF9"        # 区分の帯（中間の水色）
INK_BAND_TEXT = "00415C"   # 帯の上に載せる文字
INK_TINT = "D4EFFC"        # 質問の段落の下地（薄い水色）

MM_PER_PT = 25.4 / 72
EMU_PER_MM = 36000
TWIP_PER_MM = 1440 / 25.4


def mm2twip(mm: float) -> int:
    return int(round(mm * TWIP_PER_MM))


def mm2emu(mm: float) -> int:
    return int(round(mm * EMU_PER_MM))


def pt2half(pt: float) -> int:
    """Word のフォントサイズは 1/2 ポイント単位。"""
    return int(round(pt * 2))


# ====================================================================== 決まりごと


@dataclass
class LayoutSpec:
    """紙面の決まりごと。ここは中身によらず固定される。"""

    page_width_mm: float = 210.0      # A4 縦
    page_height_mm: float = 297.0
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 12.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0

    columns: int = 5                  # 1ページの段数（縦書きでは横に走る帯）
    column_gap_mm: float = 6.0

    body_font: str = "ＭＳ 明朝"
    heading_font: str = "ＭＳ ゴシック"
    body_pt: float = 10.5
    heading_pt: float = 16.0
    caption_pt: float = 8.5
    line_spacing: float = 1.45        # 行送り（文字の大きさに対する倍率）

    photo_height_ratio: float = 0.62  # 段の高さに対する写真の大きさ
    indent_first: bool = True         # 段落の1字下げ

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "LayoutSpec":
        if not d:
            return cls()
        known = {f for f in cls().to_dict()}
        return cls(**{k: v for k, v in d.items() if k in known})

    # -------------------------------------------------------------- 寸法

    @property
    def text_height_mm(self) -> float:
        """本文が入る高さ（縦書きでは1行の長さ）。"""
        return self.page_height_mm - self.margin_top_mm - self.margin_bottom_mm

    @property
    def text_width_mm(self) -> float:
        """本文が入る幅（縦書きでは行が並ぶ方向）。"""
        return self.page_width_mm - self.margin_left_mm - self.margin_right_mm

    @property
    def column_height_mm(self) -> float:
        """1段の高さ。縦書きではこれが「1行の長さ」になる。"""
        gaps = self.column_gap_mm * (self.columns - 1)
        return (self.text_height_mm - gaps) / max(1, self.columns)

    def metrics(self) -> dict:
        """「1段◯字 × ◯行」の目安。字数の見積もりに使う。"""
        char_mm = self.body_pt * MM_PER_PT
        line_mm = char_mm * self.line_spacing
        chars_per_line = max(1, int(self.column_height_mm / char_mm))
        lines_per_column = max(1, int(self.text_width_mm / line_mm))
        per_column = chars_per_line * lines_per_column
        return {
            "chars_per_line": chars_per_line,
            "lines_per_column": lines_per_column,
            "chars_per_column": per_column,
            "chars_per_page": per_column * self.columns,
            "column_height_mm": round(self.column_height_mm, 1),
        }


# ====================================================================== 部品


def _esc(s: str) -> str:
    return escape(s or "")


def _rpr(spec: LayoutSpec, *, font: str, pt: float, bold: bool = False,
         color: str | None = None) -> str:
    out = (f'<w:rPr><w:rFonts w:ascii="{_esc(font)}" w:eastAsia="{_esc(font)}" '
           f'w:hAnsi="{_esc(font)}"/>')
    if bold:
        out += "<w:b/>"
    if color:
        out += f'<w:color w:val="{color}"/>'
    out += f'<w:sz w:val="{pt2half(pt)}"/><w:szCs w:val="{pt2half(pt)}"/></w:rPr>'
    return out


def _para(text: str, rpr: str, *, indent: bool = False, spacing_before: int = 0,
          align: str = "", border: bool = False, keep: bool = False,
          shade: str = "", big: bool = False) -> str:
    """段落1つ。

    `big` は「本文より大きい字」の印。紙面は行のグリッドに合わせて組んで
    いるが、**大きい字をグリッドに吸着させると隣の行に重なる**ので、
    見出しなどはグリッドから外す（Word の日本語の書式でも同じ扱い）。
    """
    ppr = "<w:pPr>"
    if keep:
        # 見出しは段や頁の切れ目で割らない。
        # 行送りを本文の高さに固定してあるので、本文より大きい見出しが
        # 段の終わりに掛かると隣の行に重なって出る（実機で確認済み）。
        # keepLines で段の頭へ送り、keepNext で本文と離れないようにする。
        ppr += "<w:keepNext/><w:keepLines/>"
    if border:
        # 縦書きでは「下の罫線」が見出しの左側に出る
        ppr += ('<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="2" '
                f'w:color="{INK_ACCENT}"/></w:pBdr>')
    if shade:
        ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
    if big:
        # スキーマの順番が決まっている。snapToGrid は spacing より前
        ppr += '<w:snapToGrid w:val="0"/>'
    if spacing_before:
        ppr += f'<w:spacing w:before="{spacing_before}"/>'
    if indent:
        ppr += '<w:ind w:firstLineChars="100" w:firstLine="210"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    ppr += "</w:pPr>"
    if not text:
        return f"<w:p>{ppr}</w:p>"
    return f"<w:p>{ppr}<w:r>{rpr}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r></w:p>"


def _image_para(rid: str, width_mm: float, height_mm: float, name: str, idx: int) -> str:
    """段の中に写真を1枚入れる。"""
    cx, cy = mm2emu(width_mm), mm2emu(height_mm)
    return (
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{idx}" name="{_esc(name)}"/>'
        f'<a:graphic><a:graphicData uri="{PIC}">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{idx}" name="{_esc(name)}"/>'
        '<pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline>'
        "</w:drawing></w:r></w:p>"
    )


# 原稿の中で「ここに写真を入れる」と書く目印。
# 写真そのものは入れず、**枠だけ空けておく**という運用のため
# （写真は印刷所や担当者が Word で差し込む）。
# 「写真展のお知らせ」のような、ふつうの文を目印と取り違えないよう、
# 括弧で囲むか、「写真：」「写真 」のように区切りが要る
PHOTO_MARK = re.compile(
    r"^\s*(?:[【\[（(]\s*写真\s*[】\]）)]|写真(?=\s*[:：]|[\s　]|$))"
    r"\s*[:：]?\s*(.*)$")


def photo_mark(line: str) -> str | None:
    """写真の目印の行なら、説明文（キャプション）を返す。違えば None。"""
    m = PHOTO_MARK.match(line or "")
    return (m.group(1) or "").strip() if m else None


def _photo_frame(spec: LayoutSpec, caption: str = "") -> tuple[str, float]:
    """写真の場所を空けておく枠。

    写真を実際に入れないので、**どこに何の写真が入るかが分かる空枠**を
    置く。印刷所や担当者は、この枠を選んで写真を差し込めばよい。
    枠の大きさは、写真を入れたときと同じにしてある。

    戻り値は (XML, 紙面の横方向に使う幅mm)。
    """
    h = spec.column_height_mm * spec.photo_height_ratio
    w = min(h * 4 / 3, spec.text_width_mm * 0.42)

    label = "写真" + (f"　{caption}" if caption else "")
    rpr = _rpr(spec, font=spec.heading_font, pt=spec.caption_pt,
               color=INK_ACCENT)
    borders = "".join(
        f'<w:{side} w:val="dashed" w:sz="8" w:space="0" w:color="{INK_ACCENT}"/>'
        for side in ("top", "left", "bottom", "right"))
    # 1つの升目だけの表を、写真の入る場所として置く
    return (
        '<w:tbl><w:tblPr>'
        f'<w:tblW w:w="{mm2twip(h)}" w:type="dxa"/><w:jc w:val="center"/>'
        f'<w:tblBorders>{borders}</w:tblBorders>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="F2FAFE"/>'
        '<w:tblLayout w:type="fixed"/></w:tblPr>'
        f'<w:tblGrid><w:gridCol w:w="{mm2twip(h)}"/></w:tblGrid>'
        f'<w:tr><w:trPr><w:trHeight w:val="{mm2twip(w)}" w:hRule="exact"/></w:trPr>'
        f'<w:tc><w:tcPr><w:tcW w:w="{mm2twip(h)}" w:type="dxa"/>'
        '<w:vAlign w:val="center"/></w:tcPr>'
        '<w:p><w:pPr><w:jc w:val="center"/>'
        f'<w:spacing w:line="{mm2twip(spec.caption_pt * MM_PER_PT * 1.4)}" '
        'w:lineRule="atLeast"/></w:pPr>'
        f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(label)}</w:t></w:r>'
        "</w:p></w:tc></w:tr></w:tbl>", w)


def _weave_photos(paras: list[str], weights: list[int],
                  blocks: list[list[str]]) -> list[str]:
    """記事の写真を、その記事の本文の中に散らして置く。

    まとめて末尾に置くと、長い記事では写真が本文から何段も離れ、
    ひどいときは次のページに出てしまう。**写真は、それが写っている
    話のそばに無いと意味がない**ので、本文の段落のあいだに挟む。

    置き場所は段落の数ではなく **字数** で決める。短い段落が続いても
    写真が前に寄らないようにするため。1枚なら本文の真ん中あたり、
    複数枚なら等間隔に。

    段落より写真が多いときは、挟む場所が足りないので、あふれるぶんを
    見出しの直後（本文の前）に回す。末尾にまとめて積むより、
    見出しのそばに1枚あるほうが紙面として読める。
    """
    if not blocks:
        return list(paras)
    if not paras:
        return [x for b in blocks for x in b]

    k, n = len(blocks), len(paras)
    # 段落のあいだは n か所（末尾を含む）。足りないぶんは本文の前に置く
    lead_count = max(0, k - n)
    lead_blocks, rest = blocks[:lead_count], blocks[lead_count:]

    total = sum(weights) or 1
    points: list[int] = []
    for i in range(len(rest)):
        want = total * (i + 1) / (len(rest) + 1)
        run = 0
        for j, w in enumerate(weights, 1):
            run += w
            if run >= want:
                points.append(j)
                break
        else:
            points.append(n)
    # 同じ切れ目に重ならないよう、後ろへずらす
    for i in range(1, len(points)):
        if points[i] <= points[i - 1]:
            points[i] = min(n, points[i - 1] + 1)

    out: list[str] = [x for b in lead_blocks for x in b]
    bi = 0
    for i, para in enumerate(paras, 1):
        out.append(para)
        while bi < len(rest) and points[bi] == i:
            out.extend(rest[bi])
            bi += 1
    out.extend(x for b in rest[bi:] for x in b)   # 置き切れなかったぶん
    return out


HEADER_PART = "word/header1.xml"
HEADER_RID = "rIdHeader"


def _header_xml(spec: LayoutSpec, issue: str, paper: str, date: str) -> str:
    """柱（ページの上に出る、号数・紙名・発行日・ページ番号）。

    印刷所に渡すものなので、どの号の何ページ目かが紙面から分かる必要が
    ある。実物の議会だよりもこの形。

    本文は縦書きだが、柱は横書き。ヘッダーは本文とは別の入れ物なので、
    ここだけ `lrTb`（横書き）にできる。
    """
    rpr = _rpr(spec, font=spec.heading_font, pt=9.0, color="404040")
    tab = int(mm2twip(spec.text_width_mm))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{W}" xmlns:r="{R}">'
        '<w:p><w:pPr>'
        '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="2" '
        f'w:color="{INK_ACCENT}"/></w:pBdr>'
        f'<w:tabs><w:tab w:val="center" w:pos="{tab // 2}"/>'
        f'<w:tab w:val="right" w:pos="{tab}"/></w:tabs>'
        '<w:textDirection w:val="lrTb"/>'
        '<w:spacing w:after="60"/></w:pPr>'
        f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(issue)}</w:t></w:r>'
        f'<w:r>{rpr}<w:tab/><w:t xml:space="preserve">{_esc(paper)}</w:t></w:r>'
        f'<w:r>{rpr}<w:tab/><w:t xml:space="preserve">{_esc(date)}　（</w:t></w:r>'
        f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r>{rpr}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r>{rpr}<w:t>1</w:t></w:r>'
        f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>'
        f'<w:r>{rpr}<w:t>）</w:t></w:r>'
        "</w:p></w:hdr>"
    )


def _page_break() -> str:
    """改ページ。区分の頭は必ずページの頭から始める。"""
    return ('<w:p><w:pPr><w:spacing w:line="20" w:lineRule="exact"/></w:pPr>'
            '<w:r><w:br w:type="page"/></w:r></w:p>')


def _section_head(name: str, rpr: str, spec: LayoutSpec) -> str:
    """区分の見出し（行政報告・一般質問…）。地色を敷いて目立たせる。"""
    return (
        '<w:p><w:pPr>'
        '<w:keepNext/><w:keepLines/>'
        '<w:snapToGrid w:val="0"/>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="{INK_BAND}"/>'
        f'<w:spacing w:before="{mm2twip(3)}"/>'
        '<w:jc w:val="center"/>'
        f'</w:pPr><w:r>{rpr}<w:t xml:space="preserve">　{_esc(name)}　</w:t></w:r></w:p>'
    )


def _table_block(rows: list[list[str]], spec: LayoutSpec,
                 title: str = "") -> tuple[str, int]:
    """賛否一覧表などを、紙面の幅いっぱいの表として組む。

    表は文章と違って**折り返せない**ので、5段の中には入らない。
    そこで、表のところだけ段組みを1段に切り替える
    （`w:sectPr` を段落に入れると、その段落までが1つの区間になる）。

    紙面は縦書きなので、表も紙面の向きに合わせて組まれる。
    見出しの行が右端に立ち、1件ぶんが1本の帯になって右から左へ並ぶ。
    縦書きの議会だよりの賛否一覧表は、この形で読める。

    戻り値は (XML, 使った行数の目安)。
    """
    if not rows:
        return "", 0
    n_cols = len(rows[0])
    pt = 9.0 if n_cols <= 10 else 8.0

    # 縦書きでは、表の「列幅」が紙面の縦方向（＝段の高さ）に伸びる。
    # 1列目（議案番号）と2列目（件名）は広く、賛否の欄は狭くてよい
    if n_cols >= 4:
        weights = [1.5, 3.2] + [1.0] * (n_cols - 3) + [1.3]
    else:
        weights = [1.0] * n_cols
    span_mm = spec.text_height_mm - 6          # 上下に少し余裕をもたせる
    span = mm2twip(span_mm)
    unit = span / sum(weights)
    widths = [max(240, int(unit * w)) for w in weights]
    # 列がとても多いと、最低の幅を足し合わせただけで紙面をはみ出す。
    # はみ出すと表が次のページへ流れ、白紙のページが出る。必ず収める
    if sum(widths) > span:
        scale = span / sum(widths)
        widths = [max(120, int(w * scale)) for w in widths]

    # 行の「高さ」は紙面の横方向の厚み。表が幅いっぱいになるよう割り当てる。
    # 見出しのぶんだけ控えておかないと、1行はみ出して次のページへ送られる。
    # 中身が入りきらないときは伸びてよいので atLeast
    avail = spec.text_width_mm - (spec.heading_pt * MM_PER_PT * 2.4 if title else 4)
    thick = int(mm2twip(avail) / max(1, len(rows)))

    body_rpr = _rpr(spec, font=spec.heading_font, pt=pt)
    head_rpr = _rpr(spec, font=spec.heading_font, pt=pt, bold=True,
                    color=INK_BAND_TEXT)
    cell_line = mm2twip(pt * MM_PER_PT * 1.3)

    trs = ""
    for i, row in enumerate(rows):
        cells = ""
        for j in range(n_cols):
            text = row[j] if j < len(row) else ""
            shd = (f'<w:shd w:val="clear" w:color="auto" w:fill="{INK_BAND}"/>'
                   if i == 0 else "")
            align = "left" if j <= 1 else "center"
            cells += (
                f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/>{shd}'
                '<w:vAlign w:val="center"/></w:tcPr>'
                f'<w:p><w:pPr><w:jc w:val="{align}"/>'
                f'<w:spacing w:line="{cell_line}" w:lineRule="atLeast" '
                'w:before="20" w:after="20"/></w:pPr>'
                f'<w:r>{head_rpr if i == 0 else body_rpr}'
                f'<w:t xml:space="preserve">{_esc(text)}</w:t></w:r></w:p></w:tc>')
        # 1行目は見出し。ページをまたぐときは毎ページ出す
        head = "<w:tblHeader/>" if i == 0 else ""
        trs += (f'<w:tr><w:trPr>{head}'
                f'<w:trHeight w:val="{thick}" w:hRule="atLeast"/>'
                f"</w:trPr>{cells}</w:tr>")

    borders = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="9AA3AE"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    tbl = (
        '<w:tbl><w:tblPr>'
        f'<w:tblW w:w="{sum(widths)}" w:type="dxa"/><w:jc w:val="center"/>'
        f'<w:tblBorders>{borders}</w:tblBorders>'
        '<w:tblLayout w:type="fixed"/></w:tblPr>'
        f'<w:tblGrid>{grid}</w:tblGrid>{trs}</w:tbl>')

    # 段組みを 1段に切り替えて表を置き、そのあと5段に戻す。
    # 見出しも同じ区間に入れる（別の区間に置くと、表と離れてしまう）
    line_mm = spec.body_pt * MM_PER_PT * spec.line_spacing
    head = ""
    if title:
        head = _para(title, _rpr(spec, font=spec.heading_font, pt=spec.heading_pt,
                                 bold=True, color=INK_ACCENT),
                     border=True, keep=True, big=True)
    # 段組みを切り替える段落そのものは、場所を取らせない。
    # 表がページいっぱいのとき、この段落だけで次のページができてしまう
    tiny = '<w:spacing w:line="20" w:lineRule="exact" w:before="0" w:after="0"/>'
    xml = (f'<w:p><w:pPr>{tiny}{_sect_pr(spec, continuous=True)}</w:pPr></w:p>'
           + head + tbl
           + f'<w:p><w:pPr>{tiny}'
           f'{_sect_pr(spec, columns=1, continuous=True)}</w:pPr></w:p>')
    lines = int(-(-spec.text_width_mm // line_mm)) * spec.columns
    return xml, lines


def _sect_pr(spec: LayoutSpec, *, columns: int = 0, continuous: bool = False) -> str:
    """紙面の決まりごと。ここが 1ページ5段縦書きを決めている。"""
    char_twip = mm2twip(spec.body_pt * MM_PER_PT)
    line_twip = mm2twip(spec.body_pt * MM_PER_PT * spec.line_spacing)
    cols = columns or spec.columns
    return (
        "<w:sectPr>"
        + f'<w:headerReference w:type="default" r:id="{HEADER_RID}"/>'
        + ('<w:type w:val="continuous"/>' if continuous else "")
        + f'<w:pgSz w:w="{mm2twip(spec.page_width_mm)}" w:h="{mm2twip(spec.page_height_mm)}"/>'
        f'<w:pgMar w:top="{mm2twip(spec.margin_top_mm)}" '
        f'w:right="{mm2twip(spec.margin_right_mm)}" '
        f'w:bottom="{mm2twip(spec.margin_bottom_mm)}" '
        f'w:left="{mm2twip(spec.margin_left_mm)}" '
        'w:header="425" w:footer="425" w:gutter="0"/>'
        f'<w:cols w:num="{cols}" w:space="{mm2twip(spec.column_gap_mm)}"/>'
        '<w:textDirection w:val="tbRl"/>'
        f'<w:docGrid w:type="linesAndChars" w:linePitch="{line_twip}" '
        f'w:charSpace="{char_twip}"/>'
        "</w:sectPr>"
    )


# ====================================================================== 組み立て


@dataclass
class ComposeResult:
    path: Path
    pages_estimated: int
    chars_total: int
    photos: int
    warnings: list[str] = field(default_factory=list)
    lines_used: int = 0
    lines_per_page: int = 0

    def to_dict(self) -> dict:
        return {
            "docx": str(self.path),
            "pages": self.pages_estimated,
            "chars": self.chars_total,
            "photos": self.photos,
            "warnings": self.warnings,
            "lines_used": self.lines_used,
            "lines_per_page": self.lines_per_page,
        }


def compose(project, spec: LayoutSpec | None = None, filename: str = "") -> ComposeResult:
    """記事と写真から、5段縦書きの Word を組み立てる。

    段送りと改ページは Word が行うので、分量が増えればページが増える。
    """
    spec = spec or LayoutSpec.from_dict(project.data.get("layout"))
    m = spec.metrics()

    body: list[str] = []
    media: dict[str, bytes] = {}
    rels: list[str] = []
    warnings: list[str] = []
    chars_total = 0
    photo_count = 0
    # 何行使うかを数える。段落の終わりは行の途中で終わるので、
    # 字数の合計ではなく「行数」で数えないとページ数が合わない。
    lines_used = 0
    cpl = m["chars_per_line"]
    line_mm = spec.body_pt * MM_PER_PT * spec.line_spacing

    body_rpr = _rpr(spec, font=spec.body_font, pt=spec.body_pt)
    head_rpr = _rpr(spec, font=spec.heading_font, pt=spec.heading_pt, bold=True,
                    color=INK_ACCENT)
    lead_rpr = _rpr(spec, font=spec.heading_font, pt=spec.body_pt + 0.5, bold=True)
    name_rpr = _rpr(spec, font=spec.heading_font, pt=spec.body_pt)
    cap_rpr = _rpr(spec, font=spec.heading_font, pt=spec.caption_pt, color="444444")

    # 題字（号数・発行日）
    title = project.data.get("title") or "議会だより"
    parts: list[str] = []
    for x in (title, project.data.get("issue_no"), project.data.get("issue_date")):
        # 「第204号」が題名と号数の両方に入っていることがあるので重ねない
        if x and not any(x in q or q in x for q in parts):
            parts.append(x)
    head_line = "　".join(parts)
    body.append(_para(head_line, _rpr(spec, font=spec.heading_font,
                                      pt=spec.heading_pt + 2, bold=True,
                                      color=INK_ACCENT), border=True, big=True))
    body.append(_para("", body_rpr))

    # 構成（表紙 → 行政報告 → … → 最終ページ）の順に組む
    from . import sections as sec

    groups = sec.group_articles(project.sections, project.articles())
    if not any(g["articles"] for g in groups):
        warnings.append("記事がありません。原稿を取り込んでから組んでください。")

    sec_rpr = _rpr(spec, font=spec.heading_font, pt=spec.heading_pt + 1,
                   bold=True, color=INK_BAND_TEXT)

    # 区分の頭でページを送るため、1ページの行数を先に求めておく
    lines_per_page = max(1, m["lines_per_column"] * spec.columns)

    first_group = True
    # 表のあとは段組みが1段から5段に戻るところでページが変わる。
    # そこへさらに改ページを足すと、白紙のページができてしまう
    after_table = False

    for group in groups:
        arts = group["articles"]
        if not arts:
            continue          # 「特集」など、その号に無い区分は飛ばす

        # 区分の見出し（表紙は題字があるので付けない）
        if group["id"] != "cover":
            # 実物の議会だよりは、区分の頭で必ずページが変わる。
            # 途中から始まると、どこからどの区分か分からなくなる
            if not first_group and not after_table:
                body.append(_page_break())
                lines_used = -(-lines_used // lines_per_page) * lines_per_page
            body.append(_section_head(group["name"], sec_rpr, spec))
            lines_used += 3
        first_group = False

        for art in arts:
            # 表だけの記事（賛否一覧表など）は、見出しも表と同じ区間に置く。
            # 別々にすると、見出しが5段の中に残って表と離れてしまう
            table_only = bool(getattr(art, "table", None)) and not art.body.strip()
            if art.title and not table_only:
                body.append(_para(art.title, head_rpr, spacing_before=240,
                                  border=True, keep=True, big=True))
                # 見出しは本文より大きいので、その分だけ行を余分に使う。
                # さらに、段の途中に掛かる見出しは丸ごと次の段へ送られる
                # （keepLines）ので、その空きを見出しの高さの半分として見込む
                # ＝写真の段またぎと同じ考え方。実測10通りで確かめてある。
                head_lines = max(1, int(
                    -(-count_chars(art.title) * spec.heading_pt // (cpl * spec.body_pt))))
                lines_used += head_lines * 2 + 1 + head_lines // 2
            # 執筆者名は、日本語の名前のときだけ出す。
            # パソコンのユーザー名が紙面に印刷されたことがあるため
            from .importers import looks_like_a_person

            if art.author and looks_like_a_person(art.author):
                body.append(_para(art.author, name_rpr, align="right", keep=True))
                lines_used += 1
            if art.lead:
                body.append(_para(art.lead, lead_rpr))
                lines_used += max(1, -(-count_chars(art.lead) // cpl))

            # 本文の段落を先に作っておく。写真をこの中に挟み込むため。
            paras: list[str] = []
            weights: list[int] = []
            for line in art.body.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # 「【写真】議場のようす」のような行は、写真の場所を空ける
                cap = photo_mark(line)
                if cap is not None:
                    frame, fw = _photo_frame(spec, cap)
                    paras.append(frame)
                    weights.append(0)
                    # 枠は行が並ぶ方向に幅のぶん場所を取る。
                    # 段をまたげないので、段の変わり目に半端な空きもできる
                    fl = max(1, int(-(-fw // line_mm)))
                    lines_used += fl + fl // 2 + 1
                    continue
                n = count_chars(line)
                chars_total += n
                lines_used += max(1, -(-n // cpl))
                # 実物は「質問」の段落に薄い水色の下地が敷いてある
                tint = INK_TINT if line.startswith(("質問", "問", "再質問")) else ""
                paras.append(_para(line, body_rpr, indent=spec.indent_first,
                                   shade=tint))
                weights.append(n)

            # この記事の写真。1枚ぶんを「写真＋説明文＋撮影者」でひとまとめにする
            blocks: list[list[str]] = []
            for pid in art.photos:
                photo = project.get_photo(pid)
                if not photo:
                    continue
                src = project.photos_dir / photo.file
                if not src.exists():
                    continue
                data, w_mm, h_mm, note = _fit_photo(src.read_bytes(), spec)
                if note:
                    warnings.append(f"{photo.info.get('name', photo.file)}: {note}")
                photo_count += 1
                idx = photo_count
                ext = ".jpg" if HAS_PIL else Path(photo.file).suffix.lower() or ".jpg"
                media_name = f"photo{idx}{ext}"
                media[f"word/media/{media_name}"] = data
                rid = f"rIdImg{idx}"
                rels.append(
                    f'<Relationship Id="{rid}" Type="{R}/image" Target="media/{media_name}"/>'
                )
                block = [_image_para(rid, w_mm, h_mm, media_name, 1000 + idx)]
                # 写真は、行が並ぶ方向にその幅のぶんだけ場所を取る。
                # さらに、写真は段をまたげないので、段の変わり目で
                # 手前に空きができる。平均すると写真1枚の半分ぶん。
                photo_lines = max(1, int(-(-w_mm // line_mm)))
                lines_used += photo_lines + photo_lines // 2 + 1
                if photo.caption:
                    block.append(_para(photo.caption, cap_rpr, align="center"))
                    chars_total += count_chars(photo.caption)
                    lines_used += max(1, -(-count_chars(photo.caption) // cpl))
                if photo.credit:
                    block.append(_para(f"（撮影: {photo.credit}）", cap_rpr, align="center"))
                    lines_used += 1
                blocks.append(block)

            body.extend(_weave_photos(paras, weights, blocks))

            # 表（賛否一覧表など）。段組みを1段に切り替えて紙面いっぱいに組む
            has_table = bool(getattr(art, "table", None))
            after_table = has_table
            if has_table:
                xml, used = _table_block(art.table, spec,
                                         art.title if table_only else "")
                if xml:
                    body.append(xml)
                    lines_used += used

            # 表の直後は空段落を置かない。表がページいっぱいのとき、
            # この1行だけで白紙のページができてしまう
            if not has_table:
                body.append(_para("", body_rpr))
            # 記事の切れ目では、段の変わり目に半端な空きができる。
            # 実際の刷り上がりと突き合わせて求めた補正。
            lines_used += 7

    # ---- 書き出し
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" '
        f'xmlns:a="{A}" xmlns:pic="{PIC}">'
        f'<w:body>{"".join(body)}{_sect_pr(spec)}</w:body></w:document>'
    )

    out_name = filename or f"{title}_自動組版.docx"
    if not out_name.lower().endswith(".docx"):
        out_name += ".docx"
    project.output_dir.mkdir(parents=True, exist_ok=True)
    out = project.output_dir / out_name

    # 柱（ページの上の帯）。印刷所に渡すので、どの号の何ページ目かを出す
    issue = project.data.get("issue_no") or title
    if issue and not issue.startswith("第") and issue.isdigit():
        issue = f"第{issue}号"
    header = _header_xml(spec, issue, "日高村議会だより",
                         project.data.get("issue_date") or "")
    _write_docx(out, doc, _styles_xml(spec), media, rels, header)

    pages = max(1, -(-lines_used // lines_per_page))

    return ComposeResult(out, pages, chars_total, photo_count, warnings,
                         lines_used=lines_used, lines_per_page=lines_per_page)


def _fit_photo(data: bytes, spec: LayoutSpec) -> tuple[bytes, float, float, str]:
    """写真を段に収まる大きさにする。戻り値は (データ, 幅mm, 高さmm, 注意)。"""
    note = ""
    ratio = aspect_of(data) if HAS_PIL else 4 / 3
    # 縦書きでは、写真の「高さ」が段の高さに収まらなければならない
    max_h = spec.column_height_mm * spec.photo_height_ratio
    max_w = spec.text_width_mm * 0.42
    h = max_h
    w = h * ratio
    if w > max_w:
        w = max_w
        h = w / ratio
    if HAS_PIL:
        try:
            # 紙面に置く大きさで 350dpi 相当まで縮めて、ファイルを軽くする
            px = int(w / 25.4 * 350)
            data = crop_to_ratio(data, ratio, max_px=max(600, px))
        except Exception as e:  # pragma: no cover
            note = f"加工できませんでした（{e}）"
    return data, round(w, 1), round(h, 1), note


def _styles_xml(spec: LayoutSpec) -> str:
    line_twip = mm2twip(spec.body_pt * MM_PER_PT * spec.line_spacing)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
        f'<w:rFonts w:ascii="{_esc(spec.body_font)}" w:eastAsia="{_esc(spec.body_font)}" '
        f'w:hAnsi="{_esc(spec.body_font)}"/>'
        f'<w:sz w:val="{pt2half(spec.body_pt)}"/>'
        f'<w:szCs w:val="{pt2half(spec.body_pt)}"/>'
        "</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>"
        # 行送りは「これ以上」にする。**exact にしてはいけない。**
        # exact だと、本文より大きい字（見出し・区分の帯）が行の高さに
        # 収まらず、隣の行に重なって印刷される。LibreOffice は大目に
        # 見てくれるが Word は重ねる。実際の刷り上がりで重なった
        f'<w:spacing w:line="{line_twip}" w:lineRule="atLeast" w:after="0"/>'
        '<w:jc w:val="both"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults></w:styles>"
    )


def _write_docx(out: Path, doc_xml: str, styles_xml: str,
                media: dict[str, bytes], rels: list[str],
                header_xml: str = "") -> None:
    exts = {Path(n).suffix.lstrip(".").lower() for n in media}
    defaults = "".join(
        f'<Default Extension="{e}" ContentType="image/{"jpeg" if e in ("jpg", "jpeg") else e}"/>'
        for e in sorted(exts)
    )
    ct = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f"{defaults}"
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.styles+xml"/>'
        + (f'<Override PartName="/{HEADER_PART}" ContentType="application/vnd.'
           'openxmlformats-officedocument.wordprocessingml.header+xml"/>'
           if header_xml else "")
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rIdDoc" Type="{R}/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>'
        + (f'<Relationship Id="{HEADER_RID}" Type="{R}/header" '
           f'Target="{Path(HEADER_PART).name}"/>' if header_xml else "")
        + f'{"".join(rels)}</Relationships>'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", doc_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        if header_xml:
            z.writestr(HEADER_PART, header_xml)
        for name, blob in media.items():
            z.writestr(name, blob)
