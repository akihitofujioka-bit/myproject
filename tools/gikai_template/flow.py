"""一般質問を、様式の部品で組み直して流し込む。

前年の号の文字を入れ替える方式（core.Template.fill）は、前年と同じ構成のときは
本物と見分けがつかない。ところが一般質問は、立つ議員の人数も、1 人あたりの
質問の数も毎回違う。そこで一般質問だけは、前年の号から「部品」（題の表・
1 字ずつの名前・質問・答弁・本文・2 問目からの題）を取り出し、今年の原稿に
合わせて必要な数だけ並べ直す。

様式を調べて分かったこと（第198〜201号、2026-09-25）:
  * 本文は表紙のあとから 1 本の流れ（縦書き 5 段）。改ページは無く、文字枠は
    すべて段落につなぎ留めてある（ページに固定した枠は無い）。
    → 一般質問を組み直しても、後ろの記事は枠ごと一緒にずれるだけで崩れない
  * 議員 1 人ぶんの頭は「質問の題（1 升の表か文字枠。18〜28pt）」と
    「名前を 1 字ずつの行で組んだもの」。2 問目からの題は 14pt の段落
  * 議員の区切りは段の頭とは限らず、前の議員の続きから流れている
  * Mac の Word で第201号を測ると、1 段は 11pt の行で 36 行
    （1 行の太さは字の大きさの約 1.27 倍。14pt の行は 11pt の行の約 1.29 倍）

後ろの記事の位置を保つため、組み直した一般質問の長さを、空行で
「前年と同じ」か「ちょうど何ページ分か長い」ところまで埋める。
長さは行数の見積もりなので、最後は Word で確かめる前提。
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

import core
from core import (O, PPR_ORDER, V, WP, Template, _anchor_runs, _ensure_rpr, _has_anchor,
                  _insert_ordered, _is_blank, _name_to_lines, _replace_in_para, _set_rpr,
                  _strip_ids, _text_runs, normalize_numbers, para_text, text_width, w, wval)

# ---------------------------------------------------------------- 原稿の行の種類

MEMBER, TITLE, TEXT, PHOTO, SKIP = "議員名", "質問の題", "質問・答弁・本文", "写真", "使わない"
FLOW_KINDS = (MEMBER, TITLE, TEXT, PHOTO, SKIP)

INTRO = re.compile(r"一般質問に\s*([0-9０-９一二三四五六七八九十]+)\s*氏が立つ")
_INTRO_NUM = re.compile(r"(?<=一般質問に)[0-9０-９一二三四五六七八九十]+(?=氏)")
# 「山田太郎議員」「山田　太郎　議員」。名前は姓・名それぞれ 6 字まで
NAME_LINE = re.compile(
    r"^(?P<name>[^\s　。、，,「」（）()]{1,6}(?:[\s　]+[^\s　。、，,「」（）()]{1,6})?)[\s　]*議員$")
# gikai_simple の写真の指定行: 【写真】ファイル名｜大きさ｜説明
PHOTO_LINE = re.compile(
    r"^【写真】\s*(?P<file>[^｜|]+?)\s*(?:[｜|]\s*(?P<size>[^｜|]*?)\s*)?(?:[｜|]\s*(?P<caption>.*))?$")
PHOTO_MM = {"表紙": 180, "大": 80, "中": 55, "小": 38, "顔": 26}   # gikai_simple と同じ幅
QUESTION = re.compile(r"^(質問|問[\s　:：])")
LABELED = re.compile(r"^(質問|答弁|問[\s　:：]|答[\s　:：])")
TITLE_MAX = 25

# 様式の寸法（上の「分かったこと」を参照）
HEAD_PT = 18            # 議員ごとの題はこの大きさ以上
SUBTITLE_PT = 13        # 2 問目からの題（14pt）とみなす大きさ
TIER_LINES = 36         # 1 段に入る 11pt の行
PAGE_LINES = TIER_LINES * 5
LINE_MM = 11 * 1.27 * 25.4 / 72     # 11pt の行 1 本の太さ（約 4.9mm）
MEMBER_GAP = 2          # 議員と議員の間の空行


@dataclass
class Line:
    no: int          # 原稿の何行目か（1 から）
    text: str
    kind: str        # 使う種類（人が直していればそちら）
    auto: str        # 自動で見分けた種類
    raw: str = ""    # 行頭の字下げを残した元の行（本文に使う）


def _num(s: str) -> int:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    kan = "一二三四五六七八九"
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + kan.index(s[1]) + 1
    if "十" in s:
        a, _, b = s.partition("十")
        return (kan.index(a) + 1) * 10 + (kan.index(b) + 1 if b else 0)
    return kan.index(s) + 1 if s in kan else 0


def _title_like(t: str) -> bool:
    return (len(t) <= TITLE_MAX and not t.endswith(("。", "、"))
            and not LABELED.match(t) and not PHOTO_LINE.match(t))


def classify(text: str, overrides: dict[str, str] | None = None) -> list[Line]:
    """原稿の行ごとに種類を見分ける（空行は除く）。

    手がかり:
      * 「山田太郎議員」だけの行 → 議員名
      * 「質問　…」の直前にある短い行（句点で終わらない） → 質問の題
        （名前・写真の行はまたいで数え、2 行に分けた題もまとめて拾う）
      * 【写真】で始まる行 → 写真
      * 「一般質問に○氏が立つ」 → 使わない（人数は数えて入れ直す）
    人が確認画面で直した種類（overrides。行の文字をキーにする）を優先する。
    """
    overrides = overrides or {}
    raws = text.replace("\r\n", "\n").split("\n")
    items = [(i + 1, s.strip("　 \t")) for i, s in enumerate(raws)]
    items = [(n, s) for n, s in items if s]
    kinds = []
    for _, s in items:
        if INTRO.search(s) and len(s) <= 20:
            kinds.append(SKIP)
        elif PHOTO_LINE.match(s):
            kinds.append(PHOTO)
        elif NAME_LINE.match(s):
            kinds.append(MEMBER)
        else:
            kinds.append(TEXT)
    for i, (_, s) in enumerate(items):
        if kinds[i] != TEXT or not QUESTION.match(s):
            continue
        j, got = i - 1, 0
        while j >= 0 and got < 3:
            if kinds[j] in (MEMBER, PHOTO, SKIP):
                j -= 1
                continue
            if kinds[j] == TEXT and _title_like(items[j][1]):
                kinds[j] = TITLE
                got += 1
                j -= 1
                continue
            break
    return [Line(n, s, overrides.get(s, k) if overrides.get(s) in FLOW_KINDS else k, k,
                 raws[n - 1].rstrip())
            for (n, s), k in zip(items, kinds)]


@dataclass
class Topic:
    title: list[str]                                     # 題（行ごと。2 行に分けた題もある）
    lines: list[str] = field(default_factory=list)       # 質問・答弁・本文・【写真】行


@dataclass
class Member:
    name: str
    head_photos: list[str] = field(default_factory=list)  # 題より前の写真（顔写真など）
    topics: list[Topic] = field(default_factory=list)


def group(lines: list[Line]) -> tuple[list[Member], list[str]]:
    """種類の付いた行を、議員 → 質問の題 → 本文 の形にまとめる。"""
    members: list[Member] = []
    warns: list[str] = []
    pending: list[str] = []
    cur: Member | None = None
    topic: Topic | None = None

    def member_for(no: int) -> Member:
        nonlocal cur
        if cur is None:
            cur = Member("")
            members.append(cur)
            warns.append(f"{no} 行目: 議員名の行より前に質問があります。"
                         "名前の行（例: 山田太郎議員）を足すか、種類を直してください。")
        return cur

    for ln in lines:
        if ln.kind == SKIP:
            continue
        if ln.kind == MEMBER:
            m = NAME_LINE.match(ln.text)
            cur = Member(re.sub(r"[\s　]+", "", m.group("name") if m else ln.text))
            members.append(cur)
            topic = None          # 名前より前に書いた題（pending）は、この議員の最初の題
            continue
        if ln.kind == TITLE:
            pending.append(ln.text)
            continue
        if ln.kind == PHOTO and topic is None:
            member_for(ln.no).head_photos.append(ln.text)
            continue
        mem = member_for(ln.no)
        if pending:
            topic = Topic(pending)
            pending = []
            mem.topics.append(topic)
        elif topic is None:
            topic = Topic([])
            mem.topics.append(topic)
            warns.append(f"{ln.no} 行目: {mem.name or '（名前なし）'}議員の最初の質問に題がありません。")
        topic.lines.append(ln.text if ln.kind == PHOTO else (ln.raw or ln.text))
    if pending:
        warns.append(f"題「{pending[0]}」のあとに質問・答弁がありません。")
    for m in members:
        if not m.topics:
            warns.append(f"{m.name or '（名前なし）'}議員に質問がありません。")
    return members, warns


def summary(members: list[Member]) -> str:
    n = sum(len(m.topics) for m in members)
    return f"議員 {len(members)} 人・質問の題 {n} 件"


# ---------------------------------------------------------------- 様式から部品を取り出す


def _all_text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(w("t")))


def _big_text(el: ET.Element, pt: float) -> str:
    """pt 以上の字だけをつないだ文字（文字枠の中も含む）。"""
    out = []
    for r in el.iter(w("r")):
        sz = r.find(f"{w('rPr')}/{w('sz')}")
        if sz is not None and wval(sz).isdigit() and int(wval(sz)) / 2 >= pt:
            out.append("".join(t.text or "" for t in r.findall(w("t"))))
    return "".join(out)


def _own_pt(p: ET.Element, default: float) -> float:
    """段落そのものの字の大きさ（つなぎ留めた文字枠の中の字は数えない）。"""
    for r in p.findall(w("r")):
        if (r.findtext(w("t")) or "").strip():
            sz = r.find(f"{w('rPr')}/{w('sz')}")
            if sz is not None and wval(sz).isdigit():
                return int(wval(sz)) / 2
            break
    sz = p.find(f"{w('pPr')}/{w('rPr')}/{w('sz')}")
    if sz is not None and wval(sz).isdigit():
        return int(wval(sz)) / 2
    return default


@dataclass
class Parts:
    start: int                      # 「一般質問に○氏が立つ」の要素（body の中の番号）
    end: int                        # 次の区分の頭。start の次からこの手前までを作り直す
    old_count: int                  # 前年の人数
    head: list[ET.Element]          # 議員 1 人ぶんの頭（題の段落の見本・空行・名前）
    name_at: tuple[int, int] | None  # head の中の 1 字ずつの名前の範囲（なければ None）
    q: ET.Element
    a: ET.Element | None
    body: ET.Element
    subtitle: ET.Element | None
    blank: ET.Element


def _first_para(region: list[ET.Element], ok) -> ET.Element | None:
    for el in region:
        if el.tag == w("p") and ok(el):
            return el
    return None


def _name_group(paras: list[ET.Element]) -> tuple[int, int] | None:
    """1 字ずつの行で組んだ名前（連続する段落）の範囲。いちばん長いもの。"""
    best, i = None, 0
    while i < len(paras):
        j = i
        while (j < len(paras) and paras[j].tag == w("p")
               and 1 <= len(para_text(paras[j]).strip("　 ")) <= 2):
            j += 1
        if j - i >= 3 and (best is None or j - i > best[1] - best[0]):
            best = (i, j)
        i = max(j, i + 1)
    return best


def extract_parts(tpl: Template) -> Parts:
    kids = list(tpl.body)
    start = next((i for i, el in enumerate(kids) if INTRO.search(_all_text(el))), None)
    if start is None:
        raise ValueError("様式に「一般質問に○氏が立つ」が見つからないので、一般質問を組み直せません。")
    old_count = _num(INTRO.search(_all_text(kids[start])).group(1))
    heads: list[int] = []
    end = len(kids) - 1 if kids[-1].tag == w("sectPr") else len(kids)
    for i in range(start + 1, len(kids)):
        el = kids[i]
        if el.tag not in (w("p"), w("tbl")) or not _big_text(el, HEAD_PT).strip():
            continue
        if len(heads) == old_count:
            end = i
            break
        heads.append(i)
    if not heads:
        raise ValueError("様式の一般質問に、議員ごとの題（18pt 以上の字）が見つかりません。")
    base = tpl.base_pt
    # 最後の議員のあとには、大きな見出しの無い記事（写真の説明・お知らせ）が続くことがある
    # （第199号）。終わりは「最後の質問・答弁と、それに続く本文の段落」の次にする
    last_qa, i = None, heads[-1] + 1
    while i < end:
        el = kids[i]
        if el.tag == w("p") and LABELED.match(para_text(el).strip("　 ")):
            i += 1
            while (i < end and kids[i].tag == w("p") and not _is_blank(kids[i])
                   and not LABELED.match(para_text(kids[i]).strip("　 "))
                   and _own_pt(kids[i], base) < SUBTITLE_PT):
                i += 1
            last_qa = i
            continue
        i += 1
    if last_qa is not None:
        end = last_qa

    # 議員ごとの頭（題から最初の「質問」の手前まで）を比べ、いちばん整ったものを見本にする
    best = None
    for k, h in enumerate(heads):
        stop = heads[k + 1] if k + 1 < len(heads) else end
        head = [kids[h]]
        for el in kids[h + 1:stop]:
            if el.tag == w("p") and QUESTION.match(para_text(el).strip("　 ")):
                break
            head.append(el)
        grp = _name_group(head[1:])
        score = 0
        if kids[h].tag == w("tbl"):
            score += 2                      # 題が 1 升の表（題の字の書式を素直に採れる）
        if grp:
            chars = {para_text(p).strip("　 ") for p in head[1 + grp[0]:1 + grp[1]]}
            if "議" in chars and "員" in chars:
                score += 3                  # 名前が「議員」まで 1 字ずつそろっている
        if not _big_text(kids[h], HEAD_PT).rstrip("　 ").endswith("員"):
            score += 1                      # 名前の一部が題の枠の中に書かれていない
        if best is None or score > best[0]:
            best = (score, head, grp)
    _, head, grp = best
    # 見本の頭: 題・名前・その間の空行だけを残す（写真の説明の枠などは持ち込まない）
    keep_to = 1 + grp[1] if grp else 1
    sample, blanks = [head[0]], 0
    for k, el in enumerate(head[1:keep_to]):
        if el.tag != w("p"):
            continue
        if grp and k >= grp[0]:
            sample.append(el)
        elif _is_blank(el):
            # 題と名前の間の空行は、前年の写真の場所のことがある。2 行までにする
            # （今年の顔写真は【写真】行の大きさで場所を空ける）
            blanks += 1
            if blanks <= 2:
                sample.append(el)
    sample = [copy.deepcopy(el) for el in sample]
    for el in sample[1:]:
        for r in _anchor_runs(el):
            el.remove(r)
    # 題は、様式の表・文字枠の中のいちばん大きい字の段落を見本にして、罫線で囲んだ
    # 段落として本文の流れに置く。様式の表や枠は前年の題の長さで寸法が決めてあり、
    # 本文の外に浮かせてあるため、そのまま使うと重なったり、段の境目で切れたり、
    # 紙の端からはみ出したりする（第198・201号で確かめた）。段落なら Word が本文と
    # 同じように段・ページを送る
    sample[0] = _title_proto(sample[0], base)
    name_at = None
    if grp:
        # 名前の前にある空行は残るので、見本の中での位置を数え直す
        texts = [para_text(el).strip("　 ") for el in sample]
        lo = next(i for i in range(1, len(sample)) if 1 <= len(texts[i]) <= 2)
        name_at = (lo, len(sample))
    region = kids[start + 1:end]

    def label(p, *labs):
        return para_text(p).strip("　 ").startswith(labs)

    q = _first_para(region, lambda p: label(p, "質問", "問"))
    if q is None:
        raise ValueError("様式の一般質問に「質問」で始まる段落が見つかりません。")
    a = _first_para(region, lambda p: label(p, "答弁", "答"))
    body = _first_para(region, lambda p: (
        not LABELED.match(para_text(p).strip("　 ")) and len(para_text(p).strip()) >= 10
        and _own_pt(p, base) < SUBTITLE_PT and not _has_anchor(p))) or q
    subtitle = _first_para(region, lambda p: (
        para_text(p).strip() and SUBTITLE_PT <= _own_pt(p, base) < HEAD_PT and not _has_anchor(p)))
    blank = _first_para(region, lambda p: (
        _is_blank(p) and not _has_anchor(p) and abs(_own_pt(p, base) - base) < 0.6)) or \
        _first_para(region, lambda p: _is_blank(p) and not _has_anchor(p))
    if blank is None:
        blank = ET.Element(w("p"))
    return Parts(start, end, old_count, sample, name_at, q, a, body, subtitle, blank)


def _title_proto(el: ET.Element, base: float) -> ET.Element:
    """題の表・文字枠から、題の段落の見本（罫線で囲んだ段落）を作る。"""
    boxes = [x for x in el.iter(w("txbxContent")) if _all_text(x).strip()] or \
        [x for x in el.iter(w("tc")) if _all_text(x).strip()]
    paras = [x for box in boxes[:1] for x in box if x.tag == w("p")]
    if not paras and el.tag == w("p"):
        paras = [el]
    # 字のある段落から選ぶ（枠の中の空の段落は、字の大きさだけ大きいことがある）
    texty = [x for x in paras if para_text(x).strip()] or paras
    proto = copy.deepcopy(max(texty, key=lambda x: core._max_pt(x, base)))
    for r in _anchor_runs(proto):
        proto.remove(r)
    ppr = proto.find(w("pPr"))
    if ppr is None:
        ppr = ET.Element(w("pPr"))
        proto.insert(0, ppr)
    for tag in ("sectPr", "framePr", "pBdr", "ind", "jc"):
        for x in ppr.findall(w(tag)):
            ppr.remove(x)
    bdr = ET.Element(w("pBdr"))
    for side in ("top", "left", "bottom", "right"):
        ET.SubElement(bdr, w(side), {w("val"): "single", w("sz"): "4", w("space"): "4",
                                     w("color"): "auto"})
    _insert_ordered(ppr, bdr, PPR_ORDER)
    return proto


# ---------------------------------------------------------------- 行数の見積もり


def _para_lines(p: ET.Element, cpl, base: float) -> float:
    pt = _own_pt(p, base)
    n = max(1, math.ceil(text_width(para_text(p), True) / cpl(pt)))
    return n * max(1.0, pt / base)


def element_lines(el: ET.Element, cpl, base: float) -> float:
    """要素が紙面で使う太さ（11pt の行の本数で数える）。"""
    if el.tag == w("p"):
        return _para_lines(el, cpl, base)
    if el.tag == w("tbl"):
        total = 0.0
        for tr in el.findall(w("tr")):
            cells = [sum(_para_lines(p, cpl, base) for p in tc.findall(w("p")))
                     for tc in tr.findall(w("tc"))]
            total += max(cells or [1.0])
        return total + 0.5                      # 罫線と升の内側の余白
    return 0.0


def _positions(tpl: Template, cpl) -> list[float]:
    """本文の区間の頭からの位置（行）。区間の区切り（改ページ）で次のページの頭へ進める。"""
    kids = list(tpl.body)
    first = next((i + 1 for i, el in enumerate(kids)
                  if el.tag == w("p") and el.find(f"{w('pPr')}/{w('sectPr')}") is not None), 0)
    pos, out = 0.0, []
    for i, el in enumerate(kids):
        out.append(pos)
        if i < first:
            continue
        pos += element_lines(el, cpl, tpl.base_pt)
        if el.tag == w("p") and el.find(f"{w('pPr')}/{w('sectPr')}") is not None:
            sect = el.find(f"{w('pPr')}/{w('sectPr')}")
            if wval(sect.find(w("type")), "nextPage") in ("nextPage", "oddPage", "evenPage"):
                pos = math.ceil(pos / PAGE_LINES) * PAGE_LINES
    return out


# ---------------------------------------------------------------- 組み立て


class _Builder:
    def __init__(self, tpl: Template, parts: Parts):
        self.tpl = tpl
        self.parts = parts
        self.shape_no = 9500

    def clone(self, el: ET.Element) -> ET.Element:
        c = copy.deepcopy(el)
        _strip_ids(c)
        for node in c.iter():
            if node.tag in (f"{{{V}}}shape", f"{{{V}}}rect", f"{{{V}}}roundrect"):
                self.shape_no += 1
                node.set("id", f"_x0000_s{self.shape_no}")
                node.attrib.pop(f"{{{O}}}spid", None)
            elif node.tag == f"{{{WP}}}docPr":
                self.shape_no += 1
                node.set("id", str(self.shape_no))
        for ppr in c.iter(w("pPr")):
            for sp in ppr.findall(w("sectPr")):
                ppr.remove(sp)
        return c

    def blank(self) -> ET.Element:
        return self.clone(self.parts.blank)

    def para(self, proto: ET.Element, line: str) -> ET.Element:
        if core.NUMBERS_TATEGAKI:
            line = normalize_numbers(line)
        return self.tpl._make_para([proto], 0, line, True)

    def text_para(self, line: str) -> ET.Element:
        pr = self.parts
        protos = [p for p in (pr.q, pr.a, pr.body) if p is not None]
        if core.NUMBERS_TATEGAKI:
            line = normalize_numbers(line)
        # 「質問」「答弁」で始まる行はその見本、それ以外は本文の見本（最後）の書式
        return self.tpl._make_para(protos, len(protos) - 1, line, True)

    def photo(self, line: str) -> list[ET.Element]:
        """写真の場所: 赤字の指示 1 行と、写真の幅ぶんの空行（写真は印刷所が入れる）。"""
        m = PHOTO_LINE.match(line)
        size = (m.group("size") or "中").strip() if m else "中"
        mm = PHOTO_MM.get(size, PHOTO_MM["中"])
        label = f"【写真】{m.group('file') if m else line}（{size}・幅{mm}mm）"
        if m and m.group("caption"):
            label += f"　{m.group('caption').strip()}"
        p = self.tpl._make_para([self.parts.body], 0, label, True)
        for r in _text_runs(p):
            _set_rpr(_ensure_rpr(r), "color", {"val": "FF0000"})
        return [p] + [self.blank() for _ in range(max(0, math.ceil(mm / LINE_MM) - 1))]

    def head(self, member: Member) -> list[ET.Element]:
        pr = self.parts
        title = member.topics[0].title if member.topics and member.topics[0].title else ["（題）"]
        titles = self.title_paras(title)
        els = titles + [self.clone(el) for el in pr.head[1:]]
        name = (member.name or "（名前）") + "議員"
        if pr.name_at:
            lo, hi = (k + len(titles) - 1 for k in pr.name_at)
            old = "\n".join(para_text(p) for p in els[lo:hi])
            # 行ごとの書式（字下げの空白を含む）は、前年の同じ順番の行から写す
            new = [self.para(els[lo + min(k, hi - lo - 1)], s)
                   for k, s in enumerate(_name_to_lines(name, old))]
            els[lo:hi] = new
        else:
            els += [self.para(pr.blank, s) for s in _name_to_lines(name, "")]
        for el in els:
            _keep_next(el)
        return els

    def title_paras(self, title: list[str]) -> list[ET.Element]:
        """議員の最初の題。罫線で囲み、囲みの長さを題の長さに合わせる（1 段に入らなければ折り返す）。"""
        proto = self.parts.head[0]
        pt = core._max_pt(proto, self.tpl.base_pt)
        tier = self.tpl.geometry(1).column_len_pt
        width = max(text_width(normalize_numbers(s), True) for s in title) * pt + 12
        # 字の並ぶ向きの後ろ側（縦書きなら下）を字下げして、囲みを題の長さに縮める。
        # 並んだ段落の罫線と字下げが同じなら、Word は 1 つの囲みにまとめて描く
        end_indent = max(0, round((tier - width) * 20))
        out = []
        for s in title:
            p = self.para(proto, s)
            ppr = p.find(w("pPr"))
            _insert_ordered(ppr, ET.Element(w("ind"), {w("left"): "0", w("right"): str(end_indent),
                                                       w("firstLine"): "0"}), PPR_ORDER)
            out.append(p)
        return out

    def subtitle(self, title: list[str]) -> list[ET.Element]:
        pr = self.parts
        out = [self.blank()]
        for s in title:
            if pr.subtitle is not None:
                out.append(self.para(pr.subtitle, s))
            else:
                p = self.para(pr.body, s)          # 見本が無ければ本文の書式を 14pt・太字に
                for r in _text_runs(p):
                    rpr = _ensure_rpr(r)
                    _set_rpr(rpr, "b", {})
                    _set_rpr(rpr, "sz", {"val": "28"})
                out.append(p)
        out.append(self.blank())
        for el in out:
            _keep_next(el)
        return out

    def member(self, m: Member) -> list[ET.Element]:
        out = self.head(m)
        for line in m.head_photos:
            out += self.photo(line)
        out.append(self.blank())
        for k, t in enumerate(m.topics):
            if k:
                out += self.subtitle(t.title or ["（題）"])
            for line in t.lines:
                out += self.photo(line) if PHOTO_LINE.match(line) else [self.text_para(line)]
        return out


def _keep_next(el: ET.Element) -> None:
    """次の行と同じ段に置く（見出しだけが段の最後に取り残されないように）。"""
    paras = [el] if el.tag == w("p") else list(el.iter(w("p")))
    for p in paras:
        ppr = p.find(w("pPr"))
        if ppr is None:
            ppr = ET.Element(w("pPr"))
            p.insert(0, ppr)
        if ppr.find(w("keepNext")) is None:
            _insert_ordered(ppr, ET.Element(w("keepNext")), PPR_ORDER)


@dataclass
class FlowResult:
    members: int                # 議員の人数（行政報告・委員会報告では記事の数）
    topics: int                 # 質問の題の数（同じく記事の数）
    old_count: int              # 前年の人数（一般質問だけ）
    old_lines: float
    new_lines: float
    pad: int
    pages_added: int
    skipped_slots: set[str]
    label: str = "一般質問"
    summary: str = ""

    def text(self) -> str:
        what = self.summary or (f"議員 {self.members} 人・質問の題 {self.topics} 件。"
                                f"前年は {self.old_count} 人")
        if self.label == TOKUSHU:
            return "\n".join([f"特集の人ごとの枠に入れました（{what}）"] + self.extra)
        lines = [f"{self.label}を組み直しました（{what}）"]
        diff = self.new_lines - self.old_lines
        if self.pages_added > 0:
            lines.append(f"  → 前年より約 {diff:.0f} 行長いので、空行 {self.pad} 行を足して、"
                         f"後ろの記事をちょうど {self.pages_added} ページ分うしろへ送りました。"
                         f"全体が {self.pages_added} ページ増えます")
        elif self.pages_added < 0:
            lines.append(f"  → 前年より約 {-diff:.0f} 行短いので、空行 {self.pad} 行で埋めて、"
                         f"後ろの記事をちょうど {-self.pages_added} ページ分前へ詰めました。"
                         f"全体が {-self.pages_added} ページ減ります")
        else:
            lines.append(f"  → 前年との差（約 {diff:+.0f} 行）を空行 {self.pad} 行で埋めて、"
                         "後ろの記事の位置を前年と同じにしました")
        if self.pages_added:
            lines.append("  → 印刷は 4 ページ単位のことが多いので、ページ数が合わないときは"
                         "原稿の長さか、ほかの記事で調整してください")
        lines.append("  → 行数は見積もりです。Word で、見出しが段の途中で切れていないか、"
                     "次の区分の頭がずれていないかを確かめてください")
        return "\n".join(lines)


def _slots_in(tpl: Template, region: list[ET.Element], keep: set[int] = frozenset()) -> set[str]:
    """region の中にある欄。keep（残して移す枠の run）の欄は除く。"""
    kept = set()
    for el in region:
        for x in el.iter():
            if id(x) in keep:
                kept |= {id(y) for y in x.iter()}
    inside = {id(x) for el in region for x in el.iter()} - kept
    out = set()
    for sid, ref in tpl.refs.items():
        if ref.anchor_run is not None and id(ref.anchor_run) in keep:
            continue
        probes = list(ref.paras[:1]) + [x for x in (ref.anchor_para, ref.parent) if x is not None]
        if any(id(x) in inside for x in probes):
            out.add(sid)
    return out


def _section_heads(region: list[ET.Element]) -> list[tuple[ET.Element, ET.Element, bool]]:
    """region の中にある、ほかの区分の見出しの枠。(段落, run, 終わりへ移すか) を返す。

    組み直すときに前年の写真の説明の枠は消すが、次のものは消さずに移す。
      * 18pt 以上の大見出しの枠や「○月議会では」の枠 → 組み直した部分の頭へ
        （第201号の「閉会中の委員会活動報告」は最初の委員会の名前の行につなぎ留めてある）
      * 最後の本文より後ろにつなぎ留めた 14pt 以上の枠 → 組み直した部分の終わりへ
        （第200号の「一般会計決算額」は、次の区分の見出しの一部）
    """
    last = max((k for k, el in enumerate(region)
                if el.tag == w("p") and para_text(el).strip()), default=-1)
    out = []
    for k, el in enumerate(region):
        if el.tag != w("p"):
            continue
        for r in _anchor_runs(el):
            text = "".join(_all_text(tb) for tb in r.iter(w("txbxContent"))).replace("　", "")
            if _big_text(r, HEAD_PT).strip() or NEXT_BOX.search(text):
                out.append((el, r, False))
            elif k >= last and text.strip() and core._max_pt(r, 11) >= SUBTITLE_PT:
                out.append((el, r, True))
    return out


def _replace_region(tpl: Template, start: int, end: int, new: list[ET.Element],
                    blank: ET.Element) -> tuple[float, float, int, int, set[str]]:
    """body の [start, end) を new に入れ替え、後ろの記事がずれないよう空行で埋める。

    前年との長さの差を「ちょうど何ページ分」にそろえる（短くて 1 ページ以上余るなら
    ページごと詰める）。(前年の行数, 新しい行数, 足した空行, 増えたページ, 外した欄) を返す。
    """
    cpl = tpl.geometry(1).chars_per_line
    base = tpl.base_pt
    kids = list(tpl.body)
    pos = _positions(tpl, cpl)
    region = kids[start:end]
    old_lines = pos[end] - pos[start] if end < len(pos) else \
        sum(element_lines(el, cpl, base) for el in region)
    heads = _section_heads(region)
    skipped = _slots_in(tpl, region, {id(r) for _, r, _ in heads})

    new_lines = sum(element_lines(el, cpl, base) for el in new)
    pages = math.ceil((new_lines - old_lines) / PAGE_LINES)
    pad = round(old_lines + pages * PAGE_LINES - new_lines)
    new = new + [copy.deepcopy(blank) for _ in range(pad)]
    if heads and not new:
        new = [copy.deepcopy(blank)]
    for p, r, to_end in heads:
        p.remove(r)
        target = new[-1] if to_end else new[0]
        if target.tag != w("p"):
            target = copy.deepcopy(blank)
            if to_end:
                new.append(target)
            else:
                new.insert(0, target)
        ppr = target.find(w("pPr"))
        target.insert(1 if ppr is not None else 0, r)
        for ref in tpl.refs.values():
            if ref.anchor_run is r:
                ref.anchor_para = target
    for el in region:
        tpl.body.remove(el)
    for k, el in enumerate(new):
        tpl.body.insert(start + k, el)
    for sid in skipped:
        tpl.order.remove(sid)
        del tpl.refs[sid]
    return old_lines, new_lines, pad, pages, skipped


def apply_ippan(tpl: Template, members: list[Member]) -> FlowResult:
    """様式の一般質問を、members で組み直す（tpl をその場で書き換える）。"""
    if not members:
        raise ValueError("一般質問の原稿に議員が 1 人も見つかりません。")
    parts = extract_parts(tpl)
    intro = list(tpl.body)[parts.start]
    b = _Builder(tpl, parts)
    new: list[ET.Element] = [b.blank() for _ in range(MEMBER_GAP)]
    for k, m in enumerate(members):
        if k:
            new += [b.blank() for _ in range(MEMBER_GAP)]
        new += b.member(m)
    old, lines, pad, pages, skipped = _replace_region(
        tpl, parts.start + 1, parts.end, new, parts.blank)
    count = str(len(members))
    count = count.translate(core._H2Z) if len(count) == 1 else count
    for p in intro.iter(w("p")):
        if INTRO.search(_all_text(p)):
            _replace_in_para(p, _INTRO_NUM, count)
    return FlowResult(len(members), sum(len(m.topics) for m in members), parts.old_count,
                      old, lines, pad, pages, skipped)


# ================================================================ 行政報告・委員会報告
#
# どちらも「14pt の小見出し → 本文」の記事が並ぶ区分（第198〜201号で同じ作り）。
#   行政報告:   小見出し・空行・本文（写真の説明の枠は本文の段落につなぎ留めてある）
#   委員会報告: 委員会名（14pt。「経済建設厚生／常任委員会」のように 2 行のことがある）・
#               委員長の名前を 1 字ずつ・空行・「委員長」を 1 字ずつ・日時・説明した課長・本文
# 区分の頭（「行政報告（要旨）」の表と村長の名前）は組み直さず、前年の欄のまま差し込む。


@dataclass
class SectionSpec:
    key: str             # 画面・記録での名前
    marker: str          # 様式の大見出しに含まれる文字
    chair: bool          # 委員長の名前を組むか
    example: str         # 確認画面に出す原稿の書き方


SECTIONS = {
    "行政報告": SectionSpec("行政報告", "行政報告", False,
                            "見出し（短い行）のあとに本文。写真は【写真】行"),
    "委員会報告": SectionSpec("委員会報告", "委員会活動報告", True,
                              "委員会名 → 委員長　山田太郎 → 日時 → 課長名 → 本文"),
}
IPPAN = "一般質問"
SHINGI = "審議したこと"
TOKUSHU = "特集"
FLOW_KEYS = ("行政報告", SHINGI, "委員会報告", IPPAN, TOKUSHU)     # 紙面の順

_NAME = r"[^\s　。、，,「」（）()]{1,6}(?:[\s　]+[^\s　。、，,「」（）()]{1,6})?"
CHAIR_LINE = re.compile(rf"^(?:(?P<role1>副?委員長)[\s　]*(?P<name1>{_NAME})|"
                        rf"(?P<name2>{_NAME})[\s　]*(?P<role2>副?委員長))$")
# 説明した人の行（「高橋建設課長」）と日時の行は、短くても見出しにしない
SPEAKER = re.compile(r"(村長|副村長|教育長|課長|室長|次長|局長|所長|参事|理事|主幹|係長|園長|校長)$")
DATE_LINE = re.compile(r"^[0-9０-９]{1,2}月[0-9０-９]{1,2}日")
TITLE_MARK = re.compile(r"^[■◆●◎]\s*")


def _heading_like(t: str) -> bool:
    return (len(t) <= TITLE_MAX and not t.endswith(("。", "、", "より"))
            and not LABELED.match(t) and not PHOTO_LINE.match(t)
            and not SPEAKER.search(t) and not DATE_LINE.match(t))


def classify_section(text: str, spec: SectionSpec,
                     overrides: dict[str, str] | None = None) -> list[Line]:
    """行政報告・委員会報告の原稿の行を見分ける。

    手がかり:
      * 「■」で始まる行、または短く句点で終わらず、次に長い本文が続く行 → 見出し
      * 委員会報告: 「○○委員会」で終わる行、その直前の短い行（2 行の委員会名） → 見出し
      * 「委員長　山田太郎」「山田太郎委員長」 → 名前（委員長）
      * 課長名・日時の行は短くても本文
    """
    overrides = overrides or {}
    raws = text.replace("\r\n", "\n").split("\n")
    items = [(i + 1, s.strip("　 \t")) for i, s in enumerate(raws)]
    items = [(n, s) for n, s in items if s]
    kinds = []
    for k, (_, s) in enumerate(items):
        nxt = items[k + 1][1] if k + 1 < len(items) else None
        if spec.marker in s and len(s) <= 20:
            kinds.append(SKIP)
        elif PHOTO_LINE.match(s):
            kinds.append(PHOTO)
        elif spec.chair and CHAIR_LINE.match(s):
            kinds.append(MEMBER)
        elif TITLE_MARK.match(s):
            kinds.append(TITLE)
        elif spec.chair and s.endswith("委員会") and len(s) <= TITLE_MAX:
            kinds.append(TITLE)
        elif (_heading_like(s) and nxt is not None and not _heading_like(nxt)
              and len(nxt) > len(s)):
            kinds.append(TITLE)
        else:
            kinds.append(TEXT)
    # 2 行に分けた見出し（「経済建設厚生」「常任委員会」）: 見出しの直前の短い行も見出し
    for k in range(len(items) - 2, -1, -1):
        if kinds[k] == TEXT and kinds[k + 1] == TITLE and _heading_like(items[k][1]) \
                and (k == 0 or kinds[k - 1] != TITLE) and len(items[k][1]) <= 12:
            kinds[k] = TITLE
    return [Line(n, s, overrides.get(s, k) if overrides.get(s) in FLOW_KINDS else k, k,
                 raws[n - 1].rstrip())
            for (n, s), k in zip(items, kinds)]


@dataclass
class Article:
    title: list[str]
    chair: tuple[str, str] | None = None             # (名前, 委員長 / 副委員長)
    lines: list[str] = field(default_factory=list)   # 本文・【写真】行


def group_section(lines: list[Line]) -> tuple[list[Article], list[str]]:
    arts: list[Article] = []
    warns: list[str] = []
    cur: Article | None = None
    in_title = False
    for ln in lines:
        if ln.kind == SKIP:
            continue
        if ln.kind == TITLE:
            t = TITLE_MARK.sub("", ln.text)
            if cur is not None and in_title:
                cur.title.append(t)                  # 続けて書いた見出しは 1 つの見出し
            else:
                cur = Article([t])
                arts.append(cur)
            in_title = True
            continue
        in_title = False
        if cur is None:
            cur = Article([])
            arts.append(cur)
            warns.append(f"{ln.no} 行目: 見出しより前に本文があります（見出しなしの記事にします）。")
        if ln.kind == MEMBER:
            m = CHAIR_LINE.match(ln.text)
            if m:
                name = m.group("name1") or m.group("name2")
                role = m.group("role1") or m.group("role2")
            else:
                name, role = ln.text, "委員長"
            cur.chair = (re.sub(r"[\s　]+", "", name), role)
            continue
        cur.lines.append(ln.text if ln.kind == PHOTO else (ln.raw or ln.text))
    for a in arts:
        if not a.lines:
            warns.append(f"見出し「{''.join(a.title)}」のあとに本文がありません。")
    return arts, warns


def section_summary(arts: list[Article]) -> str:
    return f"記事 {len(arts)} 件"


@dataclass
class SectionParts:
    start: int
    end: int
    subtitle: ET.Element
    body: ET.Element
    blank: ET.Element
    name: list[ET.Element]          # 委員長の名前（1 字ずつの行）の見本
    role: list[ET.Element]          # 「委員長」（1 字ずつの行）の見本


NEXT_BOX = re.compile(r"月議会では|定例会では|一般質問に|別添|審議したこと")
# 審議の議案の行。委員会報告の中にも「問／答」はあるので、それは目印にしない
NEXT_PARA = re.compile(r"^◎")


def _starts_next(el: ET.Element, spec: SectionSpec) -> bool:
    """el が次の区分の頭か。この手前までの空行・写真の説明の枠は、この区分のものとして扱う。"""
    big = _big_text(el, HEAD_PT).replace("　", "")
    if big.strip() and spec.marker not in big:
        return True
    if el.tag == w("p"):
        if NEXT_PARA.match(para_text(el).strip("　 ")):
            return True
        for tb in el.iter(w("txbxContent")):
            if NEXT_BOX.search(_all_text(tb).replace("　", "")):
                return True
    return False


def _is_sub(p: ET.Element, base: float) -> bool:
    return (p.tag == w("p") and bool(para_text(p).strip())
            and SUBTITLE_PT <= _own_pt(p, base) < HEAD_PT)


def extract_section(tpl: Template, spec: SectionSpec) -> SectionParts:
    kids = list(tpl.body)
    base = tpl.base_pt
    h = next((i for i, el in enumerate(kids)
              if spec.marker in _big_text(el, HEAD_PT).replace("　", "")), None)
    if h is None:
        raise ValueError(f"様式に「{spec.marker}」の大見出しが見つからないので、{spec.key}を組み直せません。")
    # 大見出しの枠が、最初の記事の途中の行につなぎ留めてあることがある（第201号の委員会報告）。
    # そのときは、直前の見出し・名前の行・空行までさかのぼって記事の頭を探す
    j = h
    if spec.marker not in para_text(kids[h]).replace("　", ""):
        while j - 1 >= 0 and h - j < 30:
            el = kids[j - 1]
            if el.tag != w("p") or el.find(f"{w('pPr')}/{w('sectPr')}") is not None:
                break
            t = para_text(el).strip("　 ")
            if t and not _is_sub(el, base) and len(t) > 2:
                break
            j -= 1
    start = next((i for i in range(j, len(kids)) if _is_sub(kids[i], base)), None)
    if start is None:
        raise ValueError(f"様式の{spec.key}に、14pt の見出しが見つかりません。")
    # 終わりは次の区分の頭。区分の頭は大見出し（18pt 以上）とは限らない。第199号の
    # 「審議したこと」は「６月議会では…」の枠から始まり、大きな字の見出しが無い
    end = len(kids) - 1 if kids[-1].tag == w("sectPr") else len(kids)
    for i in range(start + 1, len(kids)):
        if _starts_next(kids[i], spec):
            end = i
            break
    region = kids[start:end]
    subtitle = next(p for p in region if _is_sub(p, base))
    body = _first_para(region, lambda p: (
        len(para_text(p).strip()) >= 10 and _own_pt(p, base) < SUBTITLE_PT
        and not LABELED.match(para_text(p).strip("　 ")))) or subtitle
    blank = _first_para(region, lambda p: (
        _is_blank(p) and not _has_anchor(p) and abs(_own_pt(p, base) - base) < 0.6)) or \
        _first_para(region, lambda p: _is_blank(p) and not _has_anchor(p)) or ET.Element(w("p"))
    name: list[ET.Element] = []
    role: list[ET.Element] = []
    if spec.chair:
        paras = list(region)
        # 最初の名前のまとまりと、その後ろの「長・員・委」
        i = 0
        groups = []
        while i < len(paras):
            sub = _name_group(paras[i:])
            if not sub:
                break
            groups.append((i + sub[0], i + sub[1]))
            i += sub[1]
        for a, b in groups:
            chars = {para_text(p).strip("　 ") for p in paras[a:b]}
            if chars == {"長", "員", "委"} and name:
                role = [copy.deepcopy(p) for p in paras[a:b]]
                break
            if not name and not chars <= {"長", "員", "委", "副"}:
                name = [copy.deepcopy(p) for p in paras[a:b]]
        for p in name + role:
            for r in _anchor_runs(p):
                p.remove(r)
    return SectionParts(start, end, subtitle, body, blank, name, role)


class _SectionBuilder(_Builder):
    def __init__(self, tpl: Template, parts: SectionParts):
        self.tpl = tpl
        self.parts = parts
        self.shape_no = 9700

    def lines_of(self, protos: list[ET.Element], text: str) -> list[ET.Element]:
        old = "\n".join(para_text(p) for p in protos)
        return [self.para(protos[min(k, len(protos) - 1)] if protos else self.parts.blank, s)
                for k, s in enumerate(_name_to_lines(text, old))]

    def article(self, a: Article) -> list[ET.Element]:
        pr = self.parts
        head = [self.para(pr.subtitle, t) for t in (a.title or ["（見出し）"])]
        head.append(self.blank())
        if a.chair:
            name, role = a.chair
            head += self.lines_of(pr.name, name) + [self.blank()]
            head += self.lines_of(pr.role, role) + [self.blank()]
        for el in head:
            _keep_next(el)
        out = head
        for line in a.lines:
            out += self.photo(line) if PHOTO_LINE.match(line) else [self.para(pr.body, line)]
        return out


def apply_section(tpl: Template, spec: SectionSpec, arts: list[Article]) -> FlowResult:
    """様式の行政報告・委員会報告の記事を、arts で組み直す（tpl をその場で書き換える）。"""
    if not arts:
        raise ValueError(f"{spec.key}の原稿に記事が 1 つも見つかりません。")
    parts = extract_section(tpl, spec)
    b = _SectionBuilder(tpl, parts)
    new: list[ET.Element] = []
    for k, a in enumerate(arts):
        if k:
            new += [b.blank() for _ in range(MEMBER_GAP)]
        new += b.article(a)
    old, lines, pad, pages, skipped = _replace_region(
        tpl, parts.start, parts.end, new, parts.blank)
    return FlowResult(len(arts), len(arts), 0, old, lines, pad, pages, skipped,
                      label=spec.key, summary=section_summary(arts))


# ================================================================ 区分をまとめて扱う


# 確認画面での種類の呼び名（中の値は区分によらず同じ。記録にはこの値を使う）
KIND_NAMES = {
    IPPAN: {MEMBER: "議員名", TITLE: "質問の題", TEXT: "質問・答弁・本文", PHOTO: "写真", SKIP: "使わない"},
    "行政報告": {TITLE: "見出し", TEXT: "本文", PHOTO: "写真", SKIP: "使わない"},
    "委員会報告": {TITLE: "見出し（委員会名）", MEMBER: "委員長の名前", TEXT: "本文", PHOTO: "写真",
                   SKIP: "使わない"},
    SHINGI: {TITLE: "区分（人事・条例など）", TEXT: "議案・質疑・本文", PHOTO: "写真", SKIP: "使わない"},
    TOKUSHU: {MEMBER: "名前（1 人・1 組の始まり）", TEXT: "所属・本文", PHOTO: "写真", SKIP: "使わない"},
}
HELP = {
    IPPAN: ("・議員名 … 「山田太郎議員」の行。ここから次の議員名までが 1 人ぶん\n"
            "・質問の題 … 議員の最初の題は囲みの題に、2 問目からは 14pt の見出しになる"),
    "行政報告": ("・見出し … 「■防災訓練」のように ■ を付けるか、本文より短い行。14pt の見出しになる\n"
                 "・本文 … 見出しの次の見出しまで。区分の頭（村長の名前）は前年の欄のまま差し込む"),
    "委員会報告": ("・見出し … 「総務常任委員会」。2 行に分けてもよい\n"
                   "・委員長の名前 … 「委員長　山田太郎」または「山田太郎委員長」。1 字ずつの行で組む\n"
                   "・本文 … 日時・説明した課長の名前・説明の中身"),
    SHINGI: ("・区分 … 「人事」「条例」「予算」「報告」「その他」などの行。罫線で囲んだ見出しになる\n"
             "・議案・質疑・本文 … 「◎議案名」「質疑」「問　…」「答　…」、候補者の名前など"),
    TOKUSHU: ("・名前 … 「山田太郎さん・花子さん」のように「さん」で終わる行。ここから次の名前までが"
              " 1 つの枠に入る（ふりがなは ｜山田《やまだ》）\n"
              "・所属・本文 … 名前の直後の短い行は所属（「田中農園」）、あとはひとこと・抱負"),
}


def kind_name(key: str, kind: str) -> str:
    return KIND_NAMES[key].get(kind, kind)


def read_flow(key: str, text: str, overrides: dict[str, str] | None = None):
    """原稿を読み、(行の一覧, まとまり, 気になる点, 要約) を返す。"""
    if key == IPPAN:
        lines = classify(text, overrides)
    elif key == SHINGI:
        lines = classify_shingi(text, overrides)
    elif key == TOKUSHU:
        lines = classify_cards(text, overrides)
    else:
        lines = classify_section(text, SECTIONS[key], overrides)
    groups, warns, summ = regroup(key, lines)
    return lines, groups, warns, summ


def regroup(key: str, lines: list[Line]):
    """確認画面で種類を直した行から、まとまりと気になる点を作り直す。"""
    if key == IPPAN:
        groups, warns = group(lines)
        return groups, warns, summary(groups)
    if key == TOKUSHU:
        groups, warns = group_cards(lines)
        return groups, warns, f"{len(groups)} 人（組）"
    groups, warns = group_section(lines)
    if key == SHINGI:
        n = sum(1 for a in groups for x in a.lines if x.lstrip("　 ").startswith("◎"))
        return groups, warns, f"区分 {len(groups)}・議案 {n} 件"
    return groups, warns, section_summary(groups)


def apply_flow(tpl: Template, key: str, groups) -> FlowResult:
    if key == IPPAN:
        return apply_ippan(tpl, groups)
    if key == SHINGI:
        return apply_shingi(tpl, groups)
    if key == TOKUSHU:
        return apply_cards(tpl, groups)
    return apply_section(tpl, SECTIONS[key], groups)


def region_slot_ids(tpl: Template, key: str = IPPAN) -> set[str]:
    """様式のうち、原稿から組み直される欄（画面で「⇄」の印を付けるため）。"""
    try:
        if key == TOKUSHU:
            return {ref.slot.id for ref in find_cards(tpl)}
        if key == IPPAN:
            parts = extract_parts(tpl)
            start, end = parts.start + 1, parts.end
        elif key == SHINGI:
            sp = extract_shingi(tpl)
            start, end = sp.start, sp.end
        else:
            sp = extract_section(tpl, SECTIONS[key])
            start, end = sp.start, sp.end
    except ValueError:
        return set()
    region = list(tpl.body)[start:end]
    return _slots_in(tpl, region, {id(r) for _, r, _ in _section_heads(region)})


# ================================================================ 審議したこと
#
# 第198〜201号で同じ作り（第198・199号は大見出しの字が読み取れないので、
# 「○月議会では」の枠を始まりの目印にする）:
#   「○月議会では…計○議案が決まった」の枠 → 「審議したこと」の大見出しの枠 →
#   区分の小さな枠（人　事・条　例・予　算・報　告・その他・議員提出議案。本文の外に浮かせてある）→
#   「◎議案名」・「質疑」・「問　…」「答　…」・候補者の名前 → 「別添（賛否表）」の枠
# 区分の枠は、題と同じく罫線で囲んだ段落にして本文の流れに置く。
# 「○月議会では」の枠と大見出し、賛否表の枠は組み直さない（前年の欄のまま差し込む）。

CATEGORY = re.compile(
    r"^(人[\s　]*事|条[\s　]*例|予[\s　]*算|決[\s　]*算|認[\s　]*定|報[\s　]*告|承[\s　]*認|"
    r"同[\s　]*意|そ[\s　]*の[\s　]*他|発[\s　]*議|請[\s　]*願|陳[\s　]*情|意[\s　]*見[\s　]*書|"
    r"契[\s　]*約|補正予算|当初予算|議員提出議案|議員発議)(関係)?$")
SHINGI_START = re.compile(r"審議したこと|月議会では|定例会では")
SHINGI_STOP_BOX = re.compile(r"別添|一般質問に|委員会活動報告")


def classify_shingi(text: str, overrides: dict[str, str] | None = None) -> list[Line]:
    """審議したことの原稿: 「人事」「条例」などの区分の行が見出し、それ以外（◎・問・答）は本文。"""
    overrides = overrides or {}
    raws = text.replace("\r\n", "\n").split("\n")
    out = []
    for i, raw in enumerate(raws):
        s = raw.strip("　 \t")
        if not s:
            continue
        if "審議したこと" in s or "決まったこと" in s:
            k = SKIP
        elif PHOTO_LINE.match(s):
            k = PHOTO
        elif CATEGORY.match(TITLE_MARK.sub("", s)) or (TITLE_MARK.match(s) and not s.startswith("◎")):
            k = TITLE
        else:
            k = TEXT
        out.append(Line(i + 1, s, overrides.get(s, k) if overrides.get(s) in FLOW_KINDS else k, k,
                        raw.rstrip()))
    return out


def _box_texts(el: ET.Element) -> list[tuple[ET.Element, str]]:
    return [(tb, _all_text(tb)) for tb in el.iter(w("txbxContent"))]


def _category_box(el: ET.Element) -> ET.Element | None:
    """区分の小さな枠（「人　事」「そ の 他」）の中身。"""
    for tb, t in _box_texts(el):
        t = re.sub(r"[\s　]", "", t)
        if 2 <= len(t) <= 8 and CATEGORY.match(t) and core._max_pt(tb, 11) >= 12:
            return tb
    return None


@dataclass
class ShingiParts:
    start: int
    end: int
    category: ET.Element            # 区分（罫線で囲んだ段落）の見本
    maru: ET.Element                # ◎議案名
    q: ET.Element | None
    a: ET.Element | None
    body: ET.Element
    blank: ET.Element


def extract_shingi(tpl: Template) -> ShingiParts:
    kids = list(tpl.body)
    base = tpl.base_pt
    h = next((i for i, el in enumerate(kids)
              if any(SHINGI_START.search(t.replace("　", "")) for _, t in _box_texts(el))
              or "審議したこと" in _big_text(el, HEAD_PT).replace("　", "")), None)
    if h is None:
        raise ValueError("様式に「審議したこと」（または「○月議会では」の枠）が見つからないので、"
                         "組み直せません。")
    start = next((i for i in range(h + 1, len(kids))
                  if kids[i].tag == w("p") and (_category_box(kids[i]) is not None
                                                or para_text(kids[i]).strip("　 ").startswith("◎"))),
                 None)
    if start is None:
        raise ValueError("様式の審議したことに、区分の枠や「◎」の議案の行が見つかりません。")
    end = len(kids) - 1 if kids[-1].tag == w("sectPr") else len(kids)
    for i in range(start + 1, len(kids)):
        el = kids[i]
        big = _big_text(el, HEAD_PT).replace("　", "")
        if (big.strip() and "審議" not in big) or any(
                SHINGI_STOP_BOX.search(t.replace("　", "")) for _, t in _box_texts(el)):
            end = i
            break
    region = kids[start:end]
    cat_box = next((b for el in region for b in [_category_box(el)] if b is not None), None)
    if cat_box is None:
        raise ValueError("様式の審議したことに、区分の枠（人事・条例など）が見つかりません。")
    maru = _first_para(region, lambda p: para_text(p).strip("　 ").startswith("◎"))
    q = _first_para(region, lambda p: re.match(r"^(問|質問)", para_text(p).strip("　 ")) is not None)
    a = _first_para(region, lambda p: re.match(r"^(答|答弁)", para_text(p).strip("　 ")) is not None)
    body = _first_para(region, lambda p: (
        len(para_text(p).strip()) >= 4 and _own_pt(p, base) < SUBTITLE_PT
        and not re.match(r"^(◎|問|答)", para_text(p).strip("　 ")))) or maru
    blank = _first_para(region, lambda p: (
        _is_blank(p) and not _has_anchor(p) and abs(_own_pt(p, base) - base) < 0.6)) or \
        _first_para(region, lambda p: _is_blank(p) and not _has_anchor(p)) or ET.Element(w("p"))
    return ShingiParts(start, end, _title_proto(cat_box, base), maru or body, q, a, body, blank)


class _ShingiBuilder(_Builder):
    def __init__(self, tpl: Template, parts: ShingiParts):
        self.tpl = tpl
        self.parts = parts
        self.shape_no = 9800

    def category(self, title: list[str]) -> list[ET.Element]:
        proto = self.parts.category
        pt = core._max_pt(proto, self.tpl.base_pt)
        tier = self.tpl.geometry(1).column_len_pt
        width = max(text_width(s, True) for s in title) * pt + 12
        indent = str(max(0, round((tier - width) * 20)))
        out = []
        for s in title:
            p = self.para(proto, s)
            _insert_ordered(p.find(w("pPr")), ET.Element(w("ind"), {
                w("left"): "0", w("right"): indent, w("firstLine"): "0"}), PPR_ORDER)
            _keep_next(p)
            out.append(p)
        blank = self.blank()
        _keep_next(blank)
        return out + [blank]

    def line(self, text: str) -> list[ET.Element]:
        if PHOTO_LINE.match(text):
            return self.photo(text)
        pr = self.parts
        protos = [x for x in (pr.maru, pr.q, pr.a, pr.body) if x is not None]
        if core.NUMBERS_TATEGAKI:
            text = normalize_numbers(text)
        p = self.tpl._make_para(protos, len(protos) - 1, text, True)
        if text.lstrip("　 ").startswith(("◎", "質疑")):
            _keep_next(p)                    # 議案名だけが段の最後に残らないように
        return [p]


def apply_shingi(tpl: Template, arts: list[Article]) -> FlowResult:
    """様式の審議したことを、区分ごとの記事（arts）で組み直す。"""
    if not arts:
        raise ValueError("審議したことの原稿に、区分も議案も見つかりません。")
    parts = extract_shingi(tpl)
    b = _ShingiBuilder(tpl, parts)
    new: list[ET.Element] = []
    for k, a in enumerate(arts):
        if k:
            new.append(b.blank())
        if a.title:
            new += b.category(a.title)
        for line in a.lines:
            new += b.line(line)
    old, lines, pad, pages, skipped = _replace_region(tpl, parts.start, parts.end, new, parts.blank)
    n = sum(1 for a in arts for x in a.lines if x.lstrip("　 ").startswith("◎"))
    return FlowResult(len(arts), n, 0, old, lines, pad, pages, skipped, label=SHINGI,
                      summary=f"区分 {len(arts)}・議案 {n} 件")


# ================================================================ 特集
#
# 特集はテーマも組み方も毎年違う（第198号: 二十歳のつどい・入学おめでとう、第200号: 金婚、
# 第201号: 新年の抱負）。第200・201号は、1 人（1 組）ごとの縦書きの文字枠を
# ページに並べて組んである。紙面を組み直すのではなく、前年の人ごとの枠に今年の人を
# 紙面の順に入れていく。枠が余れば消し、足りなければ知らせる（Word で枠を複製する）。
# 見出しの枠（「特集　新年の抱負を聞きました」）は、前年の欄に差し込む。

CARD_NAME = re.compile(r"(さん|様|氏|くん|ちゃん)([・･、\s　].*)?$")


def classify_cards(text: str, overrides: dict[str, str] | None = None) -> list[Line]:
    """特集の原稿: 「さん」で終わる短い行（「山田太郎さん・花子さん」）で 1 人（1 組）ぶんが始まる。"""
    overrides = overrides or {}
    raws = text.replace("\r\n", "\n").split("\n")
    out = []
    for i, raw in enumerate(raws):
        s = raw.strip("　 \t")
        if not s:
            continue
        if s.startswith("特集"):
            k = SKIP
        elif PHOTO_LINE.match(s):
            k = PHOTO
        elif len(core.strip_ruby(s)) <= 30 and not s.endswith(("。", "」")) and CARD_NAME.search(
                core.strip_ruby(s)):
            k = MEMBER
        else:
            k = TEXT
        out.append(Line(i + 1, s, overrides.get(s, k) if overrides.get(s) in FLOW_KINDS else k, k,
                        raw.rstrip()))
    return out


@dataclass
class Card:
    name: str
    lines: list[str] = field(default_factory=list)


def group_cards(lines: list[Line]) -> tuple[list[Card], list[str]]:
    cards: list[Card] = []
    warns: list[str] = []
    for ln in lines:
        if ln.kind == SKIP:
            continue
        if ln.kind == MEMBER:
            cards.append(Card(ln.text))
            continue
        if not cards:
            cards.append(Card(""))
            warns.append(f"{ln.no} 行目: 名前の行（「山田花子さん」）より前に文があります。")
        cards[-1].lines.append(ln.text if ln.kind == PHOTO else (ln.raw or ln.text))
    return cards, warns


def find_cards(tpl: Template) -> list:
    """特集の人ごとの枠（縦書きで、名前に「さん」などが付いた、2 段落以上の枠）を紙面の順に。

    一般質問より後ろ・編集後記より前にあるものだけを数える。
    """
    kids = list(tpl.body)
    index = {id(el): i for i, el in enumerate(kids)}
    lo = 0
    try:
        parts = extract_parts(tpl)
        lo = parts.end
    except ValueError:
        pass
    hi = next((i for i, el in enumerate(kids) if i > lo
               and "編集後記" in re.sub(r"[\s　]", "", _big_text(el, HEAD_PT))), len(kids))
    out = []
    for sid in tpl.order:
        ref = tpl.refs[sid]
        s = ref.slot
        if s.kind != "box" or not s.vertical or ref.anchor_para is None:
            continue
        i = index.get(id(ref.anchor_para))
        if i is None or not lo <= i < hi:
            continue
        paras = [core.strip_ruby(para_text(p)).strip("　 ") for p in ref.paras]
        filled = [t for t in paras if t]
        if len(filled) >= 2 and any(CARD_NAME.search(t) or "さん" in t for t in filled[:2]):
            out.append(ref)
    return out


def _fill_card(tpl: Template, ref, card: Card) -> float:
    """枠 1 つに 1 人ぶんを入れる。入りきらない行数の目安を返す。"""
    paras = ref.paras
    base = tpl.base_pt
    name_p = next((p for p in paras if "さん" in para_text(p) or CARD_NAME.search(
        core.strip_ruby(para_text(p)).strip())), paras[0])
    texty = [p for p in paras if para_text(p).strip() and p is not name_p]
    sub_p = next((p for p in texty if len(para_text(p).strip()) <= 15), None)
    body_p = max(texty, key=lambda p: len(para_text(p)), default=name_p)
    lead_blank = paras and not para_text(paras[0]).strip()
    new = []
    if lead_blank:
        new.append(copy.deepcopy(paras[0]))
    new.append(tpl._make_para([name_p], 0, card.name, True))
    started = False
    for line in card.lines:
        t = normalize_numbers(line) if core.NUMBERS_TATEGAKI else line
        short = len(t.strip("　 ")) <= 15 and not t.rstrip().endswith("。")
        if PHOTO_LINE.match(line):
            p = tpl._make_para([body_p], 0, line, True)
            for r in _text_runs(p):
                _set_rpr(_ensure_rpr(r), "color", {"val": "FF0000"})
        elif short and not started and sub_p is not None:
            p = tpl._make_para([sub_p], 0, t, True)          # 所属（「田中農園」）
        else:
            started = True
            p = tpl._make_para([body_p], 0, t, True)
        new.append(p)
    for tb in ref.boxes:                          # mc:Choice と Fallback の両方に同じ内容
        olds = [x for x in tb if x.tag == w("p")]
        at = list(tb).index(olds[0]) if olds else 0
        for x in olds:
            tb.remove(x)
        for k, x in enumerate(new):
            tb.insert(at + k, copy.deepcopy(x))
    ref.paras = [x for x in ref.boxes[0] if x.tag == w("p")] if ref.boxes else new
    text = "\n".join([card.name] + card.lines)
    return tpl._box_overflow(ref.slot, text)


def apply_cards(tpl: Template, cards: list[Card]) -> FlowResult:
    if not cards:
        raise ValueError("特集の原稿に、人（「山田花子さん」の行）が見つかりません。")
    refs = find_cards(tpl)
    if not refs:
        raise ValueError("この様式の特集は、人ごとの枠で組まれていないので、枠に入れられません"
                         "（前年の欄に差し込んでください）。")
    notes = []
    over = []
    for ref, card in zip(refs, cards):
        n = _fill_card(tpl, ref, card)
        if n:
            over.append(f"{core.strip_ruby(card.name)}（約 {math.ceil(n)} 行）")
    used = {ref.slot.id for ref in refs[:len(cards)]}
    for ref in refs[len(cards):]:                 # 余った枠は消す
        if ref.anchor_run is not None and ref.anchor_para is not None:
            ref.anchor_para.remove(ref.anchor_run)
        tpl.order.remove(ref.slot.id)
        del tpl.refs[ref.slot.id]
    for sid in used:                              # 入れた枠は、差し込み（fill）で触らない
        tpl.order.remove(sid)
        del tpl.refs[sid]
    res = FlowResult(min(len(cards), len(refs)), len(cards), 0, 0, 0, 0, 0, used,
                     label=TOKUSHU, summary=f"{len(cards)} 人（組）を、前年の {len(refs)} 枠に入れた")
    if len(cards) > len(refs):
        rest = "、".join(core.strip_ruby(c.name) for c in cards[len(refs):])
        notes.append(f"  → 枠が {len(cards) - len(refs)} つ足りません。入らなかった人: {rest}。"
                     "Word で枠を複製して入れてください")
    elif len(cards) < len(refs):
        notes.append(f"  → 前年の枠が {len(refs) - len(cards)} つ余ったので消しました。"
                     "空いた場所は Word で整えてください")
    if over:
        notes.append("  → 枠に入りきらないかもしれない人（目安）: " + "、".join(over))
    res.extra = notes
    return res
