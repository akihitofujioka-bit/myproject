"""決まった言い方を、号の操作へ置き換えるチャット（段 1）。

このモジュールは画面に依存せず、解釈しただけでは紙面を変更しない。
利用者が確認したあと ``execute`` を呼んだときだけ Edition の操作を実行する。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import layout
from grid import Rect


EXAMPLES = ["写真2を小さく", "一般質問の2人目", "元に戻して"]
HELP = """次のように入力できます。
・次のページ／前のページ／5ページ／一般質問の2人目／表紙／最終ページ
・写真2を小さく（大・中・小・顔）、写真2を外す／戻す
・この写真を小さく（紙面または部品一覧で写真を選んでから）
・3番を答弁に／この部品を質問に／7番は中見出し
・写真1を2段目の左へ／写真1を3段目の右端へ
・元に戻して／やり直し
・確かめて／Word に書き出して
・あふれているページは？／未入力のページは？"""

NUMBER = r"[0-9〇零一二三四五六七八九十百]+"
KANJI_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


@dataclass(frozen=True)
class Operation:
    """Edition に渡す 1 つの操作。番号は内部と同じく 0 から数える。"""

    kind: str
    page_no: Optional[int] = None
    part_no: Optional[int] = None
    value: str = ""
    rect: Optional[Rect] = None


@dataclass
class Interpretation:
    """読み取った操作と、人に見せる説明。"""

    operations: List[Operation] = field(default_factory=list)
    description: str = ""
    reason: str = ""
    examples: List[str] = field(default_factory=list)

    @property
    def understood(self) -> bool:
        """言い方を安全に読み取れたか返す。"""
        return not self.reason


def _number(text: str) -> int:
    """半角数字または百までの漢数字を整数にする。"""
    if text.isdigit():
        return int(text)
    total = 0
    current = 0
    for char in text:
        if char in KANJI_DIGITS:
            current = KANJI_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        else:
            raise ValueError("数字を読み取れません")
    return total + current


def _clean(text: str) -> str:
    """全角・半角と、意味に関係しない空白や句読点をそろえる。"""
    value = unicodedata.normalize("NFKC", text).strip()
    value = re.sub(r"[\s、。,.!?！？]+", "", value)
    return re.sub(r"ください$", "", value, flags=re.IGNORECASE)


def _failed(reason: str) -> Interpretation:
    return Interpretation(reason=reason, examples=list(EXAMPLES))


def _page_required(edition, page_no: int) -> Optional[Interpretation]:
    if edition is None:
        return _failed("先に号を作るか、号フォルダを開いてください。")
    if not 1 <= page_no <= len(edition.pages):
        return _failed("先に左の一覧からページを選んでください。")
    return None


def _part(edition, page_no: int, selected_part: Optional[int], number: Optional[int],
          photo_only: bool) -> int:
    """画面の選択または表示上の番号から、部品の内部番号を得る。"""
    parts = edition.parts(page_no)
    if number is None:
        if selected_part is None or not 0 <= selected_part < len(parts):
            raise ValueError("紙面または部品一覧から写真を選んでください。" if photo_only
                             else "紙面または部品一覧から部品を選んでください。")
        part_no = selected_part
    elif photo_only:
        photos = [index for index, part in enumerate(parts) if part.kind == "写真"]
        if not photos:
            raise ValueError("このページには写真がありません。")
        if not 1 <= number <= len(photos):
            raise ValueError(f"写真{number}はありません。このページの写真は{len(photos)}枚です。")
        part_no = photos[number - 1]
    else:
        part_no = number - 1
        if not 0 <= part_no < len(parts):
            raise ValueError(f"{number}番の部品はありません。このページの部品は{len(parts)}個です。")
    if photo_only and parts[part_no].kind != "写真":
        raise ValueError("選んでいる部品は写真ではありません。写真を選んでください。")
    return part_no


def _photo_reference(match) -> Optional[int]:
    value = match.groupdict().get("photo") or match.groupdict().get("before")
    return _number(value) if value else None


def _page_description(edition, page_no: int) -> str:
    page = edition.pages[page_no - 1]
    return f"{page_no}ページ（{page['label']}）へ移動します。"


def _move_rect(edition, page_no: int, part_no: int, dan: int, side: str) -> Rect:
    """指定段の左右から、部品を置ける最初の場所を探す。"""
    # 解釈中はページ状態や保存ファイルを変えない。
    result = edition._compose_page(page_no)
    current = next((place.rect for place in result.placements if place.index == part_no), None)
    if current is None:
        raise ValueError("その写真は紙面にありません。外している場合は先に戻してください。")
    if not 0 <= dan < edition.geometry.dans:
        raise ValueError(f"段は1から{edition.geometry.dans}までで指定してください。")
    last = edition.geometry.lines_per_dan - current.line_span
    lines = range(last, -1, -1) if side == "左" else range(0, last + 1)
    for line in lines:
        target = Rect(dan, line, current.dan_span, current.line_span)
        if edition.can_move_part(page_no, part_no, target):
            return target
    raise ValueError(f"{dan + 1}段目には、その写真を置ける空きがありません。")


def interpret(text: str, edition, page_no: int,
              selected_part: Optional[int]) -> Interpretation:
    """人の言葉を決まった操作へ置き換える。解釈だけでは実行しない。"""
    value = _clean(text)
    if not value:
        return _failed("言い方を入力してください。")

    if value in ("使い方", "ヘルプ", "何ができる"):
        return Interpretation(description=HELP)

    if edition is None:
        return _failed("先に号を作るか、号フォルダを開いてください。")

    if value in ("あふれているページは", "あふれたページは"):
        pages = [f"{p['no']}ページ（{p['label']}）" for p in edition.pages
                 if p["state"] == "あふれ"]
        answer = "あふれているページ: " + "、".join(pages) if pages else "あふれているページはありません。"
        return Interpretation(description=answer)
    if value in ("未入力のページは", "未入力ページは"):
        pages = [f"{p['no']}ページ（{p['label']}）" for p in edition.pages
                 if p["state"] == "未入力"]
        answer = "未入力のページ: " + "、".join(pages) if pages else "未入力のページはありません。"
        return Interpretation(description=answer)

    if value in ("元に戻して", "元に戻す", "戻して", "戻す"):
        return Interpretation([Operation("undo")], "直前の操作を元に戻します。")
    if value in ("やり直し", "やり直して", "やり直す"):
        return Interpretation([Operation("redo")], "元に戻した操作をやり直します。")
    if value in ("確かめて", "確かめる", "チェック", "チェックして"):
        return Interpretation([Operation("check")], "号全体を確かめ、結果を表示します。")
    if value.lower() in ("wordに書き出して", "wordに書き出す", "書き出して", "書き出し"):
        return Interpretation([Operation("export")], "号全体を Word と確認リストへ書き出します。")

    target = None
    if value in ("次のページ", "次のページへ"):
        target = page_no + 1
    elif value in ("前のページ", "前のページへ"):
        target = page_no - 1
    elif value == "表紙":
        target = next((p["no"] for p in edition.pages if p["section"] == layout.COVER), None)
    elif value == "最終ページ":
        target = next((p["no"] for p in edition.pages if p["section"] == layout.LAST), None)
    else:
        match = re.fullmatch(rf"({NUMBER})ページ(?:へ)?", value)
        if match:
            target = _number(match.group(1))
        else:
            match = re.fullmatch(rf"一般質問(?:の)?({NUMBER})人目(?:のページ)?(?:へ)?", value)
            if match:
                person = _number(match.group(1))
                target = next((p["no"] for p in edition.pages
                               if p["section"] == layout.IPPAN and p["index"] == person), None)
                if target is None:
                    return _failed(f"一般質問の{person}人目のページはありません。")
    if target is not None:
        if not 1 <= target <= len(edition.pages):
            return _failed(f"{target}ページはありません。ページは1から{len(edition.pages)}までです。")
        return Interpretation([Operation("page", page_no=target)],
                              _page_description(edition, target))

    required = _page_required(edition, page_no)
    if required:
        return required

    photo_head = rf"(?:(?:写真(?:の)?(?P<photo>{NUMBER}))|(?:(?P<before>{NUMBER})番(?:の)?写真)|(?:この)?写真)"
    move = re.fullmatch(photo_head + rf"(?:を|は)?(?P<dan>{NUMBER})段目(?:の)?(?P<side>左|右端|右)(?:へ|に)?(?:動かして|移動して|動かす|移動する)?", value)
    if move:
        try:
            photo_no = _photo_reference(move)
            part_no = _part(edition, page_no, selected_part, photo_no, True)
            dan = _number(move.group("dan")) - 1
            side = "左" if move.group("side") == "左" else "右"
            rect = _move_rect(edition, page_no, part_no, dan, side)
        except (OSError, ValueError) as error:
            return _failed(str(error))
        shown = photo_no or ([i for i, p in enumerate(edition.parts(page_no))
                              if p.kind == "写真"].index(part_no) + 1)
        description = f"写真{shown}を{dan + 1}段目の{side}端へ移動します。"
        return Interpretation([Operation("move", page_no, part_no, rect=rect)], description)

    photo = re.fullmatch(photo_head + r"(?:を|は)?(?P<action>小さく(?:して)?|大きく(?:して)?|[大小中顔](?:に)?(?:して)?|外して|外す|戻して|戻す)", value)
    if photo:
        try:
            photo_no = _photo_reference(photo)
            part_no = _part(edition, page_no, selected_part, photo_no, True)
        except (OSError, ValueError) as error:
            return _failed(str(error))
        action = photo.group("action")
        shown = photo_no or ([i for i, p in enumerate(edition.parts(page_no))
                              if p.kind == "写真"].index(part_no) + 1)
        if action.startswith("外"):
            return Interpretation([Operation("remove", page_no, part_no)], f"写真{shown}を紙面から外します。")
        if action.startswith("戻"):
            return Interpretation([Operation("restore", page_no, part_no)], f"写真{shown}を紙面へ戻します。")
        size = "小" if action.startswith("小") else "大" if action.startswith("大") else action[0]
        return Interpretation([Operation("resize", page_no, part_no, size)], f"写真{shown}の大きさを「{size}」にします。")

    kind = re.fullmatch(rf"(?:(?P<number>{NUMBER})番|この部品)(?:を|は)?(?P<kind>大見出し|中見出し|質問|答弁|本文|写真説明|議案)(?:に)?(?:して)?", value)
    if kind:
        try:
            number = _number(kind.group("number")) if kind.group("number") else None
            part_no = _part(edition, page_no, selected_part, number, False)
        except (OSError, ValueError) as error:
            return _failed(str(error))
        return Interpretation([Operation("kind", page_no, part_no, kind.group("kind"))],
                              f"{part_no + 1}番の部品を「{kind.group('kind')}」にします。")

    return _failed("その言い方は読み取れませんでした。推測では操作しません。")


def execute(interpretation: Interpretation, edition) -> str:
    """確認済みの操作を順に実行し、結果を人向けの文で返す。"""
    if not interpretation.understood:
        return "読み取れなかったため、実行しませんでした。"
    if not interpretation.operations:
        return interpretation.description
    results = []
    try:
        for operation in interpretation.operations:
            if operation.kind == "page":
                results.append(f"{operation.page_no}ページへ移動します。")
            elif operation.kind == "resize":
                changed = edition.resize_photo(operation.page_no, operation.part_no,
                                               operation.value)
                results.append("写真の大きさを変えました。" if changed else
                               "ほかの部品と重なるため、写真の大きさを変えませんでした。")
            elif operation.kind == "remove":
                edition.remove_photo(operation.page_no, operation.part_no)
                results.append("写真を紙面から外しました。元画像は残っています。")
            elif operation.kind == "restore":
                edition.restore_photo(operation.page_no, operation.part_no)
                results.append("写真を紙面へ戻しました。")
            elif operation.kind == "kind":
                edition.set_kind(operation.page_no, operation.part_no, operation.value)
                results.append(f"部品の種類を「{operation.value}」にしました。")
            elif operation.kind == "move":
                changed = edition.move_part(operation.page_no, operation.part_no,
                                            operation.rect)
                results.append("写真を移動しました。" if changed else
                               "その場所には置けないため、写真を移動しませんでした。")
            elif operation.kind == "undo":
                results.append("直前の操作を元に戻しました。" if edition.undo() else
                               "元に戻せる操作はありません。")
            elif operation.kind == "redo":
                results.append("操作をやり直しました。" if edition.redo() else
                               "やり直せる操作はありません。")
            elif operation.kind == "check":
                messages = edition.check()
                results.append("確かめた結果:\n" + ("\n".join(messages) if messages else
                                                     "問題はありません。"))
            elif operation.kind == "export":
                paths = edition.export()
                results.append("書き出しました。\n" + "\n".join(str(Path(p)) for p in paths[:3]))
            else:
                return "未対応の操作のため、実行しませんでした。"
    except (OSError, ValueError) as error:
        return "実行できませんでした: " + str(error)
    return "\n".join(results)
