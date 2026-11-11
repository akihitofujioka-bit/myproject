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

SAMPLE_MEMBERS = [f"見本{number}郎" for number in "一二三四五六七八九十"]


def sample_forms() -> dict:
    """3つの書き込み式ページで使う架空の見本を返す。"""
    marks = {name: ("議長" if index == 0 else "○")
             for index, name in enumerate(SAMPLE_MEMBERS)}
    return {
        "表紙": {
            "photo_caption": "見本行事の様子",
            "feature_titles": "暮らしを考える特集\n地域の取り組み",
        },
        "審議したこと・決まったこと": {
            "period": "Ｒ８．３．４～３．１１",
            "counts": [{"kind": "報告", "count": 3}, {"kind": "条例関係", "count": 2},
                       {"kind": "予算関係", "count": 4}],
            "body": "【区分】予算\n◎見本条例\n質疑\n問　見本事業の内容を伺います。\n答　計画に沿って進めます。",
            "votes": [{"kind": "条例", "title": "見本条例", "result": "可決", "marks": marks}],
        },
        "最終ページ": {
            "editorial": "今号も多くの方の協力で発行できました。",
            "free": "【見本のお知らせ】\n地域の話題と写真を募集しています。",
            "next_meeting": "次の定例会は６月４日（木）午前１０時に開会の予定です。",
        },
    }


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


def _image_p(rel_id: str = "rIdImage1", name: str = "見本写真") -> str:
    """DrawingML と VML のうち、現在の Word が使う DrawingML で画像を貼る。"""
    return (f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="100000" cy="100000"/>'
            f'<wp:docPr id="1" name="{escape(name)}"/><a:graphic>'
            f'<a:graphicData uri="{PIC}"><pic:pic><pic:blipFill><a:blip r:embed="{rel_id}"/>'
            '</pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _textbox_p(text: str) -> str:
    return (f'<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>{_p(text)}'
            '</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>')


def _document_xml(include_image: bool = False) -> str:
    body: List[str] = [
        _p("暮らしを守る防災対策", "MainHeading"),
        '<w:tbl><w:tr><w:tc>' + _p("表の中の段落です。") + '</w:tc></w:tr></w:tbl>',
        _textbox_p("テキストボックスの段落です。"),
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
    if include_image:
        body[3:3] = [_image_p(), _p("▲見本　太郎議員")]
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


def _make_ippan_docx(path: Path, include_image: bool) -> Path:
    """一般質問の見本を作る。画像付きは取り込み機能のテスト専用。"""
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
                + (f'<Relationship Id="rIdImage1" Type="{R}/image" Target="media/face.png"/>'
                   if include_image else '') +
                '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", _document_xml(include_image))
        z.writestr("word/styles.xml", _styles_xml())
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        if include_image:
            z.writestr("word/media/face.png", _png())
    return path


def make_ippan_docx(path: Path) -> Path:
    """写真を含まない、実際の受け取り方に沿った一般質問の見本を作る。"""
    return _make_ippan_docx(path, False)


def make_ingest_image_docx(path: Path) -> Path:
    """Word に貼られた画像の取り込み機能だけを確かめる一時見本を作る。"""
    return _make_ippan_docx(path, True)


def make_ippan_txt(path: Path) -> Path:
    """同じ内容を gikai_simple の印付きテキストで作る。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = """【大見出し】暮らしを守る防災対策
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


def _write_parts_docx(path: Path, body: List[str], images: List[tuple[str, bytes]]) -> Path:
    """任意の本文と画像から、取り込み確認用の小さな Word を作る。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" '
                f'xmlns:pic="{PIC}" xmlns:v="{V}"><w:body>{"".join(body)}'
                '<w:sectPr/></w:body></w:document>')
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
    image_rels = "".join(f'<Relationship Id="rIdImage{n}" Type="{R}/image" Target="media/{name}"/>'
                         for n, (name, _) in enumerate(images, 1))
    doc_rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>{image_rels}'
                '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _styles_xml())
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, data in images:
            z.writestr(f"word/media/{name}", data)
    return path


def make_overflow_ippan_docx(path: Path) -> Path:
    """答弁が 1 ページからあふれる、架空の一般質問原稿を作る。"""
    body = [_p("地域交通を将来へつなぐ", "MainHeading"),
            _p("移動手段の確保", "MinorHeading"), _p("問　地域の移動手段をどう守りますか。")]
    sentence = "答　町内の状況を丁寧に調べ、利用する人の声を聞きながら持続できる方法を検討します。"
    body.extend(_p(sentence * 5) for _ in range(12))
    return _write_parts_docx(path, body, [])


def make_gyosei_two_photos_docx(path: Path) -> Path:
    """写真が 2 枚ある、架空の行政報告原稿を作る。"""
    body = [_p("町の取り組みを報告します", "MainHeading"),
            _p("交流施設の整備", "MinorHeading"),
            _p("新しい交流施設の工事が進み、地域の皆さんによる見学会を開きました。"),
            _image_p("rIdImage1", "交流施設"), _p("▲交流施設の見学会"),
            _p("防災訓練を実施", "MinorHeading"),
            _p("架空地区で避難経路を確かめ、備蓄品の取り扱いを練習しました。"),
            _image_p("rIdImage2", "防災訓練"), _p("▲架空地区の防災訓練"),
            _p("参加者から寄せられた意見を、今後の取り組みに生かします。")]
    images = [("facility.png", _png(80, 60)), ("drill.png", _png(64, 48))]
    return _write_parts_docx(path, body, images)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    folder = Path(argv[1])
    docx = make_ippan_docx(folder / "一般質問_見本太郎.docx")
    txt = make_ippan_txt(folder / "一般質問_見本太郎.txt")
    overflow = make_overflow_ippan_docx(folder / "一般質問_あふれる見本花子.docx")
    gyosei = make_gyosei_two_photos_docx(folder / "行政報告_写真2枚.docx")
    print(f"作りました: {docx}")
    print(f"作りました: {txt}")
    print(f"作りました: {overflow}")
    print(f"作りました: {gyosei}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
