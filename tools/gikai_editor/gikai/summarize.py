"""要約・字数調整（完全オフライン）。

議会だよりの枠は「全角◯字 × ◯行」で決まっている。原稿はたいてい
枠より長いので、(1) 抽出型要約で重要な文を残す、(2) 冗長表現を機械的に
短くする、の2段構えで枠に収める。

外部の言語モデルには接続しない。ただし ``llm.py`` 経由でローカルの
言語モデル（Ollama / llama.cpp）が使える環境なら、そちらを優先できる。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .textutil import count_chars, split_paragraphs, split_sentences

# ------------------------------------------------------------------ 圧縮ルール

# 意味を変えずに短くできる定型表現。長い順に適用する。
SHORTEN_RULES: list[tuple[str, str]] = [
    ("することができるようになりました", "できるようになった"),
    ("することができませんでした", "できなかった"),
    ("させていただきたいと思います", "したい"),
    ("させていただいております", "している"),
    ("していただきたいと思います", "してほしい"),
    ("ということになっています", "としている"),
    ("ということでございます", "という"),
    ("なのではないでしょうか", "ではないか"),
    ("するということである", "するという"),
    ("を行うことといたします", "を行う"),
    ("しなければなりません", "する必要がある"),
    ("することができました", "できた"),
    ("することができません", "できない"),
    ("であると考えられます", "と考えられる"),
    ("するようにしています", "している"),
    ("という状況になっている", "という状況だ"),
    ("に関しましては", "については"),
    ("につきましては", "については"),
    ("いたしております", "している"),
    ("することができる", "できる"),
    ("しているところです", "している"),
    ("しておりました", "していた"),
    ("であると思います", "と考える"),
    ("ではないかと思う", "ではないか"),
    ("を実施いたしました", "を実施した"),
    ("を行っております", "を行っている"),
    ("しております", "している"),
    ("いたしました", "した"),
    ("ございました", "あった"),
    ("ということ", "こと"),
    ("となっている", "である"),
    ("に対しまして", "に対し"),
    ("につきまして", "について"),
    ("それに加えて", "また"),
    ("そのほかにも", "ほかにも"),
    ("という形で", "として"),
    ("を通じまして", "を通じ"),
    ("などについて", "などを"),
    ("であります", "である"),
    ("と思われます", "とみられる"),
    ("かと思います", "と考える"),
    ("いただきました", "いただいた"),
    ("なさっている", "している"),
    ("等について", "などを"),
]

# 削っても意味が変わりにくい副詞・接続詞
FILLER_WORDS = [
    "やはり", "まさに", "いわゆる", "非常に", "きわめて", "とても",
    "かなり", "しっかりと", "改めて", "やや", "ある意味", "基本的に",
    "個人的には", "正直", "実際のところ", "そういった中で",
]


def shorten(text: str, *, drop_fillers: bool = False) -> str:
    """定型的な冗長表現を機械的に短くする（意味は保つ）。"""
    for long, short in SHORTEN_RULES:
        text = text.replace(long, short)
    if drop_fillers:
        for w in FILLER_WORDS:
            text = text.replace(w, "")
    text = re.sub(r"、{2,}", "、", text)
    text = re.sub(r"^、", "", text, flags=re.MULTILINE)
    return text


# ------------------------------------------------------------------ 抽出型要約

_STOP = set(
    "これ それ あれ この その あの ここ そこ あちら こと もの ため よう "
    "など また および ならびに しかし そして さらに なお ただし つまり "
    "する した して いる ある なる れる られる ます です から より ので "
    "けれど けれども および".split()
)

_TOKEN = re.compile(r"[一-龥々]{2,}|[ァ-ヶー]{2,}|[a-zA-Z]{3,}|[０-９0-9]+[年月日人円%％]")


def _tokens(text: str) -> list[str]:
    """簡易的な特徴語抽出。形態素解析器がなくても動くようにしている。

    漢字連続・カタカナ連続・英字・数量表現を語とみなす。
    """
    return [t for t in _TOKEN.findall(text) if t not in _STOP]


def keywords(text: str, top: int = 15) -> list[tuple[str, int]]:
    """本文中の特徴語（出現回数順）。"""
    return Counter(_tokens(text)).most_common(top)


def _score_sentences(sentences: list[str]) -> list[float]:
    """TF ベース + 位置ボーナスで文に重みを付ける。"""
    df = Counter()
    tok_list = []
    for s in sentences:
        toks = _tokens(s)
        tok_list.append(toks)
        df.update(set(toks))
    n = max(1, len(sentences))
    scores = []
    for i, toks in enumerate(tok_list):
        if not toks:
            scores.append(0.0)
            continue
        tf = Counter(toks)
        score = 0.0
        for t, c in tf.items():
            idf = math.log(1 + n / (1 + df[t]))
            score += (1 + math.log(c)) * (1 + idf) * min(len(t), 6) / 6
        score /= math.sqrt(len(toks))
        # 冒頭の文は要旨を含みやすい
        if i == 0:
            score *= 1.6
        elif i == 1:
            score *= 1.2
        # 結論を示す語を含む文を優遇
        if re.search(r"(決定|可決|承認|同意|決まった|求めた|表明|方針|課題|必要)", sentences[i]):
            score *= 1.25
        # 発言者の紹介などは要旨として弱い
        if re.search(r"^(なお|ちなみに|また)", sentences[i]):
            score *= 0.85
        scores.append(score)
    return scores


@dataclass
class SummaryResult:
    text: str
    chars: int
    kept: int
    total: int
    method: str
    note: str = ""


def summarize(
    text: str,
    *,
    target_chars: int,
    keep_first: bool = True,
    aggressive: bool = True,
) -> SummaryResult:
    """``target_chars`` 全角字以内に収まるように要約する。

    手順:
      1. 冗長表現の圧縮だけで収まるならそれで終わり（情報を落とさない）
      2. 収まらなければ、重要度の低い文から落とす
      3. それでも収まらなければ、副詞なども削る

    段落構造はできるだけ保つ。
    """
    original = text
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return SummaryResult("", 0, 0, 0, "empty")

    # --- 段階1: 圧縮のみ
    compressed = "\n".join(shorten(p) for p in paragraphs)
    if count_chars(compressed) <= target_chars:
        total = len(split_sentences(original))
        return SummaryResult(
            compressed,
            count_chars(compressed),
            total,
            total,
            "圧縮のみ",
            "冗長表現の言い換えだけで枠に収まりました。内容は削っていません。",
        )

    # --- 段階2: 文の重要度で取捨選択（段落ごとに最低1文は残す）
    para_sents = [split_sentences(shorten(p)) for p in paragraphs]
    flat: list[tuple[int, int, str]] = []
    for pi, sents in enumerate(para_sents):
        for si, s in enumerate(sents):
            flat.append((pi, si, s))
    if not flat:
        return SummaryResult(compressed, count_chars(compressed), 0, 0, "圧縮のみ")

    scores = _score_sentences([s for _, _, s in flat])
    order = sorted(range(len(flat)), key=lambda i: -scores[i])

    keep: set[int] = set()
    used = 0
    # 各段落の先頭文は優先的に確保する
    if keep_first:
        for pi, sents in enumerate(para_sents):
            if not sents:
                continue
            idx = next(i for i, (p, s, _) in enumerate(flat) if p == pi and s == 0)
            w = count_chars(flat[idx][2])
            if used + w <= target_chars:
                keep.add(idx)
                used += w
    for i in order:
        if i in keep:
            continue
        w = count_chars(flat[i][2])
        if used + w <= target_chars:
            keep.add(i)
            used += w
        if used >= target_chars:
            break

    def build(kept: set[int]) -> str:
        out_paras: list[str] = []
        for pi in range(len(para_sents)):
            body = "".join(
                flat[i][2] for i in sorted(kept) if flat[i][0] == pi
            )
            if body:
                out_paras.append(body)
        return "\n".join(out_paras)

    result = build(keep)

    # --- 段階3: それでも溢れるなら副詞なども削る
    if count_chars(result) > target_chars and aggressive:
        result = shorten(result, drop_fillers=True)

    total = len(flat)
    return SummaryResult(
        result,
        count_chars(result),
        len(keep),
        total,
        "抽出要約",
        f"{total}文のうち重要度の高い{len(keep)}文を残しました。必ず内容をご確認ください。",
    )


def fit_to_frame(text: str, *, chars_per_line: int, lines: int) -> SummaryResult:
    """「◯字詰め × ◯行」の枠に合わせて要約する。"""
    # 段落ごとの端数を考えて、目標をやや小さめに取る
    target = max(1, chars_per_line * lines - chars_per_line // 2)
    return summarize(text, target_chars=target)


def lead_sentence(text: str, max_chars: int = 40) -> str:
    """リード文（見出し下の要旨）の候補を作る。"""
    sents = split_sentences(shorten(text))
    if not sents:
        return ""
    scores = _score_sentences(sents)
    best = sents[max(range(len(sents)), key=lambda i: scores[i])]
    best = re.sub(r"^(また|なお|さらに|そして)、?", "", best)
    if count_chars(best) <= max_chars:
        return best
    # 述部を落として名詞止めにする
    trimmed = re.sub(r"(である|です|ます|だ)。?$", "", best)
    while count_chars(trimmed) > max_chars and "、" in trimmed:
        trimmed = trimmed.rsplit("、", 1)[0]
    return trimmed[: max_chars] if count_chars(trimmed) > max_chars else trimmed


def headline_candidates(text: str, max_chars: int = 13, n: int = 5) -> list[str]:
    """見出し候補を作る。体言止め・短い語を優先。"""
    cands: list[tuple[float, str]] = []
    sents = split_sentences(text)
    scores = _score_sentences(sents) if sents else []
    for s, sc in zip(sents, scores):
        # 述部を落として名詞止めに
        h = re.sub(r"(することとなった|することにした|しています|している|"
                   r"となっている|であった|でした|します|ました|である|です|ます|だ)。?$", "", s)
        h = re.sub(r"^(また|なお|さらに|そして|しかし)、?", "", h)
        h = h.rstrip("。、")
        if not h:
            continue
        # 長すぎるものは最後の読点以降を採用
        while count_chars(h) > max_chars and "、" in h:
            h = h.split("、", 1)[1]
        if count_chars(h) > max_chars:
            continue
        cands.append((sc, h))
    # 特徴語の組み合わせも候補に
    kw = [w for w, _ in keywords(text, 4)]
    if len(kw) >= 2:
        joined = kw[0] + "の" + kw[1]
        if count_chars(joined) <= max_chars:
            cands.append((0.5, joined))
    seen: set[str] = set()
    out: list[str] = []
    for _, h in sorted(cands, key=lambda x: -x[0]):
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
        if len(out) >= n:
            break
    return out
