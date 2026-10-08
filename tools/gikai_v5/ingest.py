"""原稿を読み込み、紙面に置く部品へ分ける（設計図 §5・§6）。

    python ingest.py 原稿ファイル

Word の書式は部品を推測するためだけに読み、取り込み後は捨てる。
推測した部品は ``sure=False`` にして、必ず人が確かめられる形で返す。
"""

from __future__ import annotations

import posixpath
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import doc97
from grid import Geometry, layout_text

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

KINDS = ("大見出し", "中見出し", "質問", "答弁", "本文", "写真", "写真説明", "議案")

# gikai_simple/core.py と同じ書き方。大きさは取り込み時の手掛かりとしてだけ読む。
PHOTO_LINE = re.compile(
    r"^\s*【写真】\s*(?P<file>[^｜|]+?)"
    r"(?:\s*[｜|]\s*(?P<size>表紙|[大中小顔])?)?"
    r"(?:\s*[｜|]\s*(?P<caption>.*?)\s*)?$"
)
HEADING_LINE = re.compile(r"^\s*【(?P<kind>大見出し|横見出し|見出し)】\s*(?P<text>.*?)\s*$")
QA_LINE = re.compile(r"^(?P<kind>[問答])[ \u3000]")


@dataclass
class Part:
    """原稿から分けた部品。sure が偽なら、画面で人が確かめる。"""

    kind: str
    text: str = ""
    sure: bool = True
    reason: str = ""
    image: Optional[str] = None
    photo_size: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError("部品の種類が正しくありません: " + self.kind)


@dataclass
class IngestResult:
    """1 原稿を取り込んだ結果。images は元の画質のまま保持する。"""

    parts: List[Part]
    images: Dict[str, bytes]
    warnings: List[str]
    source: str


@dataclass
class FitReport:
    """原稿が指定行数に入るかの見積もり。"""

    needed_lines: int
    capacity_lines: int
    overflow_lines: int
    free_lines: int


@dataclass
class Paragraph:
    """役割を決める前の段落。書式は推測後に捨てる。"""

    text: str = ""
    size: Optional[float] = None
    bold: bool = False
    image: Optional[str] = None
    explicit_kind: Optional[str] = None
    explicit_reason: str = ""


@dataclass
class SourceData:
    """各形式の読み取り結果をそろえたもの。"""

    paragraphs: List[Paragraph]
    images: Dict[str, bytes] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    source: str = ""
    has_format: bool = False


# ---------------------------------------------------------------- 数字

_Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
_H2Z = str.maketrans("0123456789", "０１２３４５６７８９")
_NUM_GROUP = re.compile(r"[0-9０-９]+(?:[－\-‐][0-9０-９]+)+|[0-9０-９]+")


def normalize_numbers(text: str) -> str:
    """1 桁を全角、2 桁以上を半角にする。「－」つなぎは変えない。"""

    def repl(m: re.Match) -> str:
        s = m.group(0)
        if any(ch in s for ch in "－-‐"):
            return s
        half = s.translate(_Z2H)
        return half.translate(_H2Z) if len(half) == 1 else half

    out = []
    for line in text.split("\n"):
        out.append(line if PHOTO_LINE.match(line) else _NUM_GROUP.sub(repl, line))
    return "\n".join(out)


# ---------------------------------------------------------------- Word 読み取り


def _safe_xml(data: bytes, name: str, source: Path) -> ET.Element:
    """外部実体や XML 爆弾を含む XML を ElementTree に渡さない。"""
    low = data.lower()
    if b"<!doctype" in low[:4096] or b"<!entity" in low:
        raise ValueError(f"通常の Word ファイルではありません: {source.name}（{name}）")
    return ET.fromstring(data)


def _on(e: Optional[ET.Element]) -> Optional[bool]:
    """w:b などのオン・オフを読む。要素が無ければ None。"""
    if e is None:
        return None
    value = e.get(W + "val")
    return value not in ("0", "false", "off")


def _rpr_values(rpr: Optional[ET.Element]) -> Tuple[Optional[float], Optional[bool]]:
    if rpr is None:
        return None, None
    sz = rpr.find(W + "sz")
    size = None
    if sz is not None:
        try:
            size = int(sz.get(W + "val", "")) / 2
        except ValueError:
            pass
    return size, _on(rpr.find(W + "b"))


def _styles(root: Optional[ET.Element]) -> Tuple[Dict[str, dict], float, bool]:
    styles: Dict[str, dict] = {}
    default_size, default_bold = 10.5, False
    if root is None:
        return styles, default_size, default_bold
    default = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    size, bold = _rpr_values(default)
    if size is not None:
        default_size = size
    if bold is not None:
        default_bold = bold
    for s in root.findall(W + "style"):
        style_id = s.get(W + "styleId")
        if not style_id:
            continue
        based = s.find(W + "basedOn")
        size, bold = _rpr_values(s.find(W + "rPr"))
        styles[style_id] = {
            "based": based.get(W + "val") if based is not None else None,
            "size": size,
            "bold": bold,
        }
    return styles, default_size, default_bold


def _style_value(styles: Dict[str, dict], style_id: Optional[str], key: str):
    """basedOn をたどり、子に近い側で最初に指定された値を返す。"""
    seen = set()
    while style_id and style_id not in seen:
        seen.add(style_id)
        style = styles.get(style_id)
        if not style:
            break
        if style.get(key) is not None:
            return style[key]
        style_id = style.get("based")
    return None


def _paragraph_format(p: ET.Element, styles: Dict[str, dict],
                      default_size: float, default_bold: bool) -> Tuple[float, bool]:
    ppr = p.find(W + "pPr")
    pstyle = ppr.find(W + "pStyle") if ppr is not None else None
    style_id = pstyle.get(W + "val") if pstyle is not None else None
    style_size = _style_value(styles, style_id, "size")
    style_bold = _style_value(styles, style_id, "bold")
    para_size, para_bold = _rpr_values(ppr.find(W + "rPr") if ppr is not None else None)
    sizes: List[float] = []
    bolds: List[bool] = []
    for run in p.iter(W + "r"):
        rsize, rbold = _rpr_values(run.find(W + "rPr"))
        sizes.append(rsize if rsize is not None else
                     para_size if para_size is not None else
                     style_size if style_size is not None else default_size)
        bolds.append(rbold if rbold is not None else
                     para_bold if para_bold is not None else
                     style_bold if style_bold is not None else default_bold)
    if not sizes:
        sizes.append(para_size if para_size is not None else
                     style_size if style_size is not None else default_size)
        bolds.append(para_bold if para_bold is not None else
                     style_bold if style_bold is not None else default_bold)
    return max(sizes), any(bolds)


def _paragraph_tokens(p: ET.Element) -> List[Tuple[str, str]]:
    """段落内の文字と画像を順に読む。入れ子の段落は別に読むので飛ばす。"""
    tokens: List[Tuple[str, str]] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == W + "p":
                continue
            if child.tag == W + "t":
                tokens.append(("text", child.text or ""))
            elif child.tag in (W + "br", W + "cr"):
                tokens.append(("text", "\n"))
            elif child.tag == W + "tab":
                tokens.append(("text", "\t"))
            elif child.tag == A + "blip":
                rel = child.get(R + "embed")
                if rel:
                    tokens.append(("image", rel))
            elif child.tag == V + "imagedata":
                rel = child.get(R + "id")
                if rel:
                    tokens.append(("image", rel))
            else:
                walk(child)

    walk(p)
    return tokens


def read_docx(path: Path) -> SourceData:
    """.docx の本文・表・テキストボックスと、貼られた画像を順に読む。"""
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        doc_data = z.read("word/document.xml")
        root = _safe_xml(doc_data, "document.xml", path)
        styles_root = None
        if "word/styles.xml" in z.namelist():
            styles_root = _safe_xml(z.read("word/styles.xml"), "styles.xml", path)
        rels: Dict[str, str] = {}
        rel_name = "word/_rels/document.xml.rels"
        if rel_name in z.namelist():
            rel_root = _safe_xml(z.read(rel_name), "document.xml.rels", path)
            for rel in rel_root.findall(PR + "Relationship"):
                if rel.get("TargetMode") != "External" and rel.get("Id") and rel.get("Target"):
                    target = posixpath.normpath(posixpath.join("word", rel.get("Target", "")))
                    if target.startswith("word/media/") and ".." not in PurePosixPath(target).parts:
                        rels[rel.get("Id", "")] = target

        styles, default_size, default_bold = _styles(styles_root)
        paragraphs: List[Paragraph] = []
        images: Dict[str, bytes] = {}
        warnings: List[str] = []
        for p in root.iter(W + "p"):
            size, bold = _paragraph_format(p, styles, default_size, default_bold)
            text_buf: List[str] = []

            def flush_text() -> None:
                text = "".join(text_buf).strip()
                if text:
                    paragraphs.append(Paragraph(text=text, size=size, bold=bold))
                text_buf.clear()

            for token, value in _paragraph_tokens(p):
                if token == "text":
                    text_buf.append(value)
                    continue
                flush_text()
                target = rels.get(value)
                if not target or target not in z.namelist():
                    warnings.append(f"画像 {value} を文書の中から取り出せませんでした")
                    continue
                name = PurePosixPath(target).name
                original = name
                n = 2
                while name in images and images[name] != z.read(target):
                    stem, suffix = Path(original).stem, Path(original).suffix
                    name = f"{stem}_{n}{suffix}"
                    n += 1
                images[name] = z.read(target)
                paragraphs.append(Paragraph(image=name))
            flush_text()
    return SourceData(paragraphs, images, warnings, path.name, True)


def _plain_paragraphs(text: str) -> List[Paragraph]:
    return [Paragraph(text=line.strip()) for line in text.splitlines() if line.strip()]


def read_doc(path: Path) -> SourceData:
    """旧形式 Word から文字だけを読む。"""
    path = Path(path)
    return SourceData(_plain_paragraphs(doc97.extract_text(path)), source=path.name)


def read_txt(path: Path) -> SourceData:
    """テキストを UTF-8、Shift_JIS、EUC-JP の順で読む。"""
    path = Path(path)
    data = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp932", "euc_jp"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise ValueError(f"文字コードを判定できません: {path.name}")
    return SourceData(_plain_paragraphs(text), source=path.name)


def ingest_text(text: str, source: str = "事務局原稿.txt") -> IngestResult:
    """UTF-8 保存前の文章を、.txt と同じ規則で部品へ分ける。"""
    data = SourceData(_plain_paragraphs(text), source=source)
    return IngestResult(classify(data.paragraphs, data.has_format), {}, [], data.source)


# ---------------------------------------------------------------- 部品分け


def _prepare(paragraphs: List[Paragraph]) -> List[Paragraph]:
    """空の段落を除き、文字の前後の空白と数字表記をそろえる。"""
    out = []
    for p in paragraphs:
        if p.image:
            out.append(p)
            continue
        text = p.text.strip()
        if not text:
            continue
        out.append(Paragraph(normalize_numbers(text), p.size, p.bold, p.image,
                             p.explicit_kind, p.explicit_reason))
    return out


def _body_size(paragraphs: List[Paragraph]) -> float:
    """字数で重み付けした最頻値を本文の字の大きさとする。"""
    sizes: Counter = Counter()
    for p in paragraphs:
        if p.text and p.size is not None:
            sizes[round(p.size * 2) / 2] += len(p.text)
    return sizes.most_common(1)[0][0] if sizes else 10.5


def _explicit(p: Paragraph) -> Optional[Part]:
    if p.explicit_kind:
        return Part(p.explicit_kind, p.text, True, p.explicit_reason, p.image)
    if p.image:
        return Part("写真", "", True, "Word に貼られた画像", p.image)
    photo = PHOTO_LINE.match(p.text)
    if photo:
        return Part("写真", "", True, "【写真】の印", photo.group("file").strip(),
                    photo.group("size") or None)
    heading = HEADING_LINE.match(p.text)
    if heading:
        kind = "大見出し" if heading.group("kind") == "大見出し" else "中見出し"
        return Part(kind, heading.group("text").strip(), True, f"【{heading.group('kind')}】の印")
    q = QA_LINE.match(p.text)
    if q:
        kind = "質問" if q.group("kind") == "問" else "答弁"
        return Part(kind, p.text, True, f"「{q.group('kind')}」と空白で始まる段落")
    if p.text.startswith("◎"):
        return Part("議案", p.text, True, "「◎」で始まる段落")
    return None


def classify(paragraphs: List[Paragraph], has_format: Optional[bool] = None) -> List[Part]:
    """段落の印と書式から役割を決める。推測は sure=False にする。"""
    paragraphs = _prepare(paragraphs)
    if has_format is None:
        has_format = any(p.size is not None for p in paragraphs)
    decided: List[Optional[Part]] = [_explicit(p) for p in paragraphs]

    # 写真の直後の短い段落は写真説明。ただし、明示された別の役割を上書きしない。
    for i in range(1, len(paragraphs)):
        if decided[i] is None and decided[i - 1] and decided[i - 1].kind == "写真":
            text = paragraphs[i].text
            if len(text) <= 30 and (text.startswith(("▲", "△")) or not text.endswith("。")):
                sure = text.startswith(("▲", "△"))
                reason = "写真の直後にある ▲・△ で始まる短い段落" if sure else "写真の直後にある短い段落"
                decided[i] = Part("写真説明", text, sure, reason)

    candidates: List[int] = []
    if has_format:
        body_size = _body_size(paragraphs)
        for i, p in enumerate(paragraphs):
            if (decided[i] is None and p.text and len(p.text) <= 25
                    and not p.text.endswith(("。", "、"))
                    and (p.bold or (p.size is not None and p.size >= body_size + 1))):
                candidates.append(i)
        if candidates:
            biggest = max(paragraphs[i].size or body_size for i in candidates)
            for i in candidates:
                p = paragraphs[i]
                kind = "大見出し" if (p.size or body_size) == biggest else "中見出し"
                why = "本文より大きな字または太字の短い段落"
                decided[i] = Part(kind, p.text, False, why)
    else:
        # 書式の無い原稿では、次が「問」か普通の本文である短い行を見出し候補にする。
        for i, p in enumerate(paragraphs[:-1]):
            if decided[i] is not None or len(p.text) > 20 or p.text.endswith("。"):
                continue
            nxt = decided[i + 1]
            if nxt is None or nxt.kind == "質問":
                decided[i] = Part("中見出し", p.text, False,
                                  "書式のない原稿で、次が質問または本文の短い段落")

    parts: List[Part] = []
    continuing: Optional[str] = None
    for p, part in zip(paragraphs, decided):
        if part is None:
            if continuing:
                part = Part(continuing, p.text, True, "前の段落の続き")
            else:
                part = Part("本文", p.text, True, "ほかの決まった印に当てはまらない段落")
        parts.append(part)
        if part.kind in ("質問", "答弁"):
            continuing = part.kind
        elif part.kind not in ("写真説明",):
            continuing = None

        # 【写真】行に書かれた説明は、確実な写真説明として直後へ加える。
        photo = PHOTO_LINE.match(p.text) if p.text else None
        if part.kind == "写真" and photo and (photo.group("caption") or "").strip():
            parts.append(Part("写真説明", (photo.group("caption") or "").strip(), True,
                              "【写真】行に書かれた説明"))
    return parts


def ingest(path: Path) -> IngestResult:
    """拡張子に合う方法で原稿を読み、部品に分ける。"""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        source = read_docx(path)
    elif ext == ".doc":
        source = read_doc(path)
    elif ext == ".txt":
        source = read_txt(path)
    else:
        raise ValueError(f"この形式は取り込めません: {path.name}（.docx / .doc / .txt に対応）")
    return IngestResult(classify(source.paragraphs, source.has_format), source.images,
                        source.warnings, source.source)


def check_ippan(parts: List[Part]) -> List[str]:
    """一般質問のページで人が直す必要のある点を返す。"""
    warnings = []
    questions = 0
    previous = ""
    for part in parts:
        if part.kind == "質問" and previous != "質問":
            questions += 1
        previous = part.kind
    if questions >= 5:
        warnings.append(f"質問が {questions} つあります（4 つまで）")
    if not any(p.kind == "写真" for p in parts):
        warnings.append("顔写真がありません")
    return warnings


def fit_report(parts: List[Part], g: Geometry, capacity_lines: int) -> FitReport:
    """文字部品を格子の行に分け、必要行数とあふれ・余りを返す。"""
    needed = 0
    for part in parts:
        if part.kind == "中見出し":
            needed += 2
        elif part.kind in ("本文", "質問", "答弁", "議案", "写真説明"):
            needed += len(layout_text([part.text], g.chars_per_line))
    return FitReport(needed, capacity_lines, max(0, needed - capacity_lines),
                     max(0, capacity_lines - needed))


# ---------------------------------------------------------------- 表示


def _short(text: str, length: int = 30) -> str:
    text = text.replace("\n", " ")
    return text[:length] + ("…" if len(text) > length else "")


def describe(result: IngestResult, g: Optional[Geometry] = None,
             capacity_lines: int = 136) -> str:
    """CLI と画面確認に使える、取り込み結果の一覧。"""
    lines = [f"原稿: {result.source}", "", "番号  種類       判定  先頭30字                       理由"]
    for n, part in enumerate(result.parts, 1):
        mark = "✓" if part.sure else "？"
        text = part.text or (part.image or "")
        lines.append(f"{n:>3}  {part.kind:<10} {mark}    {_short(text):<31} {part.reason}")
    warnings = result.warnings + check_ippan(result.parts)
    lines.extend(["", "注意:"])
    lines.extend([f"・{w}" for w in warnings] or ["・ありません"])
    report = fit_report(result.parts, g or Geometry(), capacity_lines)
    lines.extend(["", "行数の見積もり（一般質問 1 ページ: 150 - 大見出し 8 - 顔写真 6 = 136 行）",
                  f"必要 {report.needed_lines} 行 / 入る {report.capacity_lines} 行 / "
                  f"あふれ {report.overflow_lines} 行 / 余り {report.free_lines} 行"])
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    try:
        print(describe(ingest(Path(argv[1]))))
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError, doc97.DocError) as e:
        print(f"取り込めませんでした: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
