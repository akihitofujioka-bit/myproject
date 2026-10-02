"""Word（.docx）の書き出し（設計図 §10）。

## 作りの考え方

- ページは**横書きの普通のページ**のまま。縦書きにするのは枠の中身だけ
  （`wps:bodyPr vert="eaVert"`）。区間を縦書きにすると座標の軸が 90 度回り、
  紙のふちからの寸法で置いた枠の位置が読めなくなる（gikai_editor `compose._textbox`）
- 部品は**すべて紙のふちからの寸法で置いた枠**（`wp:anchor`、`relativeFrom="page"`）。
  ページごとに改ページし、枠は そのページの段落にだけつなぎ留める。
  あるページの中身が変わっても、ほかのページの枠は動かない
- 本文の改行はこちらで決めて `w:br` で入れる（`grid.split_lines`）。Word に折り返させない
- 追加の部品は使わない。zip と文字列だけで組む

## 落とし穴（既存ツールで踏んだもの）

- 枠に `wrap="none"` や `a:normAutofit` を付けると、最後の 1 字が前の字に重なることがあった
  （gikai_editor）。`wrap="square"` にして、枠を字数ぶんより少し長くとる（`SLACK_PT`）
- 行送りを `exact` にすると、行送りより大きな字が隣の行に重なる。枠ごとに字の大きさが
  1 つなので、本ツールでは字の大きさに合った行送りを枠ごとに付ける
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from grid import Box, Geometry, mm2pt

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"

MINCHO = "ＭＳ 明朝"
GOTHIC = "ＭＳ ゴシック"

EMU_PER_PT = 12700
# 枠を 1 行の長さより少し長くとる。ちょうどにすると Word が最後の字を次の行へ送る
SLACK_PT = 2.0


def emu(pt: float) -> int:
    return int(round(pt * EMU_PER_PT))


def twip(pt: float) -> int:
    return int(round(pt * 20))


# ---------------------------------------------------------------- 部品の中身


@dataclass
class TextBox:
    """縦書きの文字の枠。lines は 1 行ずつ（改行はこちらで入れる）。"""
    box: Box
    lines: list[str]
    font: str = MINCHO
    pt: float = 11.0
    pitch_pt: float = 17.0            # 行送り
    border: bool = False              # 囲み
    center: bool = False              # 枠の中で行のかたまりを左右の真ん中に
    name: str = "text"


@dataclass
class Placeholder:
    """写真などの入る場所を示す点線の枠（中は横書きの説明）。"""
    box: Box
    label: str
    name: str = "photo"


@dataclass
class Guide:
    """確かめるための薄い線の枠（段の輪郭など）。印刷物には出さない。"""
    box: Box
    name: str = "guide"


@dataclass
class Page:
    items: list = field(default_factory=list)


# ---------------------------------------------------------------- XML


def _rpr(font: str, pt: float) -> str:
    f = escape(font, {'"': "&quot;"})
    return (f'<w:rPr><w:rFonts w:ascii="{f}" w:eastAsia="{f}" w:hAnsi="{f}"/>'
            f'<w:sz w:val="{round(pt * 2)}"/><w:szCs w:val="{round(pt * 2)}"/></w:rPr>')


def _text_para(t: TextBox) -> str:
    rpr = _rpr(t.font, t.pt)
    runs = []
    for i, line in enumerate(t.lines):
        if i:
            runs.append(f"<w:r>{rpr}<w:br/></w:r>")
        if line:
            runs.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>')
    # 縦書きの枠では「行送り」が左右の間隔になる。字の大きさより小さくしない
    pitch = max(t.pitch_pt, t.pt)
    return ('<w:p><w:pPr><w:snapToGrid w:val="0"/>'
            f'<w:spacing w:before="0" w:after="0" w:line="{twip(pitch)}" w:lineRule="exact"/>'
            '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
            '<w:jc w:val="left"/></w:pPr>'
            f'{"".join(runs)}{"" if runs else f"<w:r>{rpr}</w:r>"}</w:p>')


def _anchor(idx: int, box: Box, graphic: str, *, behind: bool = False, name: str = "") -> str:
    return (
        '<w:r><w:drawing>'
        f'<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="{idx + 2}" behindDoc="{1 if behind else 0}" locked="1" '
        'layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{emu(box.x)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{emu(box.y)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{emu(box.w)}" cy="{emu(box.h)}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{idx}" name="{escape(name or "box")}{idx}"/><wp:cNvGraphicFramePr/>'
        f'<a:graphic><a:graphicData uri="{WPS}">{graphic}</a:graphicData></a:graphic>'
        '</wp:anchor></w:drawing></w:r>'
    )


def _shape(box: Box, *, line: str, inner: str = "", body: str = "", fill: str = "") -> str:
    fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
    txbx = f"<wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx>" if inner else ""
    # f 文字列の式の中に \ は書けない（Python 3.11 まで）ので外で作る
    cnv = '<wps:cNvSpPr txBox="1"/>' if inner else "<wps:cNvSpPr/>"
    return (
        f'<wps:wsp>{cnv}'
        f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{emu(box.w)}" cy="{emu(box.h)}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill_xml}{line}</wps:spPr>'
        f'{txbx}{body or "<wps:bodyPr/>"}</wps:wsp>'
    )


def _item_xml(item, idx: int) -> str:
    if isinstance(item, TextBox):
        # 枠は 1 行の長さ（＝高さ）を少し長くとる。上の端は動かさない
        box = Box(item.box.x, item.box.y, item.box.w, item.box.h + SLACK_PT)
        line = ('<a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
                if item.border else "<a:ln><a:noFill/></a:ln>")
        body = ('<wps:bodyPr rot="0" vert="eaVert" wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" '
                f'anchor="{"ctr" if item.center else "t"}" anchorCtr="0"><a:noAutofit/></wps:bodyPr>')
        return _anchor(idx, box, _shape(box, line=line, inner=_text_para(item), body=body), name=item.name)
    if isinstance(item, Placeholder):
        line = ('<a:ln w="9525"><a:solidFill><a:srgbClr val="1E88E5"/></a:solidFill>'
                '<a:prstDash val="dash"/></a:ln>')
        rpr = _rpr(GOTHIC, 9)
        inner = (f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                 f'<w:r>{rpr}<w:t xml:space="preserve">{escape(item.label)}</w:t></w:r></w:p>')
        body = '<wps:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"><a:noAutofit/></wps:bodyPr>'
        return _anchor(idx, item.box, _shape(item.box, line=line, inner=inner, body=body, fill="F2FAFE"),
                       name=item.name)
    if isinstance(item, Guide):
        line = '<a:ln w="3175"><a:solidFill><a:srgbClr val="C8C8C8"/></a:solidFill></a:ln>'
        return _anchor(idx, item.box, _shape(item.box, line=line), behind=True, name=item.name)
    raise TypeError(item)


def document_xml(g: Geometry, pages: list[Page]) -> str:
    body = []
    idx = 1
    for n, page in enumerate(pages):
        runs = []
        for item in page.items:
            runs.append(_item_xml(item, idx))
            idx += 1
        # 枠をつなぎ留める段落。2 ページ目からは pageBreakBefore で必ずページを変える
        # （`w:br type="page"` は続けて使うと読み飛ばされることがあった。gikai_editor）
        ppr = ('<w:pPr>' + ('<w:pageBreakBefore/>' if n else '')
               + '<w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr>')
        body.append(f'<w:p>{ppr}{"".join(runs)}</w:p>')
    pw, ph = twip(mm2pt(g.page_w_mm)), twip(mm2pt(g.page_h_mm))
    sect = (f'<w:sectPr><w:pgSz w:w="{pw}" w:h="{ph}"/>'
            f'<w:pgMar w:top="{twip(mm2pt(g.margin_top_mm))}" w:right="{twip(mm2pt(g.margin_right_mm))}" '
            f'w:bottom="{twip(mm2pt(g.margin_bottom_mm))}" w:left="{twip(mm2pt(g.margin_left_mm))}" '
            'w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:wps="{WPS}">'
            f'<w:body>{"".join(body)}{sect}</w:body></w:document>')


def styles_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault>{_rpr(MINCHO, 11)}</w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="0"/></w:pPr></w:pPrDefault>'
            '</w:docDefaults></w:styles>')


def write_docx(path: Path, g: Geometry, pages: list[Page]) -> Path:
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.styles+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 f'<Relationship Id="rIdDoc" Type="{R}/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/></Relationships>')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document_xml(g, pages))
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return path
