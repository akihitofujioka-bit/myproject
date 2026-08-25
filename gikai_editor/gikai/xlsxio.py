"""Excel（.xlsx）を、追加ソフト無しで読む。

「審議したこと・決まったこと」の賛否一覧表は Excel で作られている。
表は**表のまま**紙面に載せる必要があるので、文章として読み流すのではなく
行と列のまま取り出す。

.xlsx の中身は XML を集めた ZIP なので、標準ライブラリだけで読める
（`docxio.py` と同じ考え方）。openpyxl は入れない — 役場の端末に
追加で入れるものを増やさないため。

旧形式の .xls（Excel 97-2003）は中身がまったく別の binary 形式なので
読めない。その場合は「.xlsx で保存し直してください」と伝える。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

# 表として扱う拡張子
TABLE_EXT = {".xlsx", ".xlsm", ".csv"}


def _q(tag: str, ns: str = MAIN) -> str:
    return f"{{{ns}}}{tag}"


def _col_index(ref: str) -> int:
    """セル番地の列を 0 始まりの番号にする。「C5」→ 2。"""
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out = []
    for si in root.findall(_q("si")):
        # 書式が混ざった文字列は <r><t> に分かれて入っている
        parts = [t.text or "" for t in si.iter(_q("t"))]
        out.append("".join(parts))
    return out


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    """1枚目のシートの場所。並び順は workbook.xml が持っている。"""
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return "xl/worksheets/sheet1.xml"
    rid_to_target = {
        r.get("Id"): r.get("Target", "")
        for r in rels.findall(_q("Relationship", PKG_REL))
    }
    sheets = wb.find(_q("sheets"))
    for sh in (sheets if sheets is not None else []):
        rid = sh.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rid_to_target.get(rid, "")
        if target:
            target = target.lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    return "xl/worksheets/sheet1.xml"


def _cell_text(c: ET.Element, shared: list[str]) -> str:
    kind = c.get("t", "")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in c.iter(_q("t")))
    v = c.find(_q("v"))
    if v is None or v.text is None:
        return ""
    raw = v.text
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind in ("str", "e"):
        return raw
    # 数値。1234.0 のような見え方にならないよう、整数は整数のまま
    try:
        f = float(raw)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return raw


def read_xlsx(path: Path | str) -> list[list[str]]:
    """1枚目のシートを、行と列のまま取り出す。"""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            shared = _shared_strings(z)
            sheet = z.read(_first_sheet_path(z))
    except zipfile.BadZipFile:
        raise ValueError(
            f"{path.name} を読めませんでした。"
            "旧形式（.xls）の可能性があります。Excel で開いて"
            "「名前を付けて保存」→「Excel ブック（.xlsx）」で保存し直してください。")
    except KeyError as e:
        raise ValueError(f"{path.name} の中身を読めませんでした（{e}）。")

    root = ET.fromstring(sheet)
    data = root.find(_q("sheetData"))
    rows: list[list[str]] = []
    for tr in (data if data is not None else []):
        cells: list[str] = []
        for c in tr.findall(_q("c")):
            i = _col_index(c.get("r", ""))
            while len(cells) < i:
                cells.append("")          # 空セルは番地から補う
            cells.append(_cell_text(c, shared))
        rows.append(cells)
    return _trim(rows)


def read_csv(path: Path | str) -> list[list[str]]:
    """CSV も表として読む。Excel から出したものは CP932 のことが多い。"""
    from .importers import decode_bytes

    text, _enc = decode_bytes(Path(path).read_bytes())
    return _trim([list(r) for r in csv.reader(io.StringIO(text))])


def read_table(path: Path | str) -> list[list[str]]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return read_csv(path)
    return read_xlsx(path)


def _trim(rows: list[list[str]]) -> list[list[str]]:
    """まわりの空行・空列を落とし、列数をそろえる。

    Excel は使っていない行や列まで持っていることがあるので、
    そのまま組むと空っぽの升目が並んでしまう。
    """
    rows = [[(c or "").strip() for c in r] for r in rows]
    while rows and not any(rows[0]):
        rows.pop(0)
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # 右端から、まるごと空の列を落とす
    while width > 1 and all(not r[width - 1] for r in rows):
        rows = [r[:-1] for r in rows]
        width -= 1
    # 左端も同じ
    while width > 1 and all(not r[0] for r in rows):
        rows = [r[1:] for r in rows]
        width -= 1
    return rows


def describe(rows: list[list[str]]) -> str:
    """画面に出す一言（「12行 × 8列の表」）。"""
    if not rows:
        return "空の表"
    return f"{len(rows)}行 × {len(rows[0])}列の表"
