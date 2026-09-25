"""Excel（.xlsx）の賛否一覧表を読む。

事務局が作る「議案と賛否」の Excel は、だいたい次の形をしている
（第204号の実物で確認）。

    1 行目        表題（第３回定例会議案・発議案と賛否）
    2 行目        凡例（○：賛成　●：反対）
    3〜7 行目     見出し。議員名が縦に並ぶ列と、右端の「議決結果」
    8 行目〜      区分（認定・条例など…）｜件名（改行で複数件）｜○●｜結果

行や列の位置は号によって少しずつ変わるので、番地では決め打ちせず
「議決結果」と書かれた見出しの行・列を手がかりに読む。

.xlsx は XML を集めた ZIP なので標準ライブラリだけで読める。
openpyxl は入れない（役場の端末に追加で入れるものを増やさないため）。
読み取りの部分は gikai_editor/gikai/xlsxio.py と同じ考え方で書いてある。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# 見出しの右端に来る列の名前。これを手がかりに見出しの行を探す
RESULT_WORDS = ("議決結果", "結果", "採決結果")
# 賛否の升目に入る記号。これが並んでいる行を「議案の行」とみなす
VOTE_MARKS = {"○", "〇", "●", "×", "✕", "議長", "欠席", "退席", "除斥", "―", "－", "-"}


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


def _row_index(ref: str) -> int:
    return int(re.sub(r"[^0-9]", "", ref) or "1") - 1


def _safe_xml(raw: bytes, name: str) -> ET.Element:
    # Excel が作る XML に DOCTYPE や実体定義は含まれない。含まれていたら
    # 細工されたファイルなので読まない（XML 爆弾・外部実体参照の対策）
    if b"<!doctype" in raw[:4096].lower() or b"<!entity" in raw.lower():
        raise ValueError(f"通常の Excel ファイルではありません: {name}")
    return ET.fromstring(raw)


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        root = _safe_xml(z.read("xl/sharedStrings.xml"), "sharedStrings")
    except KeyError:
        return []
    out = []
    for si in root.findall(_q("si")):
        # <rPh> はふりがな。これを混ぜると「山田花子ヤマダハナコ」と出る
        parts = [si.findtext(_q("t"), default="")]
        for r in si.findall(_q("r")):
            parts.append(r.findtext(_q("t"), default=""))
        out.append("".join(parts))
    return out


def _first_sheet_path(z: zipfile.ZipFile) -> str:
    """1 枚目のシートの場所。並び順は workbook.xml が持っている。"""
    try:
        wb = _safe_xml(z.read("xl/workbook.xml"), "workbook")
        rels = _safe_xml(z.read("xl/_rels/workbook.xml.rels"), "rels")
    except KeyError:
        return "xl/worksheets/sheet1.xml"
    rid_to_target = {r.get("Id"): r.get("Target", "")
                     for r in rels.findall(_q("Relationship", PKG_REL))}
    sheets = wb.find(_q("sheets"))
    for sh in (sheets if sheets is not None else []):
        target = rid_to_target.get(sh.get(_q("id", DOC_REL)), "")
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
    try:
        f = float(raw)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return raw


def read_cells(path: Path | str) -> list[list[str]]:
    """1 枚目のシートを、行と列の番地のまま取り出す（空の升目は ""）。"""
    path = Path(path)
    if path.suffix.lower() == ".xls":
        raise ValueError(
            f"{path.name} は古い形式（.xls）なので読めません。Excel で開いて"
            "「名前を付けて保存」→「Excel ブック（.xlsx）」で保存し直してください。")
    try:
        with zipfile.ZipFile(path) as z:
            shared = _shared_strings(z)
            root = _safe_xml(z.read(_first_sheet_path(z)), path.name)
    except zipfile.BadZipFile:
        raise ValueError(
            f"{path.name} を Excel として読めませんでした。Excel で開いて"
            "「Excel ブック（.xlsx）」で保存し直してください。")
    except KeyError as e:
        raise ValueError(f"{path.name} の中身を読めませんでした（{e}）。")

    rows: dict[int, dict[int, str]] = {}
    data = root.find(_q("sheetData"))
    for tr in (data if data is not None else []):
        for c in tr.findall(_q("c")):
            ref = c.get("r", "")
            text = _cell_text(c, shared).replace("\r\n", "\n").strip()
            if text:
                rows.setdefault(_row_index(ref), {})[_col_index(ref)] = text
    if not rows:
        return []
    nrow = max(rows) + 1
    ncol = max(max(r) for r in rows.values()) + 1
    return [[rows.get(r, {}).get(c, "") for c in range(ncol)] for r in range(nrow)]


# ====================================================================== 賛否表


@dataclass
class VoteRow:
    category: str          # 認定・条例など・補正予算・その他 …
    items: list[str]       # 件名（1 升に改行で複数件入っていれば分ける）
    votes: list[str]       # 議員ごとの ○ ● 議長 …（members と同じ並び）
    result: str            # 可決・認定・否決 …


@dataclass
class VoteTable:
    title: str = ""
    legend: str = ""
    members: list[str] = field(default_factory=list)
    rows: list[VoteRow] = field(default_factory=list)
    source: str = ""

    def summary(self) -> str:
        n = sum(len(r.items) for r in self.rows)
        return (f"{self.title or '賛否一覧表'}（議員 {len(self.members)} 人・"
                f"{len(self.rows)} 行・件名 {n} 件）")


def _norm(s: str) -> str:
    return re.sub(r"[\s　]", "", s)


def parse_vote_table(cells: list[list[str]], source: str = "") -> VoteTable:
    """升目の並びから賛否表を読み取る。

    手がかりは「議決結果」の見出し。その行が見出し行で、その列より左で
    名前の入っている列が議員の列。議員の列より左の、いちばん長い文字の
    入っている列が件名、その左が区分。
    """
    head_r = res_c = -1
    for r, row in enumerate(cells):
        for c, v in enumerate(row):
            if _norm(v) in RESULT_WORDS:
                head_r, res_c = r, c
                break
        if head_r >= 0:
            break
    if head_r < 0:
        raise ValueError(
            "賛否表の見出し（「議決結果」）が見つかりませんでした。"
            "見出しの右端の升目に「議決結果」と書かれているか確かめてください。")

    header = cells[head_r]
    member_cols = [c for c in range(res_c) if header[c]]
    if not member_cols:
        raise ValueError("議員名の列が見つかりませんでした（「議決結果」と同じ行に議員名が必要です）。")
    # 議員の列は右端の「議決結果」の左に連続して並ぶ。途中の飛び地
    # （「議員名」のような見出しの飾り）は、○● が入る列かどうかで見分ける
    first_member = min(member_cols)

    def is_vote_row(row: list[str]) -> bool:
        marks = [row[c] for c in member_cols if c < len(row) and row[c]]
        return bool(marks) and sum(_norm(m) in VOTE_MARKS for m in marks) >= len(marks) / 2

    rows: list[VoteRow] = []
    for row in cells[head_r + 1:]:
        if not is_vote_row(row):
            continue
        left = [(c, row[c]) for c in range(first_member) if row[c]]
        if not left:
            continue
        # 件名はいちばん長い升目。その左にあるのが区分
        kc, ktext = max(left, key=lambda cv: len(cv[1]))
        cat = next((v for c, v in left if c < kc), "")
        items = [s.strip() for s in ktext.split("\n") if s.strip()]
        rows.append(VoteRow(
            category=cat,
            items=items,
            votes=[row[c] if c < len(row) else "" for c in member_cols],
            result=row[res_c] if res_c < len(row) else "",
        ))
    if not rows:
        raise ValueError("議案の行（○や●が並んだ行）が見つかりませんでした。")

    title = legend = ""
    for row in cells[:head_r]:
        for v in row:
            if not v:
                continue
            if "賛成" in v and not legend:
                legend = v
            elif not title:
                title = v
    return VoteTable(title=title, legend=legend, members=[header[c] for c in member_cols],
                     rows=rows, source=source)


def read_vote_table(path: Path | str) -> VoteTable:
    return parse_vote_table(read_cells(path), source=Path(path).name)
