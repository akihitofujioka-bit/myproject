"""1 号ぶんの原稿・紙面・操作履歴を管理する。

画面に依存する判断をここへまとめ、tkinter を使わずにテストできるようにする。
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import compose as C
import docx_out as dx
import ingest as I
import layout
import photo_list
import templates
import writer
from settings import Settings
from grid import Geometry, Rect, to_box


FLOW_SECTIONS = frozenset((layout.GYOSEI, layout.YOSAN, layout.KESSAN,
                           layout.IINKAI, layout.TOKUSHU))


def _rect_data(rect: Rect) -> dict:
    return {"dan": rect.dan, "line": rect.line,
            "dan_span": rect.dan_span, "line_span": rect.line_span}


def _rect(value) -> Optional[Rect]:
    if value is None or isinstance(value, Rect):
        return value
    return Rect(value["dan"], value["line"], value.get("dan_span", 1),
                value.get("line_span", 1))


def next_hint(current: Optional["Edition"]) -> str:
    """号の状態から、利用者が次にすることを短い一文で返す。"""
    if current is None:
        return "「新しい号」を押して、号数と月を入れてください。"
    unfilled = next((page for page in current.pages if page["state"] == "未入力"), None)
    if unfilled:
        if "form" in unfilled:
            return "左の一覧で ○ のページを選び、右の「ページ」タブの「入力欄を開く」を押してください。"
        return "左の一覧で ○ のページを選び、右の「ページ」タブの「原稿を入れる」か「書いて直す」を押してください。"
    if any(page["state"] == "あふれ" for page in current.pages):
        return ("赤いページを選び、写真を小さくする・種類を直す、または"
                "「ページ」タブで次のページへ送ってください。")
    return "必要な写真は右の「写真」タブから置き、「確かめる」のあと「Word に書き出す」を押してください。"


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
        self.settings = Settings.load()
        self._ingest_cache = {}
        for page in self.pages:
            page.setdefault("placed_photos", [])
            page.setdefault("flow_to_next", False)

    @classmethod
    def create(cls, folder: Path, issue: layout.Issue) -> "Edition":
        """空の号フォルダを作り、ページ割りを保存する。"""
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("原稿", "写真", "事務局原稿", "出力"):
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
        page = {"no": slot.no, "section": slot.section, "index": slot.index,
                "label": slot.label, "source": None, "overrides": {},
                "placed_photos": [], "flow_to_next": False, "state": "未入力"}
        if slot.section in templates.FORM_SECTIONS:
            page["form"] = templates.default_form(slot.section)
        return page

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
        for page in self.pages:
            if page.get("writer_text") is not None and page.get("source"):
                path = self._source_path(page["source"])
                path.parent.mkdir(exist_ok=True)
                path.write_text(page["writer_text"], encoding="utf-8")

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
        self._update_page_state(page_no)
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

    def _source_path(self, filename: str) -> Path:
        """従来の原稿名と、事務局原稿の相対名を実ファイルへ直す。"""
        relative = Path(filename)
        if relative.parts and relative.parts[0] == "事務局原稿":
            return self.folder / relative
        return self.folder / "原稿" / filename

    def _ingest(self, filename: str) -> I.IngestResult:
        path = self._source_path(filename)
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

    def writer_text(self, page_no: int) -> str:
        """書く窓へ出す、現在の原稿を印付き文章で返す。"""
        page = self._page(page_no)
        if "form" in page:
            raise ValueError("書き込み式ページでは、この書く窓は使いません")
        if page.get("writer_text") is not None:
            return str(page["writer_text"])
        if not page.get("source"):
            return ""
        result = self._ingest(page["source"])
        return writer.marked_text(result.parts, page["section"], self._overrides(page))

    def _writer_result(self, page_no: int, text: str) -> tuple:
        page = self._page(page_no)
        result = I.ingest_text(text, f"{page_no:02d}_{page['section']}.txt")
        for part in result.parts:
            if part.kind == "写真" and part.image:
                path = self.folder / "写真" / Path(part.image).name
                if path.is_file():
                    result.images[part.image] = path.read_bytes()
        composed = C.compose_page(page["section"], result.parts, result.images,
                                  self.geometry)
        return composed, result.parts

    def preview_writer(self, page_no: int, text: str) -> tuple:
        """保存せずに事務局原稿を組み、書く窓の見本へ返す。"""
        page = self._page(page_no)
        if "form" in page:
            raise ValueError("書き込み式ページでは、この書く窓は使いません")
        return self._writer_result(page_no, text)

    def save_writer(self, page_no: int, text: str) -> str:
        """事務局原稿を UTF-8 で保存し、そのページへ割り当てる。"""
        page = self._page(page_no)
        if "form" in page:
            raise ValueError("書き込み式ページでは、この書く窓は使いません")
        before = self._state()
        safe_section = re.sub(r"[\\/:*?\"<>|]", "_", page["section"])
        name = f"{page_no:02d}_{safe_section}.txt"
        relative = str(Path("事務局原稿") / name)
        target = self.folder / relative
        target.parent.mkdir(exist_ok=True)
        target.write_text(text, encoding="utf-8")
        page["source"] = relative
        page["writer_text"] = text
        page["overrides"] = {}
        self._ingest_cache.pop(relative, None)
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの事務局原稿を保存する", before)
        return relative

    def keep_writer_photo(self, source: Path) -> str:
        """書く窓で選んだ写真を号フォルダへ写し、保存名を返す。"""
        source = Path(source)
        if not source.is_file():
            raise OSError(f"写真が見つかりません: {source}")
        target = self.folder / "写真" / source.name
        if target.exists() and target.read_bytes() != source.read_bytes():
            number = 2
            while target.exists():
                target = self.folder / "写真" / f"{source.stem}_{number}{source.suffix}"
                number += 1
        if not target.exists():
            shutil.copy2(str(source), str(target))
        return target.name

    def add_photos(self, sources) -> List[str]:
        """選んだ写真を号の「写真」へ写し、保存名を返す。"""
        return [self.keep_writer_photo(Path(source)) for source in sources]

    def photo_files(self) -> List[dict]:
        """「写真」内のファイルを、一覧表示に必要な情報とともに返す。"""
        folder = self.folder / "写真"
        folder.mkdir(exist_ok=True)
        items = []
        for path in sorted((p for p in folder.iterdir()
                            if p.is_file() and not p.name.startswith(".")),
                           key=lambda p: p.name.casefold()):
            ext = path.suffix.lower().lstrip(".")
            kind = "jpeg" if ext in ("jpg", "jpeg") else ext
            pixels = None
            message = ""
            if kind in ("png", "jpeg"):
                try:
                    pixels = dx.image_size(path.read_bytes(), kind)
                except (OSError, ValueError):
                    message = "画像を読み取れません。JPEG か PNG に変えてください"
            elif kind == "heic" and sys.platform == "darwin":
                # Mac の画面見本は sips で PNG に変換できる。画素数は変換後に表示する。
                message = ""
            else:
                message = "JPEG か PNG に変えてください"
            items.append({"name": path.name, "path": path, "kind": kind,
                          "pixels": pixels, "message": message})
        return items

    def _source_parts(self, page: dict) -> List[I.Part]:
        if not page.get("source"):
            return []
        result = self._ingest(page["source"])
        return C.apply_kind_overrides(result.parts, self._overrides(page))

    def _placed_start(self, page: dict) -> int:
        return len(self._source_parts(page))

    def _placed_part(self, page: dict, part_no: int):
        """部品番号が置いた写真なら (一覧番号, 写真データ) を返す。"""
        offset = part_no - self._placed_start(page)
        if offset >= 0 and offset % 2 == 0:
            index = offset // 2
            photos = page.get("placed_photos", [])
            if index < len(photos):
                return index, photos[index]
        return None

    def _placed_parts(self, page: dict) -> List[I.Part]:
        parts = []
        for photo in page.get("placed_photos", []):
            parts.append(I.Part("写真", sure=True, reason="写真フォルダから配置",
                                image=photo.get("file"), photo_size=photo.get("size")))
            parts.append(I.Part("写真説明", str(photo.get("caption", "")), True,
                                "写真フォルダから配置"))
        return parts

    def _all_overrides(self, page: dict) -> Dict[int, dict]:
        overrides = self._overrides(page)
        start = self._placed_start(page)
        for index, photo in enumerate(page.get("placed_photos", [])):
            existing = overrides.get(start + index * 2, {})
            overrides[start + index * 2] = {
                "rect": _rect(photo.get("rect")), "size": photo.get("size"),
                "removed": bool(photo.get("removed", False)), "kind": None,
                "space_before": existing.get("space_before", 0)}
        return overrides

    def _all_images(self, page: dict) -> Dict[str, bytes]:
        images = dict(self._ingest(page["source"]).images) if page.get("source") else {}
        for photo in page.get("placed_photos", []):
            name = photo.get("file", "")
            path = self.folder / "写真" / Path(name).name
            if name and path.is_file():
                images[name] = path.read_bytes()
        return images

    def place_photo(self, page_no: int, filename: str, rect: Rect) -> bool:
        """写真フォルダの写真を格子位置へ置く。重なる場合は何も変えない。"""
        page = self._page(page_no)
        name = Path(filename).name
        if not (self.folder / "写真" / name).is_file():
            raise ValueError("写真フォルダに写真が見つかりません: " + name)
        size = "顔" if page["section"] == layout.IPPAN else "中"
        target = C.photo_rect(self.geometry, size, rect.dan, rect.line)
        if page["section"] == layout.COVER:
            target = Rect(0, 4, 3, 22)
        elif page["section"] == layout.LAST:
            photos = [p for p in page["placed_photos"] if not p.get("removed")]
            if len(photos) >= 2:
                raise ValueError("編集後記の写真は2枚までです")
            target = Rect(0, 5 + len(photos) * 8, 1, 7)
            size = "小"
        if page["section"] not in (layout.COVER, layout.LAST):
            if not self._can_place(page_no, -1, target):
                return False
        before = self._state()
        if page["section"] == layout.COVER:
            page["placed_photos"] = []
        page["placed_photos"].append({"file": name, "rect": _rect_data(target),
                                      "size": size, "caption": "", "removed": False})
        self._sync_form_from_placed(page)
        self._update_page_state(page_no)
        self._record(f"{page_no}ページに{name}を置く", before)
        return True

    def set_photo_caption(self, page_no: int, part_no: int, caption: str) -> None:
        """置いた写真の説明を保存する。"""
        page = self._page(page_no)
        found = self._placed_part(page, part_no)
        if found is None:
            raise ValueError("写真フォルダから置いた写真を選んでください")
        before = self._state()
        found[1]["caption"] = str(caption)
        self._sync_form_from_placed(page)
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真説明を直す", before)

    def _sync_form_from_placed(self, page: dict) -> None:
        """表紙・編集後記の従来入力欄を、置いた写真と同じ内容にする。"""
        if "form" not in page:
            return
        active = [p for p in page.get("placed_photos", []) if not p.get("removed")]
        if page["section"] == layout.COVER:
            photo = active[-1] if active else None
            page["form"]["photo"] = (str(self.folder / "写真" / photo["file"])
                                      if photo else "")
            page["form"]["photo_caption"] = photo.get("caption", "") if photo else ""
        elif page["section"] == layout.LAST:
            page["form"]["editorial_photos"] = [
                {"path": str(self.folder / "写真" / p["file"]),
                 "caption": p.get("caption", "")} for p in active[:2]]

    def _overrides(self, page: dict) -> Dict[int, dict]:
        out = {}
        for key, value in page.get("overrides", {}).items():
            out[int(key)] = {"rect": _rect(value.get("rect")),
                             "size": value.get("size"),
                             "removed": bool(value.get("removed", False)),
                             "kind": value.get("kind"),
                             "space_before": max(0, int(value.get("space_before", 0) or 0))}
        return out

    def parts(self, page_no: int) -> List[I.Part]:
        """画面表示用に、人が直した種類を反映した部品を返す。"""
        page = self._page(page_no)
        return self._source_parts(page) + self._placed_parts(page)

    def _compose_page(self, page_no: int) -> C.PageResult:
        page = self._page(page_no)
        if "form" in page:
            self._sync_form_from_placed(page)
            result = templates.build(page["section"], page["form"], self.issue,
                                     self.plan, self.settings, self.geometry)
            # 表紙と編集後記は従来の専用枠に入る。選択・写真一覧のため、
            # 同じ写真を格子上の配置としても返す。
            start = self._placed_start(page)
            if page["section"] in (layout.COVER, layout.LAST):
                for index, photo in enumerate(page.get("placed_photos", [])):
                    if not photo.get("removed"):
                        result.placements.append(C.Placement(
                            self._placed_parts(page)[index * 2], _rect(photo["rect"]),
                            start + index * 2))
                return result
            # 審議ページなどの書き込み式ページでも、選んだ格子へ写真を重ねる。
            placed = self._placed_parts(page)
            if placed:
                overlay = C.compose_page(page["section"], placed,
                                         self._all_images(page), self.geometry,
                                         {index: change for index, change in
                                          ((i - start, v) for i, v in self._all_overrides(page).items())
                                          if index >= 0})
                result.page.items.extend(item for item in overlay.page.items
                                         if isinstance(item, (dx.Picture, dx.Placeholder)))
                result.placements.extend(C.Placement(p.part, p.rect, p.index + start)
                                         for p in overlay.placements if p.part.kind == "写真")
                result.warnings.extend(overlay.warnings)
            return result
        incoming = self._incoming_parts(page_no)
        parts = incoming + self.parts(page_no)
        shift = len(incoming)
        overrides = {index + shift: value
                     for index, value in self._all_overrides(page).items()}
        images = self._all_images(page)
        for part in incoming:
            if part.image and part.image not in images:
                path = self.folder / "写真" / Path(part.image).name
                if path.is_file():
                    images[part.image] = path.read_bytes()
        result = C.compose_page(page["section"], parts, images,
                                self.geometry, overrides)
        # 前ページから来た部品は選択対象にせず、このページ自身の番号は従来どおりに保つ。
        for placement in result.placements:
            placement.index = placement.index - shift if placement.index >= shift else -1
        return result

    def _incoming_parts(self, page_no: int) -> List[I.Part]:
        """直前ページから送られた、まだ紙面に入っていない部品・行を返す。"""
        if page_no <= 1:
            return []
        previous = self._page(page_no - 1)
        current = self._page(page_no)
        if (not previous.get("flow_to_next")
                or previous["section"] != current["section"]):
            return []
        return self._compose_page(page_no - 1).overflow_parts

    def can_flow_to_next(self, page_no: int) -> tuple:
        """次ページ送りを選べるかを、理由とともに返す。"""
        page = self._page(page_no)
        if page["section"] not in FLOW_SECTIONS:
            return False, f"{page['section']}は次のページへ送れません。"
        if page_no >= len(self.pages):
            return False, "次のページがありません。"
        following = self._page(page_no + 1)
        if following["section"] != page["section"]:
            return False, (f"次のページは「{following['section']}」です。"
                           "同じ区分のページにだけ送れます。")
        return True, ""

    def set_flow_to_next(self, page_no: int, enabled: bool) -> None:
        """このページのあふれを、同じ区分の次ページへ送るか保存する。"""
        page = self._page(page_no)
        if enabled:
            allowed, reason = self.can_flow_to_next(page_no)
            if not allowed:
                raise ValueError(reason)
        before = self._state()
        page["flow_to_next"] = bool(enabled)
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの次ページ送りを{'入' if enabled else '切'}にする", before)

    def change_space_before(self, page_no: int, part_no: int, delta: int) -> int:
        """部品前の空き行を増減し、現在値を返す。"""
        parts = self.parts(page_no)
        if not 0 <= part_no < len(parts):
            raise ValueError(f"部品番号が正しくありません: {part_no + 1}")
        page = self._page(page_no)
        before = self._state()
        change = page["overrides"].setdefault(str(part_no), {})
        old = max(0, int(change.get("space_before", 0) or 0))
        new = max(0, old + int(delta))
        if new == old:
            return old
        change["space_before"] = new
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの部品{part_no + 1}前の空きを{new}行にする", before)
        return new

    def compose(self, page_no: int) -> C.PageResult:
        """指定ページを組み、現在の状態を更新する。"""
        page = self._page(page_no)
        if "form" in page:
            result = self._compose_page(page_no)
            page["state"] = "あふれ" if result.overflow_lines else (
                "できた" if self._form_has_input(page) else "未入力")
            self.save()
            return result
        if (not page["source"] and not page.get("placed_photos")
                and not self._incoming_parts(page_no)):
            return C.compose_page(page["section"], [], {}, self.geometry)
        result = self._compose_page(page_no)
        page["state"] = ("できた" if page.get("flow_to_next") and result.overflow_lines
                         else "あふれ" if result.overflow_lines else "できた")
        self.save()
        return result

    @staticmethod
    def _form_has_input(page: dict) -> bool:
        """既定の決まり文句以外に、利用者が入力した欄があるか。"""
        current = page.get("form", {})
        default = templates.default_form(page["section"])
        return any(value not in ("", [], None) and value != default.get(key)
                   for key, value in current.items())

    def set_form(self, page_no: int, form: dict) -> None:
        """書き込み式ページの入力を保存し、元に戻す履歴へ記録する。"""
        page = self._page(page_no)
        if "form" not in page:
            raise ValueError("このページは書き込み式ではありません")
        before = self._state()
        values = templates.default_form(page["section"])
        values.update(copy.deepcopy(form))
        page["form"] = values
        self._sync_placed_from_form(page)
        result = self._compose_page(page_no)
        page["state"] = "あふれ" if result.overflow_lines else (
            "できた" if self._form_has_input(page) else "未入力")
        self._record(f"{page_no}ページの入力欄を直す", before)

    def _sync_placed_from_form(self, page: dict) -> None:
        """従来の写真入力欄で選んだ写真も、置いた写真へ取り込む。"""
        values = []
        if page["section"] == layout.COVER and page["form"].get("photo"):
            values = [(page["form"]["photo"], page["form"].get("photo_caption", ""),
                       "中", Rect(0, 4, 3, 22))]
        elif page["section"] == layout.LAST:
            values = [(p.get("path", ""), p.get("caption", ""), "小",
                       Rect(0, 5 + index * 8, 1, 7))
                      for index, p in enumerate(page["form"].get("editorial_photos", [])[:2])]
        if not values:
            return
        current = [(p.get("file"), p.get("caption", ""))
                   for p in page.get("placed_photos", []) if not p.get("removed")]
        wanted = [(Path(str(path)).name, str(caption)) for path, caption, _s, _r in values]
        if current == wanted:
            self._sync_form_from_placed(page)
            return
        photos = []
        for path_value, caption, size, rect in values:
            path = Path(str(path_value))
            if path.is_file():
                name = self.keep_writer_photo(path)
            else:
                name = path.name
            photos.append({"file": name, "rect": _rect_data(rect), "size": size,
                           "caption": str(caption), "removed": False})
        page["placed_photos"] = photos
        self._sync_form_from_placed(page)

    def copy_forms_from(self, other_folder: Path) -> None:
        """前号の書き込み欄を写し、号ごとの内容だけ空に戻す。"""
        other = Edition.open(other_folder)
        before = self._state()
        old = {(page["section"], page["index"]): page for page in other.pages}
        for page in self.pages:
            if "form" not in page:
                continue
            previous = old.get((page["section"], page["index"]))
            if previous and "form" in previous:
                page["form"] = templates.copied_form(page["section"], previous["form"])
                page["state"] = "未入力"
        self._record("前の号から書き込み欄を写す", before)

    def set_kind(self, page_no: int, part_no: int, kind: str) -> None:
        """部品の種類を人の判断で直し、操作履歴へ記録する。"""
        if kind not in I.KINDS:
            raise ValueError("部品の種類が正しくありません: " + kind)
        page = self._page(page_no)
        if self._placed_part(page, part_no) is not None:
            raise ValueError("写真フォルダから置いた写真の種類は変更できません")
        if not page["source"]:
            raise ValueError("原稿が未入力です")
        result = self._ingest(page["source"])
        if not 0 <= part_no < len(result.parts):
            raise ValueError(f"部品番号が正しくありません: {part_no + 1}")
        before = self._state()
        change = page["overrides"].setdefault(str(part_no), {})
        change["kind"] = kind
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの部品{part_no + 1}を{kind}にする", before)

    def _can_place(self, page_no: int, part_no: int, rect: Rect) -> bool:
        if (rect.dan < 0 or rect.line < 0
                or rect.dan + rect.dan_span > self.geometry.dans
                or rect.line + rect.line_span > self.geometry.lines_per_dan):
            return False
        page = self._page(page_no)
        occupied = list(layout.fixed_areas(page["section"], self.geometry).values())
        # 本文は置いた後に流し直せるが、ほかの写真・大見出しとは重ねない。
        if page["source"] or page.get("placed_photos"):
            current = self._compose_page(page_no)
            occupied.extend(p.rect for p in current.placements
                            if p.index != part_no and p.part.kind in ("写真", "大見出し"))
        for key, change in self._overrides(page).items():
            if key != part_no and not change["removed"] and change["rect"] is not None:
                occupied.append(change["rect"])
        return not any(rect.overlaps(other) for other in occupied)

    def move_part(self, page_no: int, part_no: int, rect: Rect) -> bool:
        """写真・大見出しを動かす。置けない場所なら変更しない。"""
        parts = self.parts(page_no)
        if not 0 <= part_no < len(parts) or parts[part_no].kind not in ("写真", "大見出し"):
            raise ValueError("動かせるのは写真と大見出しだけです")
        if not self._can_place(page_no, part_no, rect):
            return False
        before = self._state()
        placed = self._placed_part(self._page(page_no), part_no)
        if placed is not None:
            placed[1]["rect"] = _rect_data(rect)
            placed[1]["removed"] = False
            self._sync_form_from_placed(self._page(page_no))
            self._update_page_state(page_no)
            self._record(f"{page_no}ページの写真を動かす", before)
            return True
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
        parts = self.parts(page_no)
        if not 0 <= part_no < len(parts) or parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        page = self._page(page_no)
        if page["section"] == layout.COVER:
            raise ValueError("表紙の写真は、紙面いっぱいの決まった大きさです。大きさは変えられません。")
        if page["section"] == layout.LAST:
            raise ValueError("編集後記の写真は、決まった大きさ（小）です。大きさは変えられません。")
        placed = self._placed_part(page, part_no)
        if placed is not None:
            old_rect = _rect(placed[1].get("rect"))
            new_rect = C.photo_rect(self.geometry, size, old_rect.dan, old_rect.line)
            if not self._can_place(page_no, part_no, new_rect):
                return False
            before = self._state()
            placed[1]["size"] = size
            placed[1]["rect"] = _rect_data(new_rect)
            placed[1]["removed"] = False
            self._sync_form_from_placed(page)
            self._update_page_state(page_no)
            self._record(f"{page_no}ページの写真を{size}にする", before)
            return True
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
        parts = self.parts(page_no)
        if not 0 <= part_no < len(parts) or parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        before = self._state()
        placed = self._placed_part(self._page(page_no), part_no)
        if placed is not None:
            placed[1]["removed"] = True
            self._sync_form_from_placed(self._page(page_no))
            self._update_page_state(page_no)
            self._record(f"{page_no}ページの写真を外す", before)
            return
        change = self._page(page_no)["overrides"].setdefault(str(part_no), {})
        change["removed"] = True
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真{part_no + 1}を外す", before)

    def restore_photo(self, page_no: int, part_no: int) -> None:
        """外した写真を紙面へ戻す。"""
        parts = self.parts(page_no)
        if not 0 <= part_no < len(parts) or parts[part_no].kind != "写真":
            raise ValueError("写真の部品を選んでください")
        before = self._state()
        placed = self._placed_part(self._page(page_no), part_no)
        if placed is not None:
            placed[1]["removed"] = False
            self._sync_form_from_placed(self._page(page_no))
            self._update_page_state(page_no)
            self._record(f"{page_no}ページの写真を戻す", before)
            return
        change = self._page(page_no)["overrides"].setdefault(str(part_no), {})
        change["removed"] = False
        self._update_page_state(page_no)
        self._record(f"{page_no}ページの写真{part_no + 1}を戻す", before)

    def _update_page_state(self, page_no: int) -> None:
        section = self._page(page_no)["section"]
        for current_no in range(page_no, len(self.pages) + 1):
            page = self._page(current_no)
            if page["section"] != section:
                break
            incoming = self._incoming_parts(current_no)
            if "form" in page:
                result = self._compose_page(current_no)
                page["state"] = "あふれ" if result.overflow_lines else (
                    "できた" if self._form_has_input(page) else "未入力")
            elif page["source"] or page.get("placed_photos") or incoming:
                result = self._compose_page(current_no)
                page["state"] = ("できた" if page.get("flow_to_next") and result.overflow_lines
                                 else "あふれ" if result.overflow_lines else "できた")
            else:
                page["state"] = "未入力"

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
                page["placed_photos"] = previous.get("placed_photos", [])
                page["flow_to_next"] = previous.get("flow_to_next", False)
                page["state"] = previous["state"]
                if "writer_text" in previous:
                    page["writer_text"] = previous["writer_text"]
                if "form" in previous and "form" in page:
                    page["form"] = previous["form"]
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

    def _photo_position(self, box) -> str:
        """任意の写真枠を、最も近い段と右端からの行で表す。"""
        g = self.geometry
        top = g.margin_top_mm * 72 / 25.4
        right = (g.page_w_mm - g.margin_right_mm) * 72 / 25.4
        dan = round((box.y - top) / (g.dan_h_pt + g.gap_pt)) + 1
        line = round((right - (box.x + box.w)) / g.line_pitch_pt) + 1
        return f"{max(1, dan)}段目・右から{max(1, line)}行目"

    @staticmethod
    def _photo_dimensions(item, fallback_box) -> tuple:
        box = item.box if item is not None else fallback_box
        try:
            width, height = dx.picture_size(item) if isinstance(item, dx.Picture) else (box.w, box.h)
        except ValueError:
            width, height = box.w, box.h
        return width * 25.4 / 72, height * 25.4 / 72

    def _photo_records(self, write_files: bool = False) -> tuple:
        """全ページの配置済み写真を集め、必要なら元画像も出力する。"""
        records = []
        written = []
        photo_output = self.folder / "出力" / "写真"
        if write_files:
            photo_output.mkdir(parents=True, exist_ok=True)
        for page in self.pages:
            result = self.compose(page["no"])
            entries = []
            if "form" in page:
                if page["section"] == layout.COVER and page["form"].get("photo"):
                    entries.append((page["form"]["photo"], "表紙",
                                    str(page["form"].get("photo_caption", "")), "表紙写真"))
                elif page["section"] == layout.LAST:
                    for number, value in enumerate(page["form"].get("editorial_photos", []) or [], 1):
                        entries.append((value, "小", str(value.get("caption", "")),
                                        f"編集後記写真{number}"))
                form_entries = []
                for value, size, caption, label in entries:
                    path_value = value.get("path", "") if isinstance(value, dict) else value
                    item = next((part for part in result.page.items
                                 if isinstance(part, (dx.Picture, dx.Placeholder))
                                 and part.name == label), None)
                    if path_value and item is not None:
                        form_entries.append((Path(path_value).name, Path(path_value), size,
                                             caption, item.box, item,
                                             self._photo_position(item.box)))
                entries = form_entries
            elif page.get("source") or page.get("placed_photos"):
                parts = self.parts(page["no"])
                placed = {place.index: place for place in result.placements
                          if place.part.kind == "写真"}
                photo_no = 0
                normal_entries = []
                for index, part in enumerate(parts):
                    if part.kind != "写真":
                        continue
                    photo_no += 1
                    if index not in placed or not part.image:
                        continue
                    change = self._overrides(page).get(index, {})
                    size = change.get("size") or part.photo_size or (
                        "顔" if page["section"] == layout.IPPAN and photo_no == 1 else "中")
                    box = to_box(self.geometry, placed[index].rect)
                    item = next((value for value in result.page.items
                                 if isinstance(value, (dx.Picture, dx.Placeholder))
                                 and value.name == f"写真{photo_no}"), None)
                    source_path = self.folder / "写真" / Path(part.image).name
                    caption = C._caption(parts, index)
                    position = (f"{placed[index].rect.dan + 1}段目・"
                                f"右から{placed[index].rect.line + 1}行目")
                    normal_entries.append((Path(part.image).name, source_path, size,
                                           caption, box, item, position))
                entries = normal_entries
            for number, (original, source_path, size, caption, box, item, position) in enumerate(entries, 1):
                data = None
                ext = None
                try:
                    data = item.data if isinstance(item, dx.Picture) else source_path.read_bytes()
                    ext = C._image_ext(original, data)
                except (OSError, ValueError):
                    pass
                suffix = ".jpg" if ext == "jpeg" else ".png" if ext == "png" else Path(original).suffix
                output_name = f"p{page['no']:02d}_写真{number}{suffix}"
                pixels = None
                if data is not None and ext is not None:
                    try:
                        pixels = dx.image_size(data, ext)
                    except ValueError:
                        pass
                    if write_files:
                        target = photo_output / output_name
                        target.write_bytes(data)
                        written.append(target.resolve())
                width, height = self._photo_dimensions(item, box)
                records.append(photo_list.PhotoRecord(
                    page["no"], page["section"], output_name, original, size,
                    width, height, position, caption, pixels))
        return records, written

    def check(self) -> List[str]:
        """号全体で直す点・知らせる点を一覧にする。"""
        messages = ["× " + e for e in self.plan.errors]
        messages.extend("・" + n for n in self.plan.notes)
        for page in self.pages:
            prefix = f"{page['no']}ページ（{page['label']}）"
            if "form" in page:
                result = self.compose(page["no"])
                if page["state"] == "未入力":
                    messages.append(prefix + ": 入力欄が未入力です")
                if result.overflow_lines:
                    messages.append(prefix + f": {result.overflow_lines}行あふれています")
                messages.extend(prefix + ": " + w for w in result.warnings)
                continue
            incoming = self._incoming_parts(page["no"])
            if not page["source"] and not page.get("placed_photos") and not incoming:
                messages.append(prefix + ": 原稿が未入力です")
                continue
            ingested = self._ingest(page["source"]) if page.get("source") else None
            result = self.compose(page["no"])
            if result.overflow_lines and not page.get("flow_to_next"):
                messages.append(prefix + f": {result.overflow_lines}行あふれています")
            messages.extend(prefix + ": " + w for w in result.warnings)
            if ingested is not None:
                messages.extend(prefix + ": " + w for w in ingested.warnings)
            if page["section"] == layout.IPPAN and ingested is not None:
                messages.extend(prefix + ": " + w for w in I.check_ippan(ingested.parts))
        records, _written = self._photo_records()
        messages.extend(f"{item.page_no}ページ（{item.section}）: {item.output_name} {item.warning}"
                        for item in records if item.warning)
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
            if "form" in page_data:
                pages.append(self.compose(page_data["no"]).page)
                continue
            if not page_data["source"] and not page_data.get("placed_photos"):
                box = to_box(self.geometry, Rect(0, 0, 1, 10))
                pages.append(dx.Page([dx.TextBox(box, [page_data["label"]],
                                                  dx.GOTHIC, 18.0, 25.2,
                                                  True, True, "区分名")]))
                continue
            result = self.compose(page_data["no"])
            pages.append(result.page)
        docx = (output / f"第{self.issue.number}号.docx").resolve()
        dx.write_docx(docx, self.geometry, pages)
        records, written_photos = self._photo_records(write_files=True)
        photo_docx = (output / "写真配置一覧.docx").resolve()
        photo_list.write_photo_list(photo_docx, records, self.geometry)
        checklist = (output / "確認リスト.txt").resolve()
        messages = self.check()
        checklist.write_text("\n".join(messages) + ("\n" if messages else "問題はありません。\n"),
                             encoding="utf-8")
        return [docx, checklist, photo_docx] + written_photos
