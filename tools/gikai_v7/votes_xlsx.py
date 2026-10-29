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
# 前から使っているエクセルの見出しの言い方も受け付ける（空白は除いて比べる）。
HEADER_WORDS = {
    "区分": ("区分", "種類", "種別"),
    "議案番号": ("議案番号", "番号", "議案No", "議案No.", "No", "No."),
    "件名": ("件名", "議案・発議案", "議案発議案", "議案名", "案件名", "案件", "名称", "議案"),
    "議決結果": ("議決結果", "結果", "議決"),
}
# 印の字の違いをそろえる（〇は漢数字のゼロ、◯は大きい丸）。
MARK_WORDS = {"〇": "○", "◯": "○", "賛成": "○", "賛": "○", "反対": "●", "反": "●"}
HEADER_SEARCH_ROWS = 15


def _plain(value: str) -> str:
    """見出しや名前を比べるため、空白・改行を除く。"""
    return re.sub(r"\s", "", str(value or "")).replace("\u3000", "")


def _string_item(item) -> str:
    """共有文字列・セル内文字列から、本文だけを取り出す（ふりがな rPh は読まない）。"""
    direct = item.find(f"{{{NS}}}t")
    parts = [direct.text or ""] if direct is not None else []
    for run in item.findall(f"{{{NS}}}r"):
        parts.extend(node.text or "" for node in run.findall(f"{{{NS}}}t"))
    return "".join(parts)


def _member_for(plain: str, wanted: dict, chair: str):
    """見出しの文字から議員を決める。「議長」だけの見出しは議長、名前の前後に言葉が付いていてもよい。"""
    if plain in wanted:
        return wanted[plain]
    if plain == "議長" and chair:
        return chair
    matches = [name for key, name in wanted.items() if key and key in plain]
    return matches[0] if len(matches) == 1 else None


def _header_key(plain: str):
    """見出しの文字から、区分・議案番号・件名・議決結果のどれかを決める。言葉が少し違ってもよい。"""
    for key, words in HEADER_WORDS.items():
        if plain in words:
            return key
    if not plain or len(plain) > 10:      # 表の題（第3回定例会議案・発議案と賛否 など）は見出しにしない
        return None
    if "件名" in plain or "案件" in plain or "議案" in plain:
        return "件名"
    if "結果" in plain:
        return "議決結果"
    if "区分" in plain or "種類" in plain or "種別" in plain:
        return "区分"
    if "番号" in plain:
        return "議案番号"
    return None


def _find_header(rows, names, chair: str = "") -> tuple:
    """見出しの行を探す。議員名と見出しの言葉がいちばん多く並ぶ行を選ぶ。

    見出しが 2〜3 段に分かれている（上の段に区分・件名・議決結果、下の段に議員名 など）ときは、
    上下の段からも見出しの言葉を拾う。戻り値は（データが始まる行の位置, 列→見出し）。
    """
    wanted = {_plain(name): name for name in names}

    def meaning(value):
        plain = _plain(value)
        return _header_key(plain) or _member_for(plain, wanted, chair)

    best, best_score = 0, -1
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        score = sum(1 for value in row.values() if meaning(value))
        if score > best_score:
            best, best_score = index, score
    header = {}
    for column, value in rows[best].items():
        if _plain(value):
            header[column] = meaning(value) or str(value).strip()
    # 議案の行は、○・● などの印が最初に出てくる行から。それより上（見出しの行から下）は
    # 見出しの続き（セルを縦につないだ見出しなど）として読む。
    marks = {"○", "●"} | set(MARK_WORDS)   # 「議長」「欠席」は見出しにもなるので含めない
    start = next((index for index in range(best + 1, len(rows))
                  if any(_plain(v) in marks for v in rows[index].values())), best + 1)
    for index in list(range(max(0, best - 2), best)) + list(range(best + 1, start)):
        for column, value in rows[index].items():
            key = meaning(value)
            if key and header.get(column) not in (HEADERS + tuple(names)):
                header[column] = key
    return start - 1, header


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
        _inline_row(5, ("議決結果", "可決・否決・同意・認定 など(「原案」は付けない)")),
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
        inline = cell.find(f"{{{NS}}}is")
        return _string_item(inline) if inline is not None else ""
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
                shared = [_string_item(item) for item in root.findall(f"{{{NS}}}si")]
            root = ET.fromstring(package.read(_sheet_path(package)))
            rows: List[Dict[int, str]] = []
            numbers: List[int] = []
            for row in root.iter(f"{{{NS}}}row"):
                numbers.append(int(row.get("r") or (numbers[-1] + 1 if numbers else 1)))
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
    header_index, header = _find_header(rows, names, str(chair or "").strip())
    by_name = {}
    for column, value in header.items():
        by_name.setdefault(value, column)
    data_rows = rows[header_index + 1:]
    member_columns = {column for column, value in header.items() if value in names}
    subject_column = by_name.get("件名")
    if subject_column is None or not any(str(row.get(subject_column, "")).strip() for row in data_rows):
        # 件名の見出しが無い、または見出しの列に文字が無い（見出しと議案の行でセルのつなぎ方が違う）ときは、
        # 議員の列以外で、いちばん長い文が入る列を件名とみなす
        lengths: Dict[int, int] = {}
        for row in data_rows:
            for column, value in row.items():
                if column not in member_columns and column != by_name.get("議決結果"):
                    lengths[column] = lengths.get(column, 0) + len(str(value))
        if lengths:
            guess = max(lengths, key=lengths.get)
            if subject_column is None:
                warnings.append(f"件名の見出しが見つからないため、{_column(guess + 1)}列を件名として読みました。違うときはエクセルの見出しを「件名」にしてください。")
            by_name["件名"] = guess
    if "区分" not in by_name and by_name.get("件名") is not None:
        # 区分の見出しが無いときは、件名より左で、短い文字（6 字まで）が入っている列を区分とみなす
        for column in range(by_name["件名"] - 1, -1, -1):
            values = [_plain(row.get(column, "")) for row in data_rows if _plain(row.get(column, ""))]
            if values and all(len(v) <= 6 for v in values) and column not in member_columns:
                by_name["区分"] = column
                break
    for name in sorted(set(by_name) - set(HEADERS) - set(names)):
        warnings.append(f"名簿に無い議員の列があります: {name}")
    for name in names:
        if name not in by_name:
            warnings.append(f"名簿にある議員の列がありません: {name}")
    votes = []
    counts: Dict[str, int] = {}
    previous_kind = ""
    for row_number, row in zip(numbers[header_index + 1:], rows[header_index + 1:]):
        get = lambda key: row.get(by_name.get(key, -1), "").strip()
        kind, bill_no, subject, result = (get(key) for key in HEADERS)
        if subject and not kind:
            kind = previous_kind   # 区分のセルが縦につながっている（結合）ときは上の行の区分
        previous_kind = kind or previous_kind
        if not subject:
            if any(row.values()):
                warnings.append(f"{row_number}行目は件名が空のため読み飛ばしました。")
            continue
        marks = {}
        all_empty = True
        for name in names:
            mark = get(name)
            mark = MARK_WORDS.get(_plain(mark), mark)
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
    if not votes and any(any(row.values()) for row in rows[header_index + 1:]):
        warnings.insert(0, "議案を1件も読めませんでした。エクセルの見出しに「件名」（または「議案・発議案」）と議員名があるか確かめてください。")
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
