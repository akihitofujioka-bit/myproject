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
        # 書式が混ざった文字列は <r><t> に分かれて入っている。
        # ただし <rPh> はふりがな。これを混ぜると
        # 「森下けい子モケ」のように読みが本文にくっついて出てしまう
        parts = [si.findtext(_q("t"), default="")]
        for r in si.findall(_q("r")):
            parts.append(r.findtext(_q("t"), default=""))
        out.append("".join(parts))
    return out


def _merged(root: ET.Element) -> list[tuple[int, int, int, int]]:
    """結合セルの範囲。「A1:C1」→ (行1, 列1, 行2, 列2) の0始まり。"""
    out = []
    box = root.find(_q("mergeCells"))
    for mc in (box if box is not None else []):
        ref = mc.get("ref", "")
        if ":" not in ref:
            continue
        a, b = ref.split(":", 1)
        try:
            r1 = int(re.sub(r"[^0-9]", "", a)) - 1
            r2 = int(re.sub(r"[^0-9]", "", b)) - 1
        except ValueError:
            continue
        out.append((r1, _col_index(a), r2, _col_index(b)))
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

    # 結合セルは左上にしか値が入っていない。
    # **縦の結合だけ**、下の行へ値を広げる（議案番号や件名が、細かく分けた
    # 行にまたがって結合されていると、下の行が空になってしまうため）。
    # 横の結合は「○：賛成　●：反対」のような見出しのことが多く、
    # 広げると同じ言葉が横に並んでしまうので触らない
    for r1, c1, r2, c2 in _merged(root):
        if c1 != c2 or r2 <= r1:
            continue
        if r1 >= len(rows) or c1 >= len(rows[r1]):
            continue
        value = rows[r1][c1]
        if not value:
            continue
        for r in range(r1 + 1, min(r2, len(rows) - 1) + 1):
            while len(rows[r]) <= c1:
                rows[r].append("")
            if not rows[r][c1]:
                rows[r][c1] = value
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

    # まるごと空の列は、端でも途中でも落とす。
    # Excel は見た目を整えるために細い空列を挟んでいることがあり、
    # そのまま組むと表が横に伸びてページからあふれる（白紙のページが出た）
    keep = [c for c in range(width) if any(r[c] for r in rows)]
    if keep:
        rows = [[r[c] for c in keep] for r in rows]
    # 途中の空行も同じ理由で落とす
    rows = [r for r in rows if any(r)]
    return rows


def describe(rows: list[list[str]]) -> str:
    """画面に出す一言（「12行 × 8列の表」）。"""
    if not rows:
        return "空の表"
    return f"{len(rows)}行 × {len(rows[0])}列の表"
