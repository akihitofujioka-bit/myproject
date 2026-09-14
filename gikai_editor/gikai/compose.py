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

# 表紙の色も第203号の実物から採った
COVER_CREAM = "FFF1D0"     # 題字の下に敷いてあるクリーム色の地
COVER_BLUE = "005BAB"      # 題字の「ひだか」の青
COVER_INK = "231F20"       # 題字の黒
COVER_RED = "ED1C24"       # 目次の「特集」の赤

# 発行元は号によらず決まっている（第203号の表紙のとおり）。
# 変わったときはここだけ直せばよい
PUBLISHER = ("発行：高知県日高村議会　編集：議会広報発行調査特別委員会　"
             "日高村本郷61-1 〒781-2194 ☎0889-24-7777")
PAPER_NAME = "ひだか議会だより"

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


# 縦書きの中で横に並べる（縦中横）かたまり。半角の数字・英字が続くところ。
TATECHUYOKO = re.compile(r"[0-9A-Za-z]+")
TATECHUYOKO_MAX = 3        # 実物の議会だよりは3文字まで。4文字以上は寝かせる


def _runs(text: str, rpr: str) -> str:
    """字を並べる。半角の数字・英字は縦中横にする。

    縦書きでは、半角の数字や英字は既定で**横に寝てしまう**。実物の
    議会だよりは、3文字までの数字を「縦中横」にして、1文字ぶんの升目に
    横並びのまま収めている（「第204号」「1件」など）。4文字以上を
    縦中横にすると升目からはみ出して読めなくなるので、そこは寝かせる。

    `w:eastAsianLayout w:vert` が縦中横の指定。`w:vertCompress` は
    升目に収まらないときに詰める指定。**LibreOffice はこれを読まない**
    ので、こちらのプレビューでは寝たままに見える。Word では立つ。
    """
    if not text:
        return ""
    out, pos = [], 0
    for m in TATECHUYOKO.finditer(text):
        if len(m.group(0)) > TATECHUYOKO_MAX:
            continue
        if m.start() > pos:
            out.append(f'<w:r>{rpr}<w:t xml:space="preserve">'
                       f"{_esc(text[pos:m.start()])}</w:t></w:r>")
        # 同じ文書の中で id が重ならないようにする
        _runs.seq = getattr(_runs, "seq", 0) + 1
        tcy_tag = (f'<w:eastAsianLayout w:id="{_runs.seq}" w:vert="1" '
                   'w:vertCompress="1"/>')
        # 空の rPr（`<w:rPr/>`）で来ることもあるので、両方に対応する。
        # 取りこぼすと、その字だけ縦中横にならず横に寝てしまう
        if rpr.endswith("</w:rPr>"):
            tcy = rpr[:-len("</w:rPr>")] + tcy_tag + "</w:rPr>"
        elif rpr.endswith("/>"):
            tcy = rpr[:-2] + ">" + tcy_tag + "</w:rPr>"
        else:
            tcy = f"<w:rPr>{tcy_tag}</w:rPr>"
        out.append(f'<w:r>{tcy}<w:t xml:space="preserve">'
                   f"{_esc(m.group(0))}</w:t></w:r>")
        pos = m.end()
    if pos < len(text):
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">'
                   f"{_esc(text[pos:])}</w:t></w:r>")
    return "".join(out)


def _para(text: str, rpr: str, *, indent: bool = False, spacing_before: int = 0,
          align: str = "", border: bool = False, keep: bool = False,
          shade: str = "", big: bool = False, runs: str = "") -> str:
    """段落1つ。

    `big` は「本文より大きい字」の印。紙面は行のグリッドに合わせて組んで
    いるが、**大きい字をグリッドに吸着させると隣の行に重なる**ので、
    見出しなどはグリッドから外す（Word の日本語の書式でも同じ扱い）。

    `runs` を渡すと `text` の代わりにそれを字として使う。
    「質問」の頭だけ色を変えるなど、1つの段落を何色かで組むときに使う。
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
    inner = runs or _runs(text, rpr)
    if not inner:
        return f"<w:p>{ppr}</w:p>"
    return f"<w:p>{ppr}{inner}</w:p>"


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
        f"{_runs(label, rpr)}"
        "</w:p></w:tc></w:tr></w:tbl>", w)


WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _hz_para(text: str, rpr: str, *, align: str = "left", runs: str = "",
             before: int = 0, shade: str = "") -> str:
    """テキストボックスの中に入れる、横書きの1行。

    テキストボックスの中は横書きなので、縦中横（`_runs`）は要らない。
    """
    inner = runs or (f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'
                     if text else "")
    shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>' if shade else ""
    # 行送りは決め打ちしない。字の大きさに合わせて Word/LibreOffice に
    # 決めさせる（`w:line` を入れると行が重なることがあった）
    return (f'<w:p><w:pPr>{shd}<w:snapToGrid w:val="0"/>'
            f'<w:spacing w:before="{before}" w:after="0" w:line="240" '
            'w:lineRule="auto"/>'
            f'<w:jc w:val="{align}"/></w:pPr>{inner}</w:p>')


def _textbox(inner: str, w_mm: float, h_mm: float, idx: int, *,
             fill: str = "", name: str = "hako", vertical: bool = False,
             anchor: str = "t", pad_mm: float = 0.0) -> str:
    """横組みのテキストボックスを、本文の流れの中に置く。

    **これが縦組みの紙面に横組みを混ぜる、ただ一つの確かな方法。**

    ほかに2つやり方があるが、どちらも使えない:

      * 区間ごとに `w:textDirection` を切り替える → LibreOffice は文書の
        最初の向きを全ページに当ててしまい、Word とこちらのプレビューで
        見え方が食い違う。
      * 紙のふちからの寸法で図形を置く（`wp:anchor`）→ 縦組みの紙面では
        座標の軸が90度回るので、どちらのソフトでも同じになる保証がない。

    テキストボックスの中身は素直な横組みなので、座標も向きの指定も
    要らない。本文の流れに乗せる（`wp:inline`）ので、記事が動けば
    見出しも一緒に動く。
    """
    cx, cy = mm2emu(w_mm), mm2emu(h_mm)
    fill_xml = (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>'
                if fill else "<a:noFill/>")
    return (
        '<w:r><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{idx}" name="{name}{idx}"/><wp:cNvGraphicFramePr/>'
        f'<a:graphic><a:graphicData uri="{WPS}">'
        f'<wps:wsp xmlns:wps="{WPS}"><wps:cNvSpPr txBox="1"/>'
        f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'{fill_xml}<a:ln><a:noFill/></a:ln></wps:spPr>'
        f'<wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx>'
        # `wrap` は square のまま、`a:normAutofit` も付けない。
        # どちらを使っても**最後の1字が前の字に重ねて置かれた**
        # （実機で確認済み）。箱を字数より広めに取って収める
        f'<wps:bodyPr vert="{"eaVert" if vertical else "horz"}" '
        f'wrap="square" lIns="{mm2emu(pad_mm)}" tIns="0" '
        f'rIns="{mm2emu(pad_mm)}" bIns="0" anchor="{anchor}"/>'
        '</wps:wsp></a:graphicData></a:graphic></wp:inline>'
        "</w:drawing></w:r>"
    )


def _frame_row(cells: list[tuple[str, float]], h_mm: float, rpr: str) -> str:
    """写真の入る場所を空けておく、点線の枠を横に並べた1行。

    写真は入れない運用なので、**どこに何の写真が入るかが分かる空枠**を
    置く。印刷所や担当者は、この枠を選んで写真を差し込めばよい。
    """
    borders = "".join(
        f'<w:{s} w:val="dashed" w:sz="8" w:space="0" w:color="{INK_ACCENT}"/>'
        for s in ("top", "left", "bottom", "right"))
    tcs = ""
    for label, w in cells:
        tcs += (f'<w:tc><w:tcPr><w:tcW w:w="{mm2twip(w)}" w:type="dxa"/>'
                f'<w:tcBorders>{borders}</w:tcBorders>'
                '<w:shd w:val="clear" w:color="auto" w:fill="F2FAFE"/>'
                '<w:vAlign w:val="center"/></w:tcPr>'
                + _hz_para(label, rpr, align="center") + "</w:tc>")
    grid = "".join(f'<w:gridCol w:w="{mm2twip(w)}"/>' for _, w in cells)
    total = sum(mm2twip(w) for _, w in cells)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{total}" w:type="dxa"/>'
            '<w:tblLayout w:type="fixed"/></w:tblPr>'
            f'<w:tblGrid>{grid}</w:tblGrid>'
            f'<w:tr><w:trPr><w:trHeight w:val="{mm2twip(h_mm)}" '
            f'w:hRule="exact"/></w:trPr>{tcs}</w:tr></w:tbl>')


def _cover_page(spec: LayoutSpec, project, arts: list) -> str:
    """表紙。ほかのページと違い、まるごと横組みの1ページ。

    紙面いっぱいのテキストボックスを1つ置いて、その中を上から順に
    組む。座標を使わないので、本文の量や余白の設定が変わっても崩れない。

    写真は入れず**枠だけ**空ける。表紙フォルダの原稿はこう読む:

      * 「【写真】議場のようす」の行 → 写真枠の説明。1つ目が上の大きな枠、
        2つ目から下の小さな枠3つ
      * それ以外の行 → 目次（「特集　◯◯……15P」のように書く）

    題字と発行元は号によらず決まっているので、原稿には書かなくてよい。
    割りつけは第203号の表紙を測って決めた。
    """
    caps: list[str] = []
    toc: list[str] = []
    for art in arts:
        for line in (art.title + "\n" + art.body).split("\n"):
            line = line.strip()
            if not line:
                continue
            cap = photo_mark(line)
            if cap is not None:
                caps.append(cap)
            else:
                toc.append(line)

    def rpr(pt, color, bold=True, font=None):
        return _rpr(spec, font=font or spec.heading_font, pt=pt, bold=bold,
                    color=color)

    def label(i: int) -> str:
        return "写真" + (f"　{caps[i]}" if i < len(caps) and caps[i] else "")

    # 箱の中に置く表は、箱より**少しだけ狭く**する。同じ幅にすると
    # 表が入り切らず、中の字が早く折り返して行どうしが重なった
    # （実機で確認済み）
    box_w = spec.text_width_mm
    w = box_w - 3
    frame_rpr = rpr(9.0, INK_ACCENT)
    gap = 2.0
    small_w = (w - gap * 2) / 3

    out = [
        # 上の大きな写真枠
        _frame_row([(label(0), w)], 108, frame_rpr),
        _hz_para("", frame_rpr, before=mm2twip(gap)),
        # 下の小さな写真枠3つ
        _frame_row([(label(1), small_w), (label(2), small_w),
                    (label(3), small_w)], 48, frame_rpr),
    ]
    # 写真の説明（実物では小さい写真の下に1行入っている）
    if caps:
        out.append(_hz_para(caps[0], rpr(9.0, "333333", bold=False,
                                         font=spec.body_font), align="center"))

    # ここから下はクリーム色の地。題字・目次・発行元をまとめて載せる
    cream: list[str] = []
    cream.append(_hz_para(
        "", frame_rpr, align="left", before=mm2twip(4),
        runs=(f'<w:r>{rpr(36, COVER_BLUE)}<w:t>ひだか</w:t></w:r>'
              f'<w:r>{rpr(36, COVER_INK)}<w:t>議会だより</w:t></w:r>')))
    # 号数が別に入っていなければ、号の名前をそのまま使う
    issue = project.data.get("issue_no") or project.data.get("title") or ""
    date = project.data.get("issue_date") or ""
    cream.append(_hz_para(f"{issue}　{date}".strip("　"), rpr(13, COVER_INK),
                          align="right"))
    for line in toc[:6]:
        if line.startswith("特集"):
            # 行頭の「特集」だけ赤くする（実物がこの形）
            runs = (f'<w:r>{rpr(11, COVER_RED)}<w:t>特集</w:t></w:r>'
                    f'<w:r>{rpr(11, COVER_INK)}'
                    f'<w:t xml:space="preserve">{_esc(line[2:])}</w:t></w:r>')
            cream.append(_hz_para("", frame_rpr, align="center", runs=runs,
                                  before=mm2twip(1.5)))
        else:
            cream.append(_hz_para(line, rpr(11, COVER_INK), align="center",
                                  before=mm2twip(1.5)))
    cream.append(_hz_para(PUBLISHER,
                          rpr(8.5, COVER_INK, bold=False, font=spec.body_font),
                          align="center", before=mm2twip(5)))
    # クリーム色の地は「表のセル」にする。テキストボックスの中に
    # テキストボックスは入れられない（Word も LibreOffice も描かない）
    out.append(
        f'<w:tbl><w:tblPr><w:tblW w:w="{mm2twip(w)}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/></w:tblPr>'
        f'<w:tblGrid><w:gridCol w:w="{mm2twip(w)}"/></w:tblGrid>'
        f'<w:tr><w:trPr><w:trHeight w:val="{mm2twip(100)}" w:hRule="exact"/>'
        f'</w:trPr><w:tc><w:tcPr><w:tcW w:w="{mm2twip(w)}" w:type="dxa"/>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="{COVER_CREAM}"/>'
        f'</w:tcPr>{"".join(cream)}</w:tc></w:tr></w:tbl>')

    # 紙面いっぱいの箱を1つ。中は上から順に流れるので、座標は要らない。
    #
    # ただし**表紙だけは1段の区間に入れる**。ふだんの5段のままだと、
    # 箱の高さ（紙面いっぱい＝約270mm）が1段の高さ（約49mm）を超えて
    # しまい、箱の中の行が重なって刷られる（実機で確認済み）。
    # 1段にすれば段の高さが紙面の高さになり、箱がまるごと収まる。
    box = _textbox("".join(out), box_w, spec.text_height_mm - 2, 98,
                   name="hyoushi")
    tiny = '<w:spacing w:line="20" w:lineRule="exact" w:before="0" w:after="0"/>'
    return (f'<w:p><w:pPr>{tiny}'
            f'{_sect_pr(spec, continuous=True, no_header=True)}</w:pPr></w:p>'
            f'<w:p><w:pPr>{tiny}<w:snapToGrid w:val="0"/></w:pPr>{box}</w:p>'
            f'<w:p><w:pPr>{tiny}'
            f'{_sect_pr(spec, columns=1, continuous=True, no_header=True)}'
            '</w:pPr></w:p>')



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
# 表紙には柱を出さない（実物の表紙にも無い）。1ページ目だけ差し替えるため
# 「空の柱」を用意して、`w:titlePg` で1ページ目に当てる
COVER_HEADER_PART = "word/header2.xml"
COVER_HEADER_RID = "rIdHeaderCover"


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


# 「質問」「答弁」の頭。区切り（全角空き・空白・コロン）が続くときだけ
# 目印と見なす。これが無いと「問題は…」「答申を…」まで拾ってしまう
QUESTION_MARK = re.compile(r"^(再?質問|質疑|再?問)(?=[　\s:：])[　\s:：]*(.*)$")
ANSWER_MARK = re.compile(r"^(再?答弁|答)(?=[　\s:：])[　\s:：]*(.*)$")


def qa_kind(line: str) -> str:
    """本文の1行が「質問」か「答弁」か。どちらでもなければ空。"""
    if QUESTION_MARK.match(line or ""):
        return "q"
    if ANSWER_MARK.match(line or ""):
        return "a"
    return ""


def _qa_para(line: str, spec: LayoutSpec, body_rpr: str, *,
             indent: bool) -> str:
    """本文の1行。「質問」なら薄い水色の下地、「答弁」なら白地。

    実物の議会だよりは、質問の段落だけに下地を敷き、答弁は白いまま
    にして、目で追えるようにしてある。頭の「質問」「答弁」も濃い青の
    太字で、本文とはっきり分けてある。
    """
    kind = qa_kind(line)
    if not kind:
        return _para(line, body_rpr, indent=indent)
    m = (QUESTION_MARK if kind == "q" else ANSWER_MARK).match(line)
    label, rest = m.group(1), m.group(2)
    label_rpr = _rpr(spec, font=spec.heading_font, pt=spec.body_pt, bold=True,
                     color=INK_ACCENT if kind == "q" else INK_BAND_TEXT)
    runs = _runs(f"{label}　", label_rpr) + _runs(rest, body_rpr)
    # 下地は質問だけ。答弁に敷くと紙面がぜんぶ水色になって効かなくなる
    return _para("", body_rpr, shade=INK_TINT if kind == "q" else "",
                 runs=runs)


# 見出しの向きの指定。原稿の見出しの行の頭に書く。
# 実物の議会だよりは、一般質問のように横書きの見出しと、特集のように
# 縦書きの見出しが混ざっている。どちらにするかは事務局が原稿で決める
HEADING_DIR = re.compile(r"^\s*[【\[（(]\s*(横|縦)\s*[】\]）)]\s*(.*)$")


def heading_dir(title: str) -> tuple[str, str]:
    """見出しの行から向きの指定を外す。戻り値は (向き, 見出し)。

    向きは "yoko"（横書き）／"tate"（縦書き）／""（指定なし）。
    """
    m = HEADING_DIR.match(title or "")
    if not m:
        return "", (title or "").strip()
    return ("yoko" if m.group(1) == "横" else "tate"), m.group(2).strip()


def _heading_box(title: str, spec: LayoutSpec, idx: int) -> tuple[str, float]:
    """横書きの見出し（青い帯）。縦組みの紙面に横組みで載せる。

    テキストボックスの向きは中身ごとに決まるので、紙面が縦組みでも
    ここだけ横書きになる。本文の流れの中に置く（`wp:inline`）ので、
    記事が動けば見出しも一緒に動く。

    箱の大きさの取り方に注意。縦組みの紙面では

      * 箱の**幅**は紙面の横方向（行が並ぶ方向）に伸びる。紙面の幅まで
        取れる。段の高さで頭打ちにはならない
      * 箱の**高さ**は段の高さ（＝縦組みの1行の長さ）までに収める

    戻り値は (XML, 紙面の横方向に使う厚みmm)。
    """
    pt = spec.heading_pt
    n = max(1, count_chars(title))
    pad = 3.0
    # 字が入る長さに合わせる。紙面の幅は超えない。
    # 1割5分ほど余分に見ておく。書体が入っていないパソコンでは代わりの
    # 書体が使われ、字幅が広くなって折り返してしまうため
    w = min(spec.text_width_mm, n * pt * MM_PER_PT * 1.25 + pad * 2)
    # それでも折り返したときに行が重ならないよう、2行ぶんの高さを取る
    h = min(spec.column_height_mm, pt * MM_PER_PT * 2.8)
    rpr = _rpr(spec, font=spec.heading_font, pt=pt, bold=True, color="FFFFFF")
    # 見出しの最後に空き1字を足す。テキストボックスの中では、
    # **いちばん最後の1字が1つ前の字に重ねて置かれる**ことがあった
    # （実機で確認済み）。最後を空きにしておけば、重なっても見えない
    box = _textbox(_hz_para(f"{title}　", rpr, align="left"), w, h, idx,
                   fill=INK_ACCENT, name="midashi", anchor="ctr", pad_mm=pad)
    xml = ('<w:p><w:pPr><w:keepNext/><w:keepLines/><w:snapToGrid w:val="0"/>'
           f'<w:spacing w:before="{mm2twip(2)}"/></w:pPr>{box}</w:p>')
    # 帯は横方向に w だけ場所を取るが、高さは段の一部しか使わない。
    # 段の高さに対する割合で、使う行数を見積もる
    return xml, w * min(1.0, h / spec.column_height_mm)


def _section_tab(name: str, spec: LayoutSpec, idx: int) -> str:
    """紙面の右端に立てる、区分の名前の帯（見出しタブ）。

    実物の議会だよりは、ページの右の端に区分名の帯があり、めくった
    ときにどこを開いたかが分かるようになっている。

    区分の中身より先に置くと、縦組みの流れの頭＝**紙面の右端**に
    出る。紙のふちからの寸法で置く手（`w:framePr`）もあるが、縦組みの
    紙面では座標の軸が90度回るので、どちらのソフトでも同じになる保証が
    ない。流れに乗せるほうが確かで、区分が何ページ続いても、ページの
    頭ごとに置けばそのページの右端に出る。
    """
    rpr = _rpr(spec, font=spec.heading_font, pt=spec.body_pt + 1.5, bold=True,
               color=INK_BAND_TEXT)
    w = 9.5
    h = min(115.0, spec.text_height_mm * 0.45)
    inner = _hz_para(name, rpr, align="center")
    box = _textbox(inner, w, h, idx, fill=INK_BAND, name="tab",
                   vertical=True, anchor="ctr")
    return ('<w:p><w:pPr><w:keepNext/><w:snapToGrid w:val="0"/>'
            f'<w:spacing w:before="0" w:after="0"/></w:pPr>{box}</w:p>')


def _page_break() -> str:
    """改ページ。区分の頭と、一般質問の議員ごとの頭で使う。

    `<w:br w:type="page"/>` ではなく `<w:pageBreakBefore/>` を使う。
    前者は、ページが変わった直後にもう一度使うと読み飛ばされることが
    あった（一般質問で議員が3人続くと、2人目と3人目が同じページに
    出た）。`pageBreakBefore` は「この段落からページを変える」という
    指定なので、続けて使っても確実に効く。
    """
    return ('<w:p><w:pPr><w:pageBreakBefore/>'
            '<w:spacing w:line="20" w:lineRule="exact"/></w:pPr></w:p>')


def _section_head(name: str, spec: LayoutSpec) -> str:
    """区分の見出し（行政報告・一般質問…）。地色を敷いて目立たせる。

    実物は紙面の幅いっぱいの横組みの帯だが、それをそのままやると
    帯が紙面の横方向をぜんぶ使ってしまい、本文が帯の下に回り込めず
    ページがすかすかになる（実機で確認済み）。縦組みの流れに素直に
    乗せた縦の帯にしてある。区分が分かればよいので、これで足りる。
    """
    rpr = _rpr(spec, font=spec.heading_font, pt=spec.heading_pt + 1,
               bold=True, color=INK_BAND_TEXT)
    return (
        '<w:p><w:pPr>'
        '<w:keepNext/><w:keepLines/>'
        '<w:snapToGrid w:val="0"/>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="{INK_BAND}"/>'
        f'<w:spacing w:before="{mm2twip(3)}"/>'
        '<w:jc w:val="center"/>'
        f"</w:pPr>{_runs(f'　{name}　', rpr)}</w:p>"
    )


def _table_block(rows: list[list[str]], spec: LayoutSpec,
                 title: str = "") -> tuple[str, int]:
    """賛否一覧表などを、実物と同じ向きの表として組む。

    表は文章と違って**折り返せない**ので、5段の中には入らない。
    そこで、表のところだけ段組みを1段に切り替える
    （`w:sectPr` を段落に入れると、その段落までが1つの区間になる）。

    向きについて（ここが分かりにくいので詳しく書く）:

    紙面が縦書きなので、表も紙面の流れに乗って **90度倒れて**組まれる。
    エクセルの「行」は紙面では右から左へ並ぶ帯になり、「列」は上から下へ
    並ぶ。そのまま出すと、実物（議案が上から下、議員名が左から右）とは
    向きが逆になる。事務局から「実物と向きが逆」と指摘されたのがこれ。

    そこで **転置して、行の順を反転してから**組む。こうすると倒れた分が
    打ち消されて、実物と同じ

        議案番号 | 件名 | 議員名… | 議決結果
        議案第1号 |  …  |   ○ …   |   可決

    の向きになる。`w:textDirection` を表のところだけ横書きに戻す手も
    あるが、**LibreOffice はこの指定を読まない**ので、こちらの
    プレビューと Word とで見え方が食い違ってしまう。転置なら、どちらの
    ソフトでも同じ向きに出る。

    戻り値は (XML, 使った行数の目安)。
    """
    if not rows:
        return "", 0
    n_src_cols = max(len(r) for r in rows)
    src = [list(r) + [""] * (n_src_cols - len(r)) for r in rows]
    # 転置して反転（＝紙面で倒れる分を先に打ち消しておく）
    laid = [list(col) for col in zip(*src)][::-1]
    n_cols = len(laid[0])          # ＝エクセルの行数（議案の件数＋見出し）
    n_rows = len(laid)             # ＝エクセルの列数（議案番号・件名・議員名…）
    # 組んだ表の「列幅」は紙面の縦方向に伸びる＝エクセルの1行ぶんの高さ。
    # 見出しの行は中身が短いので少し薄くてよい
    span_mm = spec.text_height_mm - 6          # 上下に少し余裕をもたせる
    col_w = [0.7 if i == 0 else 1.0 for i in range(n_cols)]
    unit_mm = span_mm / sum(col_w)
    widths_mm = [max(6.0, unit_mm * w) for w in col_w]
    # 件数がとても多いと、最低の幅を足し合わせただけで紙面をはみ出す。
    # はみ出すと表が次のページへ流れ、白紙のページが出る。必ず収める
    if sum(widths_mm) > span_mm:
        scale = span_mm / sum(widths_mm)
        widths_mm = [max(4.0, w * scale) for w in widths_mm]
    widths = [mm2twip(w) for w in widths_mm]

    # 見出しと罫線のぶんを控えておく。控えが足りないと、いちばん端の
    # 1列がはみ出して次のページへ流れ、そこだけの半端なページができる
    avail = spec.text_width_mm - (26.0 if title else 10.0)

    def plan(pt: float) -> list[float]:
        """字の大きさを決めたときの、1列ぶんの厚み（mm）を数える。

        組んだ表の「行の高さ」は紙面の横方向の厚み＝エクセルの1列ぶんの
        幅にあたる。決め打ちの割合で配ると、件名のように長い字の列が
        入り切らずに切れて消えたり、逆に広がって紙からはみ出したりする
        （どちらも実機で起きた）。**中身の字数から必要な厚みを数える**。
        """
        char_mm = pt * MM_PER_PT
        line_mm = char_mm * 1.35
        out: list[float] = []
        for row in laid:
            need = 1
            for j, text in enumerate(row):
                # 1行に入る字数は、その升目の「列幅」（紙面の縦）で決まる
                per_line = max(1, int((widths_mm[j] - 1.6) / char_mm))
                need = max(need, -(-count_chars(text) // per_line))
            out.append(need * line_mm + 1.6)
        return out

    # 入り切らなければ字を小さくする。それでも駄目なら比で詰める
    pt = 9.0 if n_src_cols <= 12 else 8.0
    thicks_mm = plan(pt)
    while sum(thicks_mm) > avail and pt > 6.0:
        pt -= 0.5
        thicks_mm = plan(pt)
    # 紙面の幅いっぱいに広げる（実物の賛否表も幅いっぱい）。
    # はみ出すときは詰め、余るときは伸ばす
    scale = avail / sum(thicks_mm)
    thicks_mm = [w * scale for w in thicks_mm]
    thicks = [mm2twip(w) for w in thicks_mm]

    body_rpr = _rpr(spec, font=spec.heading_font, pt=pt)
    head_rpr = _rpr(spec, font=spec.heading_font, pt=pt, bold=True,
                    color=INK_BAND_TEXT)
    cell_line = mm2twip(pt * MM_PER_PT * 1.3)

    trs = ""
    for i, row in enumerate(laid):
        # 反転してあるので、この帯がエクセルの何列目だったか
        src_col = n_rows - 1 - i
        cells = ""
        for j in range(n_cols):
            text = row[j] if j < len(row) else ""
            # 見出しはエクセルの1行目＝組んだ表の1列目（紙面では一番上の段）
            shd = (f'<w:shd w:val="clear" w:color="auto" w:fill="{INK_BAND}"/>'
                   if j == 0 else "")
            # 議案番号と件名は行頭ぞろえ、賛否の欄は中央ぞろえ
            align = "left" if src_col <= 1 and j > 0 else "center"
            cells += (
                f'<w:tc><w:tcPr><w:tcW w:w="{widths[j]}" w:type="dxa"/>{shd}'
                '<w:vAlign w:val="center"/></w:tcPr>'
                # 升目の中はグリッドから外す。外さないと、本文（10.5pt）
                # 向きのグリッドに9ptの字が1マスずつ吸着して、計算より
                # ずっと太り、1行に入る字数が半分になって字が切れる
                # スキーマの順番は snapToGrid → spacing → jc。
                # 逆にすると Word がファイルを開けない
                f'<w:p><w:pPr><w:snapToGrid w:val="0"/>'
                f'<w:spacing w:line="{cell_line}" w:lineRule="atLeast" '
                'w:before="20" w:after="20"/>'
                f'<w:jc w:val="{align}"/></w:pPr>'
                f'{_runs(text, head_rpr if j == 0 else body_rpr)}</w:p></w:tc>')
        # 厚みは「これ以上」（atLeast）。決め打ちにすると、件名のような
        # 長い字が入り切らずに**切れて消える**。紙からはみ出すほうが、
        # 気づけるぶんまだよい。そのぶん下の `avail` を控えめに取る
        trs += (f'<w:tr><w:trPr>'
                f'<w:trHeight w:val="{thicks[i]}" w:hRule="atLeast"/>'
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
    # 表の区間は**次のページから**始める。同じページの途中から始めると、
    # そのページの残りの幅しか使えず、表が2ページに割れる（実機で確認済み）。
    # 表のあとは、同じページの続きから5段に戻す
    xml = (f'<w:p><w:pPr>{tiny}{_sect_pr(spec)}</w:pPr></w:p>'
           + head + tbl
           + f'<w:p><w:pPr>{tiny}'
           f'{_sect_pr(spec, columns=1, continuous=True)}</w:pPr></w:p>')
    lines = int(-(-spec.text_width_mm // line_mm)) * spec.columns
    return xml, lines


def _sect_pr(spec: LayoutSpec, *, columns: int = 0, continuous: bool = False,
             no_header: bool = False) -> str:
    """紙面の決まりごと。ここが 1ページ5段縦書きを決めている。"""
    char_twip = mm2twip(spec.body_pt * MM_PER_PT)
    line_twip = mm2twip(spec.body_pt * MM_PER_PT * spec.line_spacing)
    cols = columns or spec.columns
    return (
        "<w:sectPr>"
        # 表紙の区間だけ空の柱を当てる。`w:titlePg` は区間ごとに
        # 効いてしまい、区分が変わるたびにそのページの柱が消えた
        + f'<w:headerReference w:type="default" r:id="'
        + (COVER_HEADER_RID if no_header else HEADER_RID) + '"/>'
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

    title = project.data.get("title") or "議会だより"

    # 構成（表紙 → 行政報告 → … → 最終ページ）の順に組む
    from . import sections as sec

    groups = sec.group_articles(project.sections, project.articles())
    if not any(g["articles"] for g in groups):
        warnings.append("記事がありません。原稿を取り込んでから組んでください。")

    # 区分の頭でページを送るため、1ページの行数を先に求めておく
    lines_per_page = max(1, m["lines_per_column"] * spec.columns)

    first_group = True
    tab_no = 0            # 右端の帯の通し番号（図形の番号は重ねられない）
    # すでにページが変わったところでは、改ページを足してはいけない。
    # 足すと白紙のページができる。表のあと（段組みが1段から5段に戻る
    # ところ）と、紙面いっぱいの表紙のあとが、これに当たる
    page_changed = False

    for group in groups:
        arts = group["articles"]
        if not arts:
            continue          # 「特集」など、その号に無い区分は飛ばす

        # 表紙は、ほかのページとまったく別の組み方（全部横組み）。
        # 原稿から目次と写真枠の説明だけを取って、あとは決まった形に組む
        if group["id"] == "cover":
            body.append(_cover_page(spec, project, arts))
            lines_used += lines_per_page
            first_group = False
            # 表紙の箱が紙面いっぱいなので、次の中身はひとりでに次の
            # ページへ行く。ここで改ページを足すと白紙のページができる
            page_changed = True
            continue

        # 実物の議会だよりは、区分の頭で必ずページが変わる。
        # 途中から始まると、どこからどの区分か分からなくなる
        if not first_group and not page_changed:
            body.append(_page_break())
            lines_used = -(-lines_used // lines_per_page) * lines_per_page
        # 区分の頭のページには帯を出す。右端のタブは、区分が次の
        # ページへ続くときだけ出す（帯のとなりに同じ物を2つ並べない）
        body.append(_section_head(group["name"], spec))
        lines_used += 3
        first_group = False

        # 一般質問は議員ごとに1ページ。実物がこの形で、誰の質問が
        # どこまでかが紙面から分かる
        one_per_page = group["id"] == "ippan" and len(arts) > 1

        for i, art in enumerate(arts):
            if one_per_page and i:
                body.append(_page_break())
                lines_used = -(-lines_used // lines_per_page) * lines_per_page
                tab_no += 1
                body.append(_section_tab(group["name"], spec, 1900 + tab_no))
            # 表だけの記事（賛否一覧表など）は、見出しも表と同じ区間に置く。
            # 別々にすると、見出しが5段の中に残って表と離れてしまう
            table_only = bool(getattr(art, "table", None)) and not art.body.strip()
            # 見出しの向きは原稿で決める（「【横】憲法9条を守る」のように書く）
            direction, art_title = heading_dir(art.title)
            if art_title and not table_only:
                if direction == "yoko":
                    photo_count += 1        # 図形の番号は写真と通し番号にする
                    xml, hw = _heading_box(art_title, spec, 2000 + photo_count)
                    body.append(xml)
                    # 横書きの見出しは、行が並ぶ方向にその高さのぶん場所を取る
                    lines_used += max(1, int(-(-hw // line_mm))) + 1
                else:
                    body.append(_para(art_title, head_rpr, spacing_before=240,
                                      border=True, keep=True, big=True))
                    # 見出しは本文より大きいので、その分だけ行を余分に使う。
                    # さらに、段の途中に掛かる見出しは丸ごと次の段へ送られる
                    # （keepLines）ので、その空きを見出しの高さの半分として
                    # 見込む＝写真の段またぎと同じ考え方。実測で確かめてある。
                    head_lines = max(1, int(
                        -(-count_chars(art_title) * spec.heading_pt
                          // (cpl * spec.body_pt))))
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
                # 実物は「質問」の段落に薄い水色の下地が敷いてあり、
                # 「答弁」は白地。頭の語も濃い青の太字で分けてある
                paras.append(_qa_para(line, spec, body_rpr,
                                      indent=spec.indent_first))
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
            page_changed = has_table
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
        f'xmlns:wps="{WPS}" '
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
    # 表紙には柱を出さない。空の柱を1ページ目に当てる
    blank_header = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<w:hdr xmlns:w="{W}" xmlns:r="{R}">'
                    '<w:p><w:pPr><w:spacing w:line="20" w:lineRule="exact" '
                    'w:after="0"/></w:pPr></w:p></w:hdr>')
    _write_docx(out, doc, _styles_xml(spec), media, rels, header, blank_header)

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
                header_xml: str = "", cover_header_xml: str = "") -> None:
    """.docx を書き出す。

    柱（ヘッダー）は、入れ物・関係・種類の3か所すべてに書かないと
    Word がファイルを開けない。1つでも抜けると「内容に問題があります」
    になる。表紙用の空の柱も同じ。
    """
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
        + "".join(
            f'<Override PartName="/{part}" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            for part, xml in ((HEADER_PART, header_xml),
                              (COVER_HEADER_PART, cover_header_xml)) if xml)
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
        + "".join(
            f'<Relationship Id="{rid}" Type="{R}/header" '
            f'Target="{Path(part).name}"/>'
            for rid, part, xml in ((HEADER_RID, HEADER_PART, header_xml),
                                   (COVER_HEADER_RID, COVER_HEADER_PART,
                                    cover_header_xml)) if xml)
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
        if cover_header_xml:
            z.writestr(COVER_HEADER_PART, cover_header_xml)
        for name, blob in media.items():
            z.writestr(name, blob)
