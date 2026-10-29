"""特集などに入れる表。Word・エクセルの表を読み、紙面の横書きの表にする。

表は「名前」と「行ごとの文字（列はタブか｜で区切る）」で持つ。本文の中の
`【表】名前` の行に、その表が入る。紙面の原稿には、表の中身ごと 1 行にして渡す
（`【表】{"name": …, "rows": [[…], …]}`）。
"""

from __future__ import annotations

import json
import math
import re
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

from grid import text_width

MARK = "【表】"
CELL_PT = 9.0          # 表の字の大きさ
PAD_PT = 4.0           # セルの左右の余白の合計
LINE_RATIO = 1.4       # 行の高さ = 字 × 1.4（Word の「最小値」と同じ考え方）

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ---------------------------------------------------------------- 文字との行き来

def parse_rows(text: str) -> List[List[str]]:
    """入力欄の文字を行と列に分ける。列はタブ（エクセル・Word から貼った形）か｜で区切る。"""
    rows = []
    for raw in str(text or "").splitlines():
        if not raw.strip():
            continue
        if "\t" in raw:
            cells = raw.split("\t")
        else:
            cells = re.split(r"[｜|]", raw.strip().strip("｜|"))
        rows.append([cell.strip() for cell in cells])
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def rows_text(rows: List[List[str]]) -> str:
    """行と列を入力欄の文字（列は｜で区切る）にする。セルの中の改行は空白にする。"""
    return "\n".join("｜".join(str(cell).replace("\n", " ") for cell in row) for row in rows)


def encode(name: str, rows: List[List[str]]) -> str:
    return MARK + json.dumps({"name": name, "rows": rows}, ensure_ascii=False)


def decode(text: str) -> Optional[Tuple[str, List[List[str]]]]:
    """原稿の 1 行から (名前, 行) を読む。中身の入っていない【表】名前 なら None。"""
    body = str(text or "")
    if body.startswith(MARK):
        body = body[len(MARK):]
    body = body.strip()
    if not body.startswith("{"):
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    rows = [[str(cell) for cell in row] for row in value.get("rows", []) if isinstance(row, list)]
    return str(value.get("name", "")), rows


def fill_marks(body: str, tables: List[dict]) -> Tuple[str, List[str]]:
    """本文の `【表】名前` の行を、表の中身入りの行に置き換える。見つからない名前は知らせる。"""
    by_name = {str(t.get("name", "")).strip(): t for t in tables or []}
    lines, missing = [], []
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(MARK) and not stripped[len(MARK):].strip().startswith("{"):
            name = stripped[len(MARK):].strip()
            table = by_name.get(name)
            if table is None:
                missing.append(name)
                continue
            lines.append(encode(name, parse_rows(table.get("data", ""))))
        else:
            lines.append(line)
    return "\n".join(lines), missing


# ---------------------------------------------------------------- 寸法

def _cell_lines(text: str, chars: int) -> int:
    lines = 0
    for piece in str(text).split("\n") or [""]:
        lines += max(1, math.ceil(text_width(piece) / max(1, chars)))
    return lines


def layout(rows: List[List[str]], width_pt: float, pt: float = CELL_PT) -> Tuple[List[float], List[float]]:
    """列の幅と行の高さ（pt）。列の幅は、いちばん長いセルの字数に合わせて全体の幅を分ける。"""
    columns = max((len(row) for row in rows), default=1)
    need = []
    for column in range(columns):
        longest = max((text_width(row[column]) if column < len(row) else 0 for row in rows), default=0)
        need.append(max(2.0, min(float(longest), 18.0)))
    total = sum(need) or 1.0
    widths = [width_pt * value / total for value in need]
    heights = []
    for row in rows:
        lines = max(_cell_lines(row[column] if column < len(row) else "",
                                int((widths[column] - PAD_PT) // pt))
                    for column in range(columns))
        heights.append(lines * pt * LINE_RATIO + 4.0)
    return widths, heights


# ---------------------------------------------------------------- Word・エクセルから読む

def read_word_tables(path) -> List[List[List[str]]]:
    """Word(.docx) の中の表を、表ごとに行と列で返す。つないだセルは左・上のセルだけに字を入れる。"""
    source = Path(path)
    if source.suffix.lower() != ".docx":
        raise ValueError("Word の表は .docx から読みます。.doc なら Word で .docx に保存し直してください。")
    try:
        with zipfile.ZipFile(str(source)) as package:
            root = ET.fromstring(package.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError("Word ファイルの内容を読み取れません。") from error
    found = []
    for table in root.iter(W + "tbl"):
        rows = []
        for row in table.findall(W + "tr"):
            cells = []
            for cell in row.findall(W + "tc"):
                props = cell.find(W + "tcPr")
                span = 1
                merged = False
                if props is not None:
                    grid = props.find(W + "gridSpan")
                    if grid is not None:
                        span = int(grid.get(W + "val") or 1)
                    vmerge = props.find(W + "vMerge")
                    merged = vmerge is not None and vmerge.get(W + "val") != "restart"
                texts = []
                for paragraph in cell.findall(W + "p"):
                    texts.append("".join(node.text or "" for node in paragraph.iter(W + "t")))
                text = "" if merged else "\n".join(t for t in texts if t.strip()).strip()
                cells.append(text)
                cells.extend([""] * (span - 1))
            rows.append(cells)
        width = max((len(row) for row in rows), default=0)
        rows = [row + [""] * (width - len(row)) for row in rows if any(cell for cell in row)]
        if rows:
            found.append(rows)
    return found


def read_excel_table(path) -> List[List[str]]:
    """エクセル(.xlsx) の最初のシートの、字の入っている範囲を行と列で返す。"""
    import votes_xlsx

    source = Path(path)
    votes_xlsx._unsupported(source)
    try:
        with zipfile.ZipFile(str(source)) as package:
            shared = []
            if "xl/sharedStrings.xml" in package.namelist():
                strings = ET.fromstring(package.read("xl/sharedStrings.xml"))
                shared = [votes_xlsx._string_item(item) for item in strings.findall(X + "si")]
            sheet = ET.fromstring(package.read(votes_xlsx._sheet_path(package)))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError("エクセルの内容を読み取れません。ファイルが壊れていないか確かめてください。") from error
    cells = {}
    for row in sheet.iter(X + "row"):
        for cell in row.findall(X + "c"):
            match = re.match(r"([A-Z]+)(\d+)", cell.get("r", ""))
            if not match:
                continue
            column = 0
            for letter in match.group(1):
                column = column * 26 + ord(letter) - 64
            value = _number_text(votes_xlsx._cell_value(cell, shared).strip(), cell.get("t", ""))
            if value:
                cells[(int(match.group(2)), column)] = value
    if not cells:
        return []
    top = min(r for r, _c in cells)
    bottom = max(r for r, _c in cells)
    left = min(c for _r, c in cells)
    right = max(c for _r, c in cells)
    rows = [[cells.get((r, c), "") for c in range(left, right + 1)] for r in range(top, bottom + 1)]
    return [row for row in rows if any(row)]


def _number_text(value: str, kind: str) -> str:
    """エクセルの数（例 1500.0）を、紙面に出す形（1500）にする。字のセルはそのまま。"""
    if kind in ("s", "inlineStr", "str") or not value:
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return str(int(number))
    return ("%.4f" % number).rstrip("0").rstrip(".")
