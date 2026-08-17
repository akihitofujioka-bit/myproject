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
          align: str = "", border: bool = False) -> str:
    ppr = "<w:pPr>"
    if border:
        # 縦書きでは「下の罫線」が見出しの左側に出る
        ppr += ('<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="2" '
                'w:color="1F6F4A"/></w:pBdr>')
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


def _sect_pr(spec: LayoutSpec) -> str:
    """紙面の決まりごと。ここが 1ページ5段縦書きを決めている。"""
    char_twip = mm2twip(spec.body_pt * MM_PER_PT)
    line_twip = mm2twip(spec.body_pt * MM_PER_PT * spec.line_spacing)
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{mm2twip(spec.page_width_mm)}" w:h="{mm2twip(spec.page_height_mm)}"/>'
        f'<w:pgMar w:top="{mm2twip(spec.margin_top_mm)}" '
        f'w:right="{mm2twip(spec.margin_right_mm)}" '
        f'w:bottom="{mm2twip(spec.margin_bottom_mm)}" '
        f'w:left="{mm2twip(spec.margin_left_mm)}" '
        'w:header="425" w:footer="425" w:gutter="0"/>'
        f'<w:cols w:num="{spec.columns}" w:space="{mm2twip(spec.column_gap_mm)}"/>'
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
                    color="1F6F4A")
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
                                      color="1F6F4A"), border=True))
    body.append(_para("", body_rpr))

    articles = project.articles()
    if not articles:
        warnings.append("記事がありません。原稿を取り込んでから組んでください。")

    for art in articles:
        if art.title:
            body.append(_para(art.title, head_rpr, spacing_before=240, border=True))
            # 見出しは本文より大きいので、その分だけ行を余分に使う
            head_lines = -(-count_chars(art.title) * spec.heading_pt // (cpl * spec.body_pt))
            lines_used += max(1, int(head_lines)) * 2 + 1
        if art.author:
            body.append(_para(art.author, name_rpr, align="right"))
            lines_used += 1
        if art.lead:
            body.append(_para(art.lead, lead_rpr))
            lines_used += max(1, -(-count_chars(art.lead) // cpl))

        for line in art.body.split("\n"):
            line = line.strip()
            if not line:
                continue
            n = count_chars(line)
            chars_total += n
            lines_used += max(1, -(-n // cpl))
            body.append(_para(line, body_rpr, indent=spec.indent_first))

        # この記事の写真
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
            body.append(_image_para(rid, w_mm, h_mm, media_name, 1000 + idx))
            # 写真は、行が並ぶ方向にその幅のぶんだけ場所を取る。
            # さらに、写真は段をまたげないので、段の変わり目で
            # 手前に空きができる。平均すると写真1枚の半分ぶん。
            photo_lines = max(1, int(-(-w_mm // line_mm)))
            lines_used += photo_lines + photo_lines // 2 + 1
            if photo.caption:
                body.append(_para(photo.caption, cap_rpr, align="center"))
                chars_total += count_chars(photo.caption)
                lines_used += max(1, -(-count_chars(photo.caption) // cpl))
            if photo.credit:
                body.append(_para(f"（撮影: {photo.credit}）", cap_rpr, align="center"))
                lines_used += 1

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

    _write_docx(out, doc, _styles_xml(spec), media, rels)

    lines_per_page = max(1, m["lines_per_column"] * spec.columns)
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
        f'<w:spacing w:line="{line_twip}" w:lineRule="exact" w:after="0"/>'
        '<w:jc w:val="both"/>'
        "</w:pPr></w:pPrDefault></w:docDefaults></w:styles>"
    )


def _write_docx(out: Path, doc_xml: str, styles_xml: str,
                media: dict[str, bytes], rels: list[str]) -> None:
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
        'officedocument.wordprocessingml.styles+xml"/></Types>'
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
        f'{"".join(rels)}</Relationships>'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", doc_xml)
        z.writestr("word/styles.xml", styles_xml)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, blob in media.items():
            z.writestr(name, blob)
