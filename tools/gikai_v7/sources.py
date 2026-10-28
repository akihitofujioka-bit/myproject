"""Word・メール・手書き原稿の受付と、確認用 Word の作成。"""

from __future__ import annotations

import datetime
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterable, List, Tuple
from xml.sax.saxutils import escape

import ingest
import items


HEADER = re.compile(r"^\s*(From|Sent|Subject|To|Cc|件名|差出人|送信日時|宛先)\s*[:：]", re.I)
QUOTE = re.compile(r"^\s*>")
SIGNATURE = re.compile(r"^\s*--\s*$")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def _safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(value or "不明").strip()) or "不明"


def archive_file(source, issue_folder, prefix: str = "") -> Path:
    """受け取ったファイルを元のまま、時刻付きの別名で複製する。"""
    source = Path(source)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = Path(issue_folder) / "受け取った原稿"
    folder.mkdir(parents=True, exist_ok=True)
    stem = (_safe_name(prefix) + "_" if prefix else "") + source.stem
    target = _unique(folder / f"{stem}_{stamp}{source.suffix.lower()}")
    shutil.copy2(str(source), str(target))
    return target.resolve()


def read_word(path) -> dict:
    """Word から文字だけを読み、「まとめて貼る」と同じ規則で分ける。"""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".docx":
        data = ingest.read_docx(source)
    elif suffix == ".doc":
        data = ingest.read_doc(source)
    else:
        raise ValueError("Word ファイル(.docx または .doc)を選んでください。")
    text = "\n".join(paragraph.text for paragraph in data.paragraphs if paragraph.text)
    parsed = items.parse_bulk(text)
    parsed["text"] = text
    parsed["warnings"] = list(data.warnings)
    return parsed


def read_word_articles(path) -> dict:
    """行政報告・委員会報告・特集の Word を、見出しと本文の組に分ける。

    中見出しごとに 1 件にする。大見出しは欄で決めるので本文には入れず、題の候補として返す。
    Word に貼られた写真は images に入れて返す（紙面には自動で置かない）。文字は削らない。
    """
    source = Path(path)
    if source.suffix.lower() not in (".docx", ".doc"):
        raise ValueError("Word ファイル(.docx または .doc)を選んでください。")
    result = ingest.ingest(source)
    articles: List[dict] = []
    titles: List[str] = []
    photos: List[Tuple[str, bytes, str]] = []
    for index, part in enumerate(result.parts):
        if part.kind == "大見出し":
            titles.append(part.text)
        elif part.kind == "中見出し":
            articles.append({"heading": part.text, "body": ""})
        elif part.kind == "写真":
            caption = ""
            if index + 1 < len(result.parts) and result.parts[index + 1].kind == "写真説明":
                caption = result.parts[index + 1].text
            data = result.images.get(part.image or "")
            if data:
                photos.append((part.image, data, caption))
        elif part.kind in ("写真説明", "空き行", "次段"):
            continue
        elif part.text:
            if not articles:
                articles.append({"heading": "", "body": ""})
            body = articles[-1]["body"]
            articles[-1]["body"] = (body + "\n" + part.text) if body else part.text
    return {"articles": articles, "titles": titles, "photos": photos,
            "warnings": list(result.warnings)}


def email_candidates(text: str) -> List[dict]:
    """外す候補を行番号・理由付きで返す。本文は変更しない。"""
    result = []
    signature = False
    for number, line in enumerate(str(text or "").splitlines(), 1):
        reason = ""
        if signature:
            reason = "署名（-- より下）"
        elif SIGNATURE.match(line):
            signature = True
            reason = "署名の区切り"
        elif QUOTE.match(line):
            reason = "引用行（> で開始）"
        elif HEADER.match(line):
            reason = "メールのヘッダ行"
        if reason:
            result.append({"line": number, "text": line, "reason": reason})
    return result


def _normalize_line(line: str) -> str:
    # 半角カナの並びだけを全角へ直し、元からある全角空白や英字は保つ。
    value = re.sub(r"[\uFF61-\uFF9F]+",
                   lambda match: unicodedata.normalize("NFKC", match.group(0)), line)
    value = re.sub(r"^ +", lambda m: "　" * len(m.group(0)), value)
    return ingest.normalize_numbers(value)


def prepare_email(text: str, excluded_lines: Iterable[int] = ()) -> dict:
    """選ばれた候補だけを外し、文中改行をつないで取込前の結果を返す。"""
    excluded = {int(value) for value in excluded_lines}
    lines = [_normalize_line(line.rstrip()) for number, line in enumerate(str(text or "").splitlines(), 1)
             if number not in excluded]
    joined: List[str] = []
    for line in lines:
        if not joined:
            joined.append(line)
            continue
        previous = joined[-1]
        current_qa = bool(ingest.QA_LINE.match(line.strip()))
        previous_qa = bool(ingest.QA_LINE.match(previous.strip()))
        if line and previous and not current_qa and not previous_qa:
            joined[-1] = previous + line.lstrip("　 ")
        else:
            joined.append(line)
    cleaned = "\n".join(joined).strip()
    parsed = items.parse_bulk(cleaned)
    return {"original": str(text or ""), "cleaned": cleaned,
            "candidates": email_candidates(text), **parsed}


def save_email_original(text: str, issue_folder, member: str) -> Path:
    """貼られた元メール本文を新規保存する。"""
    folder = Path(issue_folder) / "受け取った原稿"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = _unique(folder / f"メール_{_safe_name(member)}_{stamp}.txt")
    target.write_text(str(text or ""), encoding="utf-8")
    return target.resolve()


def reception_status(members: Iterable[str], questions: Iterable[dict]) -> List[dict]:
    """名簿の全員について受付状況を返す。"""
    by_member = {str(value.get("member", "")).strip(): value for value in questions or []}
    output = []
    for member in members:
        value = by_member.get(str(member).strip())
        if not value:
            status = "未着"
        elif str(value.get("confirmed", "未")) == "済":
            status = "確認済み"
        elif value.get("questions") or value.get("qa_bulk"):
            status = "議員確認待ち"
        else:
            status = "入力中"
        output.append({"member": str(member), "status": status})
    return output


def _paragraph(text: str, bold: bool = False, size: int = 22) -> str:
    value = escape(str(text or ""))
    bold_xml = "<w:b/>" if bold else ""
    return (f'<w:p><w:pPr><w:spacing w:after="160" w:line="420" w:lineRule="atLeast"/></w:pPr>'
            f'<w:r><w:rPr>{bold_xml}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
            '<w:rFonts w:eastAsia="ＭＳ 明朝"/></w:rPr>'
            f'<w:t xml:space="preserve">{value}</w:t></w:r></w:p>')


def write_confirmation(path, people: Iterable[dict]) -> Path:
    """赤ペン確認用の横書き普通 Word を新規作成する。"""
    target = Path(path)
    if target.suffix.lower() != ".docx":
        target = target.with_suffix(".docx")
    target = _unique(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for person_no, person in enumerate(people or []):
        if person_no:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        body.append(_paragraph(str(person.get("title") or "一般質問 確認用"), True, 28))
        body.append(_paragraph(str(person.get("member") or "（議員名）") + " 議員", True, 24))
        questions = person.get("questions") or items.parse_bulk(person.get("qa_bulk", ""))["questions"]
        for number, qa in enumerate(questions, 1):
            body.append(_paragraph(f"{number}. {qa.get('heading', '')}", True, 24))
            body.append(_paragraph("問　" + str(qa.get("question", ""))))
            body.append(_paragraph("答　" + str(qa.get("answer", ""))))
            if qa.get("answerer"):
                body.append(_paragraph("答弁者　" + str(qa.get("answerer"))))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
                '</w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    with zipfile.ZipFile(str(target), "x", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", rels)
        package.writestr("word/document.xml", document)
    return target.resolve()
