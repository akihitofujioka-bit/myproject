"""議会だよりの構成（台割）。

議会だよりは毎号おおむね同じ順番で紙面が並ぶ。

    表紙 → 行政報告 → 審議したこと・決まったこと
    → 閉会中の委員会活動報告 → 一般質問 → 特集 → 最終ページ

この並びを「構成」として持っておくと、

  * 記事をどの区分に入れるかが決まる
  * 編集を紙面の順番どおりに進められる
  * 自動組版のとき、この順に組める

日高村議会だよりでは、この7つの区分がどれも毎号ある（特集も毎号ある）。
原稿が入っていない区分があれば、刷る前に気付けるよう画面で知らせる。
自治体ごとに違うので、号ごとに追加・削除・並べ替えができる
（`optional` を立てた区分は、空でも催促しない）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

# 既定の構成。第203号の紙面の並びに合わせてある。
DEFAULT_SECTIONS: list[dict] = [
    {
        "id": "cover",
        "name": "表紙",
        "note": "題字・特集の予告・巻頭の記事",
        "optional": False,
        "keywords": ["表紙", "ひょうし", "cover", "題字", "巻頭"],
    },
    {
        "id": "gyosei",
        "name": "行政報告",
        "note": "村長からの報告（要旨）",
        "optional": False,
        "keywords": ["行政報告", "村長報告", "町長報告", "市長報告", "行政"],
    },
    {
        "id": "shingi",
        "name": "審議したこと・決まったこと",
        "note": "議案・発議案と賛否、人事、その他",
        "optional": False,
        "keywords": ["審議", "決まった", "議案", "発議案", "賛否", "議決",
                     "定例会", "臨時会", "人事", "同意", "可決"],
    },
    {
        "id": "iinkai",
        "name": "閉会中の委員会活動報告",
        "note": "常任委員会・特別委員会の報告",
        "optional": False,
        "keywords": ["委員会", "常任委員会", "特別委員会", "閉会中",
                     "活動報告", "協議会", "総務", "経済建設厚生", "治水",
                     "議会改革"],
    },
    {
        "id": "ippan",
        "name": "一般質問",
        "note": "議員ごとの質問と答弁",
        "optional": False,
        "keywords": ["一般質問", "質問", "答弁", "問う", "質疑"],
    },
    {
        "id": "tokushu",
        "name": "特集",
        "note": "その号の企画（毎号あります）",
        "optional": False,
        "keywords": ["特集", "とくしゅう", "企画", "視察", "研修", "行政視察"],
    },
    {
        "id": "saishu",
        "name": "最終ページ",
        "note": "編集後記、お知らせ、写真募集など",
        "optional": False,
        "keywords": ["編集後記", "後記", "最終", "お知らせ", "募集",
                     "編集委員", "あとがき", "コラム"],
    },
]

UNASSIGNED = "未分類"


@dataclass
class Section:
    id: str
    name: str
    note: str = ""
    optional: bool = False
    keywords: list[str] = None  # type: ignore[assignment]
    target_pages: int = 0       # この区分の目標ページ数（0 なら成り行き）

    def to_dict(self) -> dict:
        d = asdict(self)
        d["keywords"] = list(self.keywords or [])
        return d


def default_sections() -> list[Section]:
    return [Section(**{**s, "keywords": list(s["keywords"])})
            for s in DEFAULT_SECTIONS]


def load(data: list[dict] | None) -> list[Section]:
    """保存されている構成を読む。無ければ既定の構成。"""
    if not data:
        return default_sections()
    known = {"id", "name", "note", "optional", "keywords", "target_pages"}
    out: list[Section] = []
    for s in data:
        kw = {k: v for k, v in s.items() if k in known}
        kw.setdefault("keywords", [])
        out.append(Section(**kw))
    return out or default_sections()


# ---------------------------------------------------------------- 自動判定

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return re.sub(r"[\s　_\-‐－・.,、。（）()\[\]【】「」]", "", s)


def guess_section(sections: list[Section], *, filename: str = "",
                  title: str = "", body: str = "") -> tuple[str, str]:
    """原稿がどの区分のものかを推測する。

    戻り値は (区分 id, 判定の理由)。分からなければ ("", 理由)。
    ファイル名 → 見出し → 本文の冒頭、の順に重みを付けて見る。
    """
    hay = [
        (_norm(filename), 3, "ファイル名"),
        (_norm(title), 2, "見出し"),
        (_norm(body[:200]), 1, "本文の書き出し"),
    ]
    best_id, best_score, best_why = "", 0, ""
    for sec in sections:
        name = _norm(sec.name)
        for kw in (sec.keywords or []):
            k = _norm(kw)
            if len(k) < 2:
                continue
            # 区分の名前そのもの（「特集」など）が書いてあれば、それが一番確か。
            # 委員会名のような部分的な手がかりに負けないよう下駄をはかせる
            bonus = 5 if k == name else 0
            for text, weight, where in hay:
                if not text or k not in text:
                    continue
                # 長い言葉ほど確からしい
                score = weight * 10 + len(k) + bonus
                if score > best_score:
                    best_id, best_score, best_why = sec.id, score, f"{where}の「{kw}」"
    if not best_id:
        return "", "区分を判定できませんでした"
    return best_id, best_why


def order_key(sections: list[Section], section_id: str) -> int:
    """構成の中での並び順。未分類は最後に回す。"""
    for i, s in enumerate(sections):
        if s.id == section_id:
            return i
    return len(sections) + 1


def group_articles(sections: list[Section], articles) -> list[dict]:
    """記事を構成の順に並べ、区分ごとにまとめる。

    どの区分にも入っていない記事は、最後に「未分類」としてまとめる。
    """
    buckets: dict[str, list] = {s.id: [] for s in sections}
    unassigned: list = []
    for art in articles:
        sid = getattr(art, "section", "")
        if sid in buckets:
            buckets[sid].append(art)
        else:
            unassigned.append(art)

    for items in buckets.values():
        items.sort(key=lambda a: (getattr(a, "order", 0), a.id))
    unassigned.sort(key=lambda a: (getattr(a, "order", 0), a.id))

    out = [
        {
            "id": s.id,
            "name": s.name,
            "note": s.note,
            "optional": s.optional,
            "target_pages": s.target_pages,
            "articles": buckets[s.id],
        }
        for s in sections
    ]
    if unassigned:
        out.append({
            "id": "",
            "name": UNASSIGNED,
            "note": "区分を選んでください",
            "optional": True,
            "target_pages": 0,
            "articles": unassigned,
        })
    return out
