"""段階 3 の取り込みを試す、架空の一般質問原稿を作る。

    python samples.py 出力フォルダ
"""

from __future__ import annotations

import binascii
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from typing import List
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V = "urn:schemas-microsoft-com:vml"


def _png(width: int = 8, height: int = 8) -> bytes:
    """外部部品なしで、青一色の小さな PNG を作る。"""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xffffffff)

    rows = b"".join(b"\x00" + b"\x48\x87\xc7" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _run(text: str, *, size: int = 0, bold: bool = False) -> str:
    props = ""
    if size or bold:
        props = "<w:rPr>" + (f'<w:sz w:val="{size * 2}"/>' if size else "") + ("<w:b/>" if bold else "") + "</w:rPr>"
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _p(text: str, style: str = "") -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_run(text)}</w:p>"


def _image_p() -> str:
    """DrawingML と VML のうち、現在の Word が使う DrawingML で画像を貼る。"""
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="100000" cy="100000"/>'
            '<wp:docPr id="1" name="見本写真"/><a:graphic>'
            f'<a:graphicData uri="{PIC}"><pic:pic><pic:blipFill><a:blip r:embed="rIdImage1"/>'
            '</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _textbox_p(text: str) -> str:
    return (f'<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>{_p(text)}'
            '</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>')


def _document_xml() -> str:
    body: List[str] = [
        _p("暮らしを守る防災対策", "MainHeading"),
        '<w:tbl><w:tr><w:tc>' + _p("表の中の段落です。") + '</w:tc></w:tr></w:tbl>',
        _textbox_p("テキストボックスの段落です。"),
        _image_p(),
        _p("▲見本　太郎議員"),
        f'<w:p>{_run("避難所の備え", size=14, bold=True)}</w:p>',
        _p("問　避難所の備蓄は十分ですか。"),
        _p("あわせて、期限の確認方法も伺います。"),
        _p("答　必要な数量を毎年確認しています。"),
        _p("情報の伝え方", "MinorHeading"),
        _p("問　防災情報をどう届けますか。"),
        _p("答　複数の方法で迅速に知らせます。"),
        _p("問　訓練は年2回行いますか。"),
        _p("答　地域と相談して実施します。"),
        _p("問　学校との連携を進めますか。"),
        _p("答　合同訓練を検討します。"),
        _p("◎見本の条例改正"),
        _p("2026年度に3地区で進めます。"),
    ]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" '
            f'xmlns:pic="{PIC}" xmlns:v="{V}"><w:body>{"".join(body)}<w:sectPr/></w:body></w:document>')


def _styles_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:styles xmlns:w="{W}"><w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="ＭＳ 明朝" w:eastAsia="ＭＳ 明朝"/><w:sz w:val="21"/>'
            '</w:rPr></w:rPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:styleId="HeadingBase"><w:name w:val="見出し基底"/>'
            '<w:rPr><w:sz w:val="32"/><w:b/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="MainHeading"><w:name w:val="大見出し"/>'
            '<w:basedOn w:val="HeadingBase"/></w:style>'
            '<w:style w:type="paragraph" w:styleId="MinorHeading"><w:name w:val="中見出し"/>'
            '<w:basedOn w:val="HeadingBase"/><w:rPr><w:sz w:val="24"/></w:rPr></w:style>'
            '</w:styles>')


def make_ippan_docx(path: Path) -> Path:
    """書式・表・テキストボックス・画像を含む見本の .docx を作る。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Default Extension="png" ContentType="image/png"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
                     'officedocument.wordprocessingml.document.main+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 f'<Relationship Id="rIdDoc" Type="{R}/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>'
                f'<Relationship Id="rIdImage1" Type="{R}/image" Target="media/face.png"/>'
                '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", _document_xml())
        z.writestr("word/styles.xml", _styles_xml())
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/media/face.png", _png())
    return path


def make_ippan_txt(path: Path) -> Path:
    """同じ内容を gikai_simple の印付きテキストで作る。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = """【大見出し】暮らしを守る防災対策
【写真】face.png｜顔｜▲見本　太郎議員
【見出し】避難所の備え
問　避難所の備蓄は十分ですか。
あわせて、期限の確認方法も伺います。
答　必要な数量を毎年確認しています。
【横見出し】情報の伝え方
問　防災情報をどう届けますか。
答　複数の方法で迅速に知らせます。
問　訓練は年2回行いますか。
答　地域と相談して実施します。
問　学校との連携を進めますか。
答　合同訓練を検討します。
◎見本の条例改正
2026年度に3地区で進めます。
"""
    path.write_text(text, encoding="utf-8-sig")
    return path


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    folder = Path(argv[1])
    docx = make_ippan_docx(folder / "一般質問_見本太郎.docx")
    txt = make_ippan_txt(folder / "一般質問_見本太郎.txt")
    print(f"作りました: {docx}")
    print(f"作りました: {txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
