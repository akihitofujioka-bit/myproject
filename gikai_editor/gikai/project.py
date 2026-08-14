"""編集プロジェクト（1号ぶんの作業データ）。

1つの号を作るあいだのデータを、フォルダ1つにまとめて保存する。

    第204号/
      project.json      記事・割付・設定
      template.docx     様式（Word）
      manuscripts/      議員から届いた原稿の原本
      photos/           写真の原本
      出力/             差し込み済みの Word / PDF

フォルダごとコピーすれば別のパソコンに引き継げる。
クラウドには一切保存しない。
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import photos as photos_mod
from .docxio import DocxTemplate
from .importers import read_any
from .proofread import Dictionaries, proofread, summarize_issues
from .summarize import fit_to_frame, headline_candidates, lead_sentence, summarize
from .textutil import count_chars, estimate_lines, normalize_manuscript

SCHEMA_VERSION = 1


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _safe_name(name: str) -> str:
    """ファイル名として安全な文字列にする。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:80] or "無題"


@dataclass
class Photo:
    id: str
    file: str  # photos/ からの相対パス
    caption: str = ""
    credit: str = ""
    slot: str = ""  # 差し込み先（様式の画像名）
    caption_slot: str = ""  # 説明文を入れる枠（スロット ID）
    focus: list[float] = field(default_factory=lambda: [0.5, 0.4])
    info: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Article:
    """議員1人ぶん、または1コーナーぶんの記事。"""

    id: str
    title: str = ""
    author: str = ""
    source_file: str = ""  # manuscripts/ からの相対パス
    raw: str = ""  # 取り込んだままの原稿
    body: str = ""  # 編集後の本文（これを様式に差し込む）
    lead: str = ""
    page: int = 0
    slot: str = ""  # 差し込み先スロット ID
    title_slot: str = ""
    lead_slot: str = ""
    author_slot: str = ""
    limit_chars: int = 0  # 枠の字数上限（0 なら無制限）
    chars_per_line: int = 0
    lines: int = 0
    photos: list[str] = field(default_factory=list)  # Photo の id
    status: str = "下書き"  # 下書き / 校正済み / 割付済み / 確定
    notes: str = ""
    ignored_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Project:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.data: dict = {
            "schema": SCHEMA_VERSION,
            "title": self.root.name,
            "issue_no": "",
            "issue_date": "",
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "updated": "",
            "template": "",
            "articles": [],
            "photos": [],
            "settings": {
                "max_sentence": 90,
                "checks": ["style", "typo", "confusion", "grammar", "punct", "read", "ruby", "noun"],
                "normalize_numbers": True,
            },
        }
        self._dic: Dictionaries | None = None

    # ------------------------------------------------------------ 入出力

    @property
    def json_path(self) -> Path:
        return self.root / "project.json"

    @property
    def manuscripts_dir(self) -> Path:
        return self.root / "manuscripts"

    @property
    def photos_dir(self) -> Path:
        return self.root / "photos"

    @property
    def output_dir(self) -> Path:
        return self.root / "出力"

    @classmethod
    def create(cls, root: Path | str, title: str = "") -> "Project":
        p = cls(root)
        p.root.mkdir(parents=True, exist_ok=True)
        for d in (p.manuscripts_dir, p.photos_dir, p.output_dir):
            d.mkdir(exist_ok=True)
        if title:
            p.data["title"] = title
        p.save()
        return p

    @classmethod
    def open(cls, root: Path | str) -> "Project":
        p = cls(root)
        if not p.json_path.exists():
            raise FileNotFoundError(f"{p.json_path} がありません")
        with open(p.json_path, encoding="utf-8") as f:
            p.data.update(json.load(f))
        for d in (p.manuscripts_dir, p.photos_dir, p.output_dir):
            d.mkdir(exist_ok=True)
        return p

    def save(self) -> None:
        self.data["updated"] = time.strftime("%Y-%m-%d %H:%M")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.json_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.json_path)

    # ------------------------------------------------------------ 辞書

    @property
    def dictionaries(self) -> Dictionaries:
        if self._dic is None:
            self._dic = Dictionaries(self.root / "user_dict.json")
        return self._dic

    def reload_dictionaries(self) -> None:
        self._dic = None

    # ------------------------------------------------------------ 様式

    def set_template(self, src: Path | str) -> dict:
        """様式（Word）を取り込む。.doc なら .docx に変換する。"""
        src = Path(src)
        dest = self.root / "template.docx"
        if src.suffix.lower() == ".docx":
            shutil.copy2(src, dest)
        else:
            # 様式はレイアウトごと扱うため、旧形式は .docx に変換する。
            # Word が入っていればそれを使い、無ければ LibreOffice を試す。
            from .importers import convert_doc_to_docx

            converted = convert_doc_to_docx(src)
            if converted is None:
                raise RuntimeError(
                    "旧形式（.doc）の様式を .docx に変換できませんでした。\n"
                    "Word で様式を開き、「名前を付けて保存」→"
                    "「Word 文書（.docx）」で保存し直してから読み込んでください。\n"
                    "（原稿としての .doc の読み込みは、変換なしでできます）"
                )
            shutil.copy2(converted, dest)
        self.data["template"] = "template.docx"
        self.save()
        return self.template_slots()

    def template(self) -> DocxTemplate:
        if not self.data.get("template"):
            raise RuntimeError("様式（Word）がまだ読み込まれていません")
        return DocxTemplate(self.root / self.data["template"])

    def template_slots(self) -> dict:
        t = self.template()
        return {
            "slots": [s.to_dict() for s in t.slots()],
            "images": t.images(),
        }

    # ------------------------------------------------------------ 記事

    def articles(self) -> list[Article]:
        return [Article(**a) for a in self.data["articles"]]

    def get_article(self, aid: str) -> Article | None:
        for a in self.data["articles"]:
            if a["id"] == aid:
                return Article(**a)
        return None

    def put_article(self, art: Article) -> None:
        d = art.to_dict()
        for i, a in enumerate(self.data["articles"]):
            if a["id"] == art.id:
                self.data["articles"][i] = d
                break
        else:
            self.data["articles"].append(d)
        self.save()

    def delete_article(self, aid: str) -> None:
        self.data["articles"] = [a for a in self.data["articles"] if a["id"] != aid]
        self.save()

    def import_manuscript(self, src: Path | str, *, normalize: bool | None = None) -> Article:
        """議員から届いた原稿ファイルを取り込んで記事にする。"""
        src = Path(src)
        self.manuscripts_dir.mkdir(exist_ok=True)
        dest = self.manuscripts_dir / _safe_name(src.name)
        if dest.resolve() != src.resolve():
            shutil.copy2(src, dest)

        if normalize is None:
            normalize = True
        doc = read_any(dest, normalize=False)
        text = doc.text
        if normalize and text:
            text = normalize_manuscript(
                text, numbers=self.data["settings"].get("normalize_numbers", True)
            )

        art = Article(
            id=_new_id("art"),
            title=doc.title,
            author=doc.author,
            source_file=dest.name,
            raw=doc.text,
            body=text,
        )

        # 原稿に埋め込まれていた写真も取り込む
        for img in doc.images:
            try:
                p = self._store_photo(img["data"], img["name"])
                art.photos.append(p.id)
            except Exception:
                continue

        self.put_article(art)
        return art

    # ------------------------------------------------------------ 写真

    def photos(self) -> list[Photo]:
        return [Photo(**p) for p in self.data["photos"]]

    def get_photo(self, pid: str) -> Photo | None:
        for p in self.data["photos"]:
            if p["id"] == pid:
                return Photo(**p)
        return None

    def put_photo(self, photo: Photo) -> None:
        d = photo.to_dict()
        for i, p in enumerate(self.data["photos"]):
            if p["id"] == photo.id:
                self.data["photos"][i] = d
                break
        else:
            self.data["photos"].append(d)
        self.save()

    def _store_photo(self, data: bytes, name: str) -> Photo:
        self.photos_dir.mkdir(exist_ok=True)
        pid = _new_id("ph")
        ext = Path(name).suffix.lower() or ".jpg"
        fname = f"{pid}{ext}"
        (self.photos_dir / fname).write_bytes(data)
        info = photos_mod.inspect(data, name)
        photo = Photo(id=pid, file=fname, caption="", info=info.to_dict())
        self.put_photo(photo)
        return photo

    def import_photo(self, src: Path | str) -> Photo:
        src = Path(src)
        return self._store_photo(src.read_bytes(), src.name)

    def photo_bytes(self, pid: str) -> bytes:
        p = self.get_photo(pid)
        if not p:
            raise KeyError(pid)
        return (self.photos_dir / p.file).read_bytes()

    def delete_photo(self, pid: str) -> None:
        p = self.get_photo(pid)
        if p:
            f = self.photos_dir / p.file
            if f.exists():
                f.unlink()
        self.data["photos"] = [x for x in self.data["photos"] if x["id"] != pid]
        for a in self.data["articles"]:
            a["photos"] = [x for x in a.get("photos", []) if x != pid]
        self.save()

    # ------------------------------------------------------------ 編集支援

    def proofread_article(self, aid: str) -> dict:
        art = self.get_article(aid)
        if not art:
            raise KeyError(aid)
        st = self.data["settings"]
        issues = proofread(
            art.body,
            self.dictionaries,
            enabled=set(st.get("checks", [])),
            max_sentence=st.get("max_sentence", 90),
        )
        issues = [i for i in issues if i.rule_id not in set(art.ignored_issues)]
        return {
            "issues": [i.to_dict() for i in issues],
            "summary": summarize_issues(issues),
            "chars": count_chars(art.body),
            "lines": estimate_lines(art.body, art.chars_per_line) if art.chars_per_line else 0,
        }

    def fit_article(self, aid: str, *, target: int | None = None) -> dict:
        """記事本文を枠に収まるよう要約する。結果は返すだけで、保存はしない。"""
        art = self.get_article(aid)
        if not art:
            raise KeyError(aid)
        if art.chars_per_line and art.lines:
            res = fit_to_frame(art.body, chars_per_line=art.chars_per_line, lines=art.lines)
        else:
            t = target or art.limit_chars or count_chars(art.body)
            res = summarize(art.body, target_chars=t)
        return {
            "text": res.text,
            "chars": res.chars,
            "kept": res.kept,
            "total": res.total,
            "method": res.method,
            "note": res.note,
            "before": count_chars(art.body),
        }

    def suggest_titles(self, aid: str, max_chars: int = 13) -> dict:
        art = self.get_article(aid)
        if not art:
            raise KeyError(aid)
        return {
            "titles": headline_candidates(art.body, max_chars=max_chars),
            "lead": lead_sentence(art.body),
        }

    def auto_layout(self, **kw) -> dict:
        """写真の名前から、記事と様式の枠を自動で割り当てる。"""
        from .autolayout import auto_layout

        return auto_layout(self, **kw)

    # ------------------------------------------------------------ 書き出し

    def export(self, filename: str = "", *, make_pdf: bool = False) -> dict:
        """すべての記事・写真を様式に差し込んで Word を書き出す。"""
        t = self.template()
        t.slots()

        values: dict[str, str] = {}
        unassigned: list[str] = []
        for art in self.articles():
            if art.slot:
                values[art.slot] = art.body
            else:
                unassigned.append(art.title or art.author or art.id)
            if art.title_slot and art.title:
                values[art.title_slot] = art.title
            if art.lead_slot and art.lead:
                values[art.lead_slot] = art.lead
            if art.author_slot and art.author:
                values[art.author_slot] = art.author

        # 写真の説明文（写真枠のそばのテキスト枠）
        for ph in self.photos():
            if ph.caption_slot and ph.caption:
                values[ph.caption_slot] = ph.caption

        photo_reports: list[dict] = []
        template_images = {i["name"]: i for i in t.images()}
        for ph in self.photos():
            if not ph.slot:
                continue
            target = template_images.get(ph.slot)
            if not target:
                photo_reports.append({"photo": ph.id, "ok": False,
                                      "message": f"様式に {ph.slot} がありません"})
                continue
            try:
                original = t.image_bytes(ph.slot)
                data = photos_mod.prepare_for_slot(
                    (self.photos_dir / ph.file).read_bytes(), ph.slot, original
                )
                t.replace_image(ph.slot, data)
                photo_reports.append({"photo": ph.id, "ok": True, "slot": ph.slot})
            except Exception as e:  # pragma: no cover
                photo_reports.append({"photo": ph.id, "ok": False, "message": str(e)})

        t.fill(values)

        self.output_dir.mkdir(exist_ok=True)
        name = filename or f"{_safe_name(self.data.get('title') or '議会だより')}_差込.docx"
        if not name.lower().endswith(".docx"):
            name += ".docx"
        out = t.save(self.output_dir / name)

        result = {
            "docx": str(out),
            "filled": len(values),
            "photos": photo_reports,
            "unassigned": unassigned,
            "pdf": None,
        }
        if make_pdf:
            from .docxio import docx_to_pdf

            pdf = docx_to_pdf(out, self.output_dir)
            result["pdf"] = str(pdf) if pdf else None
            if pdf is None:
                result["pdf_error"] = (
                    "PDF を作るには LibreOffice が必要です。"
                    "Word で開いて「名前を付けて保存 → PDF」でも同じものが作れます。"
                )
        return result
