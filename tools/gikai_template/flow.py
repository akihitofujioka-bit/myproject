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
    proto = copy.deepcopy(max(paras, key=lambda x: core._max_pt(x, base)))
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
    members: int
    topics: int
    old_count: int
    old_lines: float
    new_lines: float
    pad: int
    pages_added: int
    skipped_slots: set[str]

    def text(self) -> str:
        lines = [f"一般質問を組み直しました（議員 {self.members} 人・質問の題 {self.topics} 件。"
                 f"前年は {self.old_count} 人）"]
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
        lines.append("  → 行数は見積もりです。Word で、議員の題が段の途中で切れていないか、"
                     "次の区分の頭がずれていないかを確かめてください")
        return "\n".join(lines)


def apply_ippan(tpl: Template, members: list[Member]) -> FlowResult:
    """様式の一般質問を、members で組み直す（tpl をその場で書き換える）。"""
    if not members:
        raise ValueError("一般質問の原稿に議員が 1 人も見つかりません。")
    parts = extract_parts(tpl)
    geo = tpl.geometry(1)
    cpl = geo.chars_per_line
    base = tpl.base_pt
    kids = list(tpl.body)
    pos = _positions(tpl, cpl)
    region = kids[parts.start + 1:parts.end]
    old_lines = pos[parts.end] - pos[parts.start + 1] if parts.end < len(pos) else \
        sum(element_lines(el, cpl, base) for el in region)

    # 組み直す部分にあった欄は、差し込み（fill）で触らない
    inside = {id(x) for el in region for x in el.iter()}
    skipped = set()
    for sid, ref in tpl.refs.items():
        probes = list(ref.paras[:1]) + [x for x in (ref.anchor_para, ref.parent) if x is not None]
        if any(id(x) in inside for x in probes):
            skipped.add(sid)

    b = _Builder(tpl, parts)
    new: list[ET.Element] = [b.blank() for _ in range(MEMBER_GAP)]
    for k, m in enumerate(members):
        if k:
            new += [b.blank() for _ in range(MEMBER_GAP)]
        new += b.member(m)
    new_lines = sum(element_lines(el, cpl, base) for el in new)
    # 後ろの記事が前年と同じページ内の位置に来るよう、差をページ単位にそろえる。
    # 短くなって 1 ページ以上余るときは、空白のページを作らずページごと詰める
    pages = math.ceil((new_lines - old_lines) / PAGE_LINES)
    pad = round(old_lines + pages * PAGE_LINES - new_lines)
    new += [b.blank() for _ in range(pad)]

    for el in region:
        tpl.body.remove(el)
    for k, el in enumerate(new):
        tpl.body.insert(parts.start + 1 + k, el)
    count = str(len(members))
    count = count.translate(core._H2Z) if len(count) == 1 else count
    for p in kids[parts.start].iter(w("p")):
        if INTRO.search(_all_text(p)):
            _replace_in_para(p, _INTRO_NUM, count)
    for sid in skipped:
        tpl.order.remove(sid)
        del tpl.refs[sid]
    return FlowResult(len(members), sum(len(m.topics) for m in members), parts.old_count,
                      old_lines, new_lines, pad, pages, skipped)


def region_slot_ids(tpl: Template) -> set[str]:
    """様式のうち、一般質問として組み直される欄（画面で「流し込み」と出すため）。"""
    try:
        parts = extract_parts(tpl)
    except ValueError:
        return set()
    kids = list(tpl.body)
    inside = {id(x) for el in kids[parts.start + 1:parts.end] for x in el.iter()}
    out = set()
    for sid, ref in tpl.refs.items():
        probes = list(ref.paras[:1]) + [x for x in (ref.anchor_para, ref.parent) if x is not None]
        if any(id(x) in inside for x in probes):
            out.add(sid)
    return out
