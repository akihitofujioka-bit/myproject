"""Word 様式（.docx）へ原稿を差し込む。

議会だよりの様式は、本文・テキストボックス・表を組み合わせた
凝ったレイアウトになっている。python-docx はテキストボックスを
扱えないため、ここでは document.xml を直接操作する。

方針:
  * レイアウトには一切触らない。文字と画像の中身だけを入れ替える。
  * 差し込み先（スロット）は次の2通りで指定できる。
      1) 差し込みマーカー  {{記事1_本文}} のような文字列を様式に書いておく
      2) スロット番号      様式にある文字枠を自動で採番し、番号で指定する
  * 書式（フォント・サイズ・縦書き）は、その枠にもともとあった
    1つ目の run の書式を引き継ぐ。

前号の紙面をそのまま様式として使う運用（実際によくある）にも対応する。
"""

from __future__ import annotations

import copy
import re
import shutil
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V = "urn:schemas-microsoft-com:vml"

for _p, _u in (
    ("w", W), ("mc", MC), ("r", R), ("wp", WP), ("a", A), ("pic", PIC), ("v", V),
):
    ET.register_namespace(_p, _u)

MARKER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")

EMU_PER_CM = 360000


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


# ====================================================================== スロット


@dataclass
class Slot:
    """様式の中の差し込み先1か所。"""

    id: str
    kind: str  # marker / textbox / table / body
    name: str  # マーカー名、または自動採番名
    sample: str  # もともと入っている文字（前号の内容）
    chars: int
    para_count: int
    location: str  # 画面表示用の位置説明
    page_hint: int = 0
    vertical: bool = False
    guess: str = ""  # 見出し / 本文 / キャプション / 氏名

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Container:
    """様式の中の「枠」1つ。groups は同じ内容を持つ複製の集まり。"""

    kind: str  # textbox / table / body
    parent: ET.Element
    groups: list[list[ET.Element]]
    page: int = 1


def _para_text(p: ET.Element, *, skip_textboxes: bool = False) -> str:
    """段落の文字列。``skip_textboxes`` が真なら、段落内のテキストボックスの
    中身は含めない（本文とアンカーされた図の文字を混ぜないため）。"""
    skip: set[int] = set()
    if skip_textboxes:
        for tb in p.iter(q(W, "txbxContent")):
            for node in tb.iter():
                skip.add(id(node))
    parts = []
    for node in p.iter():
        if id(node) in skip:
            continue
        if node.tag == q(W, "t"):
            parts.append(node.text or "")
        elif node.tag in (q(W, "br"), q(W, "cr")):
            parts.append("\n")
        elif node.tag == q(W, "tab"):
            parts.append("\t")
    return "".join(parts)


def _has_page_break(p: ET.Element) -> bool:
    for br in p.iter(q(W, "br")):
        if br.get(q(W, "type")) == "page":
            return True
    for _ in p.iter(q(W, "lastRenderedPageBreak")):
        return True
    return False


def _image_ids(p: ET.Element) -> list[str]:
    """段落の中で参照されている画像の関係 ID を、出てくる順に返す。"""
    out: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == q(A, "blip"):                       # 新しい形式（DrawingML）
            rid = node.get(q(R, "embed")) or node.get(q(R, "link"))
            if rid:
                out.append(rid)
        elif tag == q(V, "imagedata"):                # 古い形式（VML）
            rid = node.get(q(R, "id"))
            if rid:
                out.append(rid)
    return out


def _textbox_groups(p: ET.Element) -> list[tuple[ET.Element, list[list[ET.Element]]]]:
    """段落の中にあるテキストボックスを取り出す。

    AlternateContent の Choice / Fallback は同じ内容の複製なので、
    1つの枠として束ね、グループに分けて返す。
    """
    out: list[tuple[ET.Element, list[list[ET.Element]]]] = []
    seen: set[int] = set()

    for alt in p.iter(q(MC, "AlternateContent")):
        groups: list[list[ET.Element]] = []
        for tb in alt.iter(q(W, "txbxContent")):
            seen.add(id(tb))
            paras = tb.findall(q(W, "p"))
            if paras:
                groups.append(paras)
        if groups:
            out.append((alt, groups))

    for tb in p.iter(q(W, "txbxContent")):
        if id(tb) in seen:
            continue
        paras = tb.findall(q(W, "p"))
        if paras:
            out.append((tb, [paras]))

    return out


def _guess_kind(text: str, para_count: int) -> str:
    """枠の中身から、見出しか本文かキャプションかを推測する。"""
    t = text.strip()
    n = len(t)
    if n == 0:
        return "空"
    if para_count >= 3 or n >= 120:
        return "本文"
    if n <= 6 and not t.endswith("。"):
        return "見出し"
    if re.fullmatch(r"[一-龥ぁ-んァ-ヶ﨑髙々\s　]{2,10}", t):
        return "氏名・見出し"
    if n <= 40 and not t.endswith("。"):
        return "キャプション"
    return "本文"


class DocxTemplate:
    """Word 様式を開き、スロットを検出して差し込む。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as z:
            self._names = z.namelist()
            self._blobs = {n: z.read(n) for n in self._names}
        self.root = ET.fromstring(self._blobs["word/document.xml"])
        self._slots: list[Slot] | None = None
        self._index: dict[str, list[ET.Element]] = {}

    # -------------------------------------------------------------- 検出

    def _containers(self) -> list[Container]:
        """様式を先頭から順に読み、差し込み可能な「枠」を洗い出す。

        文書順に1回だけ走査することで、スロットの並び順とページ番号の
        見当が実際の紙面と一致するようにしている。

        テキストボックスは mc:AlternateContent の中に Choice と Fallback の
        2つの複製が入っていることがある。両方を1つの枠として扱い、
        差し込み時は両方に同じ内容を書き込む（Word と LibreOffice の
        どちらで開いても同じ見た目になるようにするため）。
        """
        body = self.root.find(q(W, "body"))
        if body is None:
            return []

        out: list[Container] = []
        state = {"page": 1}
        buf: list[ET.Element] = []

        def flush_body() -> None:
            """ためた本文段落を1つの枠として確定する。"""
            while buf and not _para_text(buf[-1]).strip():
                buf.pop()
            if buf:
                out.append(Container("body", body, [list(buf)], state["page"]))
            buf.clear()

        def walk_para(p: ET.Element) -> None:
            # 段落の中にテキストボックスがあれば、先にそれを枠として取り出す
            inner = _textbox_groups(p)
            for parent, groups in inner:
                out.append(Container("textbox", parent, groups, state["page"]))
            if _has_page_break(p):
                flush_body()
                state["page"] += 1
            text = _para_text(p, skip_textboxes=True)
            if text.strip():
                buf.append(p)
            elif buf:
                # 空段落は本文の区切りとみなす
                flush_body()

        def walk_table(tbl: ET.Element) -> None:
            flush_body()
            for tc in tbl.iter(q(W, "tc")):
                paras = tc.findall(q(W, "p"))
                for p in paras:
                    for parent, groups in _textbox_groups(p):
                        out.append(Container("textbox", parent, groups, state["page"]))
                if paras:
                    out.append(Container("table", tc, [paras], state["page"]))

        for child in list(body):
            if child.tag == q(W, "p"):
                walk_para(child)
            elif child.tag == q(W, "tbl"):
                walk_table(child)
            else:
                flush_body()
        flush_body()

        return out

    def slots(self, *, refresh: bool = False) -> list[Slot]:
        """様式のスロット一覧。マーカーがあればそれを優先する。"""
        if self._slots is not None and not refresh:
            return self._slots

        slots: list[Slot] = []
        self._index = {}
        containers = self._containers()

        counters = {"textbox": 0, "table": 0, "body": 0}
        labels = {"textbox": "文字枠", "table": "表", "body": "本文"}

        for c in containers:
            joined = "\n".join(_para_text(p) for p in c.groups[0])
            markers = MARKER_RE.findall(joined)

            if markers:
                # --- マーカー方式: 様式に書かれた {{名前}} を差し込み先にする
                for name in markers:
                    sid = f"m:{name}"
                    if sid in self._index:
                        self._index[sid].extend(c.groups)
                        continue
                    self._index[sid] = list(c.groups)
                    slots.append(
                        Slot(
                            id=sid,
                            kind="marker",
                            name=name,
                            sample="",
                            chars=0,
                            para_count=len(c.groups[0]),
                            location=_location_label(c.kind, len(slots) + 1),
                            page_hint=c.page,
                            vertical=_is_vertical(c.parent),
                            guess=_guess_from_marker(name),
                        )
                    )
                continue

            # --- 自動採番方式: マーカーが無い様式でも枠を番号で指定できる
            counters[c.kind] += 1
            sid = f"{c.kind}:{counters[c.kind]}"
            self._index[sid] = list(c.groups)
            text = joined.strip()
            slots.append(
                Slot(
                    id=sid,
                    kind=c.kind,
                    name=f"{labels[c.kind]}{counters[c.kind]}",
                    sample=text[:200],
                    chars=len(re.sub(r"\s", "", text)),
                    para_count=len(c.groups[0]),
                    location=_location_label(c.kind, counters[c.kind]),
                    page_hint=c.page,
                    vertical=_is_vertical(c.parent),
                    guess=_guess_kind(text, len(c.groups[0])),
                )
            )

        self._slots = slots
        return slots

    # -------------------------------------------------------------- 差し込み

    def fill(self, values: dict[str, str]) -> None:
        """スロット ID → 差し込む文字列。

        マーカースロットはマーカー部分だけを置き換える。
        自動採番スロットは枠の中身をすべて入れ替える。
        """
        self.slots()
        for sid, value in values.items():
            groups = self._index.get(sid)
            if not groups:
                continue
            for paras in groups:
                if sid.startswith("m:"):
                    _replace_marker(paras, sid[2:], value)
                else:
                    _replace_block(paras, value)
        self._slots = None  # 中身が変わったので再検出させる

    # -------------------------------------------------------------- 画像

    def replace_image(self, media_name: str, data: bytes) -> None:
        """様式に入っている画像を、同じ枠のまま差し替える。

        枠のサイズ・位置・回り込みはそのまま。中身のバイト列だけを入れ替える。
        """
        target = f"word/media/{media_name}"
        if target not in self._blobs:
            raise KeyError(f"様式に {media_name} という画像はありません")
        self._blobs[target] = data

    def image_anchors(self) -> list[dict]:
        """様式の中で、画像がどの位置（何ページ目・何番目）にあるかを調べる。

        写真を記事のそばへ自動で置くために使う。同じ画像が複数の場所で
        使われている場合は、最初に出てきた位置を採用する。
        """
        rels = self._image_rels()
        body = self.root.find(q(W, "body"))
        if body is None:
            return []

        found: dict[str, dict] = {}
        page, order = 1, 0
        for para in body.iter(q(W, "p")):
            if _has_page_break(para):
                page += 1
            for rid in _image_ids(para):
                name = rels.get(rid)
                if not name or name in found:
                    continue
                order += 1
                found[name] = {"name": name, "page": page, "order": order}
        # 本文に出てこない画像（ヘッダなど）も一覧には残す
        for img in self.images():
            found.setdefault(img["name"], {"name": img["name"], "page": 0, "order": 999})
        return sorted(found.values(), key=lambda d: (d["order"], d["name"]))

    def _image_rels(self) -> dict[str, str]:
        """関係 ID → 画像ファイル名。"""
        raw = self._blobs.get("word/_rels/document.xml.rels")
        if not raw:
            return {}
        out: dict[str, str] = {}
        for rel in ET.fromstring(raw):
            target = rel.get("Target") or ""
            if "media/" in target:
                out[rel.get("Id") or ""] = Path(target).name
        return out

    def image_bytes(self, media_name: str) -> bytes | None:
        """様式に入っている画像のバイト列（差し替え前の確認・縦横比の判定用）。"""
        return self._blobs.get(f"word/media/{media_name}")

    def images(self) -> list[dict]:
        """様式に入っている画像の一覧。"""
        out = []
        for n in self._names:
            if n.startswith("word/media/"):
                out.append({"name": Path(n).name, "path": n, "size": len(self._blobs[n])})
        return out

    # -------------------------------------------------------------- 保存

    def save(self, out_path: Path | str) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._blobs["word/document.xml"] = ET.tostring(
            self.root, encoding="UTF-8", xml_declaration=True
        )
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            # [Content_Types].xml は先頭に置くのが安全
            order = sorted(self._blobs, key=lambda n: (n != "[Content_Types].xml", n))
            for name in order:
                z.writestr(name, self._blobs[name])
        return out_path


# ====================================================================== 補助


def _is_vertical(el: ET.Element) -> bool:
    for node in el.iter():
        if node.tag == q(W, "textDirection"):
            if (node.get(q(W, "val")) or "").startswith("tb"):
                return True
        if node.tag == q(A, "bodyPr") and node.get("vert", "").startswith("eaVert"):
            return True
    return False


def _location_label(kind: str, n: int) -> str:
    return {"textbox": "テキストボックス", "table": "表のセル", "body": "本文"}.get(kind, kind) + f" #{n}"


def _guess_from_marker(name: str) -> str:
    for key, val in (
        ("見出し", "見出し"), ("題", "見出し"), ("タイトル", "見出し"),
        ("本文", "本文"), ("記事", "本文"),
        ("写真", "写真"), ("画像", "写真"),
        ("説明", "キャプション"), ("キャプション", "キャプション"),
        ("氏名", "氏名"), ("名前", "氏名"), ("議員", "氏名"),
    ):
        if key in name:
            return val
    return ""


def _first_rpr(paras: list[ET.Element]) -> ET.Element | None:
    """最初の run の書式（フォント・サイズなど）を取り出す。"""
    for p in paras:
        for r in p.findall(q(W, "r")):
            rpr = r.find(q(W, "rPr"))
            if rpr is not None:
                return copy.deepcopy(rpr)
    for p in paras:
        ppr = p.find(q(W, "pPr"))
        if ppr is not None:
            rpr = ppr.find(q(W, "rPr"))
            if rpr is not None:
                return copy.deepcopy(rpr)
    return None


def _make_run(text: str, rpr: ET.Element | None) -> ET.Element:
    r = ET.Element(q(W, "r"))
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = ET.SubElement(r, q(W, "t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return r


def _clear_runs(p: ET.Element) -> None:
    for child in list(p):
        if child.tag != q(W, "pPr"):
            p.remove(child)


def _replace_block(paras: list[ET.Element], value: str) -> None:
    """段落のかたまり（1つの枠の中身）を、新しい本文で置き換える。

    元の段落要素を使い回すことで、字下げ・行間・縦書きなどの
    段落書式をそのまま保つ。段落数が足りなければ最後の段落に
    改行でまとめ、余ったら中身を空にする（枠や段落自体は消さない）。
    """
    if not paras:
        return
    rpr = _first_rpr(paras)
    lines = value.split("\n") if value else [""]
    n = len(paras)

    for i, p in enumerate(paras):
        _clear_runs(p)
        if i >= len(lines):
            continue
        if i == n - 1 and len(lines) > n:
            # あふれたぶんは最後の段落に改行でまとめる
            for j, ln in enumerate(lines[i:]):
                if j:
                    br = ET.SubElement(p, q(W, "r"))
                    if rpr is not None:
                        br.append(copy.deepcopy(rpr))
                    ET.SubElement(br, q(W, "br"))
                if ln:
                    p.append(_make_run(ln, rpr))
        elif lines[i]:
            p.append(_make_run(lines[i], rpr))


def _replace_marker(paras: list[ET.Element], name: str, value: str) -> None:
    """{{name}} を含む run のテキストだけを差し替える。

    マーカーが複数の run にまたがっている場合にも対応するため、
    段落単位で文字列を組み立て直してから書き戻す。
    """
    marker = "{{" + name + "}}"
    lines = value.split("\n")
    for p in paras:
        text = _para_text(p)
        # 空白を許容した表記ゆれも拾う
        norm = MARKER_RE.sub(lambda m: "{{" + m.group(1) + "}}", text)
        if marker not in norm:
            continue
        rpr = _first_rpr([p])
        replaced = norm.replace(marker, "\x00".join(lines))
        _clear_runs(p)
        for j, part in enumerate(replaced.split("\x00")):
            if j:
                br = ET.SubElement(p, q(W, "r"))
                if rpr is not None:
                    br.append(copy.deepcopy(rpr))
                ET.SubElement(br, q(W, "br"))
            if part:
                p.append(_make_run(part, rpr))


# ====================================================================== 変換


def docx_to_pdf(docx_path: Path | str, outdir: Path | str) -> Path | None:
    """PDF にする（校正刷りの確認用）。Word → LibreOffice の順に試す。

    どちらも無ければ None。呼び出し側は「PDF は作れなかったが Word は
    できている」と伝えること。行き止まりにしない。
    """
    from .importers import convert_to_pdf_with_word, convert_with_soffice

    out = convert_to_pdf_with_word(docx_path) or convert_with_soffice(docx_path, "pdf")
    if out is None:
        return None
    dest = Path(outdir) / out.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, dest)
    return dest
