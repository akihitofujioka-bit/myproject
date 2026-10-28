"""議案と賛否の Excel ひな形作成・取り込み。

外部ライブラリを使わず、xlsx（ZIP 内の XML）だけを扱う。画面には依存しない。
"""

from __future__ import annotations

import datetime
import re
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


MAIN_SHEET = "議案と賛否"
HELP_SHEET = "書き方"
HEADERS = ("区分", "議案番号", "件名", "議決結果")
VALID_MARKS = ("○", "●", "欠席", "議長")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _unique_path(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def _column(number: int) -> str:
    out = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        out = chr(65 + remainder) + out
    return out


def _inline_row(number: int, values: Iterable[str], style: int = 0) -> str:
    cells = []
    for column, value in enumerate(values, 1):
        ref = f"{_column(column)}{number}"
        text = escape(str(value), {'"': "&quot;"})
        cells.append(f'<c r="{ref}" t="inlineStr" s="{style}"><is><t>{text}</t></is></c>')
    return f'<row r="{number}">' + "".join(cells) + "</row>"


def _worksheet(rows: List[str], freeze: bool = False, autofilter: str = "") -> str:
    view = ('<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews>') if freeze else ""
    filter_xml = f'<autoFilter ref="{autofilter}"/>' if autofilter else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{NS}">{view}<sheetFormatPr defaultRowHeight="18"/>'
            '<cols><col min="1" max="2" width="14" customWidth="1"/>'
            '<col min="3" max="3" width="42" customWidth="1"/>'
            '<col min="4" max="200" width="14" customWidth="1"/></cols>'
            '<sheetData>' + "".join(rows) + f'</sheetData>{filter_xml}</worksheet>')


def make_template(path, members, chair) -> Path:
    """名簿順のひな形を新規作成する。既存ファイルは連番で避ける。"""
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    target = _unique_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    names = [str(name).strip() for name in members if str(name).strip()]
    headers = list(HEADERS) + names
    main = _worksheet([_inline_row(1, headers, 1)], True,
                      f"A1:{_column(len(headers))}1")
    help_rows = [
        _inline_row(1, ("項目", "書き方"), 1),
        _inline_row(2, ("区分", "議案・発議案・同意・報告 など")),
        _inline_row(3, ("議案番号", "議案第1号 など。無い場合は空欄")),
        _inline_row(4, ("件名", "1行に1件。必ず入力")),
        _inline_row(5, ("議決結果", "原案可決・否決・承認 など")),
        _inline_row(6, ("○", "賛成")),
        _inline_row(7, ("●", "反対")),
        _inline_row(8, ("欠席", "採決を欠席")),
        _inline_row(9, ("議長", "採決に加わらない議長")),
        _inline_row(10, ("空欄", "印なし。議長の列は取り込み時に『議長』として扱う")),
    ]
    help_sheet = _worksheet(help_rows)
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                     '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<Relationships xmlns="{PKG_REL_NS}">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<workbook xmlns="{NS}" xmlns:r="{REL_NS}"><sheets>'
                f'<sheet name="{MAIN_SHEET}" sheetId="1" r:id="rId1"/>'
                f'<sheet name="{HELP_SHEET}" sheetId="2" r:id="rId2"/>'
                '</sheets></workbook>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     f'<Relationships xmlns="{PKG_REL_NS}">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
                     '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                     '</Relationships>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              f'<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Meiryo"/></font>'
              '<font><b/><sz val="11"/><name val="Meiryo"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="2"><xf fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>')
    with zipfile.ZipFile(str(target), "x", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", root_rels)
        package.writestr("xl/workbook.xml", workbook)
        package.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        package.writestr("xl/styles.xml", styles)
        package.writestr("xl/worksheets/sheet1.xml", main)
        package.writestr("xl/worksheets/sheet2.xml", help_sheet)
    return target.resolve()


def _unsupported(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in (".xls", ".csv"):
        raise ValueError("この形式は直接読めません。Excel で『名前を付けて保存』→ Excel ブック(.xlsx)で保存し直してください。")
    if suffix != ".xlsx":
        raise ValueError("Excel ブック(.xlsx)を選んでください。")


def _cell_value(cell, shared: List[str]) -> str:
    kind = cell.get("t", "")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{NS}}}t"))
    node = cell.find(f"{{{NS}}}v")
    value = node.text if node is not None and node.text is not None else ""
    if kind == "s" and value:
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return value
    return value


def _sheet_path(package: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(package.read("xl/workbook.xml"))
    sheets = workbook.find(f"{{{NS}}}sheets")
    chosen = None
    for sheet in list(sheets or []):
        if chosen is None or sheet.get("name") == MAIN_SHEET:
            chosen = sheet
        if sheet.get("name") == MAIN_SHEET:
            break
    if chosen is None:
        raise ValueError("Excel にシートがありません。")
    relationship = chosen.get(f"{{{REL_NS}}}id")
    rels = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
    target = next((rel.get("Target") for rel in rels
                   if rel.get("Id") == relationship), None)
    if not target:
        raise ValueError("Excel のシートを読み取れません。")
    target = target.lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target


def read_votes(path, members, chair) -> Tuple[List[dict], List[dict], List[str]]:
    """xlsx を読み、votes、区分別 counts、止めない注意一覧を返す。"""
    source = Path(path)
    _unsupported(source)
    names = [str(name).strip() for name in members if str(name).strip()]
    warnings: List[str] = []
    try:
        with zipfile.ZipFile(str(source)) as package:
            shared = []
            if "xl/sharedStrings.xml" in package.namelist():
                root = ET.fromstring(package.read("xl/sharedStrings.xml"))
                shared = ["".join(t.text or "" for t in item.iter(f"{{{NS}}}t"))
                          for item in root.findall(f"{{{NS}}}si")]
            root = ET.fromstring(package.read(_sheet_path(package)))
            rows: List[Dict[int, str]] = []
            for row in root.iter(f"{{{NS}}}row"):
                values = {}
                for cell in row.findall(f"{{{NS}}}c"):
                    ref = cell.get("r", "")
                    letters = re.match(r"[A-Z]+", ref)
                    if not letters:
                        continue
                    column = 0
                    for letter in letters.group(0):
                        column = column * 26 + ord(letter) - 64
                    values[column - 1] = _cell_value(cell, shared).strip()
                rows.append(values)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError("Excel ブック(.xlsx)の内容を読み取れません。ファイルが壊れていないか確かめてください。") from error
    if not rows:
        return [], [], ["見出し行がありません。"]
    header = rows[0]
    by_name = {value: column for column, value in header.items() if value}
    for name in sorted(set(by_name) - set(HEADERS) - set(names)):
        warnings.append(f"名簿に無い議員の列があります: {name}")
    for name in names:
        if name not in by_name:
            warnings.append(f"名簿にある議員の列がありません: {name}")
    votes = []
    counts: Dict[str, int] = {}
    for row_number, row in enumerate(rows[1:], 2):
        get = lambda key: row.get(by_name.get(key, -1), "").strip()
        kind, bill_no, subject, result = (get(key) for key in HEADERS)
        if not subject:
            if any(row.values()):
                warnings.append(f"{row_number}行目は件名が空のため読み飛ばしました。")
            continue
        marks = {}
        all_empty = True
        for name in names:
            mark = get(name)
            if mark:
                all_empty = False
            if not mark and name == chair:
                mark = "議長"
            marks[name] = mark
            if mark and mark not in VALID_MARKS:
                warnings.append(f"{row_number}行目・{name}の印『{mark}』は ○・●・欠席・議長 以外です。")
        if all_empty:
            warnings.append(f"{row_number}行目は全員の印が空です。")
        title = f"{bill_no}　{subject}" if bill_no else subject
        votes.append({"kind": kind, "title": title, "result": result, "marks": marks})
        counts[kind] = counts.get(kind, 0) + 1
    return votes, [{"kind": kind, "count": count} for kind, count in counts.items()], warnings


def archive_import(path, issue_folder) -> Tuple[Path, str]:
    """元を変えず、号フォルダの賛否へ時刻付きで複製する。"""
    source = Path(path)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = Path(issue_folder) / "賛否"
    folder.mkdir(parents=True, exist_ok=True)
    target = _unique_path(folder / f"{source.stem}_{stamp}{source.suffix.lower()}")
    shutil.copy2(str(source), str(target))
    imported_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    return target.resolve(), imported_at
