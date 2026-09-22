"""日本語テキストの正規化ユーティリティ。

議会だよりは縦書きのため、数字の全角／半角の使い分けなど、
一般的な文書とは異なる表記ルールがある。ここではその基礎処理を提供する。
外部ライブラリには依存しない（オフライン前提）。
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 文字種判定

ZEN_DIGITS = "０１２３４５６７８９"
HAN_DIGITS = "0123456789"
_Z2H_DIGIT = str.maketrans(ZEN_DIGITS, HAN_DIGITS)
_H2Z_DIGIT = str.maketrans(HAN_DIGITS, ZEN_DIGITS)

# 全角英字 → 半角英字
_ZEN_ALPHA = "".join(chr(c) for c in range(0xFF21, 0xFF3B)) + "".join(
    chr(c) for c in range(0xFF41, 0xFF5B)
)
_HAN_ALPHA = "".join(chr(c) for c in range(0x41, 0x5B)) + "".join(
    chr(c) for c in range(0x61, 0x7B)
)
_Z2H_ALPHA = str.maketrans(_ZEN_ALPHA, _HAN_ALPHA)
_H2Z_ALPHA = str.maketrans(_HAN_ALPHA, _ZEN_ALPHA)

# 半角カナ → 全角カナ（濁点結合を含む）
_HANKAKU_KANA_BASE = (
    "｡｢｣､･ｦｧｨｩｪｫｬｭｮｯｰｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝﾞﾟ"
)

CJK_RANGES = (
    (0x3000, 0x303F),  # 記号
    (0x3040, 0x309F),  # ひらがな
    (0x30A0, 0x30FF),  # カタカナ
    (0x4E00, 0x9FFF),  # 漢字
    (0xF900, 0xFAFF),  # 互換漢字
    (0xFF00, 0xFF60),  # 全角形
    (0xFFE0, 0xFFE6),
)


def is_fullwidth(ch: str) -> bool:
    """縦書き組版で1文字ぶんの幅を占める文字か。"""
    if not ch:
        return False
    return unicodedata.east_asian_width(ch) in ("F", "W", "A")


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in CJK_RANGES)


# ---------------------------------------------------------------- 字数カウント


def count_chars(text: str, *, ignore_newline: bool = True) -> int:
    """原稿の実字数。半角2文字を全角1文字として数える（組版の目安）。

    議会だよりの枠は「全角何文字 × 何行」で決まるため、
    半角英数は2文字で全角1文字ぶんとして数えるのが実務に合う。
    """
    n = 0.0
    for ch in text:
        if ignore_newline and ch in "\r\n":
            continue
        n += 1.0 if is_fullwidth(ch) else 0.5
    return int(n + 0.999)  # 切り上げ


def count_raw(text: str) -> int:
    """改行を除いた素の文字数。"""
    return len(re.sub(r"[\r\n]", "", text))


def estimate_lines(text: str, chars_per_line: int) -> int:
    """1行あたり ``chars_per_line`` 文字の枠に流し込んだときの行数を見積もる。

    段落ごとに改行が入り、各段落の先頭は1字下げになる前提。
    """
    if chars_per_line <= 0:
        return 0
    lines = 0
    for para in text.split("\n"):
        para = para.rstrip()
        if not para:
            lines += 1
            continue
        w = count_chars(para)
        lines += max(1, -(-w // chars_per_line))
    return lines


# ---------------------------------------------------------------- 正規化


def normalize_space(text: str) -> str:
    """余分な空白・改行を整理する。全角スペースの行頭字下げは保持。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    out = []
    for line in text.split("\n"):
        indent = "　" if line.startswith("　") else ""
        body = line.strip().lstrip("　")
        # 連続する半角スペースを1つに
        body = re.sub(r" {2,}", " ", body)
        # 全角文字に挟まれた半角スペースは削除（不要な空きになりやすい）
        body = re.sub(r"(?<=[^\x00-\x7F]) (?=[^\x00-\x7F])", "", body)
        out.append(indent + body)
    text = "\n".join(out)
    # 3行以上の連続改行は2行に
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def to_halfwidth_alnum(text: str) -> str:
    """全角の英数字を半角にする（記号は変えない）。"""
    return text.translate(_Z2H_ALPHA).translate(_Z2H_DIGIT)


def hankaku_kana_to_zenkaku(text: str) -> str:
    """半角カナを全角カナへ。"""
    if not any(ch in _HANKAKU_KANA_BASE for ch in text):
        return text
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------- 数字の表記

_NUM_RE = re.compile(r"[0-9０-９]+")


def normalize_numbers_tategaki(text: str) -> str:
    """縦書きの慣行に合わせて数字表記を統一する。

    ルール（議会だより第203号の実物から確認）:
      * 1桁の数字は全角（例: ４月、５月15日）
      * 2桁以上の数字は半角（例: 12日、59･60％、1千400人）
      * 小数点・区切りの「・」「.」は半角中点「･」

    西暦・電話番号・郵便番号のように「桁で区切らない」ものは
    呼び出し側で除外すること。
    """

    def repl(m: re.Match) -> str:
        s = m.group(0).translate(_Z2H_DIGIT)
        if len(s) == 1:
            return s.translate(_H2Z_DIGIT)
        return s

    text = _NUM_RE.sub(repl, text)
    # 数字にはさまれた中点・ピリオドを半角中点に
    text = re.sub(r"(?<=[0-9])[\.．・]\s*(?=[0-9])", "･", text)
    return text


def normalize_punctuation(text: str) -> str:
    """句読点・括弧・記号を全角に統一する。"""
    table = {
        ",": "、",
        ".": "。",
        "!": "！",
        "?": "？",
        "(": "（",
        ")": "）",
        "[": "「",
        "]": "」",
        ":": "：",
        ";": "；",
        "~": "〜",
        "ｰ": "ー",
    }
    out = []
    for ch in text:
        # 半角英数の直後・直前の記号は英文用としてそのまま残す判定はせず、
        # 日本語本文を前提に全角へ寄せる
        out.append(table.get(ch, ch))
    text = "".join(out)
    text = text.replace("｡", "。").replace("､", "、")
    text = re.sub(r"。{2,}", "。", text)
    text = re.sub(r"、{2,}", "、", text)
    text = text.replace("...", "…").replace("……………", "……")
    return text


def normalize_manuscript(text: str, *, numbers: bool = True) -> str:
    """取り込んだ原稿に対する既定の正規化一式。"""
    text = hankaku_kana_to_zenkaku(text)
    text = normalize_space(text)
    text = normalize_punctuation(text)
    text = to_halfwidth_alnum(text)
    if numbers:
        text = normalize_numbers_tategaki(text)
    return text


# ---------------------------------------------------------------- 文分割

_SENT_END = re.compile(r"(?<=[。！？])(?![」』）】\)])")


def split_sentences(text: str) -> list[str]:
    """日本語の文に分割する。括弧内の句点では切らない。"""
    sentences: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        buf = ""
        depth = 0
        for ch in para:
            buf += ch
            if ch in "「『（【(":
                depth += 1
            elif ch in "」』）】)":
                depth = max(0, depth - 1)
            elif ch in "。！？" and depth == 0:
                sentences.append(buf.strip())
                buf = ""
        if buf.strip():
            sentences.append(buf.strip())
    return sentences


def split_paragraphs(text: str) -> list[str]:
    return [p for p in (s.strip() for s in text.split("\n")) if p]


# ---------------------------------------------------------------- 距離


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    """編集距離。``limit`` を超える場合は打ち切って limit+1 を返す。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(v)
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]
