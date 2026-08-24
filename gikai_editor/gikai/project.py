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
    section: str = ""      # 構成のどの区分か（sections.py の id）
    order: int = 0         # 区分の中での並び順
    section_why: str = ""  # 区分をどう判定したか（画面で見せる）
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
            "layout": {},          # 紙面の決まりごと（自動組版で使う）
            "sections": [],        # 構成（台割）。空なら既定の並び
            "settings": {
                "compose_mode": "auto",   # auto=自動組版 / slots=前号の様式に差し込む
                "target_pages": 0,        # 0 なら成り行き
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
        # どの区分の原稿かを、名前と見出しから見当を付ける
        from . import sections as sec

        art.section, art.section_why = sec.guess_section(
            self.sections, filename=dest.name, title=doc.title, body=text)
        # 同じ区分の末尾に置く（届いた順に並ぶ）
        art.order = 1 + max(
            [a.order for a in self.articles() if a.section == art.section] or [0])

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

    # ------------------------------------------------------------ 構成（台割）

    @property
    def sections(self):
        from . import sections as sec

        return sec.load(self.data.get("sections"))

    def set_sections(self, items: list[dict]) -> dict:
        """構成を保存する。区分の追加・削除・並べ替えに使う。"""
        from . import sections as sec

        loaded = sec.load(items)
        self.data["sections"] = [x.to_dict() for x in loaded]
        self.save()
        return self.outline()

    def outline(self) -> dict:
        """構成の順に記事を並べた一覧。編集の進み具合もここで見る。"""
        from . import sections as sec

        groups = sec.group_articles(self.sections, self.articles())
        out = []
        for g in groups:
            arts = g["articles"]
            out.append({
                "id": g["id"],
                "name": g["name"],
                "note": g["note"],
                "optional": g["optional"],
                "target_pages": g["target_pages"],
                "count": len(arts),
                "chars": sum(count_chars(a.body) for a in arts),
                "done": sum(1 for a in arts if a.status in ("校正済み", "割付済み", "確定")),
                "articles": [a.to_dict() for a in arts],
            })
        return {"sections": out, "unassigned": sum(
            1 for a in self.articles() if not a.section)}

    def assign_sections(self, *, only_unassigned: bool = True) -> dict:
        """原稿の名前や見出しから、どの区分のものかを推測して割り当てる。

        判定した理由も残すので、画面で確かめて直せる。
        """
        from . import sections as sec

        secs = self.sections
        report = {"assigned": [], "unknown": []}
        for art in self.articles():
            if only_unassigned and art.section:
                continue
            sid, why = sec.guess_section(
                secs, filename=art.source_file, title=art.title, body=art.body)
            row = {"id": art.id, "label": art.title or art.author or art.id,
                   "section": sid, "why": why}
            if sid:
                art.section = sid
                art.section_why = why
                self.put_article(art)
                row["section_name"] = next(
                    (x.name for x in secs if x.id == sid), sid)
                report["assigned"].append(row)
            else:
                report["unknown"].append(row)
        self.renumber()
        return report

    def renumber(self) -> None:
        """区分ごとに、記事の並び順を 1 から振り直す。"""
        from . import sections as sec

        for group in sec.group_articles(self.sections, self.articles()):
            for i, art in enumerate(group["articles"], 1):
                if art.order != i:
                    art.order = i
                    self.put_article(art)

    def move_article(self, aid: str, delta: int) -> dict:
        """区分の中で、記事を1つ上／下へ動かす。"""
        from . import sections as sec

        art = self.get_article(aid)
        if not art:
            raise KeyError(aid)
        siblings = [
            a for a in self.articles() if a.section == art.section
        ]
        siblings.sort(key=lambda a: (a.order, a.id))
        idx = next((i for i, a in enumerate(siblings) if a.id == aid), -1)
        if idx < 0:
            raise KeyError(aid)
        new = idx + delta
        if not (0 <= new < len(siblings)):
            return self.outline()
        siblings[idx], siblings[new] = siblings[new], siblings[idx]
        for i, a in enumerate(siblings, 1):
            a.order = i
            self.put_article(a)
        return self.outline()

    def delete_articles(self, ids: list[str]) -> dict:
        """選んだ原稿をまとめて削除する。

        記事の登録を消すだけで、`manuscripts/` の原本には手を付けない。
        写真も消さない（別の記事で使うことがあるため）。
        """
        ids = [i for i in (ids or []) if i]
        if not ids:
            return {"deleted": 0, "titles": []}
        titles = [
            (a.title or a.author or a.source_file or a.id)
            for a in self.articles() if a.id in ids
        ]
        before = len(self.data["articles"])
        self.data["articles"] = [
            a for a in self.data["articles"] if a["id"] not in ids
        ]
        self.save()
        self.renumber()
        return {"deleted": before - len(self.data["articles"]), "titles": titles}

    # ------------------------------------------------------------ 自動組版

    @property
    def layout_spec(self):
        from .compose import LayoutSpec

        return LayoutSpec.from_dict(self.data.get("layout"))

    def set_layout(self, spec_dict: dict) -> dict:
        from .compose import LayoutSpec

        spec = LayoutSpec.from_dict({**self.data.get("layout", {}), **(spec_dict or {})})
        self.data["layout"] = spec.to_dict()
        self.save()
        return {"layout": spec.to_dict(), "metrics": spec.metrics()}

    def compose(self, filename: str = "") -> dict:
        """5段縦書きの紙面を、中身に合わせて組み上げる。"""
        from .compose import compose as _compose

        return _compose(self, self.layout_spec, filename).to_dict()

    def plan_pages(self, target_pages: int) -> dict:
        """目標ページ数に収めるために、各記事を何字にすればよいかを出す。

        いきなり本文を書き換えず、記事ごとの字数上限を決めて返す。
        実際に詰めるかどうかは利用者が決める。
        """
        from .compose import compose as _compose

        spec = self.layout_spec
        m = spec.metrics()
        now = _compose(self, spec, "_見積もり用.docx")
        # 見積もり用に作ったファイルは残さない
        Path(now.path).unlink(missing_ok=True)

        per_page = max(1, now.lines_per_page)
        if target_pages <= 0 or now.pages_estimated <= target_pages:
            return {
                "pages_now": now.pages_estimated,
                "target": target_pages,
                "need_cut": False,
                "plan": [],
                "message": (f"いまの分量は約 {now.pages_estimated} ページです。"
                            + (f"目標の {target_pages} ページに収まっています。"
                               if target_pages > 0 else "")),
            }

        # 削るべき行数を、記事の長さに応じて割り振る
        over_lines = now.lines_used - target_pages * per_page
        arts = [a for a in self.articles() if a.body.strip()]
        total = sum(count_chars(a.body) for a in arts) or 1
        cpl = m["chars_per_line"]
        plan = []
        for a in arts:
            cur = count_chars(a.body)
            share = over_lines * (cur / total)
            cut = int(share * cpl)
            plan.append({
                "id": a.id,
                "label": a.title or a.author or a.id,
                "now": cur,
                "target": max(60, cur - cut),
                "cut": min(cut, max(0, cur - 60)),
            })
        return {
            "pages_now": now.pages_estimated,
            "target": target_pages,
            "need_cut": True,
            "over_lines": over_lines,
            "plan": plan,
            "message": (f"いまの分量は約 {now.pages_estimated} ページです。"
                        f"{target_pages} ページに収めるには、全体で約 "
                        f"{sum(p['cut'] for p in plan)} 字を詰める必要があります。"),
        }

    def fit_to_pages(self, target_pages: int) -> dict:
        """目標ページ数に合わせて、全記事をまとめて詰める。

        記事ごとの結果を返す。元の原稿は manuscripts/ に残っているので、
        画面の「取り込んだ原稿に戻す」でいつでも戻せる。
        """
        plan = self.plan_pages(target_pages)
        if not plan.get("need_cut"):
            # 詰める必要が無くても、呼び出し側が同じ形で扱えるようにそろえる
            return {**plan, "applied": [], "pages_after": plan["pages_now"]}

        # 詰めると行の折り返しが変わるので、目標に届くまで数回くり返す。
        # （1回では、削った字数のわりにページが減らないことがある）
        first: dict[str, int] = {}
        applied: dict[str, dict] = {}
        current = plan
        for _ in range(4):
            if not current.get("need_cut"):
                break
            changed = False
            for item in current["plan"]:
                if item["cut"] <= 0:
                    continue
                art = self.get_article(item["id"])
                if not art:
                    continue
                before = count_chars(art.body)
                res = summarize(art.body, target_chars=item["target"])
                if res.chars >= before:
                    continue          # これ以上は縮まない
                first.setdefault(art.id, before)
                art.body = res.text
                self.put_article(art)
                applied[art.id] = {
                    "id": art.id, "label": item["label"],
                    "before": first[art.id], "after": res.chars, "method": res.method,
                }
                changed = True
            if not changed:
                break
            current = self.plan_pages(target_pages)

        after = self.plan_pages(target_pages)
        out = {**plan, "applied": list(applied.values()), "pages_after": after["pages_now"]}
        if after["pages_now"] > target_pages:
            out["message"] = (
                plan["message"] + f" これ以上は縮まず、約 {after['pages_now']} ページまでになりました。"
                "写真を減らすか、記事を次号に回すことを検討してください。"
            )
        return out

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
