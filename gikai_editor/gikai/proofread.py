"""日本語校正エンジン（完全オフライン・ルールベース）。

議会だよりの原稿に対して、誤字脱字・表記ゆれ・公用文ルール違反・
読みにくさを検出し、指摘（Issue）の一覧を返す。

外部サービスにも外部辞書サーバにも接続しない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from .textutil import (
    count_chars,
    is_fullwidth,
    levenshtein,
    split_sentences,
)

DATA_DIR = Path(__file__).parent / "data"

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclass
class Issue:
    """1件の指摘。"""

    start: int
    end: int
    text: str
    category: str
    severity: str  # error / warn / info
    message: str
    suggestion: str | None = None
    rule_id: str = ""
    auto_fixable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _load(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class Dictionaries:
    """辞書一式。ユーザー辞書で上書き・追加できる。"""

    def __init__(self, user_dict_path: Path | None = None):
        self.style = _load("style_rules.json")
        self.confusions = _load("confusions.json")
        self.local = _load("local_terms.json")
        self.ruby = _load("ruby.json")
        self.user: dict = {"terms": [], "rules": [], "ignore": []}
        if user_dict_path and Path(user_dict_path).exists():
            with open(user_dict_path, encoding="utf-8") as f:
                self.user.update(json.load(f))

    # -- 固有名詞の平坦なリスト -------------------------------------------
    def proper_nouns(self) -> list[str]:
        out: list[str] = []
        for terms in self.local.get("groups", {}).values():
            out.extend(terms)
        out.extend(self.user.get("terms", []))
        return sorted(set(out), key=len, reverse=True)


# ====================================================================== 個別チェック


def _iter_style_rules(style: dict) -> Iterable[tuple[str, dict]]:
    for group, block in style.items():
        if not isinstance(block, dict):
            continue
        for rule in block.get("rules", []):
            if rule.get("skip"):
                continue
            yield group, rule


def check_style(text: str, dic: Dictionaries) -> list[Issue]:
    """表記ゆれ・公用文ルール・重言・敬語・記号のチェック。"""
    issues: list[Issue] = []
    for group, rule in _iter_style_rules(dic.style):
        find = rule["find"]
        excludes = rule.get("context_exclude", [])
        for m in re.finditer(re.escape(find), text):
            s, e = m.start(), m.end()
            if excludes:
                # 前後を含めた語として除外語に該当するならスキップ
                window = text[max(0, s - 3) : e + 3]
                if any(ex in window for ex in excludes):
                    continue
            issues.append(
                Issue(
                    start=s,
                    end=e,
                    text=find,
                    category=group,
                    severity=rule.get("severity", "info"),
                    message=rule.get("note") or f"「{find}」は「{rule['to']}」に統一します",
                    suggestion=rule["to"],
                    rule_id=f"style.{group}.{find}",
                    auto_fixable="／" not in rule["to"] and "/" not in rule["to"],
                )
            )
    return issues


def check_typos(text: str, dic: Dictionaries) -> list[Issue]:
    """明確な誤字。"""
    issues: list[Issue] = []
    for rule in dic.confusions.get("typos", {}).get("pairs", []):
        find, to = rule["find"], rule["to"]
        if find == to:
            continue
        for m in re.finditer(re.escape(find), text):
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=find,
                    category="誤字",
                    severity="error",
                    message=f"「{find}」は誤りです。「{to}」が正しい表記です",
                    suggestion=to,
                    rule_id=f"typo.{find}",
                    auto_fixable="／" not in to,
                )
            )
    return issues


def check_confusions(text: str, dic: Dictionaries) -> list[Issue]:
    """同音異義語の使い分け確認（自動修正はしない）。"""
    issues: list[Issue] = []
    for pair in dic.confusions.get("pairs", []):
        if pair.get("skip"):
            continue
        word = pair["word"]
        alts = [a for a in pair.get("alts", []) if a != word]
        if not alts:
            continue
        for m in re.finditer(re.escape(word), text):
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=word,
                    category="同音異義語",
                    severity=pair.get("severity", "info"),
                    message=f"「{word}」／{'・'.join(alts)}の使い分けを確認してください。{pair.get('hint', '')}".strip(),
                    suggestion=None,
                    rule_id=f"confusion.{word}",
                    auto_fixable=False,
                )
            )
    return issues


def check_grammar(text: str) -> list[Issue]:
    """ら抜き・い抜き・二重助詞など、文法まわりのチェック。"""
    issues: list[Issue] = []

    # ら抜き言葉（代表的な一段動詞に限定して誤検出を抑える）
    ranuki_stems = [
        "見", "着", "起き", "落ち", "過ぎ", "信じ", "食べ", "受け", "開け",
        "閉め", "分け", "決め", "続け", "考え", "覚え", "投げ", "借り",
        "降り", "寝", "出", "来",
    ]
    for stem in ranuki_stems:
        for m in re.finditer(re.escape(stem) + r"れる|" + re.escape(stem) + r"れな", text):
            frag = m.group(0)
            fixed = frag.replace("れ", "られ", 1)
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=frag,
                    category="ら抜き言葉",
                    severity="warn",
                    message=f"ら抜き言葉の可能性があります。「{fixed}」が正しい形です",
                    suggestion=fixed,
                    rule_id="grammar.ranuki",
                    auto_fixable=True,
                )
            )

    # い抜き言葉（〜してる／〜見てる）
    for m in re.finditer(r"([てで])(る|ます)(?![らるれろ])", text):
        prev = text[max(0, m.start() - 1) : m.start()]
        if prev in ("っ", "ん", "し", "い"):
            continue
        if m.group(2) == "る":
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=m.group(0),
                    category="い抜き言葉",
                    severity="info",
                    message="い抜き言葉の可能性があります（例: している → してる）。書き言葉では「〜ている」に",
                    suggestion=m.group(1) + "いる",
                    rule_id="grammar.inuki",
                    auto_fixable=False,
                )
            )

    # 二重助詞
    for m in re.finditer(r"(のの|をを|にに|がが|はは|でで|とと|への の)", text):
        issues.append(
            Issue(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                category="助詞",
                severity="error",
                message="助詞が重複しています",
                suggestion=m.group(0)[0],
                rule_id="grammar.dup_particle",
                auto_fixable=True,
            )
        )

    # さ入れ言葉
    for m in re.finditer(r"(?:読|書|話|飲|休|使|作|待|包|運)まさせて|[ぁ-ん一-龥]らさせて", text):
        issues.append(
            Issue(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                category="さ入れ言葉",
                severity="warn",
                message="さ入れ言葉の可能性があります（例: 読まさせて → 読ませて）",
                suggestion=None,
                rule_id="grammar.sainre",
                auto_fixable=False,
            )
        )

    return issues


def check_punctuation(text: str) -> list[Issue]:
    """括弧の対応、句読点の重複、半角カナなど。"""
    issues: list[Issue] = []

    pairs = {"「": "」", "『": "』", "（": "）", "【": "】", "《": "》", "〈": "〉"}
    closers = {v: k for k, v in pairs.items()}
    stack: list[tuple[str, int]] = []
    for i, ch in enumerate(text):
        if ch in pairs:
            stack.append((ch, i))
        elif ch in closers:
            if not stack or stack[-1][0] != closers[ch]:
                issues.append(
                    Issue(
                        start=i,
                        end=i + 1,
                        text=ch,
                        category="括弧",
                        severity="error",
                        message=f"対応する開き括弧がない「{ch}」があります",
                        rule_id="punct.unbalanced",
                    )
                )
            else:
                stack.pop()
    for ch, i in stack:
        issues.append(
            Issue(
                start=i,
                end=i + 1,
                text=ch,
                category="括弧",
                severity="error",
                message=f"閉じ括弧がない「{ch}」があります",
                rule_id="punct.unbalanced",
            )
        )

    # 半角カナ
    for m in re.finditer(r"[｡-ﾟ]+", text):
        issues.append(
            Issue(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                category="文字種",
                severity="error",
                message="半角カナは使えません。全角に直してください",
                rule_id="punct.hankaku_kana",
                auto_fixable=True,
            )
        )

    # 句読点の重複・行頭の句読点
    for m in re.finditer(r"[、。]{2,}", text):
        issues.append(
            Issue(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                category="句読点",
                severity="warn",
                message="句読点が連続しています",
                suggestion=m.group(0)[0],
                rule_id="punct.repeat",
                auto_fixable=True,
            )
        )

    # 全角と半角が混在した数字
    if re.search(r"[0-9]", text) and re.search(r"[０-９]", text):
        for m in re.finditer(r"[０-９]{2,}", text):
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=m.group(0),
                    category="数字表記",
                    severity="warn",
                    message="縦書きでは2桁以上の数字は半角にそろえます",
                    suggestion=m.group(0).translate(
                        str.maketrans("０１２３４５６７８９", "0123456789")
                    ),
                    rule_id="punct.number_width",
                    auto_fixable=True,
                )
            )
    for m in re.finditer(r"(?<![0-9])[0-9](?![0-9])", text):
        # 単独の半角1桁は全角にする（縦書きの慣行）
        after = text[m.end() : m.end() + 1]
        if after in ("F", "P", "p", "％"):
            continue
        issues.append(
            Issue(
                start=m.start(),
                end=m.end(),
                text=m.group(0),
                category="数字表記",
                severity="info",
                message="縦書きでは1桁の数字は全角にします",
                suggestion=m.group(0).translate(
                    str.maketrans("0123456789", "０１２３４５６７８９")
                ),
                rule_id="punct.number_width1",
                auto_fixable=True,
            )
        )

    return issues


def check_readability(text: str, *, max_sentence: int = 90) -> list[Issue]:
    """読みやすさ。長すぎる文、同じ助詞の連続、同語反復。"""
    issues: list[Issue] = []
    pos = 0
    for sent in split_sentences(text):
        idx = text.find(sent, pos)
        if idx < 0:
            idx = pos
        pos = idx + len(sent)
        n = count_chars(sent)
        if n > max_sentence:
            issues.append(
                Issue(
                    start=idx,
                    end=idx + len(sent),
                    text=sent[:30] + "…",
                    category="読みやすさ",
                    severity="warn",
                    message=f"1文が{n}字と長すぎます（目安{max_sentence}字以内）。文を分けてください",
                    rule_id="read.long_sentence",
                )
            )
        # 「が」の多用（逆接と主格が混ざり読みにくくなる）
        if sent.count("が、") >= 2:
            issues.append(
                Issue(
                    start=idx,
                    end=idx + len(sent),
                    text=sent[:30] + "…",
                    category="読みやすさ",
                    severity="info",
                    message="1文の中に「が、」が2回以上あります。文を分けると読みやすくなります",
                    rule_id="read.ga",
                )
            )
        # 同じ助詞「の」の3連続
        if re.search(r"の[^、。]{1,6}の[^、。]{1,6}の", sent):
            issues.append(
                Issue(
                    start=idx,
                    end=idx + len(sent),
                    text=sent[:30] + "…",
                    category="読みやすさ",
                    severity="info",
                    message="「の」が続いています。言い換えを検討してください",
                    rule_id="read.no_chain",
                )
            )
    return issues


def check_ruby(text: str, dic: Dictionaries) -> list[Issue]:
    """難読語にルビを振る提案。"""
    issues: list[Issue] = []
    for word, reading in dic.ruby.get("words", {}).items():
        for m in re.finditer(re.escape(word), text):
            issues.append(
                Issue(
                    start=m.start(),
                    end=m.end(),
                    text=word,
                    category="ルビ",
                    severity="info",
                    message=f"難読語です。ルビ（{reading}）を振ることを検討してください",
                    suggestion=f"{word}（{reading}）",
                    rule_id=f"ruby.{word}",
                    auto_fixable=False,
                )
            )
    return issues


_NOUN_CAND = re.compile(r"[一-龥ァ-ヶ][一-龥ァ-ヶー々]{1,9}")


def check_proper_nouns(text: str, dic: Dictionaries) -> list[Issue]:
    """固有名詞の誤記チェック。

    辞書の語と「1〜2文字だけ違う」語が本文にあれば、誤記の可能性を指摘する。
    完全一致するものは当然ながら指摘しない。
    """
    issues: list[Issue] = []
    nouns = dic.proper_nouns()
    noun_set = set(nouns)
    seen: set[tuple[int, int]] = set()

    # 1) 字形が似た漢字の取り違え（例: 山崎 と 山﨑）
    for a, b in dic.local.get("confusable_kanji", {}).get("pairs", []):
        if a == b:
            continue
        for correct in nouns:
            for wrong_ch, right_ch in ((a, b), (b, a)):
                if right_ch not in correct:
                    continue
                wrong = correct.replace(right_ch, wrong_ch)
                if wrong == correct or wrong in noun_set:
                    continue
                for m in re.finditer(re.escape(wrong), text):
                    key = (m.start(), m.end())
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(
                        Issue(
                            start=m.start(),
                            end=m.end(),
                            text=wrong,
                            category="固有名詞",
                            severity="error",
                            message=f"「{correct}」の誤記の可能性があります（{right_ch} と {wrong_ch} の取り違え）",
                            suggestion=correct,
                            rule_id="noun.confusable_kanji",
                            auto_fixable=True,
                        )
                    )

    # 2) 編集距離による類似チェック
    for m in _NOUN_CAND.finditer(text):
        cand = m.group(0)
        if cand in noun_set:
            continue
        key = (m.start(), m.end())
        if key in seen:
            continue
        for correct in nouns:
            if abs(len(correct) - len(cand)) > 1 or len(correct) < 3:
                continue
            d = levenshtein(cand, correct, limit=1)
            if d == 1:
                seen.add(key)
                issues.append(
                    Issue(
                        start=m.start(),
                        end=m.end(),
                        text=cand,
                        category="固有名詞",
                        severity="warn",
                        message=f"辞書にある「{correct}」に似ています。誤記でないか確認してください",
                        suggestion=correct,
                        rule_id="noun.similar",
                        auto_fixable=False,
                    )
                )
                break
    return issues


# ====================================================================== まとめ

CHECKS = {
    "style": "表記ルール",
    "typo": "誤字",
    "confusion": "同音異義語",
    "grammar": "文法",
    "punct": "記号・句読点",
    "read": "読みやすさ",
    "ruby": "ルビ",
    "noun": "固有名詞",
}


def proofread(
    text: str,
    dic: Dictionaries | None = None,
    *,
    enabled: set[str] | None = None,
    max_sentence: int = 90,
) -> list[Issue]:
    """本文を校正して指摘の一覧を返す。位置順・重要度順に整列済み。"""
    dic = dic or Dictionaries()
    enabled = enabled or set(CHECKS)
    issues: list[Issue] = []
    if "style" in enabled:
        issues += check_style(text, dic)
    if "typo" in enabled:
        issues += check_typos(text, dic)
    if "confusion" in enabled:
        issues += check_confusions(text, dic)
    if "grammar" in enabled:
        issues += check_grammar(text)
    if "punct" in enabled:
        issues += check_punctuation(text)
    if "read" in enabled:
        issues += check_readability(text, max_sentence=max_sentence)
    if "ruby" in enabled:
        issues += check_ruby(text, dic)
    if "noun" in enabled:
        issues += check_proper_nouns(text, dic)

    ignore = set(dic.user.get("ignore", []))
    issues = [i for i in issues if i.rule_id not in ignore]

    issues.sort(key=lambda i: (i.start, SEVERITY_ORDER.get(i.severity, 9)))
    return issues


def apply_fixes(text: str, issues: list[Issue], rule_ids: set[str] | None = None) -> str:
    """自動修正可能な指摘をまとめて適用する（後ろから置換して位置ずれを防ぐ）。"""
    targets = [
        i
        for i in issues
        if i.auto_fixable
        and i.suggestion
        and (rule_ids is None or i.rule_id in rule_ids)
    ]
    # 重なりを除去（前のものを優先）
    targets.sort(key=lambda i: (i.start, -(i.end - i.start)))
    picked: list[Issue] = []
    last_end = -1
    for i in targets:
        if i.start >= last_end:
            picked.append(i)
            last_end = i.end
    for i in reversed(picked):
        text = text[: i.start] + i.suggestion + text[i.end :]
    return text


def summarize_issues(issues: list[Issue]) -> dict:
    """カテゴリ別・重要度別の件数。"""
    by_sev = {"error": 0, "warn": 0, "info": 0}
    by_cat: dict[str, int] = {}
    for i in issues:
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
        by_cat[i.category] = by_cat.get(i.category, 0) + 1
    return {"total": len(issues), "by_severity": by_sev, "by_category": by_cat}
