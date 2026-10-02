"""1 号ぶんの原稿・紙面・操作履歴を管理する。

画面に依存する判断をここへまとめ、tkinter を使わずにテストできるようにする。
"""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import compose as C
import docx_out as dx
import ingest as I
import layout
from grid import Geometry, Rect, to_box


def _rect_data(rect: Rect) -> dict:
    return {"dan": rect.dan, "line": rect.line,
            "dan_span": rect.dan_span, "line_span": rect.line_span}


def _rect(value) -> Optional[Rect]:
    if value is None or isinstance(value, Rect):
        return value
    return Rect(value["dan"], value["line"], value.get("dan_span", 1),
                value.get("line_span", 1))


class Edition:
    """号フォルダと、そこに保存する紙面の状態。"""

    def __init__(self, folder: Path, issue: layout.Issue, data: dict) -> None:
        self.folder = Path(folder).resolve()
        self.issue = issue
        self.plan = layout.make_plan(issue)
        self.pages = data.get("pages", [])
        self.history = data.get("history", [])
        self.history_index = data.get("history_index", len(self.history))
        self.geometry = Geometry()
        self._ingest_cache = {}

    @classmethod
    def create(cls, folder: Path, issue: layout.Issue) -> "Edition":
        """空の号フォルダを作り、ページ割りを保存する。"""
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("原稿", "写真", "出力"):
            (folder / name).mkdir(exist_ok=True)
        plan = layout.make_plan(issue)
        data = {"pages": [cls._new_page(p) for p in plan.pages],
                "history": [], "history_index": 0}
        edition = cls(folder, issue, data)
        edition.save()
        return edition

    @classmethod
    def open(cls, folder: Path) -> "Edition":
        """保存済みの号フォルダを開く。"""
        folder = Path(folder).resolve()
        issue = layout.Issue.load(folder)
        data = json.loads((folder / "紙面.json").read_text(encoding="utf-8"))
        return cls(folder, issue, data)

    @staticmethod
    def _new_page(slot: layout.PageSlot) -> dict:
        return {"no": slot.no, "section": slot.section, "index": slot.index,
                "label": slot.label, "source": None, "overrides": {},
                "state": "未入力"}

    def save(self) -> None:
        """号情報と紙面を JSON に保存する。履歴も紙面.json に含める。"""
        self.issue.save(self.folder)
        data = {"version": 1, "pages": self.pages, "history": self.history,
                "history_index": self.history_index}
        (self.folder / "紙面.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _state(self) -> dict:
        return {"issue": asdict(self.issue), "pages": copy.deepcopy(self.pages)}

    def _restore_state(self, state: dict) -> None:
        self.issue = layout.Issue(**state["issue"])
        self.plan = layout.make_plan(self.issue)
        self.pages = copy.deepcopy(state["pages"])
        self._ingest_cache.clear()

    def _record(self, action: str, before: dict) -> None:
        self.history = self.history[:self.history_index]
        self.history.append({"action": action, "before": before,
                             "after": self._state()})
        self.history_index = len(self.history)
        self.save()

    def _page(self, page_no: int) -> dict:
        if not 1 <= page_no <= len(self.pages):
            raise ValueError(f"ページ番号が正しくありません: {page_no}")
        return self.pages[page_no - 1]

    def assign(self, page_no: int, source: Path) -> str:
        """原稿を号フォルダへ写し、ページへ割り当てる。"""
        source = Path(source)
        if not source.is_file():
            raise ValueError(f"原稿が見つかりません: {source}")
        before = self._state()
        target = self.folder / "原稿" / source.name
        if source.resolve() != target.resolve():
            if target.exists() and target.read_bytes() != source.read_bytes():
                stem, suffix = source.stem, source.suffix
                n = 2
                while target.exists():
                    target = self.folder / "原稿" / f"{stem}_{n}{suffix}"
                    n += 1
            if not target.exists():
                shutil.copy2(str(source), str(target))
        result = I.ingest(target)
        self._keep_photos(source.parent, result)
        self._ingest_cache[target.name] = (target.stat().st_mtime_ns,
                                           target.stat().st_size, result)
        page = self._page(page_no)
        page["source"] = target.name
        page["overrides"] = {}
        composed = self._compose_page(page_no)
        page["state"] = "あふれ" if composed.overflow_lines else "できた"
        self._record(f"{page_no}ページに原稿を入れる", before)
        return target.name

    # 画面側で意味が読みやすい別名も用意する。
    assign_source = assign

    def _keep_photos(self, source_folder: Path, result: I.IngestResult) -> None:
        for name, data in result.images.items():
            target = self.folder / "写真" / Path(name).name
            if not target.exists():
                target.write_bytes(data)
        for part in result.parts:
            if part.kind != "写真" or not part.image or part.image in result.images:
                continue
            candidate = source_folder / part.image
            target = self.folder / "写真" / Path(part.image).name
            if candidate.is_file() and not target.exists():
                shutil.copy2(str(candidate), str(target))

    def _ingest(self, filename: str) -> I.IngestResult:
        path = self.folder / "原稿" / filename
        stat = path.stat()
        cached = self._ingest_cache.get(filename)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2]
        result = I.ingest(path)
        for part in result.parts:
            if part.kind == "写真" and part.image and part.image not in result.images:
                photo = self.folder / "写真" / Path(part.image).name
                if photo.is_file():
                    result.images[part.image] = photo.read_bytes()
        self._ingest_cache[filename] = (stat.st_mtime_ns, stat.st_size, result)
        return result

    def _overrides(self, page: dict) -> Dict[int, dict]:
        out = {}
        for key, value in page.get("overrides", {}).items():
            out[int(key)] = {"rect": _rect(value.get("rect")),
                             "size": value.get("size"),
                             "removed": bool(value.get("removed", False))}
        return out

    def _compose_page(self, page_no: int) -> C.PageResult:
        page = self._page(page_no)
        result = self._ingest(page["source"])
        return C.compose_page(page["section"], result.parts, result.images,
                              self.geometry, self._overrides(page))

    def compose(self, page_no: int) -> C.PageResult:
        """指定ページを組み、現在の状態を更新する。"""
        page = self._page(page_no)
        if not page["source"]:
            return C.compose_page(page["section"], [], {}, self.geometry)
        result = self._compose_page(page_no)
        page["state"] = "あふれ" if result.overflow_lines else "できた"
        self.save()
        return result

    def _can_place(self, page_no: int, part_no: int, rect: Rect) -> bool:
        if (rect.dan < 0 or rect.line < 0
                or rect.dan + rect.dan_span > self.geometry.dans
                or rect.line + rect.line_span > self.geometry.lines_per_dan):
            return False
        page = self._page(page_no)
        occupied = list(layout.fixed_areas(page["section"], self.geometry).values())
        # 本文は置いた後に流し直せるが、ほかの写真・大見出しとは重ねない。
        if page["source"]:
            current = self._compose_page(page_no)
            occupied.extend(p.rect for p in current.placements
                            if p.index != part_no and p.part.kind in ("写真", "大見出し"))
        for key, change in self._overrides(page).items():
            if key != part_no and not change["removed"] and change["rect"] is not None:
                occupied.append(change["rect"])
        return not any(rect.overlaps(other) for other in occupied)

    def move_part(self, page_no: int, part_no: int, rect: Rect) -> bool:
        """写真・大見出しを動かす。置けない場所なら変更しない。"""
        result = self._ingest(self._page(page_no)["source"])
        if not 0 <= part_no < len(result.parts) or result.parts[part_no].kind not in ("写真", "大見出し"):
            raise ValueError("動かせるのは写真と大見出しだけです")
        if not self._can_place(page_no, part_no, rect):
            return False
        before = self._state()
        change = self._page(page_no)["overrides"].setdefault(str(part_no), {})
        change["rect"] = _rect_data(rect)
        change.setdefault("size", None)
        change["removed"] = False
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの部品{part_no + 1}を動かす", before)
        return True

    def can_move_part(self, page_no: int, part_no: int, rect: Rect) -> bool:
        """画面で、離す前の場所へ部品を置けるか確かめる。"""
        return self._can_place(page_no, part_no, rect)

    def resize_photo(self, page_no: int, part_no: int, size: str) -> bool:
        """写真の大きさを変える。現在位置で重なる場合は変更しない。"""
        if size not in C.PHOTO_WIDTH_MM:
            raise ValueError("写真の大きさは 大・中・小・顔 のいずれかです")
        result = self._ingest(self._page(page_no)["source"])
        if not 0 <= part_no < len(result.parts) or result.parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        page = self._page(page_no)
        old = self._overrides(page).get(part_no, {})
        rect = old.get("rect")
        new_rect = C.photo_rect(self.geometry, size, rect.dan, rect.line) if rect else None
        if new_rect is not None and not self._can_place(page_no, part_no, new_rect):
            return False
        before = self._state()
        change = page["overrides"].setdefault(str(part_no), {})
        change["size"] = size
        change["rect"] = _rect_data(new_rect) if new_rect else change.get("rect")
        change["removed"] = False
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真{part_no + 1}を{size}にする", before)
        return True

    change_photo_size = resize_photo

    def remove_photo(self, page_no: int, part_no: int) -> None:
        """写真を紙面から外す。元画像は削除しない。"""
        result = self._ingest(self._page(page_no)["source"])
        if not 0 <= part_no < len(result.parts) or result.parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        before = self._state()
        change = self._page(page_no)["overrides"].setdefault(str(part_no), {})
        change["removed"] = True
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真{part_no + 1}を外す", before)

    def restore_photo(self, page_no: int, part_no: int) -> None:
        """外した写真を紙面へ戻す。"""
        result = self._ingest(self._page(page_no)["source"])
        if not 0 <= part_no < len(result.parts) or result.parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        before = self._state()
        change = self._page(page_no)["overrides"].setdefault(str(part_no), {})
        change["removed"] = False
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真{part_no + 1}を戻す", before)

    def _update_page_state(self, page_no: int) -> None:
        page = self._page(page_no)
        if page["source"]:
            page["state"] = "あふれ" if self._compose_page(page_no).overflow_lines else "できた"

    def change_issue(self, **changes) -> None:
        """号情報を変え、同じ区分・順番の原稿を新しいページへ引き継ぐ。"""
        before = self._state()
        values = asdict(self.issue)
        unknown = set(changes) - set(values)
        if unknown:
            raise ValueError("号情報にない項目です: " + "、".join(sorted(unknown)))
        values.update(changes)
        self.issue = layout.Issue(**values)
        self.plan = layout.make_plan(self.issue)
        old = {(p["section"], p["index"]): p for p in self.pages}
        self.pages = []
        for slot in self.plan.pages:
            page = self._new_page(slot)
            previous = old.get((slot.section, slot.index))
            if previous:
                page["source"] = previous["source"]
                page["overrides"] = previous["overrides"]
                page["state"] = previous["state"]
            self.pages.append(page)
        self._record("号情報を変える", before)

    def undo(self) -> bool:
        """直前の操作を元に戻す。"""
        if self.history_index == 0:
            return False
        self.history_index -= 1
        self._restore_state(self.history[self.history_index]["before"])
        self.save()
        return True

    def redo(self) -> bool:
        """元に戻した操作をやり直す。"""
        if self.history_index >= len(self.history):
            return False
        self._restore_state(self.history[self.history_index]["after"])
        self.history_index += 1
        self.save()
        return True

    def check(self) -> List[str]:
        """号全体で直す点・知らせる点を一覧にする。"""
        messages = ["× " + e for e in self.plan.errors]
        messages.extend("・" + n for n in self.plan.notes)
        for page in self.pages:
            prefix = f"{page['no']}ページ（{page['label']}）"
            if not page["source"]:
                messages.append(prefix + ": 原稿が未入力です")
                continue
            ingested = self._ingest(page["source"])
            result = self.compose(page["no"])
            if result.overflow_lines:
                messages.append(prefix + f": {result.overflow_lines}行あふれています")
            messages.extend(prefix + ": " + w for w in result.warnings)
            messages.extend(prefix + ": " + w for w in ingested.warnings)
            if page["section"] == layout.IPPAN:
                messages.extend(prefix + ": " + w for w in I.check_ippan(ingested.parts))
        return messages

    def export(self) -> List[Path]:
        """全ページの Word・確認リスト・使用写真を書き出し、絶対パスを返す。"""
        output = self.folder / "出力"
        photo_output = output / "写真"
        output.mkdir(exist_ok=True)
        photo_output.mkdir(exist_ok=True)
        pages = []
        written_photos = []
        for page_data in self.pages:
            if not page_data["source"]:
                box = to_box(self.geometry, Rect(0, 0, 1, 10))
                pages.append(dx.Page([dx.TextBox(box, [page_data["label"]],
                                                  dx.GOTHIC, 18.0, 22.0,
                                                  True, True, "区分名")]))
                continue
            ingested = self._ingest(page_data["source"])
            result = self.compose(page_data["no"])
            pages.append(result.page)
            placed = {p.index for p in result.placements if p.part.kind == "写真"}
            number = 0
            for index, part in enumerate(ingested.parts):
                if part.kind != "写真":
                    continue
                number += 1
                if index not in placed or not part.image or part.image not in ingested.images:
                    continue
                data = ingested.images[part.image]
                try:
                    ext = C._image_ext(part.image, data)
                except ValueError:
                    continue
                suffix = ".jpg" if ext == "jpeg" else ".png"
                target = photo_output / f"p{page_data['no']:02d}_写真{number}{suffix}"
                target.write_bytes(data)
                written_photos.append(target.resolve())
        docx = (output / f"第{self.issue.number}号.docx").resolve()
        dx.write_docx(docx, self.geometry, pages)
        checklist = (output / "確認リスト.txt").resolve()
        messages = self.check()
        checklist.write_text("\n".join(messages) + ("\n" if messages else "問題はありません。\n"),
                             encoding="utf-8")
        return [docx, checklist] + written_photos
