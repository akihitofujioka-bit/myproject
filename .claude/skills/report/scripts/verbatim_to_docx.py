#!/usr/bin/env python3
"""逐語録の Markdown を Word（.docx）とプレーンテキスト（.txt）に変換する。

merge_transcripts.py が出した Markdown を、そのまま Word で開いて校正できる形にする。
議事録は Word で回覧・修正することが多いため、見出し・話者・注記が段落として
分かれていることが重要。

標準ライブラリだけで書く（merge_transcripts.py と同じ方針）。docx は
XML を集めた ZIP なので、この程度の構造なら外部ライブラリは要らない。

使い方:
    verbatim_to_docx.py 逐語録.md                    # .docx と .txt を同じ場所に作る
    verbatim_to_docx.py 逐語録.md --docx out.docx
    verbatim_to_docx.py 逐語録.md --txt-only
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import zipfile
from xml.sax.saxutils import escape

# 日本語の既定フォント。手元に無ければ Word が代替する。
FONT_BODY = "ＭＳ 明朝"
FONT_HEAD = "ＭＳ ゴシック"
FONT_LATIN = "Century"

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


# --------------------------------------------------------------------------
# Markdown の読み取り
# --------------------------------------------------------------------------

SPEAKER_RE = re.compile(r"^\*\*\[(?P<time>[^\]]+)\]\s*(?P<who>.+?)\*\*(?P<flag>.*)$")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
COMMENT_RE = re.compile(r"^<!--\s*(.*?)\s*-->$")
TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")


def parse(md: str) -> list[dict]:
    """Markdown を、段落の並びに落とす。

    merge_transcripts.py が出す形だけを相手にする汎用でない変換。
    未知の行は本文段落として素通しするので、取りこぼしても内容は落ちない。
    """
    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        # 表：ヘッダ行 + 区切り行 + 本体
        if (line.startswith("|") and i + 1 < len(lines)
                and TABLE_SEP_RE.match(lines[i + 1].strip())):
            header = split_row(line)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue

        m = COMMENT_RE.match(line.strip())
        if m:
            blocks.append({"kind": "marker", "text": m.group(1)})
            i += 1
            continue

        m = HEADING_RE.match(line)
        if m:
            blocks.append({"kind": "heading", "level": len(m.group(1)),
                           "text": m.group(2)})
            i += 1
            continue

        m = SPEAKER_RE.match(line)
        if m:
            blocks.append({"kind": "speaker", "time": m.group("time"),
                           "who": m.group("who"),
                           "flagged": "⚠" in m.group("flag")})
            i += 1
            continue

        if line.startswith(">"):
            blocks.append({"kind": "note", "text": line.lstrip("> ").rstrip()})
            i += 1
            continue

        if line.startswith("- "):
            blocks.append({"kind": "bullet", "text": line[2:]})
            i += 1
            continue

        blocks.append({"kind": "body", "text": line})
        i += 1
    return blocks


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def strip_marks(text: str) -> str:
    """本文中の Markdown 装飾を落とす。逐語録の本文自体は書き換えない。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


# --------------------------------------------------------------------------
# Word 出力
# --------------------------------------------------------------------------

def run(text: str, *, bold=False, size=21, color=None, font=None) -> str:
    """w:r をひとつ。size は half-point（21 = 10.5pt）。"""
    # w:rPr の子要素は順序が決まっている（rFonts → b → color → sz）。
    # 並びが違うとスキーマ違反になり、Word も LibreOffice も開けない。
    face = font or FONT_BODY
    props = [f'<w:rFonts w:ascii="{escape(FONT_LATIN)}" w:hAnsi="{escape(FONT_LATIN)}" '
             f'w:eastAsia="{escape(face)}"/>']
    if bold:
        props.append("<w:b/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return (f"<w:r><w:rPr>{''.join(props)}</w:rPr>"
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def para(runs: str, *, style=None, before=0, after=60, indent=0,
         border=False, align=None) -> str:
    # w:pPr も順序が決まっている（pStyle → pBdr → spacing → ind → jc）。
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if border:
        props.append('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" '
                     'w:color="AAAAAA"/></w:pBdr>')
    props.append(f'<w:spacing w:before="{before}" w:after="{after}"/>')
    if indent:
        props.append(f'<w:ind w:left="{indent}"/>')
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(props)}</w:pPr>{runs}</w:p>"


def table(header: list[str], rows: list[list[str]]) -> str:
    cols = max([len(header)] + [len(r) for r in rows]) or 1
    total = 9350                                  # A4 の本文幅（DXA）
    width = total // cols
    widths = [width] * cols
    widths[-1] = total - width * (cols - 1)       # 端数は最終列で吸収

    def cell(text: str, *, head: bool) -> str:
        shade = ('<w:shd w:val="clear" w:color="auto" w:fill="EFEFEF"/>'
                 if head else "")
        return (f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                + para(run(strip_marks(text), bold=head, size=18), after=0) + "</w:tc>")

    def line(cells: list[str], *, head: bool) -> str:
        padded = list(cells) + [""] * (cols - len(cells))
        return "<w:tr>" + "".join(cell(c, head=head) for c in padded) + "</w:tr>"

    borders = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    body = line(header, head=True) + "".join(line(r, head=False) for r in rows)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{total}" w:type="dxa"/>'
            f"<w:tblBorders>{borders}</w:tblBorders></w:tblPr>"
            f"<w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>"
            + para("", after=0))          # 表の直後は空段落が要る（表が続くと結合される）


def build_body(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        kind = b["kind"]

        if kind == "heading":
            level = min(b["level"], 3)
            size = {1: 32, 2: 26, 3: 22}[level]
            out.append(para(
                run(strip_marks(b["text"]), bold=True, size=size, font=FONT_HEAD),
                style=f"Heading{level}", before=240 if level > 1 else 0, after=120,
                border=(level == 1)))

        elif kind == "speaker":
            mark = "  ⚠要確認" if b["flagged"] else ""
            out.append(para(
                run(f"［{b['time']}］ {b['who']}{mark}", bold=True, size=20,
                    font=FONT_HEAD, color="C00000" if b["flagged"] else "1F3864"),
                before=180, after=40))

        elif kind == "note":
            out.append(para(run(strip_marks(b["text"]), size=18, color="A0522D"),
                            indent=567, before=0, after=20))

        elif kind == "marker":
            out.append(para(run(f"― {b['text']} ―", size=18, color="808080",
                                font=FONT_HEAD),
                            before=240, after=120, align="center"))

        elif kind == "bullet":
            out.append(para(run("・" + strip_marks(b["text"])), indent=283, after=40))

        elif kind == "table":
            out.append(table(b["header"], b["rows"]))

        else:
            out.append(para(run(strip_marks(b["text"]))))
    return "".join(out)


DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document {ns}><w:body>{body}
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>
<w:pgMar w:top="1418" w:right="1276" w:bottom="1418" w:left="1276"
 w:header="851" w:footer="992" w:gutter="0"/></w:sectPr>
</w:body></w:document>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {ns}>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="{latin}" w:hAnsi="{latin}" w:eastAsia="{body}"/>
<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
<w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
<w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>
<w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/>
<w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>
</w:styles>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def write_docx(blocks: list[dict], path: pathlib.Path) -> None:
    document = DOCUMENT.format(ns=NS, body=build_body(blocks))
    styles = STYLES.format(ns=NS, latin=escape(FONT_LATIN), body=escape(FONT_BODY))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", styles)


# --------------------------------------------------------------------------
# テキスト出力
# --------------------------------------------------------------------------

def write_txt(blocks: list[dict], path: pathlib.Path) -> None:
    out: list[str] = []
    for b in blocks:
        kind = b["kind"]
        if kind == "heading":
            bar = "=" if b["level"] == 1 else "-"
            title = strip_marks(b["text"])
            out += ["", title, bar * (len(title) * 2)]
        elif kind == "speaker":
            mark = "  ⚠要確認" if b["flagged"] else ""
            out += ["", f"［{b['time']}］ {b['who']}{mark}"]
        elif kind == "note":
            out.append("    " + strip_marks(b["text"]))
        elif kind == "marker":
            out += ["", f"― {b['text']} ―"]
        elif kind == "bullet":
            out.append("・" + strip_marks(b["text"]))
        elif kind == "table":
            widths = [len(b["header"])] if b["header"] else [0]
            out.append("  " + " | ".join(strip_marks(c) for c in b["header"]))
            out.append("  " + "-" * 60)
            for row in b["rows"]:
                out.append("  " + " | ".join(strip_marks(c) for c in row))
            out.append("")
        else:
            out.append(strip_marks(b["text"]))
    path.write_text("\n".join(out).strip() + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown", help="merge_transcripts.py が出した逐語録の .md")
    ap.add_argument("--docx", help="Word の出力先（既定：入力と同じ場所・同じ名前）")
    ap.add_argument("--txt", help="テキストの出力先")
    ap.add_argument("--docx-only", action="store_true")
    ap.add_argument("--txt-only", action="store_true")
    args = ap.parse_args()

    src = pathlib.Path(args.markdown)
    if not src.exists():
        sys.exit(f"エラー: ファイルがない: {src}")
    blocks = parse(src.read_text(encoding="utf-8"))

    if not args.txt_only:
        out = pathlib.Path(args.docx) if args.docx else src.with_suffix(".docx")
        write_docx(blocks, out)
        print(f"書き出した: {out}")
    if not args.docx_only:
        out = pathlib.Path(args.txt) if args.txt else src.with_suffix(".txt")
        write_txt(blocks, out)
        print(f"書き出した: {out}")


if __name__ == "__main__":
    main()
