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
- 行送りはすべて `atLeast` にする。Windows の Word は `exact` だと、行からはみ出した
  字の部分を切り落とすため、字の大きさの 1.4 倍以上になる前提で枠寸法を決める
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
GYOSHO = "HGP行書体"

EMU_PER_PT = 12700
# 枠を 1 行の長さより少し長くとる。ちょうどにすると Word が最後の字を次の行へ送る
# 2pt では、役場の Windows の Word で 12 字目の下の端が切れた（画面表示で字の位置が
# わずかにずれるため。2026-10-08 確認）。段の間は 26pt あるので半字ぶんとる
SLACK_PT = 6.0


def emu(pt: float) -> int:
    return int(round(pt * EMU_PER_PT))


def twip(pt: float) -> int:
    return int(round(pt * 20))


# ---------------------------------------------------------------- 部品の中身


@dataclass
class TextBox:
    """文字の枠。lines は 1 行ずつ（改行はこちらで入れる）。"""
    box: Box
    lines: list[str]
    font: str = MINCHO
    pt: float = 11.0
    pitch_pt: float = 17.0            # 行送り
    border: bool = False              # 囲み
    center: bool = False              # 枠の中で行のかたまりを左右の真ん中に
    name: str = "text"
    vertical: bool = True             # 偽なら横書き
    align: str = "左"                 # 横書きの左・中央・右
    bold: bool = False                # 太字
    # 行ごとの (文字, 書体) の並び。None の行は font を使う。
    # 行分けそのものは lines が正で、書体を変えても字数計算には影響させない。
    line_runs: list[list[tuple[str, str]]] | None = None
    shape: str = "rect"               # 囲みの形。rect（四角）か ellipse（楕円）
    # 行ごとの字の色（"0070C0" のような 16 進）。None の行は黒。
    line_colors: list | None = None


@dataclass
class Table:
    """ページに固定する横書きの表。列幅は pt、rows は行ごとの文字。"""
    box: Box
    column_widths: list[float]
    rows: list[list[str]]
    pt: float = 8.0
    font: str = MINCHO
    border: bool = True
    name: str = "table"
    cell_pts: object = None             # 行×列の字の大きさ。無ければ pt
    vertical_cells: object = None       # 縦書きにするセル (行, 列) の集まり
    row_heights: object = None          # 行ごとの最低の高さ(pt)。None の行は Word に任せる
    col_spans: object = None            # {(行, 列): 列数} 右の列とつなぐセル
    v_merge: object = None              # {(行, 列): "restart" か "continue"} 下の行とつなぐセル
    diagonal_cells: object = None       # {(行, 列): (右上の字, 左下の字)} 左上から右下へ斜めの線を引くセル


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


def _rpr(font: str, pt: float, bold: bool = False, color: str | None = None) -> str:
    f = escape(font, {'"': "&quot;"})
    return (f'<w:rPr><w:rFonts w:ascii="{f}" w:eastAsia="{f}" w:hAnsi="{f}"/>'
            f'{"<w:b/>" if bold else ""}'
            f'{f"<w:color w:val={chr(34)}{color}{chr(34)}/>" if color else ""}'
            f'<w:sz w:val="{round(pt * 2)}"/><w:szCs w:val="{round(pt * 2)}"/></w:rPr>')


def _line_runs(line: str, font: str, pt: float, ids: list[int], *,
               vertical: bool = True, bold: bool = False, color: str | None = None) -> list[str]:
    """1 行を run に分ける。2〜3 桁の半角数字は縦中横の run にする。

    縦中横は `w:eastAsianLayout w:vert="1" w:vertCompress="1"`（Word の「拡張書式→縦中横」で
    「行内に収める」）。`w:combine="1"` は割注（2 行に分けて小さく詰める）なので使わない。
    文書の中で一意の id が要る（gikai_template §11）。
    """
    rpr = _rpr(font, pt, bold, color)
    if not vertical:
        return [f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line)}</w:t></w:r>']
    out, pos = [], 0
    for m in TATECHUYOKO.finditer(line):
        if m.start() > pos:
            out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line[pos:m.start()])}</w:t></w:r>')
        ids[0] += 1
        tcy = rpr.replace("</w:rPr>", f'<w:eastAsianLayout w:id="{ids[0]}" w:vert="1" w:vertCompress="1"/></w:rPr>')
        out.append(f"<w:r>{tcy}<w:t>{m.group(0)}</w:t></w:r>")
        pos = m.end()
    if pos < len(line):
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(line[pos:])}</w:t></w:r>')
    return out


# Windows の Word は「最小値」だと、おおむね字の大きさの 1.4 倍まで行を広げる。
# 文字枠はこの実効行送りで収まるように作る。
AT_LEAST_RATIO = 1.4


def effective_pitch(pt: float, pitch: float) -> float:
    """Word の「最小値」で実際に必要になる 1 行ぶんの寸法。"""
    return max(pitch, pt * AT_LEAST_RATIO)


def line_rule(pt: float, pitch: float) -> str:
    """文字の大きさや指定行送りにかかわらず、常に「最小値」を使う。"""
    return "atLeast"


def textbox_frame_warning(t: TextBox) -> str:
    """行数と実効行送りが文字枠に収まらないときの警告。"""
    needed = len(t.lines) * effective_pitch(t.pt, t.pitch_pt)
    available = t.box.w if t.vertical else t.box.h
    if needed <= available + 1e-6:
        return ""
    direction = "幅" if t.vertical else "高さ"
    return (f"{t.name}は、{len(t.lines)}行×実効行送り"
            f"{effective_pitch(t.pt, t.pitch_pt):g}ptが枠の{direction}{available:.1f}ptに収まりません")


def page_textbox_warnings(page: Page) -> list[str]:
    """ページ内の収まらない文字枠を列挙する。"""
    return [warning for item in page.items if isinstance(item, TextBox)
            if (warning := textbox_frame_warning(item))]


def _text_para(t: TextBox, ids: list[int]) -> str:
    rpr = _rpr(t.font, t.pt, t.bold)
    runs = []
    for i, line in enumerate(t.lines):
        if i:
            runs.append(f"<w:r>{rpr}<w:br/></w:r>")
        styled = t.line_runs[i] if t.line_runs and i < len(t.line_runs) else [(line, t.font)]
        for text, font in styled:
            if text:
                color = t.line_colors[i] if t.line_colors and i < len(t.line_colors) else None
                runs.extend(_line_runs(text, font, t.pt, ids,
                                       vertical=t.vertical, bold=t.bold, color=color))
    pitch = t.pitch_pt
    # autoSpaceDE/DN: 日本語と英字・数字のあいだに Word が自動で入れるすき間を止める。
    # 入れられると行が計算より長くなり、最後の字が次の行へ送られる（段階 1 で確認）
    align = {"左": "left", "中央": "center", "右": "right"}.get(t.align, "left")
    return ('<w:p><w:pPr><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/><w:snapToGrid w:val="0"/>'
            f'<w:spacing w:before="0" w:after="0" w:line="{twip(pitch)}" w:lineRule="{line_rule(t.pt, pitch)}"/>'
            '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
            f'<w:jc w:val="{align}"/></w:pPr>'
            f'{"".join(runs)}{"" if runs else f"<w:r>{rpr}</w:r>"}</w:p>')


def _table_xml(table: Table) -> str:
    """固定幅の Word 表を作る。セル内でも自動の和欧文間隔を止める。"""
    widths = table.column_widths or [table.box.w]
    grid = "".join(f'<w:gridCol w:w="{twip(width)}"/>' for width in widths)
    border = "single" if table.border else "nil"
    borders = "".join(
        f'<w:{side} w:val="{border}" w:sz="4" w:space="0" w:color="000000"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    rows = []
    spans = table.col_spans or {}
    merges = table.v_merge or {}
    for row_index, values in enumerate(table.rows):
        cells = []
        covered = set()
        for start, count in ((c, n) for (r, c), n in spans.items() if r == row_index and n > 1):
            covered.update(range(start + 1, start + count))
        for index, width in enumerate(widths):
            if index in covered:
                continue
            span = max(1, int(spans.get((row_index, index), 1)))
            width = sum(widths[index:index + span])
            merge = merges.get((row_index, index))
            value = "" if merge == "continue" else (values[index] if index < len(values) else "")
            diagonal = (table.diagonal_cells or {}).get((row_index, index))
            pt = table.pt
            if table.cell_pts and row_index < len(table.cell_pts) and index < len(table.cell_pts[row_index]):
                pt = table.cell_pts[row_index][index]
            rpr = _rpr(table.font, pt)
            para = ('<w:p><w:pPr><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>'
                    '<w:snapToGrid w:val="0"/><w:spacing w:before="0" w:after="0"/>'
                    '<w:jc w:val="center"/></w:pPr>'
                    + f'<w:r>{rpr}<w:br/></w:r>'.join(
                        f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>'
                        for part in str(value).split("\n")) + '</w:p>')
            vertical = bool(table.vertical_cells) and (row_index, index) in table.vertical_cells
            direction = '<w:textDirection w:val="tbRlV"/>' if vertical else ""
            if diagonal:
                # 右上に 1 つ目、左下に 2 つ目の字。あいだは空の段落で下へ送る（行の高さに合わせる）。
                height_pt = (table.row_heights or [None] * (row_index + 1))[row_index] or pt * 3
                gap = max(0, int(height_pt / (pt * 1.4)) - 2)
                def side(text, jc):
                    return ('<w:p><w:pPr><w:autoSpaceDE w:val="0"/><w:autoSpaceDN w:val="0"/>'
                            '<w:snapToGrid w:val="0"/><w:spacing w:before="0" w:after="0"/>'
                            f'<w:jc w:val="{jc}"/></w:pPr><w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
                para = side(diagonal[0], "right") + side("", "left") * gap + side(diagonal[1], "left")
            grid_span = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
            v_merge = ('<w:vMerge w:val="restart"/>' if merge == "restart"
                       else '<w:vMerge/>' if merge == "continue" else "")
            # 表全体の罫線（borders）とは別の名前にする（同じ名前で上書きすると表の罫線が消える）
            cell_borders = ('<w:tcBorders><w:tl2br w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tcBorders>'
                            if diagonal else "")
            align = "top" if diagonal else "center"
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{twip(width)}" w:type="dxa"/>'
                         f'{grid_span}{v_merge}{cell_borders}{direction}<w:vAlign w:val="{align}"/></w:tcPr>{para}</w:tc>')
        height = None
        if table.row_heights and row_index < len(table.row_heights):
            height = table.row_heights[row_index]
        trpr = (f'<w:trPr><w:trHeight w:val="{twip(height)}" w:hRule="atLeast"/></w:trPr>'
                if height else "")
        rows.append('<w:tr>' + trpr + "".join(cells) + '</w:tr>')
    return ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
            '<w:tblLayout w:type="fixed"/><w:tblBorders>' + borders + '</w:tblBorders>'
            '</w:tblPr><w:tblGrid>' + grid + '</w:tblGrid>' + "".join(rows) + '</w:tbl>')


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


def _shape(box: Box, *, line: str, inner: str = "", body: str = "", fill: str = "",
           prst: str = "rect") -> str:
    fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
    txbx = f"<wps:txbx><w:txbxContent>{inner}</w:txbxContent></wps:txbx>" if inner else ""
    # f 文字列の式の中に \ は書けない（Python 3.11 まで）ので外で作る
    cnv = '<wps:cNvSpPr txBox="1"/>' if inner else "<wps:cNvSpPr/>"
    return (
        f'<wps:wsp>{cnv}'
        f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{emu(box.w)}" cy="{emu(box.h)}"/></a:xfrm>'
        f'<a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>{fill_xml}{line}</wps:spPr>'
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


def picture_size(item: Picture) -> tuple[float, float]:
    """Word に実際に置く画像部分の幅と高さを pt で返す。"""
    px_w, px_h = image_size(item.data, item.ext)
    caption_h = 16.0 if item.caption else 0.0
    available_h = max(0.0, item.box.h - caption_h)
    scale = min(item.box.w / px_w, available_h / px_h)
    return px_w * scale, px_h * scale


def _picture_xml(item: Picture, idx: int, rel_id: str) -> tuple[str, int]:
    """画像を上寄せ・左右中央に置き、必要なら下端へ説明枠を置く。"""
    px_w, px_h = image_size(item.data, item.ext)
    caption_h = 16.0 if item.caption else 0.0
    available_h = max(0.0, item.box.h - caption_h)
    width, height = picture_size(item)
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
        rpr = _rpr(GOTHIC, 10)
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
        # Windows の Word は縦書きの行送りをわずかに広く取るため、字の枠を
        # 左へ 1 行送りぶん広げる。右端・上端と、従来の高さの余裕は変えない。
        old_box = (Box(item.box.x, item.box.y, item.box.w, item.box.h + SLACK_PT)
                   if item.vertical else item.box)
        # 字を中央にそろえる枠（見出し）は、左だけ広げると字の中央が左へ半行ずれて
        # 隣の本文に重なった。左右に半行ずつ広げて中央の位置を保つ
        shift = item.pitch_pt / 2 if item.center else item.pitch_pt
        box = (Box(old_box.x - shift, old_box.y,
                   old_box.w + item.pitch_pt, old_box.h)
               if item.vertical else old_box)
        no_line = "<a:ln><a:noFill/></a:ln>"
        vert = ' vert="eaVert"' if item.vertical else ""
        body = (f'<wps:bodyPr rot="0"{vert} wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" '
                f'anchor="{"ctr" if item.center else "t"}" anchorCtr="0"><a:noAutofit/></wps:bodyPr>')
        text = _anchor(idx, box, _shape(box, line=no_line, inner=_text_para(item, ids), body=body),
                       name=item.name)
        if not item.border:
            return text, 1
        # 囲み線は広げる前の位置・大きさのまま、別の図形として重ねる。
        border_line = '<a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
        border = _anchor(idx + 1, old_box, _shape(old_box, line=border_line, prst=item.shape),
                         name=item.name + "_border")
        return text + border, 2
    if isinstance(item, Table):
        line = '<a:ln><a:noFill/></a:ln>'
        body = '<wps:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"><a:noAutofit/></wps:bodyPr>'
        return (_anchor(idx, item.box,
                        _shape(item.box, line=line, inner=_table_xml(item), body=body),
                        name=item.name), 1)
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
               + '<w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="atLeast"/></w:pPr>')
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
