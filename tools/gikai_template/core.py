"""前年の同じ月の号を様式にして、今年の原稿を差し込む。

日高村議会だよりは年 4 回（4・7・10・1 月）発行で、毎年の構成がほとんど
変わらない。そこで「前年の同じ月の号」をそのまま様式として使い、
**書式・文字枠の位置・表紙・裏表紙はそのまま、文字だけを入れ替える**。

様式（第198〜201号）の作りを調べて分かったこと（2026-09-25）:
  * A4、余白 上15・下12・左右15mm。表紙は横書き 1 段、本文は縦書き 5 段
  * **改ページが 1 つも無い。** ページの区切りも枠の位置も、空行の数と
    ページ基準で置いた文字枠（VML）で手作業で合わせてある
  * 見出し・質問題・写真の説明文・囲み記事は文字枠。見出しには 1 升の表もある
  * 写真は文書に入っておらず、本文の空行で場所を空けてある（印刷所が入れる）
  * 本文は 11pt、1 段の 1 行は 12 字

このため、記事の長さが変わると以降がずれて、枠と本文が食い違う。
それを防ぐために、**記事が伸び縮みした行数だけ、すぐ後ろの空行を
減らしたり足したりする**（compensate）。空行が足りなければ、どれだけ
あふれたかを報告する。最後は人が Word で整える前提。

XML は標準ライブラリの ElementTree で扱う（追加の部品を入れずに済むように）。
ElementTree は使っていない名前空間の宣言を落とすが、Word は
mc:Ignorable に書かれた接頭辞の宣言が無いと「壊れている」と判断するので、
保存するときにルート要素の開始タグだけ元のものに戻している（_serialize）。
"""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

import doc97
from xlsx_vote import VoteTable, read_vote_table

# ---------------------------------------------------------------- 名前空間

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
V = "urn:schemas-microsoft-com:vml"
O = "urn:schemas-microsoft-com:office:office"
W10 = "urn:schemas-microsoft-com:office:word"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def wval(el: ET.Element | None, default: str = "") -> str:
    return default if el is None else el.get(w("val"), default)


# ---------------------------------------------------------------- 決まりごと

SEASONS = ["4月号", "7月号", "10月号", "1月号"]
SEASON_NOTE = {
    "4月号": "3月定例会（当初予算）。第198号の形",
    "7月号": "6月定例会。第199号の形",
    "10月号": "9月定例会（決算・行政視察）。第200号の形",
    "1月号": "12月定例会（特集：新年の抱負）。第201号の形",
}

INFO_NAME = "号情報.json"
DATA_NAME = "差し込み.json"
TEMPLATE_NAME = "様式.docx"
ATTACH_DIR = "別添"
OUT_DIR = "出力"

# 前年のまま残した欄に付ける印（黄色の蛍光ペン）。刷る前に人が確かめるため
KEEP_HIGHLIGHT = "yellow"
# 縦書きの紙面では数字の全角・半角をそろえる（1 桁は全角、2 桁以上は半角）
NUMBERS_TATEGAKI = True
# 縦中横（数字を立てて 1 字分に収める）を掛ける半角数字の桁数
TATECHUYOKO = re.compile(r"(?<![0-9A-Za-z.,])[0-9]{2,3}(?![0-9A-Za-z])")
# 見出しとみなす字の大きさ（この大きさ以上の字がある欄から、画面の区切りを作る）
GROUP_HEAD_PT = 18

# 欄の状態
NEW, KEEP, SAME, EMPTY, TABLE = "new", "keep", "same", "empty", "table"
MODE_LABEL = {
    NEW: "今年の原稿",
    KEEP: "前年のまま（黄色の印）",
    SAME: "毎号同じ（印なし）",
    EMPTY: "空にする",
    TABLE: "賛否表を入れる",
}


# ---------------------------------------------------------------- 文字の幅

_Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
_H2Z = str.maketrans("0123456789", "０１２３４５６７８９")
_NUM_GROUP = re.compile(r"[0-9０-９]+(?:[－\-‐][0-9０-９]+)+|[0-9０-９]+")


def normalize_numbers(text: str) -> str:
    """縦書きの慣行に合わせて数字をそろえる（第198〜201号の書き方）。

    1 桁は全角、2 桁以上は半角。「－」でつないだ郵便番号・電話番号・番地は
    書いてあるとおり残す。小数（92・７ など）もそのまま拾われるが、
    どちらも各桁ごとの規則なので崩れない。
    """

    def repl(m: re.Match) -> str:
        s = m.group(0)
        if any(ch in s for ch in "－-‐"):
            return s
        h = s.translate(_Z2H)
        return h.translate(_H2Z) if len(h) == 1 else h

    return _NUM_GROUP.sub(repl, text)


RUBY = re.compile(r"｜([^｜《》\n]+)《([^《》\n]+)》|([一-龥々〆ヵヶ﨑髙]+)《([^《》\n]+)》")


def strip_ruby(text: str) -> str:
    """「｜山田《やまだ》」→「山田」。字数を数えるときに読みがなを除く。"""
    return RUBY.sub(lambda m: m.group(1) or m.group(3), text)


def text_width(text: str, vertical: bool) -> float:
    """紙面での字数（全角 1、半角 0.5。縦書きの縦中横は 1 字）。"""
    text = strip_ruby(text)
    n = 0.0
    if vertical:
        # 縦中横になる 2〜3 桁の数字は 1 字ぶん
        n += len(TATECHUYOKO.findall(text))
        text = TATECHUYOKO.sub("", text)
    for ch in text:
        if ch in "\t":
            n += 1
        else:
            n += 0.5 if unicodedata.east_asian_width(ch) in ("Na", "H") else 1
    return n


# ---------------------------------------------------------------- XML の読み書き


def _safe_parse(raw: bytes, name: str) -> ET.Element:
    # Word が作る XML に DOCTYPE や実体定義は含まれない。含まれていたら
    # 細工されたファイルなので読まない（XML 爆弾・外部実体参照の対策）
    if b"<!doctype" in raw[:4096].lower() or b"<!entity" in raw.lower():
        raise ValueError(f"通常の Word ファイルではありません: {name}")
    return ET.fromstring(raw)


def _register_namespaces(raw: bytes) -> None:
    """文書で使われている接頭辞（w: v: o: w14: …）をそのまま使って書き出す。

    ElementTree は知らない名前空間に ns0: のような名前を付けてしまう。
    mc:Ignorable="w14 wp14" のように属性の値の中で接頭辞を使っているので、
    名前が変わると Word が読めなくなる。
    """
    head = raw[: raw.find(b">", raw.find(b"<w:document")) + 1].decode("utf-8", "replace")
    for prefix, uri in re.findall(r'xmlns:(\w+)="([^"]+)"', head):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def _root_open_tag(raw: bytes) -> bytes:
    start = raw.find(b"<w:document")
    return raw[start: raw.find(b">", start) + 1]


def _serialize(root: ET.Element, original_open_tag: bytes) -> bytes:
    body = ET.tostring(root, encoding="unicode").encode("utf-8")
    # 開始タグを元のもの（すべての名前空間の宣言と mc:Ignorable 付き）に戻す
    end = body.find(b">")
    return (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            + original_open_tag + body[end + 1:])


def _strip_ids(el: ET.Element) -> None:
    """複製した段落から、文書内で一意であるべき番号を外す。"""
    for node in el.iter():
        for key in (f"{{{W14}}}paraId", f"{{{W14}}}textId", f"{{{W14}}}anchorId"):
            node.attrib.pop(key, None)


# ---------------------------------------------------------------- 段落の文字


def _is_skip(tag: str) -> bool:
    # テキストボックスの中身は、その枠の欄として別に扱う。
    # mc:Fallback は mc:Choice と同じ内容の複製なので読まない
    return tag in (w("txbxContent"), f"{{{MC}}}Fallback", w("instrText"), w("delText"))


def para_text(p: ET.Element) -> str:
    """段落の見えている文字。ルビは「｜親字《よみ》」の形で返す。"""
    out: list[str] = []

    def walk(node: ET.Element) -> None:
        for ch in node:
            tag = ch.tag
            if _is_skip(tag):
                continue
            if tag == w("ruby"):
                base = "".join(para_text(x) for x in ch.iter(w("rubyBase")))
                rt = "".join(para_text(x) for x in ch.iter(w("rt")))
                out.append(f"｜{base}《{rt}》" if rt else base)
                continue
            if tag == w("t"):
                out.append(ch.text or "")
            elif tag == w("tab"):
                out.append("\t")
            elif tag in (w("br"), w("cr")) and ch.get(w("type")) not in ("page", "column"):
                out.append("\n")
            elif tag == w("noBreakHyphen"):
                out.append("‐")
            else:
                walk(ch)

    walk(p)
    return "".join(out)


def _has_anchor(el: ET.Element) -> bool:
    """段落（または run）に、文字枠・図形・図がつなぎ留められているか。"""
    for node in el.iter():
        if node.tag in (w("pict"), w("drawing"), w("object"), f"{{{MC}}}AlternateContent"):
            return True
    return False


def _anchor_runs(p: ET.Element) -> list[ET.Element]:
    """段落の直下にある、枠・図をつなぎ留めている run。"""
    return [r for r in p if r.tag == w("r") and _has_anchor(r)]


def _is_blank(p: ET.Element) -> bool:
    return not para_text(p).strip()


def _max_pt(el: ET.Element, default: float) -> float:
    sizes = [int(wval(s, "0")) / 2 for s in el.iter(w("sz")) if wval(s).isdigit()]
    return max(sizes) if sizes else default


def _run_pt(p: ET.Element, default: float) -> float:
    """段落の本文の字の大きさ（最初の文字の run の大きさ）。"""
    for r in p.iter(w("r")):
        if r.find(w("t")) is not None and (r.findtext(w("t")) or "").strip():
            sz = r.find(f"{w('rPr')}/{w('sz')}")
            if sz is not None and wval(sz).isdigit():
                return int(wval(sz)) / 2
            break
    sz = p.find(f"{w('pPr')}/{w('rPr')}/{w('sz')}")
    if sz is not None and wval(sz).isdigit():
        return int(wval(sz)) / 2
    return default


# ---------------------------------------------------------------- 寸法


def _length_pt(value: str) -> float | None:
    """VML の寸法（'261pt' '72mm' '1.5in' '3cm'）を pt にする。"""
    m = re.fullmatch(r"\s*(-?[0-9.]+)\s*(pt|mm|cm|in|px)?\s*", value or "")
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "px"
    return n * {"pt": 1, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72, "px": 0.75}[unit]


def _style_dict(style: str) -> dict[str, str]:
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _style_str(d: dict[str, str]) -> str:
    return ";".join(f"{k}:{v}" for k, v in d.items())


@dataclass
class Geometry:
    """区間（セクション）の紙面の寸法。1 行に入る字数を出すのに使う。"""
    vertical: bool
    columns: int
    column_len_pt: float      # 1 段の長さ（縦書きなら 1 行の長さ）
    base_pt: float            # 本文の字の大きさ（空行の大きさ）

    def chars_per_line(self, pt: float) -> int:
        return max(1, int(self.column_len_pt / max(pt, 1) + 0.05))


def _geometry(sect: ET.Element | None, base_pt: float) -> Geometry:
    def num(el, attr, default):
        try:
            return int(el.get(w(attr), default)) if el is not None else default
        except ValueError:
            return default

    pg = sect.find(w("pgSz")) if sect is not None else None
    mar = sect.find(w("pgMar")) if sect is not None else None
    cols = sect.find(w("cols")) if sect is not None else None
    td = sect.find(w("textDirection")) if sect is not None else None
    vertical = wval(td).startswith("tb")
    n = max(1, num(cols, "num", 1))
    space = num(cols, "space", 425)
    width, height = num(pg, "w", 11906), num(pg, "h", 16838)
    if vertical:
        length = height - num(mar, "top", 1440) - num(mar, "bottom", 1440)
    else:
        length = width - num(mar, "left", 1440) - num(mar, "right", 1440)
    col = (length - space * (n - 1)) / n
    return Geometry(vertical, n, col / 20, base_pt)


# ---------------------------------------------------------------- 欄


@dataclass
class Slot:
    """様式の中の差し込み欄 1 つ。"""
    id: str
    kind: str                  # body（本文の記事）/ cell（表の升目）/ box（文字枠）
    old_text: str              # 前年の文章（見本）
    section: int               # 何番目の区間か（0 = 表紙）
    vertical: bool
    size_pt: float             # いちばん大きい字の大きさ
    group: str = ""            # 画面で束ねる見出し
    box_mm: tuple[float, float] | None = None    # 文字枠の幅・高さ（mm）
    copy_of: str = ""          # 複製した欄なら元の欄の ID
    kind_override: str = ""    # 人が選び直した種類（KIND_CHOICES のどれか）

    @property
    def kind_label(self) -> str:
        if self.kind_override and self.kind in ("body", "cell"):
            return self.kind_override
        if self.kind == "box":
            return "枠（縦）" if self.vertical else "枠（横）"
        if self.kind == "cell":
            return "見出しの升"
        if _looks_like_name_lines(self.old_text):
            return "名前（1字ずつ）"
        if self.size_pt >= 13 and "\n" not in self.old_text.strip():
            return "見出し"
        return "本文"

    @property
    def short(self) -> str:
        t = re.sub(r"\s+", " ", strip_ruby(self.old_text)).strip()
        return t[:24] + ("…" if len(t) > 24 else "")


# 人が選び直せる種類。どれも本文の流れの中の段落なので、中身の作りは同じ。
# 文字枠・表の升目・本文は Word の中で入れ物が違うので、互いには変えられない
KIND_CHOICES = ("本文", "見出し", "名前（1字ずつ）")


def _looks_like_name_lines(text: str) -> bool:
    """「　長\n　村\n郎\n　太\n　田\n　山」のような、1 字ずつの行で
    組んだ名前か。縦書きの紙面で名前を横に並べるための組み方で、
    第201号の一般質問・行政報告の見出しに使われている。"""
    lines = [s.strip() for s in text.strip("\n").split("\n")]
    return len(lines) >= 3 and all(1 <= len(s) <= 2 for s in lines)


@dataclass
class _Ref:
    """欄が XML のどこにあるか（作業用。保存はしない）。"""
    slot: Slot
    parent: ET.Element | None = None        # 段落の親（body / tc / txbxContent）
    paras: list[ET.Element] = field(default_factory=list)
    boxes: list[ET.Element] = field(default_factory=list)   # txbxContent（複製ぶんも）
    shapes: list[ET.Element] = field(default_factory=list)  # v:shape / wps:wsp など
    anchor_run: ET.Element | None = None    # 枠をつなぎ留めている run
    anchor_para: ET.Element | None = None


# ---------------------------------------------------------------- 様式


class Template:
    """様式（前年の号の .docx）を開き、欄を見つけて差し込む。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            with zipfile.ZipFile(self.path) as z:
                self._blobs = {n: z.read(n) for n in z.namelist()}
        except zipfile.BadZipFile:
            raise ValueError(
                f"{self.path.name} は .docx ではありません。古い .doc の場合は、"
                "Word で開いて「名前を付けて保存」→「Word 文書（.docx）」で保存し直してください。")
        raw = self._blobs.get("word/document.xml")
        if raw is None:
            raise ValueError(f"{self.path.name} は Word の文書ではありません。")
        _register_namespaces(raw)
        self._open_tag = _root_open_tag(raw)
        self.root = _safe_parse(raw, self.path.name)
        self.body = self.root.find(w("body"))
        self.base_pt = self._default_pt()
        self._ids = 0
        self.refs: dict[str, _Ref] = {}
        self.order: list[str] = []
        self._scan()

    # -------------------------------------------------------------- 読み取り

    def _default_pt(self) -> float:
        raw = self._blobs.get("word/styles.xml")
        if raw:
            st = _safe_parse(raw, "styles.xml")
            sz = st.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}/{w('sz')}")
            if sz is not None and wval(sz).isdigit():
                return int(wval(sz)) / 2
        return 10.5

    def _sections(self) -> list[ET.Element]:
        """区間の区切り（sectPr）を文書順に。最後は body 直下のもの。"""
        out = [p.find(f"{w('pPr')}/{w('sectPr')}") for p in self.body if p.tag == w("p")]
        out = [s for s in out if s is not None]
        last = self.body.find(w("sectPr"))
        if last is not None:
            out.append(last)
        return out

    def _section_of(self) -> dict[int, int]:
        """body 直下の要素 → 区間番号。"""
        m, sec = {}, 0
        for child in self.body:
            m[id(child)] = sec
            if child.tag == w("p") and child.find(f"{w('pPr')}/{w('sectPr')}") is not None:
                sec += 1
        return m

    def geometry(self, section: int) -> Geometry:
        secs = self._sections()
        sect = secs[min(section, len(secs) - 1)] if secs else None
        # 空行の字の大きさ = その区間の本文の大きさ
        sizes: dict[float, int] = {}
        sec_of = self._section_of()
        for child in self.body:
            if child.tag == w("p") and sec_of[id(child)] == section and _is_blank(child):
                pt = _run_pt(child, self.base_pt)
                sizes[pt] = sizes.get(pt, 0) + 1
        base = max(sizes, key=sizes.get) if sizes else self.base_pt
        return _geometry(sect, base)

    def _new_id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}{self._ids:03d}"

    def _scan(self) -> None:
        """文書を頭から 1 回だけ読み、欄を紙面の順に並べる。"""
        sec_of = self._section_of()
        group = "表紙"
        buf: list[ET.Element] = []

        def add(ref: _Ref) -> None:
            nonlocal group
            s = ref.slot
            if (s.size_pt >= GROUP_HEAD_PT and s.old_text.strip() and s.section > 0
                    and not _looks_like_name_lines(s.old_text)):
                # 見出しの 1 行目だけを使う（枠の中に同じ見出しが重ねて書かれていることがある）
                first = next(t for t in strip_ruby(s.old_text).split("\n") if t.strip())
                group = re.sub(r"\s+", " ", first).strip()[:20]
            s.group = group
            self.refs[s.id] = ref
            self.order.append(s.id)

        def flush(section: int) -> None:
            if buf:
                text = "\n".join(para_text(p) for p in buf)
                geo_v = self._vertical_section(section)
                add(_Ref(Slot(self._new_id("B"), "body", text, section, geo_v,
                              max(_max_pt(p, self.base_pt) for p in buf)),
                         parent=self.body, paras=list(buf)))
            buf.clear()

        def boxes_in(el: ET.Element, section: int) -> None:
            for ref in self._find_boxes(el, section):
                add(ref)

        for child in list(self.body):
            section = sec_of[id(child)]
            if child.tag == w("p"):
                boxes_in(child, section)
                if _is_blank(child):
                    flush(section)
                else:
                    buf.append(child)
                if child.find(f"{w('pPr')}/{w('sectPr')}") is not None:
                    flush(section)
            elif child.tag == w("tbl"):
                flush(section)
                boxes_in(child, section)
                for tc in child.iter(w("tc")):
                    paras = [p for p in tc if p.tag == w("p")]
                    text = "\n".join(para_text(p) for p in paras)
                    if text.strip():
                        add(_Ref(Slot(self._new_id("C"), "cell", text, section,
                                      self._vertical_cell(tc, section),
                                      max(_max_pt(p, self.base_pt) for p in paras)),
                                 parent=tc, paras=paras))
            else:
                flush(section)
        flush(max(0, len(self._sections()) - 1))

    def _vertical_section(self, section: int) -> bool:
        secs = self._sections()
        if not secs:
            return False
        td = secs[min(section, len(secs) - 1)].find(w("textDirection"))
        return wval(td).startswith("tb")

    def _vertical_cell(self, tc: ET.Element, section: int) -> bool:
        td = tc.find(f"{w('tcPr')}/{w('textDirection')}")
        if td is not None:
            return wval(td).startswith("tb")
        return self._vertical_section(section)

    def _find_boxes(self, top: ET.Element, section: int) -> list[_Ref]:
        """要素の中の文字枠を、文書順に取り出す。

        mc:AlternateContent の Choice と Fallback は同じ枠の複製なので 1 つに束ね、
        差し込むときは両方に同じ内容を書く（片方だけだと Word と他のソフトで
        表示が食い違う）。枠の中の枠は描かれないので扱わない。
        """
        out: list[_Ref] = []
        seen: set[int] = set()
        parent_of = {id(c): p for p in top.iter() for c in p}

        def up(el, tag):
            while el is not None and el.tag != tag:
                el = parent_of.get(id(el))
            return el

        for tb in top.iter(w("txbxContent")):
            if id(tb) in seen:
                continue
            # 枠の中の枠は扱わない
            anc, nested = parent_of.get(id(tb)), False
            while anc is not None:
                if anc.tag == w("txbxContent"):
                    nested = True
                    break
                anc = parent_of.get(id(anc))
            if nested:
                continue
            alt = up(tb, f"{{{MC}}}AlternateContent")
            group = [x for x in alt.iter(w("txbxContent"))] if alt is not None else [tb]
            for x in group:
                seen.add(id(x))
            paras = [p for p in tb if p.tag == w("p")]
            text = "\n".join(para_text(p) for p in paras)
            if not text.strip():
                continue
            shapes = []
            for x in group:
                sh = x
                while sh is not None and sh.tag not in (f"{{{V}}}shape", f"{{{V}}}rect",
                                                        f"{{{V}}}roundrect", f"{{{WPS}}}wsp"):
                    sh = parent_of.get(id(sh))
                if sh is not None:
                    shapes.append(sh)
            run = up(alt if alt is not None else tb, w("r"))
            para = up(run, w("p")) if run is not None else None
            vertical = self._box_vertical(tb, parent_of)
            out.append(_Ref(
                Slot(self._new_id("T"), "box", text, section, vertical,
                     max(_max_pt(p, self.base_pt) for p in paras),
                     box_mm=self._box_mm(shapes, parent_of)),
                parent=tb, paras=paras, boxes=group, shapes=shapes,
                anchor_run=run, anchor_para=para))
        return out

    @staticmethod
    def _box_vertical(tb: ET.Element, parent_of: dict) -> bool:
        el = parent_of.get(id(tb))
        while el is not None:
            if el.tag == f"{{{V}}}textbox":
                return "layout-flow:vertical" in (el.get("style") or "")
            if el.tag == f"{{{WPS}}}wsp":
                bp = el.find(f"{{{WPS}}}bodyPr")
                return bp is not None and (bp.get("vert") or "") in ("vert", "eaVert", "wordArtVert")
            el = parent_of.get(id(el))
        return False

    @staticmethod
    def _box_mm(shapes: list[ET.Element], parent_of: dict) -> tuple[float, float] | None:
        for sh in shapes:
            if sh.tag == f"{{{WPS}}}wsp":
                el = parent_of.get(id(sh))
                while el is not None and el.tag not in (f"{{{WP}}}anchor", f"{{{WP}}}inline"):
                    el = parent_of.get(id(el))
                ext = el.find(f"{{{WP}}}extent") if el is not None else None
                if ext is not None:
                    return (int(ext.get("cx", 0)) / 36000, int(ext.get("cy", 0)) / 36000)
            else:
                st = _style_dict(sh.get("style", ""))
                wpt, hpt = _length_pt(st.get("width", "")), _length_pt(st.get("height", ""))
                if wpt and hpt:
                    return (wpt * 25.4 / 72, hpt * 25.4 / 72)
        return None

    # -------------------------------------------------------------- 一覧

    def slots(self) -> list[Slot]:
        return [self.refs[i].slot for i in self.order]

    # -------------------------------------------------------------- 複製・削除

    def duplicate(self, slot_id: str, new_id: str) -> Slot:
        """欄をもう 1 つ作る（前年に無い記事を足すため）。

        本文の記事は、元の記事の直後に空行 1 つを挟んで同じ段落を複製する。
        文字枠は、同じ場所に複製して少し（10mm）下へずらす。重なって
        見えなくならないようにするためで、正しい位置へは Word で動かす。
        """
        ref = self.refs[slot_id]
        s = ref.slot
        if s.kind == "cell":
            raise ValueError("見出しの升目は複製できません。Word で表ごと複製してください。")
        if s.kind == "body":
            last = ref.paras[-1]
            if last.find(f"{w('pPr')}/{w('sectPr')}") is not None:
                raise ValueError("区間の最後の記事は複製できません（ページの区切りが崩れるため）。")
            idx = list(self.body).index(last)
            blank = self._blank_like(last)
            clones = [copy.deepcopy(p) for p in ref.paras]
            for c in clones:
                _strip_ids(c)
                for r in _anchor_runs(c):     # 枠まで複製すると同じ枠が 2 つ重なる
                    c.remove(r)
            for k, el in enumerate([blank] + clones):
                self.body.insert(idx + 1 + k, el)
            new = _Ref(Slot(new_id, "body", s.old_text, s.section, s.vertical, s.size_pt,
                            s.group, copy_of=slot_id), parent=self.body, paras=clones)
        else:
            if ref.anchor_run is None or ref.anchor_para is None:
                raise ValueError("この枠は複製できません（つなぎ留めている場所が分かりません）。")
            run = copy.deepcopy(ref.anchor_run)
            _strip_ids(run)
            for node in run.iter():
                if node.tag in (f"{{{V}}}shape", f"{{{V}}}rect", f"{{{V}}}roundrect"):
                    node.set("id", f"_x0000_s{9000 + self._ids}")
                    node.attrib.pop(f"{{{O}}}spid", None)
                    st = _style_dict(node.get("style", ""))
                    top = _length_pt(st.get("margin-top", "0")) or 0
                    st["margin-top"] = f"{top + 10 * 72 / 25.4:.2f}pt"
                    node.set("style", _style_str(st))
                if node.tag == f"{{{WP}}}docPr":
                    node.set("id", str(9000 + self._ids))
                if node.tag == f"{{{WP}}}positionV":
                    off = node.find(f"{{{WP}}}posOffset")
                    if off is not None:
                        off.text = str(int(off.text or 0) + 360000)
            self._ids += 1
            ref.anchor_para.insert(list(ref.anchor_para).index(ref.anchor_run) + 1, run)
            found = self._find_boxes(run, s.section)
            if not found:
                raise ValueError("枠を複製できませんでした。")
            new = found[0]
            new.anchor_run, new.anchor_para = run, ref.anchor_para
            new.slot = Slot(new_id, "box", s.old_text, s.section, s.vertical, s.size_pt,
                            s.group, box_mm=s.box_mm, copy_of=slot_id)
        self.refs[new_id] = new
        self.order.insert(self.order.index(slot_id) + 1, new_id)
        return new.slot

    def split(self, slot_id: str, at: int, new_id: str) -> Slot:
        """欄を、at 番目の段落の前で 2 つに分ける（読み取りで 1 つにまとまりすぎたとき）。

        見出しと本文、2 つの記事が空行なしで続いていると 1 つの欄になる。
        分けた後ろ側は、元の欄と同じ入れ物（本文・升目・文字枠）のまま別の欄になる。
        """
        ref = self.refs[slot_id]
        if not 0 < at < len(ref.paras):
            raise ValueError("分ける位置は、欄の 2 行目から最後の行までの間で選んでください。")
        s = ref.slot
        tail = ref.paras[at:]
        ref.paras = ref.paras[:at]
        s.old_text = "\n".join(para_text(p) for p in ref.paras)
        s.size_pt = max(_max_pt(p, self.base_pt) for p in ref.paras)
        new = _Ref(Slot(new_id, s.kind, "\n".join(para_text(p) for p in tail), s.section,
                        s.vertical, max(_max_pt(p, self.base_pt) for p in tail), s.group,
                        box_mm=s.box_mm),
                   parent=ref.parent, paras=tail, boxes=ref.boxes, shapes=ref.shapes,
                   anchor_run=ref.anchor_run, anchor_para=ref.anchor_para)
        self.refs[new_id] = new
        self.order.insert(self.order.index(slot_id) + 1, new_id)
        return new.slot

    def merge(self, slot_id: str, expect: str = "") -> str:
        """欄を、すぐ後ろの同じ入れ物の欄とつなげる。つなげた相手の ID を返す。

        写真の場所として空けた空行で 1 つの記事が 2 つに分かれたときに使う。
        間にある空行や、そこにつなぎ留めた枠はそのまま残る（今年の原稿を入れると、
        記事のすぐ後ろへ回り、空行での位置合わせに使われる）。
        """
        ref = self.refs[slot_id]
        idx = self.order.index(slot_id)
        nxt = next((self.refs[i] for i in self.order[idx + 1:]
                    if self.refs[i].parent is ref.parent), None)
        if nxt is not None and expect and nxt.slot.id != expect:
            raise ValueError(f"つなげる相手が記録（{expect}）と違うので、つなげませんでした。")
        if nxt is None:
            raise ValueError("つなげられる欄が後ろにありません（本文どうし、または同じ枠の中どうしだけ"
                             "つなげられます）。")
        kids = list(ref.parent)
        a, b = kids.index(ref.paras[-1]), kids.index(nxt.paras[0])
        for k in kids[a + 1:b]:
            if k.tag != w("p") or not _is_blank(k):
                raise ValueError("間に本文や表があるので、つなげられません。")
        if ref.paras[-1].find(f"{w('pPr')}/{w('sectPr')}") is not None:
            raise ValueError("ページの区切り（区間の終わり）をまたいではつなげられません。")
        ref.paras = ref.paras + nxt.paras
        s = ref.slot
        s.old_text = "\n".join(para_text(p) for p in ref.paras)
        s.size_pt = max(s.size_pt, nxt.slot.size_pt)
        self.order.remove(nxt.slot.id)
        del self.refs[nxt.slot.id]
        return nxt.slot.id

    def set_kind(self, slot_id: str, label: str) -> None:
        s = self.refs[slot_id].slot
        if label and label not in KIND_CHOICES:
            raise ValueError(f"種類は {'・'.join(KIND_CHOICES)} から選んでください。")
        if label and s.kind == "box":
            raise ValueError("文字枠の種類は変えられません（縦書き・横書きは Word の枠の設定で決まります）。")
        s.kind_override = label

    def remove_box(self, slot_id: str) -> None:
        """文字枠そのものを消す（本文の記事は「空にする」で行を詰める）。"""
        ref = self.refs[slot_id]
        if ref.slot.kind != "box" or ref.anchor_run is None:
            raise ValueError("消せるのは文字枠だけです。本文は「空にする」を使ってください。")
        ref.anchor_para.remove(ref.anchor_run)
        self.order.remove(slot_id)
        del self.refs[slot_id]

    # -------------------------------------------------------------- 差し込み

    def fill(self, entries: dict[str, "Entry"], *, gou: str = "", hakkoubi: str = "",
             vote: VoteTable | None = None, mark_keep: bool = True,
             rep: "Report | None" = None) -> "Report":
        """欄ごとの内容を差し込む。結果（あふれ・前年のまま）を返す。"""
        rep = rep or Report()
        for sid in list(self.order):
            ref = self.refs[sid]
            s = ref.slot
            e = entries.get(sid) or Entry()
            mode = e.mode
            if mode == KEEP and s.section == 0 and (gou or hakkoubi):
                # 表紙の号数と発行日だけは、号の情報から自動で直す
                if self._fix_cover(ref, gou, hakkoubi):
                    rep.auto.append(s)
                    continue
            if mode == KEEP:
                if mark_keep:
                    self._highlight(ref)
                rep.kept.append(s)
                continue
            if mode == SAME:
                continue
            if mode == TABLE:
                if s.kind != "box":
                    rep.warnings.append(f"{s.short}: 賛否表は文字枠にしか入れられません。")
                    continue
                if vote is None:
                    rep.warnings.append(f"{s.short}: 賛否表の Excel が選ばれていません。")
                    continue
                self._put_vote_table(ref, vote)
                rep.tables.append(s)
                tier_mm = self._tier_height_mm(s.section)
                if s.box_mm and s.box_mm[1] > tier_mm:
                    rep.warnings.append(
                        f"賛否表の高さが約 {s.box_mm[1]:.0f}mm あり、1 段（約 {tier_mm:.0f}mm）を"
                        "超えます。上の段の本文と重なるので、Word で本文の空行を増やすか、"
                        "表の字を小さくしてください。")
                continue
            text = "" if mode == EMPTY else e.text
            if NUMBERS_TATEGAKI and s.vertical:
                text = normalize_numbers(text)
            self._write(ref, text, rep)
        return rep

    # 表紙 ------------------------------------------------------------

    _GOU = re.compile(r"第[0-9０-９]+号")
    _DATE = re.compile(r"(令和|平成)[0-9０-９元]+年[0-9０-９]+月[0-9０-９]+日")

    def _fix_cover(self, ref: _Ref, gou: str, hakkoubi: str) -> bool:
        # 号数・発行日を含む表紙の欄は、その部分だけを書式を保って直す。
        # 同じ欄の題字（ひだか議会だより）は毎号同じなので印は付けない
        text = ref.slot.old_text
        if not ((gou and self._GOU.search(text)) or (hakkoubi and self._DATE.search(text))):
            return False
        for p in ref.paras:
            if gou:
                _replace_in_para(p, self._GOU, "第" + gou.translate(_H2Z) + "号")
            if hakkoubi:
                _replace_in_para(p, self._DATE, hakkoubi.translate(_H2Z))
        return True

    # 前年のまま ------------------------------------------------------

    def _highlight(self, ref: _Ref) -> None:
        for p in ref.paras:
            for r in _text_runs(p):
                rpr = _ensure_rpr(r)
                _set_rpr(rpr, "highlight", {"val": KEEP_HIGHLIGHT})

    # 文字を入れ替える ------------------------------------------------

    def _write(self, ref: _Ref, text: str, rep: "Report") -> None:
        s = ref.slot
        old = ref.paras
        lines = text.split("\n") if text else [""]
        if s.kind_label == "名前（1字ずつ）" and text and "\n" not in text:
            lines = _name_to_lines(text, s.old_text)
        protos = old
        if s.kind_label == "見出し":
            # 見出しは、欄の中でいちばん大きい字の段落の書式でそろえる
            protos = [max(old, key=lambda p: _max_pt(p, self.base_pt))]
        new = [self._make_para(protos, i, line, s.vertical) for i, line in enumerate(lines)]
        if s.kind == "body" and not text:
            new = []            # 本文を空にするときは段落ごと消し、あとで空行で埋める

        # 枠をつなぎ留めている run は、同じ順番の段落へ移す
        for i, p in enumerate(old):
            for r in _anchor_runs(p):
                if not new:
                    new = [self._blank_like(old[-1])]
                target = new[min(i, len(new) - 1)]
                ppr = target.find(w("pPr"))
                target.insert(1 if ppr is not None else 0, r)
        # 区間の区切り（sectPr）は最後の段落に残す
        sect = next((p.find(f"{w('pPr')}/{w('sectPr')}") for p in old
                     if p.find(f"{w('pPr')}/{w('sectPr')}") is not None), None)
        if sect is not None:
            if not new:
                new = [self._blank_like(old[-1])]
            for p in new:
                ppr = p.find(w("pPr"))
                if ppr is not None:
                    for sp in ppr.findall(w("sectPr")):
                        ppr.remove(sp)
            ppr = new[-1].find(w("pPr"))
            if ppr is None:
                ppr = ET.Element(w("pPr"))
                new[-1].insert(0, ppr)
            _insert_ordered(ppr, sect, PPR_ORDER)

        parent = ref.parent
        kids = list(parent)
        at = kids.index(old[0])
        for p in old:
            parent.remove(p)
        for k, p in enumerate(new):
            parent.insert(at + k, p)
        if s.kind == "box" or s.kind == "cell":
            if not new:      # 枠と升目は段落が 1 つも無いと壊れる
                parent.insert(at, self._blank_like(old[0]))
        ref.paras = new

        if s.kind == "box":
            over = self._box_overflow(s, text)
            if over:
                rep.overflow_box.append((s, over))
        elif s.kind == "body":
            self._compensate(ref, old, new, rep)

    def _make_para(self, protos: list[ET.Element], i: int, line: str,
                   vertical: bool) -> ET.Element:
        proto = _pick_proto(protos, i, line)
        p = ET.Element(w("p"))
        ppr = proto.find(w("pPr"))
        if ppr is not None:
            ppr = copy.deepcopy(ppr)
            for sp in ppr.findall(w("sectPr")):
                ppr.remove(sp)
            p.append(ppr)
        label_rpr, body_rpr = _proto_rprs(proto, line)
        if label_rpr is not None:
            # 「質問」「答弁」など頭の言葉だけ見本の頭の書式にする
            label = _first_text(proto).strip()
            rest = line.lstrip("　 ")
            head = line[: len(line) - len(rest)] + label
            for r in _runs_for(head, label_rpr, vertical):
                p.append(r)
            line = rest[len(label):]
        for r in _runs_for(line, body_rpr, vertical):
            p.append(r)
        return p

    def _blank_like(self, p: ET.Element) -> ET.Element:
        """空行を 1 つ作る（段落の書式と字の大きさは p にそろえる）。"""
        b = ET.Element(w("p"))
        ppr = p.find(w("pPr"))
        if ppr is not None:
            ppr = copy.deepcopy(ppr)
            for sp in ppr.findall(w("sectPr")):
                ppr.remove(sp)
            b.append(ppr)
        return b

    # 空行で位置を保つ ------------------------------------------------

    def _lines(self, p: ET.Element, text: str | None, geo: Geometry) -> float:
        """段落が紙面で何行ぶん（本文の行の太さで数えて）使うか。"""
        pt = _run_pt(p, geo.base_pt)
        t = para_text(p) if text is None else text
        n = max(1, math.ceil(text_width(t, geo.vertical) / geo.chars_per_line(pt)))
        return n * max(1.0, pt / geo.base_pt)

    def _compensate(self, ref: _Ref, old: list[ET.Element], new: list[ET.Element],
                    rep: "Report") -> None:
        s = ref.slot
        geo = self.geometry(s.section)
        before = sum(self._lines(p, None, geo) for p in old) if old else 0
        # old はもう文書から外れているが、文字は残っているので数えられる
        after = sum(self._lines(p, None, geo) for p in new) if new else 0
        delta = round(after - before)
        if delta == 0 or not (new or old):
            return
        body = self.body
        kids = list(body)
        # 記事を空にして段落が 1 つも残らなかったときは、前の欄の直後が基準
        last = new[-1] if new else None
        if last is not None and last.find(f"{w('pPr')}/{w('sectPr')}") is not None:
            if delta > 0:
                rep.overflow_body.append((s, delta, geo))
            return
        at = kids.index(last) + 1 if last is not None else self._index_after_removed(ref)
        # 直後の空行の並び（枠をつなぎ留めている空行も 1 行と数えるが、消さない）
        run: list[ET.Element] = []
        for k in kids[at:]:
            if k.tag != w("p") or not _is_blank(k):
                break
            run.append(k)
            if k.find(f"{w('pPr')}/{w('sectPr')}") is not None:
                break
        if delta > 0:
            removable = [k for k in run if not _has_anchor(k)
                         and k.find(f"{w('pPr')}/{w('sectPr')}") is None]
            if run and len(removable) == len(run):
                removable = removable[1:]      # 記事と記事の間の空き 1 行は残す
            take = min(delta, len(removable))
            for k in removable[-take:] if take else []:
                body.remove(k)
            if delta > take:
                rep.overflow_body.append((s, delta - take, geo))
        else:
            proto = run[0] if run else (new[-1] if new else old[-1])
            for _ in range(-delta):
                body.insert(at, self._blank_like(proto))
            rep.added_blank += -delta

    def _index_after_removed(self, ref: _Ref) -> int:
        # 空にした記事は段落ごと消えている。その位置は「前の欄の最後」の次
        idx = self.order.index(ref.slot.id)
        for sid in reversed(self.order[:idx]):
            r = self.refs[sid]
            if r.slot.kind == "body" and r.paras and r.paras[-1] in list(self.body):
                return list(self.body).index(r.paras[-1]) + 1
        return 0

    def _box_overflow(self, s: Slot, text: str) -> float:
        """文字枠に入りきらない行数の目安（0 なら収まる見込み）。"""
        if not s.box_mm or not text.strip():
            return 0
        wmm, hmm = s.box_mm
        pt_mm = s.size_pt * 25.4 / 72
        along, across = (hmm, wmm) if s.vertical else (wmm, hmm)
        per_line = max(1, int((along - 3) / pt_mm))
        lines_cap = max(1, int((across - 1.5) / (pt_mm * 1.15)))
        need = sum(max(1, math.ceil(text_width(t, s.vertical) / per_line))
                   for t in text.split("\n"))
        return max(0, need - lines_cap)

    # 賛否表 ----------------------------------------------------------

    def _tier_height_mm(self, section: int) -> float:
        """1 段の高さ（mm）。縦書きの区間では、段の長さ＝紙面での高さ。"""
        return self.geometry(section).column_len_pt * 25.4 / 72

    def _put_vote_table(self, ref: _Ref, vote: VoteTable) -> None:
        """文字枠の中身を賛否表に入れ替え、枠を紙面の幅いっぱいに広げる。

        枠は横書きの文字枠なので、表は Excel と同じ向きのまま入る
        （縦書きの本文の中に直接置くと 90 度倒れてしまう）。
        """
        from vote_docx import build_vote_blocks, vote_table_height_mm

        width_mm = 176.0                   # 本文の幅 180mm より少し狭く（箱の内側の余白）
        for tb in ref.boxes:
            for ch in list(tb):
                tb.remove(ch)
            for el in build_vote_blocks(vote, width_mm - 4):
                tb.append(el)
        height_mm = vote_table_height_mm(vote, width_mm - 4) + 4
        for sh in ref.shapes:
            if sh.tag == f"{{{WPS}}}wsp":
                continue
            st = _style_dict(sh.get("style", ""))
            st["width"] = f"{width_mm * 72 / 25.4:.1f}pt"
            st["height"] = f"{height_mm * 72 / 25.4:.1f}pt"
            # 様式では、表の入るページの一番下の段が空けてある（第198〜201号）。
            # 大きくした枠がページからはみ出さないよう、余白の内側の下端・中央にそろえる
            for k in ("margin-left", "margin-top"):
                st[k] = "0"
            st["mso-position-horizontal"] = "center"
            st["mso-position-horizontal-relative"] = "margin"
            st["mso-position-vertical"] = "bottom"
            st["mso-position-vertical-relative"] = "margin"
            sh.set("style", _style_str(st))
            # VML では基準の取り方を w10:wrap の anchorx / anchory でも持っている
            wrap = sh.find(f"{{{W10}}}wrap")
            if wrap is None:
                wrap = ET.SubElement(sh, f"{{{W10}}}wrap")
            wrap.set("anchorx", "margin")
            wrap.set("anchory", "margin")
        ref.slot.box_mm = (width_mm, height_mm)

    # -------------------------------------------------------------- 保存

    def save(self, out: Path | str) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        blobs = dict(self._blobs)
        blobs["word/document.xml"] = _serialize(self.root, self._open_tag)
        tmp = out.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name in sorted(blobs, key=lambda n: (n != "[Content_Types].xml", n)):
                z.writestr(name, blobs[name])
        tmp.replace(out)
        return out


# ---------------------------------------------------------------- 段落を組む部品

# pPr と rPr の子要素は順番がスキーマで決まっている。順番を崩すと Word が開けない
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
             "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
             "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
             "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
             "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
             "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
             "sectPr", "pPrChange"]
RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
             "dstrike", "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid",
             "vanish", "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs",
             "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs",
             "em", "lang", "eastAsianLayout", "specVanish", "oMath"]


def _insert_ordered(parent: ET.Element, child: ET.Element, order: list[str]) -> None:
    local = child.tag.split("}")[1]
    for old in parent.findall(child.tag):
        parent.remove(old)
    rank = order.index(local) if local in order else len(order)
    for k, el in enumerate(list(parent)):
        name = el.tag.split("}")[1] if "}" in el.tag else el.tag
        if (order.index(name) if name in order else len(order)) > rank:
            parent.insert(k, child)
            return
    parent.append(child)


def _set_rpr(rpr: ET.Element, name: str, attrs: dict[str, str]) -> None:
    el = ET.Element(w(name), {w(k): v for k, v in attrs.items()})
    _insert_ordered(rpr, el, RPR_ORDER)


def _ensure_rpr(run: ET.Element) -> ET.Element:
    rpr = run.find(w("rPr"))
    if rpr is None:
        rpr = ET.Element(w("rPr"))
        run.insert(0, rpr)
    return rpr


def _text_runs(p: ET.Element) -> list[ET.Element]:
    """段落の文字の run（枠の中は含めない。ルビの中は含める）。"""
    out = []

    def walk(node):
        for ch in node:
            if _is_skip(ch.tag):
                continue
            if ch.tag == w("r") and (ch.find(w("t")) is not None or ch.find(w("ruby")) is not None):
                out.append(ch)
                for sub in ch.iter(w("r")):
                    if sub is not ch and sub.find(w("t")) is not None:
                        out.append(sub)
            elif ch.tag != w("r"):
                walk(ch)

    walk(p)
    return out


def _first_text(p: ET.Element) -> str:
    for r in p:
        if r.tag == w("r") and not _has_anchor(r):
            t = "".join(x.text or "" for x in r.findall(w("t")))
            if t.strip():
                return t
    return ""


def _clean_rpr(rpr: ET.Element | None) -> ET.Element | None:
    if rpr is None:
        return None
    rpr = copy.deepcopy(rpr)
    for name in ("eastAsianLayout", "highlight", "rPrChange", "ins", "del"):
        for el in rpr.findall(w(name)):
            rpr.remove(el)
    return rpr


def _proto_rprs(proto: ET.Element, line: str) -> tuple[ET.Element | None, ET.Element | None]:
    """見本の段落から、文字の書式を採る。

    「質問」「答弁」のように、段落の頭だけ書式が違う（太字など）ことがある。
    新しい行も同じ言葉で始まっていれば、頭とそれ以降で書式を分けて引き継ぐ。
    """
    runs = [r for r in proto if r.tag == w("r") and not _has_anchor(r)
            and "".join(x.text or "" for x in r.findall(w("t"))).strip()]
    if not runs:
        ppr_rpr = proto.find(f"{w('pPr')}/{w('rPr')}")
        return None, _clean_rpr(ppr_rpr)
    first = runs[0]
    rpr0 = _clean_rpr(first.find(w("rPr")))
    t0 = "".join(x.text or "" for x in first.findall(w("t"))).strip()
    if len(runs) >= 2 and 1 <= len(t0) <= 6 and line.lstrip().startswith(t0):
        rpr1 = _clean_rpr(runs[1].find(w("rPr")))
        if ET.tostring(rpr0 if rpr0 is not None else ET.Element("x")) != \
                ET.tostring(rpr1 if rpr1 is not None else ET.Element("x")):
            return rpr0, rpr1
    # 頭が空白だけの run は位置合わせ用なので、書式は中身の run から採る
    return None, rpr0


LABELS = ("質問", "答弁", "問", "答", "◎", "○", "●", "・", "※", "〈", "【")


def _pick_proto(protos: list[ET.Element], i: int, line: str) -> ET.Element:
    """新しい i 行目の書式の見本にする段落を選ぶ。

    同じ言葉（質問・答弁・◎ …）で始まる段落が見本の中にあればそれを、
    なければ同じ順番の段落（はみ出したら最後の段落）を使う。
    """
    head = line.lstrip("　 ")
    for lab in LABELS:
        if head.startswith(lab):
            for p in protos:
                if para_text(p).lstrip("　 ").startswith(lab):
                    return p
            break
    texty = [p for p in protos if not _is_blank(p)] or protos
    return texty[min(i, len(texty) - 1)]


_EA_ID = [100000]


def _t(text: str) -> ET.Element:
    t = ET.Element(w("t"))
    t.text = text
    if text != text.strip() or "  " in text:
        t.set(XML_SPACE, "preserve")
    return t


def _run(text: str, rpr: ET.Element | None, *, tcy: bool = False) -> ET.Element:
    r = ET.Element(w("r"))
    rp = copy.deepcopy(rpr) if rpr is not None else None
    if tcy:
        rp = rp if rp is not None else ET.Element(w("rPr"))
        _EA_ID[0] += 1
        _set_rpr(rp, "eastAsianLayout", {"id": str(_EA_ID[0]), "vert": "1", "vertCompress": "1"})
    if rp is not None and len(rp):
        r.append(rp)
    parts = text.split("\t")
    for k, part in enumerate(parts):
        if k:
            r.append(ET.Element(w("tab")))
        if part:
            r.append(_t(part))
    return r


def _ruby_run(base: str, reading: str, rpr: ET.Element | None) -> ET.Element:
    """ルビ（ふりがな）付きの run。第201号の特集で名前に振ってある形。"""
    size = 22
    if rpr is not None:
        sz = rpr.find(w("sz"))
        if sz is not None and wval(sz).isdigit():
            size = int(wval(sz))
    r = ET.Element(w("r"))
    if rpr is not None and len(rpr):
        r.append(copy.deepcopy(rpr))
    ruby = ET.SubElement(r, w("ruby"))
    pr = ET.SubElement(ruby, w("rubyPr"))
    for name, val in (("rubyAlign", "distributeSpace"), ("hps", str(max(2, size // 2))),
                      ("hpsRaise", str(size - 2)), ("hpsBaseText", str(size)),
                      ("lid", "ja-JP")):
        ET.SubElement(pr, w(name), {w("val"): val})
    small = copy.deepcopy(rpr) if rpr is not None else ET.Element(w("rPr"))
    _set_rpr(small, "sz", {"val": str(max(2, size // 2))})
    rt = ET.SubElement(ruby, w("rt"))
    rt.append(_run(reading, small))
    rb = ET.SubElement(ruby, w("rubyBase"))
    rb.append(_run(base, rpr))
    return r


def _runs_for(text: str, rpr: ET.Element | None, vertical: bool) -> list[ET.Element]:
    """文字列を run の並びにする（ルビと縦中横をここで作る）。"""
    out: list[ET.Element] = []
    pos = 0
    for m in RUBY.finditer(text):
        out += _plain_runs(text[pos:m.start()], rpr, vertical)
        base = m.group(1) or m.group(3)
        reading = m.group(2) or m.group(4)
        out.append(_ruby_run(base, reading, rpr))
        pos = m.end()
    out += _plain_runs(text[pos:], rpr, vertical)
    return out


def _plain_runs(text: str, rpr: ET.Element | None, vertical: bool) -> list[ET.Element]:
    if not text:
        return []
    if not vertical:
        return [_run(text, rpr)]
    out, pos = [], 0
    for m in TATECHUYOKO.finditer(text):
        if m.start() > pos:
            out.append(_run(text[pos:m.start()], rpr))
        out.append(_run(m.group(0), rpr, tcy=True))
        pos = m.end()
    if pos < len(text):
        out.append(_run(text[pos:], rpr))
    return out


def _replace_in_para(p: ET.Element, pattern: re.Pattern, repl: str) -> None:
    """書式を保ったまま、段落の中の文字の一部だけを置き換える。

    「第２０１号」の「第」と「２０１号」が別の run に分かれていても直せるよう、
    段落の w:t をつないで探し、最初にかかる w:t に置き換え後の文字を入れて、
    残りの w:t からは該当部分を削る。
    """
    ts = [t for r in _text_runs(p) for t in r.findall(w("t"))]
    joined = "".join(t.text or "" for t in ts)
    m = pattern.search(joined)
    if not m:
        return
    start, end = m.span()
    pos = 0
    placed = False
    for t in ts:
        s = t.text or ""
        a, b = pos, pos + len(s)
        pos = b
        if b <= start or a >= end:
            continue
        lo, hi = max(start, a) - a, min(end, b) - a
        if not placed:
            t.text = s[:lo] + repl + s[hi:]
            placed = True
        else:
            t.text = s[:lo] + s[hi:]
        if t.text != (t.text or "").strip():
            t.set(XML_SPACE, "preserve")


def _name_to_lines(name: str, old: str) -> list[str]:
    """「山田太郎　村長」を、1 字ずつの行（縦書きで横に並んで見える形）にする。

    縦書きでは段落が右から左へ並ぶので、名前は後ろの字から順に 1 行ずつ置く。
    行頭の空白（上下の位置合わせ）は前年の同じ順番の行から写す。
    """
    chars = [c for c in name if not c.isspace()]
    old_lines = old.strip("\n").split("\n")
    pads = [len(s) - len(s.lstrip("　 ")) for s in old_lines] or [0]
    out = []
    for k, ch in enumerate(reversed(chars)):
        out.append("　" * pads[min(k, len(pads) - 1)] + ch)
    return out


# ---------------------------------------------------------------- 結果


@dataclass
class Report:
    kept: list[Slot] = field(default_factory=list)
    auto: list[Slot] = field(default_factory=list)
    tables: list[Slot] = field(default_factory=list)
    overflow_body: list[tuple[Slot, int, Geometry]] = field(default_factory=list)
    overflow_box: list[tuple[Slot, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    added_blank: int = 0
    out: Path | None = None
    notes: list[str] = field(default_factory=list)      # 一般質問の組み直しの結果など

    def text(self) -> str:
        lines = []
        if self.out:
            lines.append(f"できあがり: {self.out}")
            lines.append("")
        if self.notes:
            lines += self.notes
            lines.append("")
        if self.auto:
            lines.append(f"表紙の号数・発行日を直しました（{len(self.auto)} か所）")
        if self.tables:
            lines.append(f"賛否表を入れました: {', '.join(s.short for s in self.tables)}")
            lines.append("  → 表の大きさに合わせて枠を広げました。本文と重なっていないか、"
                         "Word で確かめて位置を整えてください")
        if self.overflow_body:
            lines.append("")
            lines.append("■ 記事が前年より長く、すぐ後ろの空行では吸収しきれなかったところ"
                         "（以降の紙面がこの行数だけ後ろへずれます。目安）")
            for s, n, geo in self.overflow_body:
                lines.append(f"  ・{s.group} ／ {s.short}　約 {n} 行")
        if self.overflow_box:
            lines.append("")
            lines.append("■ 文字枠に入りきらないかもしれない欄（目安。Word で枠を広げるか、字を削る）")
            for s, n in self.overflow_box:
                lines.append(f"  ・{s.group} ／ {s.short}　約 {math.ceil(n)} 行はみ出し")
        if self.kept:
            lines.append("")
            lines.append(f"■ 前年のまま残した欄: {len(self.kept)} か所（黄色の印が付いています。"
                         "刷る前に直すか、印を消してください）")
            for s in self.kept[:60]:
                lines.append(f"  ・{s.group} ／ {s.short}")
            if len(self.kept) > 60:
                lines.append(f"  ほか {len(self.kept) - 60} か所")
        if self.warnings:
            lines.append("")
            lines += [f"！ {m}" for m in self.warnings]
        if not (self.overflow_body or self.overflow_box or self.kept or self.warnings):
            lines.append("気になるところは見つかりませんでした。")
        return "\n".join(lines)


# ---------------------------------------------------------------- 1 号 = 1 フォルダ


@dataclass
class Entry:
    mode: str = KEEP
    text: str = ""


@dataclass
class Issue:
    """1 号ぶんのフォルダ。

    第205号/
      号情報.json     号数・発行日・月号
      様式.docx       作るときに写した前年の号（あとで様式を差し替えても欄がずれないように）
      差し込み.json   欄ごとの内容
      別添/           賛否表の Excel など
      出力/           できあがった Word
    """
    folder: Path
    gou: str = ""
    hakkoubi: str = ""
    season: str = ""
    vote_xlsx: str = ""
    entries: dict[str, Entry] = field(default_factory=dict)
    # 欄の組み替え（複製・分ける・つなげる・枠を消す）を、やった順に記録する。
    # 様式を開くたびに頭からやり直すので、順番が大事（分けた欄をさらに複製する、など）
    ops: list[dict] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)  # 人が選び直した種類
    # 原稿から組み直す区分（flow.py。行政報告・委員会報告・一般質問）ごとの
    # 原稿ファイル（source）と、人が直した行の種類（kinds）
    flows: dict[str, dict] = field(default_factory=dict)

    @property
    def template_path(self) -> Path:
        return self.folder / TEMPLATE_NAME

    @classmethod
    def create(cls, parent: Path | str, gou: str, hakkoubi: str, season: str,
               template: Path | str) -> "Issue":
        gou = gou.strip().translate(_Z2H)
        if not gou.isdigit():
            raise ValueError("号数は数字で入れてください（例: 205）。")
        folder = Path(parent) / f"第{gou}号"
        if folder.exists() and any(folder.iterdir()):
            raise ValueError(f"{folder} はすでにあります。別の場所を選ぶか、そのフォルダを開いてください。")
        Template(template)                       # 読めない様式ならここで止める
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ATTACH_DIR).mkdir(exist_ok=True)
        (folder / OUT_DIR).mkdir(exist_ok=True)
        shutil.copy2(template, folder / TEMPLATE_NAME)
        issue = cls(folder, gou, hakkoubi.strip(), season)
        issue.save()
        return issue

    @classmethod
    def open(cls, folder: Path | str) -> "Issue":
        folder = Path(folder)
        info_path = folder / INFO_NAME
        if not info_path.exists():
            raise ValueError(f"{folder} は号のフォルダではありません（{INFO_NAME} がありません）。")
        info = json.loads(info_path.read_text(encoding="utf-8-sig"))
        issue = cls(folder, info.get("gou", ""), info.get("hakkoubi", ""), info.get("season", ""),
                    info.get("vote_xlsx", ""))
        data_path = folder / DATA_NAME
        if data_path.exists():
            data = json.loads(data_path.read_text(encoding="utf-8-sig"))
            issue.entries = {k: Entry(v.get("mode", KEEP), v.get("text", ""))
                             for k, v in data.get("slots", {}).items()}
            issue.ops = data.get("ops", [])
            # 最初の版の記録（copies / removed）も読めるようにしておく
            issue.ops[:0] = ([{"op": "copy", "src": c["src"], "id": c["id"]}
                              for c in data.get("copies", [])]
                             + [{"op": "remove", "id": i} for i in data.get("removed", [])])
            issue.kinds = data.get("kinds", {})
            issue.flows = data.get("flows", {})
            if data.get("ippan", {}).get("source") and "一般質問" not in issue.flows:
                issue.flows["一般質問"] = data["ippan"]     # 一般質問だけだった版の記録
        return issue

    def save(self) -> None:
        info = {"gou": self.gou, "hakkoubi": self.hakkoubi, "season": self.season,
                "vote_xlsx": self.vote_xlsx}
        _write_json(self.folder / INFO_NAME, info)
        data = {"version": 1,
                "slots": {k: asdict(v) for k, v in self.entries.items()
                          if v.mode != KEEP or v.text},
                "ops": self.ops, "kinds": self.kinds,
                "flows": {k: v for k, v in self.flows.items() if v.get("source") or v.get("kinds")}}
        _write_json(self.folder / DATA_NAME, data)

    # 様式を開いて、これまでの複製・削除をやり直した状態にする
    def load_template(self) -> Template:
        tpl = Template(self.template_path)
        for op in self.ops:
            kind = op.get("op")
            sid = op.get("src") if kind == "copy" else op.get("id")
            if sid not in tpl.refs:
                continue            # 元の欄が無い（様式が違う）ときは飛ばす
            try:
                if kind == "copy" and op["id"] not in tpl.refs:
                    tpl.duplicate(op["src"], op["id"])
                elif kind == "split" and op["new"] not in tpl.refs:
                    tpl.split(sid, int(op["at"]), op["new"])
                elif kind == "merge":
                    tpl.merge(sid, expect=op.get("with", ""))
                elif kind == "remove":
                    tpl.remove_box(sid)
            except ValueError:
                continue
        for sid, label in self.kinds.items():
            if sid in tpl.refs:
                try:
                    tpl.set_kind(sid, label)
                except ValueError:
                    pass
        return tpl

    def new_id(self, src: str, mark: str, tpl: "Template") -> str:
        """複製（+）・分けた後ろ側（/）の欄の ID。元の ID に番号を付ける。"""
        n = 1
        while f"{src}{mark}{n}" in tpl.refs or any(
                op.get("id") == f"{src}{mark}{n}" or op.get("new") == f"{src}{mark}{n}"
                for op in self.ops):
            n += 1
        return f"{src}{mark}{n}"

    def entry(self, sid: str) -> Entry:
        return self.entries.setdefault(sid, Entry())

    def vote_table(self) -> VoteTable | None:
        if not self.vote_xlsx:
            return None
        p = Path(self.vote_xlsx)
        if not p.is_absolute():
            p = self.folder / p
        return read_vote_table(p)

    def flow_source(self, key: str) -> str:
        return self.flows.get(key, {}).get("source", "")

    def flow_kinds(self, key: str) -> dict[str, str]:
        return self.flows.setdefault(key, {}).setdefault("kinds", {})

    def set_flow_source(self, key: str, path: str) -> None:
        self.flows.setdefault(key, {})["source"] = path

    def flow_path(self, key: str) -> Path | None:
        src = self.flow_source(key)
        if not src:
            return None
        p = Path(src)
        return p if p.is_absolute() else self.folder / p

    def flow_read(self, key: str):
        """区分の原稿を読み、(行の一覧, まとまり, 気になる点, 要約) を返す。"""
        import flow
        return flow.read_flow(key, import_manuscript(self.flow_path(key)), self.flow_kinds(key))

    def build(self, *, mark_keep: bool = True) -> Report:
        tpl = self.load_template()
        vote = None
        warn = []
        rep = Report()
        # 行政報告・委員会報告・一般質問は、原稿が選んであれば、前年の文字を入れ替えるの
        # ではなく部品で組み直す（flow.py）。差し込みより先に行う（前年の長さは、
        # 手を加える前の様式で測るため）
        import flow
        for key in flow.FLOW_KEYS:
            if not self.flow_source(key):
                continue
            try:
                _, groups, warns, _ = self.flow_read(key)
                res = flow.apply_flow(tpl, key, groups)
                rep.notes.append(res.text())
                warn += [f"{key}の原稿: {m}" for m in warns]
            except (OSError, ValueError) as e:
                warn.append(f"{key}を組み直せませんでした（前年の形のまま残します）: {e}")
        if any(e.mode == TABLE for e in self.entries.values()):
            try:
                vote = self.vote_table()
            except (OSError, ValueError) as e:
                warn.append(str(e))
        rep = tpl.fill(self.entries, gou=self.gou, hakkoubi=self.hakkoubi, vote=vote,
                       mark_keep=mark_keep, rep=rep)
        rep.warnings[:0] = warn
        out = self.folder / OUT_DIR / f"第{self.gou}号.docx"
        try:
            rep.out = tpl.save(out)
        except PermissionError:
            raise ValueError(f"{out.name} を書き込めませんでした。Word で開いたままなら閉じてから、もう一度押してください。")
        return rep


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- 原稿の取り込み


def read_text_file(path: Path | str) -> str:
    """文字コードを自動判別してテキストを読む（UTF-8 → CP932 → EUC-JP）。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp932", "euc_jp"):
        try:
            return raw.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def docx_to_text(path: Path | str) -> str:
    """議員から届いた .docx の文字（本文・表・文字枠）を段落ごとに取り出す。"""
    with zipfile.ZipFile(path) as z:
        root = _safe_parse(z.read("word/document.xml"), Path(path).name)
    lines = []
    for p in root.iter(w("p")):          # 文字枠の中の段落もここで拾われる
        t = para_text(p)
        if t.strip() or not _has_anchor(p):
            lines.append(t)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def import_manuscript(path: Path | str) -> str:
    """原稿ファイル（.docx / .doc / .txt）から文字だけを取り出す。"""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        return docx_to_text(path)
    if ext == ".doc":
        return doc97.extract_text(path)
    if ext in (".txt", ".text", ".md"):
        return read_text_file(path)
    raise ValueError(f"この形式は取り込めません: {path.name}（.docx / .doc / .txt に対応）")


# ---------------------------------------------------------------- 原稿を欄へ振り分ける

HEADING, BODY = "見出し", "本文"
# 振り分けで、見出しのまとまりを入れてよい欄の種類
HEADING_KINDS = ("見出し", "見出しの升")
# この大きさ以上の字の文字枠（区分の大見出し・一般質問の質問題・「人事」「条例」の
# 14pt の枠）も見出しを受け取る。写真の説明文の枠（10.5〜11pt）は原稿に書かれて
# いないことが多いので飛ばす
HEADING_BOX_PT = 13


def accepts(slot: Slot, kind: str) -> bool:
    """その欄に、見出し／本文のまとまりを入れてよいか（振り分け案で使う）。"""
    if kind == HEADING:
        return slot.kind_label in HEADING_KINDS or (slot.kind == "box" and slot.size_pt >= HEADING_BOX_PT)
    return slot.kind_label == BODY


@dataclass
class Block:
    """取り込んだ原稿の 1 まとまり（見出し 1 行、または次の見出しまでの本文）。"""
    kind: str        # HEADING / BODY
    text: str

    @property
    def short(self) -> str:
        t = re.sub(r"\s+", " ", self.text).strip()
        return t[:30] + ("…" if len(t) > 30 else "")


def _looks_like_heading_text(line: str, next_line: str | None) -> bool:
    """書式の分からない原稿（.doc / .txt）で、見出しらしい行か。

    短く（25 字まで）、句点で終わらず、「質問」「答弁」などで始まらない行を見出しとみなす。
    後ろに本文が続かない行（原稿の最後の署名など）は見出しにしない。
    """
    t = line.strip("　 \t")
    if not t or len(t) > 25 or t.endswith(("。", "、", "）", ")")):
        return False
    if t.startswith(LABELS) or re.match(r"^[（(]?[0-9０-９一二三四五六七八九十]+[)）.．、]", t):
        return False
    return next_line is not None and len(next_line.strip()) > len(t)


def _docx_paragraphs(path: Path) -> list[tuple[str, bool]]:
    """.docx の段落を (文字, 書式から見て見出しか) で返す。

    見出しの手がかり: 「見出し」スタイル（アウトラインのレベル付き）、
    段落の文字がすべて太字、本文よりはっきり大きい字（2pt 以上）。
    """
    with zipfile.ZipFile(path) as z:
        root = _safe_parse(z.read("word/document.xml"), path.name)
        try:
            styles = _safe_parse(z.read("word/styles.xml"), "styles.xml")
        except KeyError:
            styles = None
    heading_styles = set()
    if styles is not None:
        for st in styles.iter(w("style")):
            name = wval(st.find(w("name"))).lower()
            if ("heading" in name or "見出し" in name or name in ("title", "表題")
                    or st.find(f"{w('pPr')}/{w('outlineLvl')}") is not None):
                heading_styles.add(st.get(w("styleId"), ""))
    body = root.find(w("body"))
    paras = [p for p in body.iter(w("p"))] if body is not None else []
    sizes: dict[float, int] = {}
    info = []
    for p in paras:
        t = para_text(p)
        runs = [r for r in _text_runs(p) if "".join(x.text or "" for x in r.findall(w("t"))).strip()]
        pts = [_run_pt(p, 10.5)]
        for r in runs:
            sz = r.find(f"{w('rPr')}/{w('sz')}")
            if sz is not None and wval(sz).isdigit():
                pts.append(int(wval(sz)) / 2)
        pt = max(pts)
        if t.strip():
            sizes[pt] = sizes.get(pt, 0) + len(t)
        bold = bool(runs) and all(
            (b := r.find(f"{w('rPr')}/{w('b')}")) is not None and wval(b, "1") not in ("0", "false")
            for r in runs)
        style = wval(p.find(f"{w('pPr')}/{w('pStyle')}"))
        outline = p.find(f"{w('pPr')}/{w('outlineLvl')}") is not None
        info.append((t, pt, bold, style in heading_styles or outline))
    base = max(sizes, key=sizes.get) if sizes else 10.5
    out = []
    for t, pt, bold, styled in info:
        short = len(t.strip()) <= 40 and not t.strip().endswith("。")
        out.append((t, bool(t.strip()) and (styled or (short and (bold or pt >= base + 2)))))
    return out


def split_manuscript(path: Path | str) -> list[Block]:
    """原稿ファイルを、見出しと本文のまとまりに分ける。

    議員から届く原稿は、見出しと本文が 1 つのファイルに続けて書かれている。
    そのまま 1 つの欄に入れると、欄ごとに 1 つずつ写し直す手間がかかるので、
    まとまりに分けてから欄へ振り分ける（assign_blocks）。
    """
    path = Path(path)
    if path.suffix.lower() == ".docx":
        paras = _docx_paragraphs(path)
        styled = any(h for _, h in paras)
    else:
        text = import_manuscript(path)
        paras = [(t, False) for t in text.split("\n")]
        styled = False
    lines = [t for t, _ in paras]
    blocks: list[Block] = []
    body: list[str] = []

    def flush() -> None:
        while body and not body[-1].strip():
            body.pop()
        if body:
            blocks.append(Block(BODY, "\n".join(body)))
        body.clear()

    for i, (t, is_head) in enumerate(paras):
        nxt = next((x for x in lines[i + 1:] if x.strip()), None)
        # 書式に見出しの印が 1 つも無い原稿は、行の形から見分ける
        if is_head or (not styled and _looks_like_heading_text(t, nxt)):
            flush()
            blocks.append(Block(HEADING, t.strip("　 \t")))
        elif t.strip():
            body.append(t)
        elif body:
            flush()           # 空行も本文の区切りにする
    flush()
    return blocks


def _same_start(a: str, b: str) -> bool:
    a = re.sub(r"[\s　]", "", strip_ruby(a))[:6]
    b = re.sub(r"[\s　]", "", strip_ruby(b))[:6]
    return len(a) >= 2 and a == b


# 振り分けの手間（小さいほどよい）。前から順に詰めるだけだと、1 か所ずれると
# 後ろがすべてずれた（第201号で確かめて 26 のうち 8 しか合わなかった）ので、
# 全体でいちばん手間の少ない組み合わせを探す
COST_SKIP_SLOT = 1.0       # 様式の欄を使わずに飛ばす（前年のまま残る）
COST_SKIP_MINOR = 0.1      # 写真の説明文・名前など、原稿に無いのがふつうの欄を飛ばす
COST_APPEND = 0.6          # 本文を、前の本文と同じ欄につなげる
COST_DROP = 3.0            # まとまりをどの欄にも入れない
BONUS_SAME = 0.8           # 前年と同じ言葉で始まる（毎年ある「防災訓練」など）


def assign_blocks(blocks: list[Block], slots: list[Slot], start_id: str) -> list[str | None]:
    """まとまりを、start_id の欄から紙面の順に欄へ当てはめる案を作る。

    見出しは「見出し」「見出しの升」と大きい字の文字枠へ、本文は「本文」の欄へ入れる。
    順番は入れ替えない。そのうえで次の手を組み合わせ、手間の合計が最小の案を選ぶ
    （動的計画法）。
      * 欄を飛ばす（写真の説明文の枠・名前の欄は安く、それ以外は高めに）
      * 本文を前の本文と同じ欄につなげる（原稿の方が細かく分かれているとき）
      * 合う欄が無いまとまりは入れない（後ろをずらさないため）
    案なので、必ず画面で人が確かめてから反映する。
    """
    ids = [s.id for s in slots]
    cand = slots[ids.index(start_id):] if start_id in ids else slots
    n, m = len(blocks), len(cand)
    INF = float("inf")
    # best[i][j][f]: i 個のまとまりを入れ、次に使える欄が j。f=1 は「直前のまとまりを
    # 欄 j-1 に入れた」（本文のつなげ足しができる）
    best = [[[INF, INF] for _ in range(m + 1)] for _ in range(n + 1)]
    back: dict[tuple[int, int, int], tuple[int, int, int, str | None]] = {}
    best[0][0][0] = 0.0

    def relax(i, j, f, cost, prev, choice):
        if cost < best[i][j][f]:
            best[i][j][f] = cost
            back[(i, j, f)] = (*prev, choice)

    for i in range(n + 1):
        for j in range(m + 1):
            for f in (0, 1):
                c = best[i][j][f]
                if c == INF:
                    continue
                if j < m:        # 欄を飛ばす
                    minor = cand[j].kind == "box" and not accepts(cand[j], HEADING) \
                        or cand[j].kind_label == "名前（1字ずつ）"
                    relax(i, j + 1, 0, c + (COST_SKIP_MINOR if minor else COST_SKIP_SLOT),
                          (i, j, f), "skip")
                if i == n:
                    continue
                b = blocks[i]
                if j < m and accepts(cand[j], b.kind):      # この欄に入れる
                    bonus = BONUS_SAME if _same_start(b.text, cand[j].old_text) else 0
                    relax(i + 1, j + 1, 1, c - bonus, (i, j, f), cand[j].id)
                if f and b.kind == BODY and blocks[i - 1].kind == BODY:   # 前の欄につなげる
                    relax(i + 1, j, 1, c + COST_APPEND, (i, j, f), cand[j - 1].id)
                relax(i + 1, j, 0, c + COST_DROP, (i, j, f), None)     # 入れない

    # まとまりをすべて処理した状態のうち、いちばん安いもの（残りの欄は前年のまま）
    j, f = min(((j, f) for j in range(m + 1) for f in (0, 1)), key=lambda jf: best[n][jf[0]][jf[1]])
    i = n
    out: list[str | None] = [None] * n
    while (i, j, f) != (0, 0, 0):
        pi, pj, pf, choice = back[(i, j, f)]
        if pi == i - 1:
            out[pi] = choice
        i, j, f = pi, pj, pf
    return out


# ---------------------------------------------------------------- .doc を .docx に


def convert_doc_with_word(src: Path | str, dst: Path | str) -> Path:
    """Windows の Word で .doc を .docx に保存し直す（PowerShell 経由）。

    役場のパソコンには Word が入っているので、追加の部品なしで変換できる。
    パスは環境変数で渡す（日本語や空白を含むパスで引用符が崩れないように）。
    """
    import os
    import subprocess
    import sys

    if sys.platform != "win32":
        raise ValueError("自動の変換は Windows の Word でだけ行えます。"
                         "Word で開いて「名前を付けて保存」→「Word 文書（.docx）」で保存してください。")
    src, dst = Path(src).resolve(), Path(dst).resolve()
    script = (
        "$ErrorActionPreference='Stop';"
        "$w=New-Object -ComObject Word.Application;$w.Visible=$false;"
        "try{$d=$w.Documents.Open($env:GIKAI_SRC,$false,$true);"
        "$d.SaveAs2($env:GIKAI_DST,16);$d.Close($false)}finally{$w.Quit()}")
    env = dict(os.environ, GIKAI_SRC=str(src), GIKAI_DST=str(dst))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env=env, capture_output=True, text=True, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not dst.exists():
        raise ValueError("Word での変換に失敗しました。Word で開いて「名前を付けて保存」→"
                         "「Word 文書（.docx）」で保存してください。\n" + (r.stderr or "")[-500:])
    return dst
