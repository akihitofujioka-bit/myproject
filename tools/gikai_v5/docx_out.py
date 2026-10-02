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

import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from grid import TATECHUYOKO, Box, Geometry, mm2pt

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

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
class Picture:
    """画像と、その下に付ける横書きの説明。box 全体の中へ収める。"""
    box: Box
    data: bytes
    ext: str
    caption: str = ""
    name: str = "photo"

    def __post_init__(self) -> None:
        if self.ext.lower() not in ("png", "jpeg"):
            raise ValueError("画像の拡張子は png または jpeg にしてください")


@dataclass
class Page:
    items: list = field(default_factory=list)


# ---------------------------------------------------------------- XML


def _rpr(font: str, pt: float) -> str:
    f = escape(font, {'"': "&quot;"})
    return (f'<w:rPr><w:rFonts w:ascii="{f}" w:eastAsia="{f}" w:hAnsi="{f}"/>'
            f'<w:sz w:val="{round(pt * 2)}"/><w:szCs w:val="{round(pt * 2)}"/></w:rPr>')


def _line_runs(line: str, font: str, pt: float, ids: list[int]) -> list[str]:
    """1 行を run に分ける。2〜3 桁の半角数字は縦中横の run にする。

    縦中横（`w:eastAsianLayout w:combine="1"`）は文書の中で一意の id が要る（gikai_template §11）。
    """
    rpr = _rpr(font, pt)
    out, pos = [], 0
    for m in TATECHUYOKO.finditer(line):
        if m.start() > pos:
            out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line[pos:m.start()])}</w:t></w:r>')
        ids[0] += 1
        tcy = rpr.replace("</w:rPr>", f'<w:eastAsianLayout w:id="{ids[0]}" w:combine="1"/></w:rPr>')
        out.append(f"<w:r>{tcy}<w:t>{m.group(0)}</w:t></w:r>")
        pos = m.end()
    if pos < len(line):
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line[pos:])}</w:t></w:r>')
    return out


def _text_para(t: TextBox, ids: list[int]) -> str:
    rpr = _rpr(t.font, t.pt)
    runs = []
    for i, line in enumerate(t.lines):
        if i:
            runs.append(f"<w:r>{rpr}<w:br/></w:r>")
        runs.extend(_line_runs(line, t.font, t.pt, ids))
    # 縦書きの枠では「行送り」が左右の間隔になる。字の大きさより小さくしない
    pitch = max(t.pitch_pt, t.pt)
    # autoSpaceDE/DN: 日本語と英字・数字のあいだに Word が自動で入れるすき間を止める。
    # 入れられると行が計算より長くなり、最後の字が次の行へ送られる（段階 1 で確認）
    return ('<w:p><w:pPr><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/><w:snapToGrid w:val="0"/>'
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


def image_size(data: bytes, ext: str) -> tuple[int, int]:
    """PNG の IHDR または JPEG の SOFn から画素数を読む。"""
    ext = ext.lower()
    if ext == "png":
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("PNG のヘッダーを読めません")
        return struct.unpack(">II", data[16:24])
    if ext not in ("jpg", "jpeg") or len(data) < 4 or data[:2] != b"\xff\xd8":
        raise ValueError("JPEG のヘッダーを読めません")
    pos = 2
    sof = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(data):
            break
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > len(data):
            break
        if marker in sof and length >= 7:
            height, width = struct.unpack(">HH", data[pos + 3:pos + 7])
            if width and height:
                return width, height
        pos += length
    raise ValueError("JPEG の SOF ヘッダーを読めません")


def _picture_xml(item: Picture, idx: int, rel_id: str) -> tuple[str, int]:
    """画像を上寄せ・左右中央に置き、必要なら下端へ説明枠を置く。"""
    px_w, px_h = image_size(item.data, item.ext)
    caption_h = 12.0 if item.caption else 0.0
    available_h = max(0.0, item.box.h - caption_h)
    scale = min(item.box.w / px_w, available_h / px_h)
    width, height = px_w * scale, px_h * scale
    image_box = Box(item.box.x + (item.box.w - width) / 2, item.box.y, width, height)
    graphic = (
        '<pic:pic><pic:nvPicPr>'
        f'<pic:cNvPr id="{idx}" name="{escape(item.name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{emu(width)}" cy="{emu(height)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:ln><a:noFill/></a:ln></pic:spPr></pic:pic>')
    out = [_anchor(idx, image_box, graphic, name=item.name).replace(WPS, PIC, 1)]
    used = 1
    if item.caption:
        caption_box = Box(item.box.x, item.box.y + item.box.h - caption_h, item.box.w, caption_h)
        rpr = _rpr(GOTHIC, 8)
        inner = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr>'
                 f'<w:r>{rpr}<w:t xml:space="preserve">{escape(item.caption)}</w:t></w:r></w:p>')
        body = '<wps:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"><a:noAutofit/></wps:bodyPr>'
        line = '<a:ln><a:noFill/></a:ln>'
        out.append(_anchor(idx + 1, caption_box, _shape(caption_box, line=line, inner=inner, body=body),
                           name=item.name + "_caption"))
        used += 1
    return "".join(out), used


def _item_xml(item, idx: int, ids: list[int], rel_id: str = "") -> tuple[str, int]:
    if isinstance(item, TextBox):
        # 枠は 1 行の長さ（＝高さ）を少し長くとる。上の端は動かさない
        box = Box(item.box.x, item.box.y, item.box.w, item.box.h + SLACK_PT)
        line = ('<a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
                if item.border else "<a:ln><a:noFill/></a:ln>")
        body = ('<wps:bodyPr rot="0" vert="eaVert" wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" '
                f'anchor="{"ctr" if item.center else "t"}" anchorCtr="0"><a:noAutofit/></wps:bodyPr>')
        return _anchor(idx, box, _shape(box, line=line, inner=_text_para(item, ids), body=body), name=item.name), 1
    if isinstance(item, Placeholder):
        line = ('<a:ln w="9525"><a:solidFill><a:srgbClr val="1E88E5"/></a:solidFill>'
                '<a:prstDash val="dash"/></a:ln>')
        rpr = _rpr(GOTHIC, 9)
        inner = (f'<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                 f'<w:r>{rpr}<w:t xml:space="preserve">{escape(item.label)}</w:t></w:r></w:p>')
        body = '<wps:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"><a:noAutofit/></wps:bodyPr>'
        return (_anchor(idx, item.box, _shape(item.box, line=line, inner=inner, body=body, fill="F2FAFE"),
                        name=item.name), 1)
    if isinstance(item, Guide):
        line = '<a:ln w="3175"><a:solidFill><a:srgbClr val="C8C8C8"/></a:solidFill></a:ln>'
        return _anchor(idx, item.box, _shape(item.box, line=line), behind=True, name=item.name), 1
    if isinstance(item, Picture):
        return _picture_xml(item, idx, rel_id)
    raise TypeError(item)


def document_xml(g: Geometry, pages: list[Page]) -> str:
    body = []
    idx = 1
    picture_idx = 0
    ids = [0]          # 縦中横の通し番号
    for n, page in enumerate(pages):
        runs = []
        for item in page.items:
            if isinstance(item, Picture):
                picture_idx += 1
            rel_id = f"rIdImage{picture_idx}" if isinstance(item, Picture) else ""
            xml, used = _item_xml(item, idx, ids, rel_id)
            runs.append(xml)
            idx += used
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
    pic_ns = f' xmlns:pic="{PIC}"' if picture_idx else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:wps="{WPS}"{pic_ns}>'
            f'<w:body>{"".join(body)}{sect}</w:body></w:document>')


def styles_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault>{_rpr(MINCHO, 11)}</w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="0"/></w:pPr></w:pPrDefault>'
            '</w:docDefaults></w:styles>')


def write_docx(path: Path, g: Geometry, pages: list[Page]) -> Path:
    pictures = [item for page in pages for item in page.items if isinstance(item, Picture)]
    extensions = {("jpeg" if p.ext.lower() in ("jpg", "jpeg") else "png") for p in pictures}
    defaults = "".join(f'<Default Extension="{ext}" ContentType="image/{ext}"/>'
                       for ext in sorted(extensions))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          f'{defaults}'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.document.main+xml"/>'
          '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.styles+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 f'<Relationship Id="rIdDoc" Type="{R}/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    image_rels = "".join(f'<Relationship Id="rIdImage{n}" Type="{R}/image" Target="media/image{n}.{("jpeg" if p.ext.lower() in ("jpg", "jpeg") else "png")}"/>'
                         for n, p in enumerate(pictures, 1))
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>{image_rels}</Relationships>')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document_xml(g, pages))
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for n, picture in enumerate(pictures, 1):
            ext = "jpeg" if picture.ext.lower() in ("jpg", "jpeg") else "png"
            z.writestr(f"word/media/image{n}.{ext}", picture.data)
    return path
