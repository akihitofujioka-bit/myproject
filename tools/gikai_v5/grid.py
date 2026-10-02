"""紙面の格子（設計図 §4）と、本文の流し込み（§7）。

1 ページを「段 × 行」の格子として扱う。縦書きなので

- 段は上から 1 段目・2 段目…（ページを横に切った帯）
- 行は段の中を**右から左へ**数える。1 行は縦に 12 字

部品はすべて「何段目から何段ぶん × 何行目から何行ぶん」の長方形（`Rect`）で置く。
長方形から紙の上の寸法（pt）への換算はこのファイルだけが行い、Word の書き出し
（`docx_out.py`）はその寸法をそのまま使う。

本文の 1 行の切れ目もここで決める（`split_lines`）。Word に折り返しを任せず、
こちらで決めた位置で改行を入れるので、**ツールの計算と Word の表示が食い違わない**。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MM_PER_PT = 25.4 / 72


def mm2pt(mm: float) -> float:
    return mm / MM_PER_PT


# ---------------------------------------------------------------- 寸法


@dataclass(frozen=True)
class Geometry:
    """紙面の寸法。数字は既存ツールで実物を解析した値（gikai_template 設計書 §2）。"""
    page_w_mm: float = 210.0          # A4
    page_h_mm: float = 297.0
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 12.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0
    dans: int = 5                     # 段数
    body_pt: float = 11.0             # 本文の字の大きさ（＝字送り。全角は 1 字 1 em）
    chars_per_line: int = 12          # 1 段の 1 行に入る字数
    line_pitch_pt: float = 17.0       # 行送り（縦書きなので左右の間隔）

    @property
    def dan_h_pt(self) -> float:
        """1 段の高さ ＝ 1 行の長さ。"""
        return self.body_pt * self.chars_per_line

    @property
    def text_w_pt(self) -> float:
        return mm2pt(self.page_w_mm - self.margin_left_mm - self.margin_right_mm)

    @property
    def text_h_pt(self) -> float:
        return mm2pt(self.page_h_mm - self.margin_top_mm - self.margin_bottom_mm)

    @property
    def gap_pt(self) -> float:
        """段と段のあいだ。版面の高さから段の高さを引いた残りを等分する。"""
        if self.dans == 1:
            return 0.0
        return (self.text_h_pt - self.dan_h_pt * self.dans) / (self.dans - 1)

    @property
    def lines_per_dan(self) -> int:
        return int(self.text_w_pt / self.line_pitch_pt + 1e-6)

    def check(self) -> list[str]:
        """寸法の組み合わせが成り立つか。成り立たない理由を返す（空なら良し）。"""
        bad = []
        if self.gap_pt < 0:
            bad.append(f"{self.dans} 段 × {self.chars_per_line} 字が版面の高さに入りません")
        if self.lines_per_dan < 1:
            bad.append("行送りが版面の幅より大きくなっています")
        return bad


# ---------------------------------------------------------------- 長方形


@dataclass(frozen=True)
class Rect:
    """格子の上の長方形。段・行とも 0 から数える（行は右端が 0）。"""
    dan: int
    line: int
    dan_span: int = 1
    line_span: int = 1

    def cells(self):
        for d in range(self.dan, self.dan + self.dan_span):
            for ln in range(self.line, self.line + self.line_span):
                yield d, ln

    def overlaps(self, other: "Rect") -> bool:
        return not (self.dan + self.dan_span <= other.dan or other.dan + other.dan_span <= self.dan
                    or self.line + self.line_span <= other.line
                    or other.line + other.line_span <= self.line)


@dataclass(frozen=True)
class Box:
    """紙の上の寸法（pt）。原点は紙の左上。"""
    x: float
    y: float
    w: float
    h: float


def to_box(g: Geometry, r: Rect) -> Box:
    """格子の長方形を、紙の上の寸法にする。

    行は右から数えるので、x は版面の右端から行送りぶんずつ左へ下がる。
    版面の幅が行送りで割り切れないときの余り（1pt 未満）は左端に寄せる。
    """
    right = mm2pt(g.page_w_mm - g.margin_right_mm)
    w = r.line_span * g.line_pitch_pt
    x = right - r.line * g.line_pitch_pt - w
    y = mm2pt(g.margin_top_mm) + r.dan * (g.dan_h_pt + g.gap_pt)
    h = r.dan_span * g.dan_h_pt + (r.dan_span - 1) * g.gap_pt
    return Box(x, y, w, h)


# ---------------------------------------------------------------- 行分け（禁則）

# 行の頭に来てはいけない字（句読点・閉じ括弧・小さい仮名・長音など）
GYOTO_KINSOKU = set("、。，．・：；？！‐ー〜～）」』】〕〉》］｝ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々ゝゞヽヾ")
# 行の終わりに来てはいけない字（開き括弧）
GYOMATSU_KINSOKU = set("（「『【〔〈《［｛")
# 追い出しで 1 行を何字まで短くしてよいか。これより短くなるなら禁則を諦める
MIN_LINE_RATIO = 0.75


# 縦中横（2〜3 桁の半角数字を横に並べて 1 字ぶんに収める）にする数字のかたまり。
# 4 桁以上は縦中横にせず、半角のまま 1 字 0.5 字ぶんで横に寝かせる（gikai_simple §6 と同じ）。
# 「－」でつないだ番号（郵便番号・電話番号・番地）は書いてあるとおりに残し、縦中横にしない
_TCY = r"(?<![0-9－\-‐])[0-9]{2,3}(?![0-9－\-‐])"
TATECHUYOKO = re.compile(_TCY)
# 半角の英単語は途中で行を分けない（8 字まで。長い語は分けないと 1 行に入らない）
_WORD = r"[A-Za-z]{2,8}"
_UNIT = re.compile(_TCY + "|" + _WORD + "|.", re.S)


def units(text: str) -> list[str]:
    """行分けの単位に分ける。縦中横の数字・英単語はひとかたまり、ほかは 1 字ずつ。"""
    return _UNIT.findall(text)


def _char_width(c: str) -> float:
    if ord(c) < 0x80 or 0xFF61 <= ord(c) <= 0xFF9F:   # 半角英数・半角カナ
        return 0.5
    return 1.0


def unit_width(u: str) -> float:
    """1 単位が縦に占める長さ（全角 1 字 = 1）。"""
    if TATECHUYOKO.fullmatch(u):            # 縦中横は 1 字ぶん
        return 1.0
    return sum(_char_width(c) for c in u)


def text_width(text: str) -> float:
    return sum(unit_width(u) for u in units(text))


def split_lines(paragraph: str, n: int, indent: bool = True) -> list[str]:
    """1 つの段落を、1 行 n 字ぶん以内の行に分ける。

    禁則は**追い出し**（前の行の最後の字を次の行へ送る）で守る。ぶら下げ
    （句読点を行の外へはみ出させる）は使わない。はみ出すと枠からこぼれ、
    計算と紙面が食い違うため。

    半角の英数字は 0.5 字ぶん、縦中横の数字は 1 字ぶんで数える。
    indent が真なら段落の頭を 1 字下げる。
    """
    text = ("　" + paragraph) if indent and paragraph else paragraph
    if not text:
        return [""]
    us = units(text)
    lines: list[str] = []
    i = 0
    while i < len(us):
        # n 字ぶんに収まるところまで取る
        end, width = i, 0.0
        while end < len(us) and width + unit_width(us[end]) <= n + 1e-9:
            width += unit_width(us[end])
            end += 1
        end = max(end, i + 1)
        if end < len(us):
            floor = i + max(1, int((end - i) * MIN_LINE_RATIO))
            cut = end
            # 次の行の頭が禁則の字、または この行の終わりが開き括弧なら 1 字ずつ送る
            while cut > floor and (us[cut][0] in GYOTO_KINSOKU or us[cut - 1][-1] in GYOMATSU_KINSOKU):
                cut -= 1
            if us[cut][0] in GYOTO_KINSOKU or us[cut - 1][-1] in GYOMATSU_KINSOKU:
                cut = end          # 送りきれない（禁則の字が続きすぎ）ときは元の位置で切る
            end = cut
        lines.append("".join(us[i:end]))
        i = end
    return lines


def layout_text(paragraphs: list[str], n: int, indent: bool = True) -> list[str]:
    """複数の段落を行に分ける。段落の境目は行の境目になる。"""
    out: list[str] = []
    for p in paragraphs:
        out.extend(split_lines(p, n, indent))
    return out


# ---------------------------------------------------------------- 流し込み


@dataclass
class Run:
    """本文を入れる、段の中で切れ目なく続く行のかたまり（＝ Word の枠 1 つ）。"""
    rect: Rect
    lines: list[str] = field(default_factory=list)


@dataclass
class FlowResult:
    runs: list[Run]
    overflow: list[str]        # 入りきらなかった行
    free_lines: int            # 余った行の数

    @property
    def overflow_lines(self) -> int:
        return len(self.overflow)


def free_runs(g: Geometry, area: Rect, occupied: list[Rect]) -> list[Rect]:
    """area の中で、occupied に重ならない行を、読む順（段は上から、行は右から）に
    切れ目ごとにまとめて返す。写真が段の途中にあれば、その段は 2 つに分かれる。"""
    taken = {c for r in occupied for c in r.cells()}
    runs: list[Rect] = []
    for d in range(area.dan, area.dan + area.dan_span):
        start = None
        for ln in range(area.line, area.line + area.line_span + 1):
            free = ln < area.line + area.line_span and (d, ln) not in taken
            if free and start is None:
                start = ln
            elif not free and start is not None:
                runs.append(Rect(d, start, 1, ln - start))
                start = None
    return runs


def flow(g: Geometry, lines: list[str], area: Rect, occupied: list[Rect]) -> FlowResult:
    """行を、area の空いている所へ読む順に流し込む。"""
    runs = [Run(r) for r in free_runs(g, area, occupied)]
    i = 0
    for run in runs:
        take = lines[i:i + run.rect.line_span]
        run.lines = take
        i += len(take)
    capacity = sum(r.rect.line_span for r in runs)
    return FlowResult([r for r in runs if r.lines], lines[i:], max(0, capacity - len(lines)))


def whole_page(g: Geometry) -> Rect:
    return Rect(0, 0, g.dans, g.lines_per_dan)
