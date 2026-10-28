"""V7 の項目テンプレートと、印付き原稿への変換。

tkinter やファイル選択画面には依存しない。画面はこのモジュールの辞書を編集し、
Edition が保存・紙面への反映を担当する。
"""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import ingest
import layout
import templates


ITEMS_FILE = "項目.json"
PREVIOUS_FILE = "項目_前回.json"


def _text(value) -> str:
    return str(value or "").strip()


def default_data(issue: Optional[layout.Issue] = None) -> dict:
    """新しい号の入力欄を返す。呼び出すたびに独立した辞書になる。"""
    issue = issue or layout.Issue(0, 4)
    budget_name = layout.KESSAN if issue.month == 10 else layout.YOSAN
    return {
        "version": 1,
        "issue": asdict(issue),
        "cover": templates.default_form(layout.COVER),
        "gyosei": {"title": layout.GYOSEI, "reports": []},
        "budget_kind": budget_name,
        "budget": {"title": budget_name, "summary": "", "questions": []},
        "shingi": {"meeting": templates.meeting_name(issue), "period": "",
                   "counts": [], "bills": []},
        "votes": [],
        "committees": [],
        "questions": [],
        "feature": {"title": "", "body": ""},
        "last": templates.default_form(layout.LAST),
        "photos": [],
        "completed": [],
    }


# 画面が入力欄を作るときに使う、表示順と説明。データ変換の規則は下の関数に置く。
TEMPLATES = {
    layout.GYOSEI: ("title", "reports"),
    layout.YOSAN: ("title", "summary", "questions"),
    layout.KESSAN: ("title", "summary", "questions"),
    layout.SHINGI: ("meeting", "period", "counts", "bills"),
    "賛否表": ("votes",),
    layout.IINKAI: ("committees",),
    layout.IPPAN: ("questions",),
    layout.TOKUSHU: ("title", "body"),
}


def parse_bulk(text: str) -> dict:
    """まとめて貼った文章を見出し・概要・問答へ分ける。

    問答と判断できない行は ``body`` に順番どおり残す。問答の継続行も直前の
    問または答へ連結するため、入力文字を捨てない。
    """
    heading = ""
    body: List[str] = []
    pairs: List[dict] = []
    current = None
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        match = ingest.QA_LINE.match(line.strip())
        if match:
            kind = match.group("kind")
            value = line.strip()[match.end():].strip()
            if kind == "問":
                current = {"heading": heading, "question": value, "answer": "",
                           "answerer": ""}
                pairs.append(current)
                heading = ""
            elif current is not None:
                current["answer"] = value
            else:
                body.append(line)
            continue
        if current is not None and line.strip().startswith("答弁者"):
            current["answerer"] = line.strip().replace("答弁者", "", 1).lstrip(" ：:　")
            continue
        if current is not None and line.strip():
            key = "answer" if current.get("answer") else "question"
            current[key] = (current[key] + "\n" + line).strip()
        elif line.strip():
            if not heading and len(line.strip()) <= 30:
                heading = line.strip()
            else:
                if heading:
                    body.append(heading)
                    heading = ""
                body.append(line)
    if heading:
        body.append(heading)
    return {"body": "\n".join(body), "questions": pairs}


def _qa_lines(values: Iterable[dict], answerer: bool = False) -> List[str]:
    lines: List[str] = []
    for value in values or []:
        heading = _text(value.get("heading") or value.get("title"))
        question = _text(value.get("question") or value.get("q"))
        answer = _text(value.get("answer") or value.get("a"))
        if heading:
            lines.append("【見出し】" + heading)
        if question:
            lines.append("問　" + question)
        if answerer and _text(value.get("answerer")):
            # 短い役職名を答弁の直前へ置くと、既存 compose が答弁者名として扱う。
            lines.append(_text(value.get("answerer")))
        if answer:
            lines.append("答　" + answer)
    return lines


def limit_questions(values: Iterable[dict], maximum: int = 4) -> List[dict]:
    """質問数を上限へ収める。超過分は最後の答へ追記し、文字を捨てない。"""
    copied = [copy.deepcopy(value) for value in (values or [])]
    if len(copied) <= maximum:
        return copied
    kept, extra = copied[:maximum], copied[maximum:]
    tail = []
    for value in extra:
        if _text(value.get("heading")):
            tail.append(_text(value.get("heading")))
        if _text(value.get("question") or value.get("q")):
            tail.append("問　" + _text(value.get("question") or value.get("q")))
        if _text(value.get("answer") or value.get("a")):
            tail.append("答　" + _text(value.get("answer") or value.get("a")))
    kept[-1]["answer"] = (_text(kept[-1].get("answer")) + "\n" + "\n".join(tail)).strip()
    return kept


def gyosei_text(value: dict) -> str:
    lines = ["【大見出し】" + (_text(value.get("title")) or layout.GYOSEI)]
    for report in value.get("reports", []) or []:
        if _text(report.get("heading")):
            lines.append("【見出し】" + _text(report.get("heading")))
        if _text(report.get("body")):
            lines.append(_text(report.get("body")))
    return "\n".join(lines)


def budget_text(value: dict, section: str) -> str:
    lines = ["【大見出し】" + (_text(value.get("title")) or section)]
    if _text(value.get("summary")):
        lines.append(_text(value.get("summary")))
    lines.extend(_qa_lines(value.get("questions", [])))
    return "\n".join(lines)


def committee_text(values: Iterable[dict]) -> str:
    lines: List[str] = []
    for report in values or []:
        committee = _text(report.get("committee"))
        heading = _text(report.get("heading"))
        if committee:
            lines.append("【大見出し】" + committee)
        if heading:
            lines.append("【見出し】" + heading)
        if _text(report.get("body")):
            lines.append(_text(report.get("body")))
    return "\n".join(lines)


def question_text(value: dict) -> str:
    """一般質問1人分。顔写真は印刷所差し替え用の枠を必ず入れる。"""
    lines = ["【大見出し・横】" + _text(value.get("title")), "【顔写真枠】"]
    member = _text(value.get("member"))
    if member:
        lines.append("▲" + member + "議員")
    lines.extend(_qa_lines(limit_questions(value.get("questions") or []), answerer=True))
    return "\n".join(line for line in lines if line)


def feature_text(value: dict) -> str:
    lines = ["【大見出し】" + _text(value.get("title"))]
    if _text(value.get("body")):
        lines.append(_text(value.get("body")))
    return "\n".join(line for line in lines if line)


def shingi_form(data: dict, issue: layout.Issue) -> dict:
    value = data.get("shingi", {})
    lines: List[str] = []
    for bill in value.get("bills", []) or []:
        if _text(bill.get("kind")):
            lines.append("【区分】" + _text(bill.get("kind")))
        if _text(bill.get("title")):
            lines.append("◎" + _text(bill.get("title")))
        if _text(bill.get("description")):
            lines.append(_text(bill.get("description")))
        if bill.get("questions"):
            lines.append("質疑")
            lines.extend(_qa_lines(bill.get("questions", [])))
    form = templates.default_form(layout.SHINGI)
    form.update({"meeting": _text(value.get("meeting")) or templates.meeting_name(issue),
                 "period": _text(value.get("period")),
                 "counts": copy.deepcopy(value.get("counts", [])),
                 "body": "\n".join(lines),
                 "votes": copy.deepcopy(data.get("votes", []))})
    return form


def build_votes(rows: Iterable[dict], members: Iterable[str], chair: str = "") -> List[dict]:
    """名簿順の賛否表を作る。未指定は賛成、議長は議長とする。"""
    names = [str(name).strip() for name in members if str(name).strip()]
    output = []
    for row in rows or []:
        old = row.get("marks", {}) or {}
        marks = {name: str(old.get(name) or ("議長" if name == chair else "○"))
                 for name in names}
        output.append({"kind": _text(row.get("kind")), "title": _text(row.get("title")),
                       "result": _text(row.get("result")) or "原案可決", "marks": marks})
    return output


def marked_pages(data: dict, issue: layout.Issue) -> Dict[str, List[str]]:
    """区分ごとのページ原稿を返す。流し込み区分は先頭ページ分だけを返す。"""
    budget_section = layout.KESSAN if issue.month == 10 else layout.YOSAN
    return {
        layout.GYOSEI: [gyosei_text(data.get("gyosei", {}))],
        budget_section: [budget_text(data.get("budget", {}), budget_section)],
        layout.IINKAI: [committee_text(data.get("committees", []))],
        layout.IPPAN: [question_text(value) for value in data.get("questions", [])],
        layout.TOKUSHU: [feature_text(data.get("feature", {}))],
    }


def issue_from_data(data: dict, fallback: layout.Issue) -> layout.Issue:
    """入力人数からページ割り用の Issue を作る。エラー判定は layout.make_plan に任せる。"""
    raw = dict(data.get("issue", {}) or {})
    known = {name: raw.get(name, getattr(fallback, name))
             for name in layout.Issue.__dataclass_fields__}
    known["questioners"] = len(data.get("questions", []) or [])
    known["committee_pages"] = len(data.get("committees", []) or [])
    return layout.Issue(**known)


def load(folder: Path, issue: Optional[layout.Issue] = None) -> dict:
    path = Path(folder) / ITEMS_FILE
    if not path.is_file():
        return default_data(issue)
    value = json.loads(path.read_text(encoding="utf-8"))
    base = default_data(issue)
    base.update(value)
    return base


def save(folder: Path, data: dict) -> Path:
    """項目を保存する。既存内容は、上書き前に項目_前回.jsonへ写す。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ITEMS_FILE
    if target.is_file():
        shutil.copy2(str(target), str(folder / PREVIOUS_FILE))
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
