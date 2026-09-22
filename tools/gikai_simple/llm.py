"""ローカル LLM の差し込み口（任意。無くてもツールは動く）。

ルールベースの校正（proofread.py）は「規則に当てはまるもの」しか見つけられない。
文脈で決まる誤り — 脱字、「以外／意外」の取り違え、係り受けの乱れ — は
規則に書けないので、この小さな言語モデルに見てもらう。

## 外に出さないための決まりごと

**つなぐ先は 127.0.0.1（このパソコン自身）だけ。** 別のパソコンやインターネット上の
サービスは、設定でも指定できないようにしてある（`_check_host` で弾く）。
原稿がこのパソコンから出ることはない。

## 動かすのに要るもの

1. **Ollama**（<https://ollama.com>）— このパソコンの中で言語モデルを動かす仕組み
2. **モデル**（1〜2GB のファイル）

役場のパソコンはインターネットにつながらないので、どちらも
インターネットにつながるパソコンで用意して USB で持ち込む。手順は README.md の
「ローカル LLM を使う（任意）」を見ること。

入っていなければ `available()` が理由を返し、画面には「使えません」と出るだけで、
ほかの機能はふつうに動く。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

# つなぐ先。ここを書き換えて外部のサービスを指すことはできない（_check_host で弾く）
HOST = "127.0.0.1"
PORT = 11434
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")

# 1 回に見てもらう長さ。小さいモデルは長い文章を渡すと精度が落ちるので短く区切る
CHUNK_CHARS = 400
TIMEOUT_SEC = 120        # 画像処理装置のないパソコンだと 1 かたまりで数十秒かかる

PROMPT = """あなたは日本の市町村議会が出す広報紙の校正係です。
次の文章から、明らかな誤りだけを拾ってください。

拾うもの:
- 誤字・脱字（「実施ます」→「実施します」など）
- 同音異義語の取り違え（意外／以外、追求／追及、保障／保証 など）
- 主語と述語が食い違っている、助詞がおかしい

拾わないもの:
- 言い回しの好み、もっと良い表現の提案
- 漢字をひらがなに開くかどうか
- 固有名詞、数字の全角半角（別の仕組みで見ています）
- 少しでも迷うもの（**確信のあるものだけ**にしてください。
  間違っていないものを間違いと言われるほうが困ります）

見つからなければ [] とだけ答えてください。
説明や前置きは書かず、次の形の JSON だけを答えてください。

[{"text": "原文のままの誤っている部分", "fix": "直した形", "why": "理由を20字以内で"}]

--- 文章 ---
"""


@dataclass
class LlmIssue:
    """LLM が見つけた指摘。proofread.Issue と同じように扱えるようにしてある。"""
    start: int
    end: int
    text: str
    category: str = "AI校正"
    severity: str = "info"       # 確実ではないので、いちばん弱い扱いにする
    message: str = ""
    suggestion: str | None = None
    rule_id: str = "llm"
    auto_fixable: bool = False   # 人が見て直す。まとめて自動修正はさせない


def _check_host(host: str) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"つなぐ先は {ALLOWED_HOSTS} だけです（指定: {host}）。"
            "原稿を外に出さないための決まりです。"
        )


def _get(path: str, timeout: int = 5):
    _check_host(HOST)
    url = f"http://{HOST}:{PORT}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310（127.0.0.1 限定）
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, payload: dict, timeout: int):
    _check_host(HOST)
    url = f"http://{HOST}:{PORT}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310（127.0.0.1 限定）
        return json.loads(r.read().decode("utf-8"))


def models() -> list[str]:
    """このパソコンに入っているモデルの名前。つながらなければ空。"""
    try:
        data = _get("/api/tags")
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return []
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


# 試した結果、同じ原稿で 7b は誤検出 0 件、3b は 3 件だった。大きいほうを優先する。
PREFERRED = ("qwen2.5:7b", "qwen2.5:3b", "qwen2.5", "qwen", "llama3.1", "gemma2")


def pick_model(found: list[str] | None = None) -> str:
    """入っているモデルから、校正に向いたものを選ぶ。"""
    found = found if found is not None else models()
    for want in PREFERRED:
        for m in found:
            if m.startswith(want):
                return m
    return found[0] if found else ""


def available() -> tuple[bool, str]:
    """使える状態か。使えないときは、何をすればよいかを日本語で返す。"""
    found = models()
    if not found:
        return False, (
            "このパソコンでは AI 校正を使えません。\n\n"
            "Ollama（言語モデルを動かす仕組み）が動いていないか、モデルが入っていません。\n"
            "入れ方は README.md の「ローカル LLM を使う（任意）」を見てください。\n\n"
            "AI 校正が無くても、ふつうの校正と文字数チェックは使えます。"
        )
    return True, "／".join(found)


def _chunks(text: str, size: int = CHUNK_CHARS):
    """文の切れ目で区切って、(本文中の位置, 文字列) を返す。"""
    pos, buf, start = 0, "", 0
    for part in re.split(r"(?<=[。！？\n])", text):
        if buf and len(buf) + len(part) > size:
            yield start, buf
            start, buf = pos, ""
        if not buf:
            start = pos
        buf += part
        pos += len(part)
    if buf.strip():
        yield start, buf


def _parse(reply: str) -> list[dict]:
    """モデルの返事から JSON を取り出す。小さいモデルは前置きを付けがちなので緩く拾う。"""
    m = re.search(r"\[.*\]", reply, re.S)
    if not m:
        return []
    try:
        got = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [g for g in got if isinstance(g, dict) and g.get("text")]


# モデルが返しがちな、役に立たない指摘のふるい分け。
# 第201号の実際の原稿で試して決めた値（下の「試した結果」を参照）。
MAX_SPAN = 40          # これより長い指摘は文まるごとの書き直しとみなす
MAX_DIFF_RATIO = 0.3   # 元の 3 割を超えて書き換える提案は「言い換え」なので捨てる


def _diff_ratio(a: str, b: str) -> float:
    """2 つの文字列がどれくらい違うか（0＝同じ、1＝まるで別物）。

    誤字の直し（「説明ました」→「説明しました」）は少ししか変わらないが、
    言い換えの提案は大きく変わる。この差で見分ける。
    """
    import difflib
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def _is_noise(found: str, fix: str, nouns: set[str]) -> bool:
    """採ってはいけない指摘か。

    小さいモデルは、直っていない指摘・固有名詞の言い換え・文まるごとの
    書き直しを返してくる。実際の原稿で試したところ指摘の大半がこれだったので、
    ここで落とす。落としすぎると本当の誤りも消えるので、条件は控えめにしてある。
    """
    if not fix or fix == found:
        return True                        # 「武政義幸様 → 武政義幸様」のたぐい
    if len(found) > MAX_SPAN:
        return True                        # 文まるごとの書き直し
    if _diff_ratio(found, fix) > MAX_DIFF_RATIO:
        return True                        # 直しではなく言い換えの提案
    if found in nouns or fix in nouns:
        return True                        # 固有名詞は辞書の担当（勝手に変えさせない）
    if any(n in found for n in nouns if len(n) >= 3):
        return True                        # 固有名詞を含む範囲も触らせない
    return False


def check(text: str, model: str, *, progress=None) -> list[LlmIssue]:
    """本文を見てもらい、指摘の一覧を返す。

    progress に関数を渡すと (終わったかたまり数, 全体数) で呼ぶ（画面の進み具合用）。
    途中で失敗したかたまりは黙って飛ばす（一部でも結果が出たほうが役に立つため）。
    """
    parts = list(_chunks(text))
    issues: list[LlmIssue] = []
    try:
        import proofread
        nouns = set(proofread.Dictionaries().proper_nouns())
    except Exception:
        nouns = set()
    for n, (offset, chunk) in enumerate(parts, 1):
        if progress:
            progress(n, len(parts))
        try:
            res = _post(
                "/api/generate",
                {
                    "model": model,
                    "prompt": PROMPT + chunk,
                    "stream": False,
                    "options": {"temperature": 0},   # 毎回同じ答えになるように
                },
                timeout=TIMEOUT_SEC,
            )
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
        for got in _parse(res.get("response", "")):
            found = str(got["text"])
            # モデルが原文にない文字列を返すことがあるので、本文にある場合だけ採る
            i = chunk.find(found)
            if i < 0 or not found.strip():
                continue
            fix = str(got.get("fix", "") or "").strip()
            why = str(got.get("why", "") or "").strip()
            if _is_noise(found, fix, nouns):
                continue
            issues.append(LlmIssue(
                start=offset + i,
                end=offset + i + len(found),
                text=found,
                message=(why or "確認してください") + "（AI の指摘です。必ず人の目で確かめてください）",
                suggestion=fix or None,
            ))
    issues.sort(key=lambda i: i.start)
    return issues
