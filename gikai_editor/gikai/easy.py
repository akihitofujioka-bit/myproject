"""かんたんモード — フォルダに入れて、ボタンひとつ。

細かい設定を覚えなくても1号ぶんを作れるようにするための道具立て。
考え方はひとつだけ。

    **フォルダの中身が、そのまま紙面になる。**

号のフォルダの中に、紙面の区分と同じ名前のフォルダを作る。

    第204号/原稿/
      01_表紙/
      02_行政報告/
      03_審議したこと・決まったこと/
      04_閉会中の委員会活動報告/
      05_一般質問/
      06_特集/
      07_最終ページ/

議員から届いた原稿と写真を、載せたい区分のフォルダへ入れる。
ファイル名の先頭に `01_` `02_` と番号を付ければ、その順に載る。
写真は、同じ名前の原稿に付く（`森下けい子.docx` ↔ `森下けい子.jpg`）。

あとは「議会だよりを作る」を押すだけ。区分の判定も割り付けも要らない。
**どのフォルダに入れたかが答えなので、当てずっぽうが入り込まない。**

作り直しは何度でもできる。同じフォルダからは必ず同じ紙面ができる
（`build` は毎回、取り込んだままの原稿から組み直す）。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from . import sections as sec
from .textutil import count_chars

INBOX = "原稿"

# 取り込む拡張子
DOC_EXT = {".docx", ".doc", ".txt", ".md", ".rtf", ".pdf", ".odt", ".csv"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic"}

README_NAME = "はじめにお読みください.txt"


def _safe_dir(name: str) -> str:
    """フォルダ名に使えない文字を落とす。"""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .") or "その他"


def folder_name(index: int, section: sec.Section) -> str:
    """`05_一般質問` のような、並び順が一目で分かる名前。"""
    return f"{index:02d}_{_safe_dir(section.name)}"


def inbox_dir(project) -> Path:
    return project.root / INBOX


def folders(project) -> list[dict]:
    """区分ごとのフォルダの一覧（無くても一覧には出す）。"""
    base = inbox_dir(project)
    out = []
    for i, s in enumerate(project.sections, 1):
        d = base / folder_name(i, s)
        out.append({
            "id": s.id,
            "name": s.name,
            "note": s.note,
            "optional": s.optional,
            "folder": folder_name(i, s),
            "path": str(d),
            "exists": d.is_dir(),
        })
    return out


def ensure_folders(project) -> dict:
    """区分ごとのフォルダを作る。すでにあるものはそのまま。

    中に置き場所の説明を1枚入れておく。フォルダを開いた人が、
    何を入れればよいかその場で分かるように。
    """
    base = inbox_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    made = []
    for f in folders(project):
        d = Path(f["path"])
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            made.append(f["folder"])
    _write_readme(project, base)
    return {"inbox": str(base), "made": made, "folders": folders(project)}


def _write_readme(project, base: Path) -> None:
    lines = [
        "議会だより 原稿編集ツール — 原稿の置き場所",
        "=" * 44,
        "",
        "この中の区分ごとのフォルダに、原稿と写真を入れてください。",
        "入れ終わったらツールの画面で「議会だよりを作る」を押します。",
        "",
        "・原稿  … Word(.docx / .doc)・テキスト・PDF・リッチテキスト",
        "・写真  … jpg / png など",
        "",
        "載せる順番",
        "  ファイル名の先頭に番号を付けると、その順に載ります。",
        "    01_あいさつ.docx",
        "    02_森下けい子.docx",
        "",
        "写真の付け方",
        "  原稿と同じ名前にすると、その記事に付きます。",
        "    森下けい子.docx  ←  森下けい子.jpg",
        "  複数あるときは 森下けい子1.jpg 森下けい子2.jpg（番号順）。",
        "  名前が合わない写真は、その区分の先頭の記事に付きます。",
        "",
        "作り直し",
        "  何度でも押せます。フォルダの中身がそのまま紙面になります。",
        "  フォルダから消したものは、紙面からも消えます。",
        "",
        "区分の一覧",
    ]
    for f in folders(project):
        opt = "（無い号もあります）" if f["optional"] else ""
        lines.append(f"  {f['folder']}  … {f['note']}{opt}")
    (base / README_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 中身を見る


def _stamp(p: Path) -> str:
    """更新日時と大きさ。差し替えられたかどうかの判定に使う。"""
    st = p.stat()
    return f"{int(st.st_mtime)}:{st.st_size}"


def _sort_key(p: Path) -> tuple:
    """`01_` のような先頭の番号を数として見て並べる。"""
    name = unicodedata.normalize("NFKC", p.stem)
    m = re.match(r"\s*(\d+)", name)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


def scan(project) -> dict:
    """フォルダに何が入っているかを数える（取り込みはしない）。"""
    out = []
    total_docs = total_imgs = 0
    for f in folders(project):
        d = Path(f["path"])
        docs = imgs = []
        if d.is_dir():
            files = [x for x in d.iterdir() if x.is_file() and x.name != README_NAME]
            docs = sorted([x for x in files if x.suffix.lower() in DOC_EXT], key=_sort_key)
            imgs = sorted([x for x in files if x.suffix.lower() in IMG_EXT], key=_sort_key)
        total_docs += len(docs)
        total_imgs += len(imgs)
        out.append({
            **f,
            "docs": [x.name for x in docs],
            "photos": [x.name for x in imgs],
        })
    return {"inbox": str(inbox_dir(project)), "sections": out,
            "docs": total_docs, "photos": total_imgs}


def hand_edited(project) -> list[str]:
    """画面で本文を直した記事の見出し。作り直す前の確認に出す。"""
    return [a.title or a.origin or a.id
            for a in project.articles() if a.hand_edited]


# ---------------------------------------------------------------- 組み立てる


def _strip_index(stem: str) -> str:
    """先頭の並び順の番号を外す。「01_森下けい子」→「森下けい子」。

    載せる順を決めるための番号なので、写真と突き合わせるときは邪魔になる。
    """
    s = unicodedata.normalize("NFKC", stem)
    return re.sub(r"^\s*\d+\s*[_\-.．・]?\s*", "", s) or stem


def _match_photos(docs: list[Path], imgs: list[Path]) -> dict[str, list[Path]]:
    """写真を原稿に結びつける。

    同じ名前なら、その原稿に付ける（`森下けい子.docx` ↔ `森下けい子2.jpg`）。
    並び順の番号（`01_`）は付いていても外して見るので、
    `01_森下けい子.docx` ↔ `森下けい子.jpg` でも結びつく。
    どれにも当てはまらない写真は、その区分の先頭の記事に付ける。
    """
    from .autolayout import normalize_key, split_number

    keys: dict[str, str] = {}
    for d in docs:
        for cand in (d.stem, _strip_index(d.stem), split_number(d.stem)[0],
                     split_number(_strip_index(d.stem))[0]):
            keys.setdefault(normalize_key(cand), d.name)

    out: dict[str, list[Path]] = {d.name: [] for d in docs}
    leftovers: list[Path] = []
    for img in imgs:
        base, _num = split_number(img.stem)
        target = None
        for cand in (base, img.stem, _strip_index(base), _strip_index(img.stem)):
            target = keys.get(normalize_key(cand))
            if target:
                break
        if target:
            out[target].append(img)
        else:
            leftovers.append(img)
    if leftovers and docs:
        out[docs[0].name] = leftovers + out[docs[0].name]
    return out


def build(project, *, max_pages: int = 0) -> dict:
    """フォルダの中身から、1号ぶんを組み立てる。

    1. フォルダを見て、増えた原稿を取り込み、消えた原稿を落とす
    2. 写真を原稿に結びつける
    3. 最大ページ数が決まっていれば、そこに収まるまで要約する
    4. 5段縦書きの Word に組む

    何をしたかは全部返す。黙って進めない。
    """
    report = {"added": [], "updated": [], "kept": [], "removed": [],
              "photos_added": [], "photos_removed": [], "skipped": []}

    scanned = scan(project)
    seen_docs: set[str] = set()
    seen_imgs: set[str] = set()

    by_origin = {a.origin: a for a in project.articles() if a.origin}
    ph_by_origin = {p.origin: p for p in project.photos() if p.origin}

    for grp in scanned["sections"]:
        d = Path(grp["path"])
        docs = [d / n for n in grp["docs"]]
        imgs = [d / n for n in grp["photos"]]
        photo_of = _match_photos(docs, imgs)

        for order, doc in enumerate(docs, 1):
            rel = f"{grp['folder']}/{doc.name}"
            seen_docs.add(rel)
            stamp = _stamp(doc)
            art = by_origin.get(rel)
            try:
                if art is None:
                    art = project.import_manuscript(doc)
                    report["added"].append(rel)
                elif art.origin_stamp != stamp:
                    # 原稿が差し替えられていたら読み直す
                    project.delete_article(art.id)
                    art = project.import_manuscript(doc)
                    report["updated"].append(rel)
                else:
                    report["kept"].append(rel)
            except Exception as e:
                # 1本読めなくても、残りは作れるようにする
                report["skipped"].append({"file": rel, "why": str(e)})
                continue

            art.origin = rel
            art.origin_stamp = stamp
            art.section = grp["id"]
            art.section_why = f"「{grp['folder']}」フォルダに入っていたため"
            art.order = order

            # 写真
            art.photos = []
            for img in photo_of.get(doc.name, []):
                irel = f"{grp['folder']}/{img.name}"
                seen_imgs.add(irel)
                istamp = _stamp(img)
                ph = ph_by_origin.get(irel)
                if ph is None or ph.origin_stamp != istamp:
                    if ph is not None:
                        project.delete_photo(ph.id)
                    try:
                        ph = project.import_photo(img)
                    except Exception as e:
                        report["skipped"].append({"file": irel, "why": str(e)})
                        continue
                    ph.origin = irel
                    ph.origin_stamp = istamp
                    project.put_photo(ph)
                    ph_by_origin[irel] = ph
                    report["photos_added"].append(irel)
                art.photos.append(ph.id)
            project.put_article(art)

    # フォルダから消えたものは、紙面からも消す
    for rel, art in by_origin.items():
        if rel not in seen_docs:
            project.delete_article(art.id)
            report["removed"].append(rel)
    for rel, ph in ph_by_origin.items():
        if rel not in seen_imgs:
            project.delete_photo(ph.id)
            report["photos_removed"].append(rel)

    project.save()

    # 手で直した本文を持ち越さない（同じフォルダからは同じ紙面ができるように）
    for art in project.articles():
        if art.origin and art.hand_edited:
            art.hand_edited = False
            project.put_article(art)

    # ページ数を合わせてから組む
    fit = {}
    if max_pages > 0:
        project.data["settings"]["target_pages"] = max_pages
        project.save()
        fit = project.fit_to_pages(max_pages)

    result = project.compose()
    return {
        "report": report,
        "fit": fit,
        "compose": result,
        "max_pages": max_pages,
        "outline": project.outline(),
        "counts": {"articles": len(project.articles()),
                   "photos": len(project.photos()),
                   "chars": sum(count_chars(a.body) for a in project.articles())},
    }
