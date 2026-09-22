"""写真の自動割り付け。

「写真のファイル名を原稿と同じにしておけば、その記事のそばに入る」
という使い方を実現するための処理。

やること:
  1. 写真のファイル名と、記事（原稿ファイル名・執筆者・見出し）を
     突き合わせて、どの記事の写真かを判定する
  2. その記事が入る枠のページを見て、いちばん近い写真枠に割り当てる
  3. 写真枠のそばにある説明文（キャプション）の枠も押さえる

自動でやったことは必ず一覧で返す。画面で確認して、違っていれば
手で選び直せるようにするため。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

from .textutil import levenshtein

# 判定の確からしさ。これを下回ったら「分からなかった」とする。
MIN_SCORE = 55


# ---------------------------------------------------------------- 名前の正規化

# 末尾の連番（_1 / -02 / （3） / ①…）を切り出すための形
_TAIL_NUM = re.compile(
    r"[\s_\-‐－（(\[]*"
    r"(?:no\.?|#)?\s*"
    r"(?P<num>[0-9]{1,3}|[①-⑳]|[一二三四五六七八九十]{1,3})"
    r"[\s_\-）)\]]*$"
)
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_KANJI_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_DROP = re.compile(r"[\s　_\-‐－・.,、。／/（）()\[\]【】「」]")
# 写真であることを示すだけの語。名前を比べるときは邪魔になるので外す。
_NOISE = ["写真", "画像", "しゃしん", "photo", "img", "image", "dsc", "pic",
          "原稿", "げんこう", "提出", "最終", "修正", "コピー", "copy"]


def split_number(stem: str) -> tuple[str, int]:
    """末尾の連番を切り離す。「森下けい子_写真2」→ ("森下けい子_写真", 2)"""
    m = _TAIL_NUM.search(stem)
    if not m:
        return stem, 0
    raw = m.group("num")
    if raw in _CIRCLED:
        num = _CIRCLED.index(raw) + 1
    elif raw[0] in _KANJI_NUM:
        num = _KANJI_NUM.get(raw, 0)
    else:
        num = int(raw)
    return stem[: m.start()], num


def normalize_key(name: str) -> str:
    """比較用に名前をそろえる。全角半角・記号・大文字小文字の違いを吸収する。"""
    s = unicodedata.normalize("NFKC", str(name)).lower()
    s = _DROP.sub("", s)
    return s


def strip_noise(key: str) -> str:
    """「写真」「原稿」など、区別に役立たない語を落とす。"""
    for w in _NOISE:
        key = key.replace(normalize_key(w), "")
    return key


# ---------------------------------------------------------------- 突き合わせ


@dataclass
class Match:
    photo_id: str
    photo_name: str
    article_id: str = ""
    article_label: str = ""
    order: int = 0
    score: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _article_keys(art) -> list[tuple[str, int, str]]:
    """記事側の照合用キー。(キー, 点数, 理由) の一覧。"""
    keys: list[tuple[str, int, str]] = []
    if art.source_file:
        stem = Path(art.source_file).stem
        base, _ = split_number(stem)
        keys.append((normalize_key(base), 100, "原稿のファイル名と同じ"))
    if art.author:
        keys.append((normalize_key(art.author), 80, "執筆者の名前が入っている"))
    if art.title:
        keys.append((normalize_key(art.title), 70, "見出しと同じ言葉が入っている"))
    return [(k, s, r) for k, s, r in keys if len(k) >= 2]


def match_photo(photo_name: str, articles) -> Match:
    """写真1枚を、いちばん近い記事に結びつける。"""
    stem = Path(photo_name).stem
    base, order = split_number(stem)
    pkey = normalize_key(base)
    pkey_clean = strip_noise(pkey)

    best = Match(photo_id="", photo_name=photo_name, order=order)
    for art in articles:
        label = art.title or art.author or Path(art.source_file or "").stem or art.id
        for akey, base_score, reason in _article_keys(art):
            akey_clean = strip_noise(akey)
            score = 0
            if pkey == akey:
                score = base_score
            elif akey_clean and pkey_clean and akey_clean == pkey_clean:
                score = base_score - 3
            elif akey_clean and pkey_clean and (
                pkey_clean.startswith(akey_clean) or akey_clean.startswith(pkey_clean)
            ):
                score = base_score - 8
            elif akey_clean and len(akey_clean) >= 3 and akey_clean in pkey_clean:
                score = base_score - 15
            elif akey_clean and pkey_clean and len(akey_clean) >= 4:
                d = levenshtein(pkey_clean, akey_clean, limit=2)
                if d <= 2:
                    score = base_score - 20 - d * 5
            if score > best.score:
                best = Match(
                    photo_id="", photo_name=photo_name, article_id=art.id,
                    article_label=label, order=order, score=score, reason=reason,
                )
    if best.score < MIN_SCORE:
        return Match(photo_id="", photo_name=photo_name, order=order,
                     reason="名前の近い記事が見つかりませんでした")
    return best


# ---------------------------------------------------------------- 枠の割り当て


def _slot_page(slots_by_id: dict, slot_id: str) -> int:
    s = slots_by_id.get(slot_id)
    return int(s.get("page_hint") or 0) if s else 0


def assign_image_slots(articles, photos, anchors, slots_by_id) -> dict[str, str]:
    """写真 → 様式の写真枠。記事が入るページに近い枠を選ぶ。

    戻り値は 写真 ID → 画像名。
    """
    used = {p.slot for p in photos if p.slot}
    free = [a for a in anchors if a["name"] not in used]
    out: dict[str, str] = {}

    by_id = {a.id: a for a in articles}
    # 記事の載るページ順に処理して、前のほうの記事から枠を取っていく
    targets: list[tuple[int, object, list]] = []
    for art in articles:
        mine = [p for p in photos if p.id in art.photos and not p.slot]
        if not mine:
            continue
        targets.append((_slot_page(slots_by_id, art.slot), art, mine))
    targets.sort(key=lambda t: (t[0] == 0, t[0]))

    for page, art, mine in targets:
        for photo in mine:
            if not free:
                break
            if page:
                # 同じページ → 近いページ、の順に選ぶ
                free.sort(key=lambda a: (abs((a["page"] or 99) - page), a["order"]))
            best = free.pop(0)
            out[photo.id] = best["name"]
    return out


def assign_caption_slots(photo_slots, anchors, slots, taken) -> dict[str, str]:
    """写真枠のそばにある説明文の枠を押さえる。

    戻り値は 写真 ID → スロット ID。
    """
    anchor_by_name = {a["name"]: a for a in anchors}
    candidates = [
        s for s in slots
        if s["kind"] == "textbox"
        and s["guess"] in ("キャプション", "氏名・見出し")
        and s["id"] not in taken
    ]
    out: dict[str, str] = {}
    for photo_id, image_name in photo_slots.items():
        anchor = anchor_by_name.get(image_name)
        if not anchor or not candidates:
            continue
        page = anchor.get("page") or 0
        candidates.sort(key=lambda s: (abs((s.get("page_hint") or 99) - page)
                                       if page else 0, s["id"]))
        chosen = candidates.pop(0)
        out[photo_id] = chosen["id"]
    return out


# ---------------------------------------------------------------- まとめ


def auto_layout(project, *, match_names: bool = True, assign_slots: bool = True) -> dict:
    """写真の自動割り付けを実行する。

    行った内容を一覧で返すので、画面で確認して手直しできる。
    """
    articles = project.articles()
    photos = project.photos()
    report: dict = {"matched": [], "unmatched": [], "slots": [], "captions": 0}

    if not articles:
        report["message"] = "記事がまだありません。先に原稿を取り込んでください。"
        return report

    # --- 1. 名前で記事と結びつける
    if match_names:
        assigned = {pid for a in articles for pid in a.photos}
        for photo in photos:
            if photo.id in assigned:
                continue
            src = photo.info.get("name") or photo.file
            m = match_photo(src, articles)
            m.photo_id = photo.id
            if m.article_id:
                art = project.get_article(m.article_id)
                if art and photo.id not in art.photos:
                    art.photos.append(photo.id)
                    project.put_article(art)
                report["matched"].append(m.to_dict())
            else:
                report["unmatched"].append(m.to_dict())
        # 記事ごとに、写真の連番どおりの並びにそろえる
        order_of = {p.id: split_number(Path(p.info.get("name") or p.file).stem)[1]
                    for p in photos}
        for art in project.articles():
            if len(art.photos) > 1:
                art.photos.sort(key=lambda pid: (order_of.get(pid, 0), pid))
                project.put_article(art)

    # --- 2. 様式の写真枠に割り当てる
    if assign_slots and project.data.get("template"):
        tpl = project.template()
        slots = [s.to_dict() for s in tpl.slots()]
        slots_by_id = {s["id"]: s for s in slots}
        anchors = tpl.image_anchors()

        articles = project.articles()
        photos = project.photos()
        photo_slots = assign_image_slots(articles, photos, anchors, slots_by_id)

        taken = {a.slot for a in articles if a.slot} | {a.title_slot for a in articles if a.title_slot}
        taken |= {p.caption_slot for p in photos if p.caption_slot}
        captions = assign_caption_slots(photo_slots, anchors, slots, taken)

        for photo in photos:
            changed = False
            if photo.id in photo_slots:
                photo.slot = photo_slots[photo.id]
                changed = True
                report["slots"].append({"photo": photo.id, "image": photo.slot})
            if photo.id in captions:
                photo.caption_slot = captions[photo.id]
                report["captions"] += 1
                changed = True
            if changed:
                project.put_photo(photo)

        if not anchors:
            report["message"] = (
                "様式に写真枠が見つかりませんでした。"
                "写真の入る位置が図として作られていない様式かもしれません。"
            )

    return report
