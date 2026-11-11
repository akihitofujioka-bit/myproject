"""号全体の共通シートをページ別の印付き原稿へ分ける。"""

from __future__ import annotations

import re
from typing import Dict

PAGE = re.compile(r"^【ページ(?::|：)([0-9]+)】\s*$")
SPLIT = "【分割】"


def parse(text: str, pages: list[dict]) -> Dict[int, str]:
    """ページ印のある範囲だけを読む。既存のページ状態は変更しない。"""
    blocks: Dict[int, list[str]] = {}
    current = None
    for line_no, line in enumerate(text.splitlines(), 1):
        mark = PAGE.fullmatch(line.strip())
        if mark:
            number = int(mark.group(1))
            if not 1 <= number <= len(pages):
                raise ValueError(f"{line_no}行目: ページ番号 {number} はありません")
            if "form" in pages[number - 1]:
                raise ValueError(f"{line_no}行目: {number}ページは専用の入力欄で作成します")
            if number in blocks:
                raise ValueError(f"{line_no}行目: {number}ページの指定が重複しています")
            blocks[number] = []
            current = number
        elif current is None:
            if line.strip():
                raise ValueError(f"{line_no}行目: 最初に【ページ:番号】を入れてください")
        else:
            if line.strip().startswith("【ページ"):
                raise ValueError(f"{line_no}行目: ページ指定の書き方を確認してください")
            blocks[current].append(line)
    if not blocks:
        raise ValueError("【ページ:番号】がありません")
    result = {}
    for number, lines in blocks.items():
        page_text = "\n".join(lines).strip()
        if not page_text:
            raise ValueError(f"{number}ページの原稿が空です")
        # 一つの長い本文を好きな箇所で部品へ分ける。文字は消さない。
        page_text = re.sub(r"(?m)^【分割】\s*$", "", page_text)
        page_text = page_text.replace(SPLIT, "\n【本文】")
        if not page_text.strip():
            raise ValueError(f"{number}ページに本文がありません")
        result[number] = page_text
    return result
