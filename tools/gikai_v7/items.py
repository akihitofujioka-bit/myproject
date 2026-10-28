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


# 行政報告の大見出しの決まった書き方（従来の紙面どおり）。
GYOSEI_TITLE = "行政報告（要旨）"

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
        "gyosei": {"title": GYOSEI_TITLE, "reports": []},
        "budget_kind": budget_name,
        "budget": {"title": budget_name, "summary": "", "questions": []},
        "kessan": default_kessan(),
        "yosan": default_yosan(),
        "shingi": {"meeting": templates.meeting_name(issue), "period": "",
                   "counts": [], "bills": []},
        "votes": [],
        "votes_import": {},
        "votes_warnings": [],
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
    layout.KESSAN: ("title", "kinds", "photo", "chart_note", "accounts", "questions"),
    layout.SHINGI: ("meeting", "period", "counts", "bills"),
    "賛否表": ("votes",),
    layout.IINKAI: ("committees",),
    layout.IPPAN: ("questions",),
    layout.TOKUSHU: ("title", "body"),
}


def default_kessan() -> dict:
    """決算ページ（10 月号）の入力欄。会計の並びは第204号の表に合わせた見本で、金額は空。"""
    accounts = [("特別会計", "国民健康保険特別会計"), ("特別会計", "介護保険特別会計"),
                ("特別会計", "後期高齢者医療特別会計"),
                ("簡易水道事業会計", "収益的収支"), ("簡易水道事業会計", "資本的収支")]
    return {"title": "", "kinds": "一般会計\n特別会計\n公営企業会計", "photo": "",
            "chart_note": "一般会計の円グラフはひだか広報１１月号のを使用",
            "accounts": [{"group": group, "name": name, "revenue": "", "expense": ""}
                         for group, name in accounts],
            "questions": []}


def default_yosan() -> dict:
    """当初予算の見開き（4・5 月号）の入力欄。会計の並びは第202号に合わせた見本で、金額は空。"""
    accounts = [("公営企業会計", "簡易水道事業"), ("特別会計", "国民健康保険"),
                ("特別会計", "介護保険"), ("特別会計", "後期高齢者医療")]
    return {"title": "", "kinds": "一般会計\n特別会計\n公営企業会計", "chart_title": "",
            "chart_note": "一般会計（歳出）の円グラフは、ひだか広報のものを使用",
            "general_total": "", "chart_items": [],
            "accounts": [{"group": group, "name": name, "amount": "", "note": ""}
                         for group, name in accounts],
            "headline": "", "focus": [], "previous_title": "", "previous": []}


def yosan_form(data: dict, issue: layout.Issue) -> dict:
    """当初予算の入力を、templates の当初予算の型へ渡す形にする。"""
    value = dict(default_yosan())
    value.update(data.get("yosan", {}) or {})
    value["title"] = _text(value.get("title")) or templates.yosan_title(issue)
    return value


def kessan_form(data: dict, issue: layout.Issue, photo_folder: Optional[Path] = None) -> dict:
    """決算ページの入力を、templates の決算の型へ渡す形にする。"""
    value = dict(default_kessan())
    value.update(data.get("kessan", {}) or {})
    lines: List[str] = []
    for question in value.get("questions", []) or []:
        account = _text(question.get("heading") or question.get("account"))
        if account:
            lines.append("【区分】" + account.strip("【】"))
        if _text(question.get("question")):
            lines.append("問　" + _text(question.get("question")))
        if _text(question.get("answer")):
            lines.append("答　" + _text(question.get("answer")))
    photo = _text(value.get("photo"))
    if photo and photo_folder is not None:
        photo = str(Path(photo_folder) / Path(photo).name)
    return {"title": _text(value.get("title")) or templates.kessan_title(issue),
            "kinds": value.get("kinds", ""), "photo": photo,
            "chart_note": value.get("chart_note", ""),
            "accounts": list(value.get("accounts", []) or []), "body": "\n".join(lines)}


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
        stripped = line.strip()
        if (stripped.startswith(("【", "［", "[")) and stripped.endswith(("】", "］", "]"))
                and len(stripped) <= 30):
            # 【一般会計】のような見出しは、答の続きにせず次の問の見出しにする。
            if heading:
                body.append(heading)
            heading = stripped.strip("【】［］[]")
            current = None
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
        role = _text(value.get("answerer")) if answerer else ""
        if answer:
            # 「答　役職名　本文」の形にすると、既存 compose が役職名までをゴシックにする。
            lines.append("答　" + (role + "　" if role else "") + answer)
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
    lines = ["【大見出し】" + (_text(value.get("title")) or GYOSEI_TITLE)]
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
        # 第204号の形: 記事の見出しを大きく囲み、委員会名はその左に小さめの見出しで入れる。
        if heading or committee:
            lines.append("【大見出し】" + (heading or committee))
        if committee and heading:
            lines.append("【見出し】" + committee)
        if _text(report.get("body")):
            lines.append(_text(report.get("body")))
    return "\n".join(lines)


def question_text(value: dict) -> str:
    """一般質問1人分。顔写真は印刷所差し替え用の枠を必ず入れる。"""
    # 一般質問の題は、ほかの記事の大見出しと同じ縦書きの囲み（V5 設計図 §3.3）。
    lines = ["【大見出し】" + _text(value.get("title")), "【顔写真枠】"]
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
        # Excel で明示された空欄は「印なし」。値が無い場合だけ既定値を使う。
        marks = {name: str(old[name]) if name in old
                 else ("議長" if name == chair else "○") for name in names}
        vote = {"kind": _text(row.get("kind")), "title": _text(row.get("title")),
                "result": _text(row.get("result")) or "可決", "marks": marks}
        if row.get("source_title"):   # エクセルにあった元の件名（手直しを当て直すときの目印）
            vote["source_title"] = row["source_title"]
        output.append(vote)
    return output


def marked_pages(data: dict, issue: layout.Issue) -> Dict[str, List[str]]:
    """区分ごとのページ原稿を返す。流し込み区分は先頭ページ分だけを返す。"""
    pages = {
        layout.GYOSEI: [gyosei_text(data.get("gyosei", {}))],
        layout.IINKAI: [committee_text(data.get("committees", []))],
        layout.IPPAN: [question_text(value) for value in data.get("questions", [])],
        layout.TOKUSHU: [feature_text(data.get("feature", {}))],
    }
    # 当初予算・決算は決まった型のページなので、流し込みの原稿は作らない。
    return pages


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
