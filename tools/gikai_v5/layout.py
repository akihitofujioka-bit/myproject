"""号の構成とページ割り（設計図 §3）。

    python layout.py 月 一般質問の人数 [委員会報告のページ数] [特集のページ数]
    例: python layout.py 10 5

号の月と一般質問の人数を決めると、どの区分が何ページ目に来るかが決まる。
ページの合計は **22 ページ以内の偶数**。特集を 2 にするか 3 にするかで偶数に合わせる
（人が決めた数を渡せば、それを使う）。

ここは「何ページ目に何が来るか」だけを決める。ページの中の配置は grid.py・後の段階で行う。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grid import Geometry, Rect

MAX_PAGES = 22
MAX_QUESTIONERS = 10             # 一般質問の人数の上限（議会の決まり）
MONTHS = (4, 7, 10, 1)
# 号の月 → その号で報告する定例会の月
TEIREIKAI = {4: 3, 7: 6, 10: 9, 1: 12}
COMMITTEE_PAGES = 2
FEATURE_PAGES = (2, 3)

ZEN = str.maketrans("0123456789", "０１２３４５６７８９")

# 区分の名前（画面・ファイル名・ページ一覧で使う）
COVER = "表紙"
GYOSEI = "行政報告"
YOSAN = "当初予算"
KESSAN = "決算"
SHINGI = "審議したこと・決まったこと"
IINKAI = "閉会中の委員会報告"
IPPAN = "一般質問"
TOKUSHU = "特集"
LAST = "最終ページ"


@dataclass
class Section:
    name: str
    pages: int
    note: str = ""


@dataclass
class PageSlot:
    """1 ページぶんの割り当て。"""
    no: int                 # ページ番号（表紙が 1）
    section: str
    index: int              # 区分の中で何ページ目か（1 から）
    label: str              # 画面に出す名前（例: 一般質問（2 人目））


@dataclass
class Plan:
    sections: list[Section]
    pages: list[PageSlot]
    errors: list[str] = field(default_factory=list)     # 直さないと作れないこと
    notes: list[str] = field(default_factory=list)      # 知らせておくこと

    @property
    def total(self) -> int:
        return len(self.pages)

    def first_page(self, section: str) -> int | None:
        return next((p.no for p in self.pages if p.section == section), None)

    def page_range(self, section: str) -> tuple[int, int] | None:
        nos = [p.no for p in self.pages if p.section == section]
        return (nos[0], nos[-1]) if nos else None


@dataclass
class Issue:
    """号情報.json の中身。"""
    number: int                          # 号数（第 205 号なら 205）
    month: int                           # 4・7・10・1
    date: str = ""                       # 発行日（例: 令和８年４月３０日）
    questioners: int = 0                 # 一般質問の人数
    committee_pages: int = COMMITTEE_PAGES
    feature_pages: int | None = None     # None ならツールが 2 か 3 を決める
    feature_title: str = ""              # 表紙の目次に出す特集の題

    def save(self, folder: Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "号情報.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, folder: Path) -> "Issue":
        data = json.loads((Path(folder) / "号情報.json").read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def title(self) -> str:
        head = f"第{self.number}号" if self.number else ""
        return f"{head}（{self.month}月号）"


def _sections(issue: Issue, feature_pages: int) -> list[Section]:
    secs = [Section(COVER, 1), Section(GYOSEI, 2)]
    if issue.month == 4:
        secs.append(Section(YOSAN, 1, "当初予算の内容と質疑"))
    elif issue.month == 10:
        secs.append(Section(KESSAN, 1, "決算の報告と質疑"))
    secs.append(Section(SHINGI, 1, "下部に発議案と賛否の表"))
    if issue.committee_pages:
        secs.append(Section(IINKAI, issue.committee_pages))
    if issue.questioners:
        secs.append(Section(IPPAN, issue.questioners, "1 人 1 ページ・質問は 4 つまで"))
    secs.append(Section(TOKUSHU, feature_pages, "行政視察の記事もここで作る"))
    secs.append(Section(LAST, 1, "1 段目 編集後記／2〜4 段目 自由／5 段目 傍聴の案内・署名"))
    return secs


def make_plan(issue: Issue) -> Plan:
    errors: list[str] = []
    notes: list[str] = []
    if issue.month not in MONTHS:
        errors.append(f"号の月は 4・7・10・1 のどれかです（{issue.month} 月になっています）")
    if issue.questioners < 0 or issue.committee_pages < 0:
        errors.append("人数・ページ数に負の数は使えません")
    if issue.questioners > MAX_QUESTIONERS:
        errors.append(f"一般質問は {MAX_QUESTIONERS} 人までです（{issue.questioners} 人になっています）")
    if issue.questioners == 0:
        notes.append("一般質問の人数が 0 です。一般質問のページは作りません")

    fixed = sum(s.pages for s in _sections(issue, 0))
    if issue.feature_pages is None:
        # 偶数になる方を選ぶ。2 も 3 も 22 を超えるなら、少ない 2 で数えて知らせる
        feature = next((f for f in FEATURE_PAGES if (fixed + f) % 2 == 0), FEATURE_PAGES[0])
        notes.append(f"特集は {feature} ページにしました（合計を偶数にするため）")
    else:
        feature = issue.feature_pages
        if feature not in FEATURE_PAGES:
            notes.append(f"特集が {feature} ページです（ふつうは 2〜3 ページ）")

    secs = _sections(issue, feature)
    pages: list[PageSlot] = []
    for s in secs:
        for i in range(1, s.pages + 1):
            if s.name == IPPAN:
                label = f"{IPPAN}（{i} 人目）"
            elif s.pages > 1:
                label = f"{s.name}（{i}/{s.pages}）"
            else:
                label = s.name
            pages.append(PageSlot(len(pages) + 1, s.name, i, label))

    total = len(pages)
    if total > MAX_PAGES:
        errors.append(f"合計 {total} ページで、{MAX_PAGES} ページを {total - MAX_PAGES} ページ超えています。"
                      "委員会報告・特集のページを減らしてください")
    if total % 2:
        errors.append(f"合計 {total} ページで奇数です。特集か委員会報告のページを 1 つ増やすか減らしてください")
    return Plan(secs, pages, errors, notes)


def max_questioners(month: int, committee_pages: int = COMMITTEE_PAGES) -> int:
    """一般質問の人数の上限。10 人か、22 ページに収まる人数の少ない方。"""
    n = 0
    while n < MAX_QUESTIONERS and not make_plan(Issue(0, month, questioners=n + 1, committee_pages=committee_pages)).errors:
        n += 1
    return n


# ---------------------------------------------------------------- 表紙の目次


def page_label(first: int, last: int) -> str:
    """「１４Ｐ」「１６～１７Ｐ」の形（過去号の表紙の書き方）。"""
    if first == last:
        return f"{first}".translate(ZEN) + "Ｐ"
    return f"{first}～{last}".translate(ZEN) + "Ｐ"


def toc_line(title: str, first: int, last: int) -> str:
    return f"特集　{title}……{page_label(first, last)}"


# ---------------------------------------------------------------- ページの中の決まった場所


def fixed_areas(section: str, g: Geometry) -> dict[str, Rect]:
    """区分ごとに中身の決まっている場所（設計図 §3.1）。ほかの記事はここを避けて流す。"""
    full = g.lines_per_dan
    if section == LAST:
        return {"編集後記": Rect(0, 0, 1, full),
                "自由": Rect(1, 0, 3, full),
                "傍聴の案内・署名": Rect(4, 0, 1, full)}
    if section == SHINGI:
        # 下部に発議案と賛否の表。段数は表の大きさで変わるので、まず 2 段とっておく
        return {"発議案と賛否の表": Rect(g.dans - 2, 0, 2, full)}
    return {}


# ---------------------------------------------------------------- 表示


def describe(issue: Issue, plan: Plan) -> str:
    out = [f"{issue.title}　{TEIREIKAI.get(issue.month, '?')}月定例会　合計 {plan.total} ページ", ""]
    for p in plan.pages:
        out.append(f"{p.no:>3}  {p.label}")
    for n in plan.notes:
        out.append(f"・{n}")
    for e in plan.errors:
        out.append(f"× {e}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 1
    month, q = int(argv[1]), int(argv[2])
    committee = int(argv[3]) if len(argv) > 3 else COMMITTEE_PAGES
    feature = int(argv[4]) if len(argv) > 4 else None
    issue = Issue(0, month, questioners=q, committee_pages=committee, feature_pages=feature)
    plan = make_plan(issue)
    print(describe(issue, plan))
    print(f"（この月の一般質問は {max_questioners(month, committee)} 人まで）")
    return 1 if plan.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
