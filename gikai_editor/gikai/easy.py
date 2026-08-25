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


# ---------------------------------------------------------------- 名前を変える

# 議員から届く原稿は名前がばらばら（「原稿.docx」「森下.docx」など）。
# 載せる順番は先頭の番号で決まり、写真は原稿と同じ名前で結びつくので、
# 名前をそろえる作業がどうしても要る。エクスプローラーへ行かずに
# 画面から済ませられるようにする。


def _safe_file(name: str) -> str:
    """ファイル名に使えない文字を落とす。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name or "")).strip(" .")
    return name[:120]


def _find(project, rel: str) -> Path:
    """`05_一般質問/森下けい子.docx` を実際の場所に直す。

    原稿フォルダの外に出ないことを必ず確かめる。
    """
    base = inbox_dir(project).resolve()
    target = (base / rel).resolve()
    if not str(target).startswith(str(base)) or not target.is_file():
        raise ValueError(f"{rel} が見つかりません。")
    if target.name == README_NAME:
        raise ValueError("説明のファイルは変えられません。")
    return target


def _folder_of(project, section_id: str) -> str:
    for f in folders(project):
        if f["id"] == section_id:
            return f["folder"]
    raise ValueError("その区分はありません。")


def _retag(project, old_rel: str, new_rel: str) -> None:
    """名前を変えたことを、取り込み済みの記事・写真にも反映する。

    ここを直しておかないと、次に作り直したときに「消えた」「新しく入った」
    と見なされ、写真との結びつきが切れる。
    """
    for art in project.articles():
        if art.origin == old_rel:
            art.origin = new_rel
            art.source_file = Path(new_rel).name
            project.put_article(art)
    for ph in project.photos():
        if ph.origin == old_rel:
            ph.origin = new_rel
            project.put_photo(ph)


def rename(project, rel: str, new_name: str, *,
           section_id: str = "", with_photos: bool = False) -> dict:
    """原稿や写真の名前を変える（区分の移動もここで行う）。

    区分を変えるのは「別のフォルダへ移す」ことなので、名前を変えるのと
    同じ操作になる。画面の窓口を1つで済ませられる。
    """
    src = _find(project, rel)
    folder = src.parent.name
    new_folder = _folder_of(project, section_id) if section_id else folder

    name = _safe_file(new_name)
    if not name:
        raise ValueError("新しい名前を入れてください。")
    if not Path(name).suffix:
        name += src.suffix           # 拡張子は付け忘れても困らないように
    if Path(name).suffix.lower() != src.suffix.lower():
        raise ValueError(
            f"種類（{src.suffix}）は変えられません。名前だけを変えてください。")

    dest = inbox_dir(project) / new_folder / name
    if dest.resolve() == src.resolve():
        return {"renamed": [], "message": "同じ名前です。"}
    if dest.exists():
        raise ValueError(f"「{new_folder}」に {name} がすでにあります。"
                         "別の名前にしてください。")
    dest.parent.mkdir(parents=True, exist_ok=True)

    done = []
    # 原稿に付いている写真も、同じ名前にそろえる（そろえないと外れる）
    if with_photos and src.suffix.lower() in DOC_EXT:
        for img, num in _photos_for(project, src):
            tail = str(num) if num else ""
            iname = _safe_file(Path(name).stem + tail) + img.suffix
            idest = inbox_dir(project) / new_folder / iname
            if idest.exists() or idest.resolve() == img.resolve():
                continue
            img.rename(idest)
            _retag(project, f"{folder}/{img.name}", f"{new_folder}/{iname}")
            done.append({"from": f"{folder}/{img.name}",
                         "to": f"{new_folder}/{iname}"})

    src.rename(dest)
    _retag(project, f"{folder}/{src.name}", f"{new_folder}/{name}")
    done.insert(0, {"from": rel, "to": f"{new_folder}/{name}"})
    project.save()
    return {"renamed": done,
            "message": f"{len(done)} 件の名前を変えました。"}


def _photos_for(project, doc: Path) -> list[tuple[Path, int]]:
    """その原稿に結びついている写真（と末尾の連番）。"""
    from .autolayout import split_number

    d = doc.parent
    imgs = sorted([x for x in d.iterdir()
                   if x.is_file() and x.suffix.lower() in IMG_EXT], key=_sort_key)
    docs = sorted([x for x in d.iterdir()
                   if x.is_file() and x.suffix.lower() in DOC_EXT], key=_sort_key)
    mine = _match_photos(docs, imgs).get(doc.name, [])
    return [(img, split_number(img.stem)[1]) for img in mine]


UNUSED = "使わない写真"


def photo_plan(project) -> dict:
    """写真を原稿に割り当てるための材料を返す。

    議員から届く写真は `IMG_2451.jpg` `DSC00123.jpg` のように、原稿とは
    まったく違う名前で来る。名前で結びつける決まりにしている以上、
    どこかで人が「これは誰の写真か」を教えるしかない。

    そこで、**写真を見ながら原稿を選ぶだけ**で済むようにする。
    いま名前で結びついているものは初めから選んでおくので、
    ばらばらな名前のものだけを選べばよい。
    """
    out = []
    total = unmatched = 0
    for f in folders(project):
        d = Path(f["path"])
        if not d.is_dir():
            continue
        files = [x for x in d.iterdir() if x.is_file() and x.name != README_NAME]
        docs = sorted([x for x in files if x.suffix.lower() in DOC_EXT], key=_sort_key)
        imgs = sorted([x for x in files if x.suffix.lower() in IMG_EXT], key=_sort_key)
        if not imgs:
            continue

        # いま名前で結びついているもの（当てずっぽうではなく、実際の規則）
        matched = _match_photos(docs, imgs)
        owner: dict[str, str] = {}
        for doc_name, items in matched.items():
            for img in items:
                owner[img.name] = doc_name
        # 名前が本当に一致したものだけを「決まっている」とみなす。
        # 「区分の先頭に付ける」の救済で入ったものは、人に選び直してほしい
        from .autolayout import normalize_key, split_number

        keys = set()
        for doc in docs:
            for cand in (doc.stem, _strip_index(doc.stem),
                         split_number(_strip_index(doc.stem))[0]):
                keys.add(normalize_key(cand))
        leftovers = {
            img.name for img in imgs
            if not ({normalize_key(split_number(img.stem)[0]),
                     normalize_key(img.stem),
                     normalize_key(_strip_index(split_number(img.stem)[0]))} & keys)
        }

        rows = []
        for img in imgs:
            decided = img.name not in leftovers
            rows.append({
                "rel": f"{f['folder']}/{img.name}",
                "name": img.name,
                "doc": owner.get(img.name, "") if decided else "",
                "decided": decided,
            })
            total += 1
            if not decided:
                unmatched += 1
        out.append({"id": f["id"], "name": f["name"], "folder": f["folder"],
                    "docs": [x.name for x in docs], "photos": rows})
    return {"sections": out, "photos": total, "unmatched": unmatched}


def assign_photos(project, mapping: dict) -> dict:
    """「この写真はこの原稿」の対応どおりに、写真の名前をそろえる。

    原稿が `01_森下けい子.docx` なら、写真は `01_森下けい子.jpg`
    （複数なら `01_森下けい子1.jpg` `01_森下けい子2.jpg`）になる。
    「使わない」を選んだ写真は、区分フォルダの下の「使わない写真」へ
    よけておく。消さずによけるだけなので、あとから戻せる。
    """
    # 区分フォルダごとに、原稿→写真 の順番付きの一覧を作る
    per_folder: dict[str, dict[str, list[Path]]] = {}
    unused: list[Path] = []
    for rel, doc_name in (mapping or {}).items():
        img = _find(project, rel)
        if img.suffix.lower() not in IMG_EXT:
            raise ValueError(f"{img.name} は写真ではありません。")
        folder = img.parent.name
        if doc_name == UNUSED:
            unused.append(img)
            continue
        if not doc_name:
            continue                      # 触らない
        if not (img.parent / doc_name).is_file():
            raise ValueError(f"「{folder}」に {doc_name} がありません。")
        per_folder.setdefault(folder, {}).setdefault(doc_name, []).append(img)

    done: list[dict] = []
    tmp: list[tuple[Path, Path]] = []

    def stage(src: Path, dest: Path) -> None:
        if src.resolve() == dest.resolve():
            return
        holding = src.parent / f"__なまえ変更中__{src.name}"
        src.rename(holding)
        tmp.append((holding, dest))
        done.append({"from": f"{src.parent.name}/{src.name}",
                     "to": f"{dest.parent.name}/{dest.name}"})

    for folder, by_doc in per_folder.items():
        for doc_name, imgs in by_doc.items():
            imgs.sort(key=_sort_key)
            stem = Path(doc_name).stem
            for i, img in enumerate(imgs, 1):
                tail = "" if len(imgs) == 1 else str(i)
                stage(img, img.parent / f"{_safe_file(stem + tail)}{img.suffix}")

    for img in unused:
        box = img.parent / UNUSED
        box.mkdir(exist_ok=True)
        stage(img, box / img.name)

    for holding, dest in tmp:
        dest.parent.mkdir(parents=True, exist_ok=True)
        holding.rename(dest)
    for row in done:
        _retag(project, row["from"], row["to"])
    project.save()

    moved = len([x for x in done if UNUSED in x["to"]])
    return {
        "renamed": done,
        "message": (
            f"{len(done) - moved} 枚の名前をそろえました。"
            + (f"{moved} 枚を「{UNUSED}」へよけました。" if moved else "")
            if done else "変えるものはありませんでした。"),
    }


def photo_bytes(project, rel: str) -> tuple[bytes, str]:
    """割り当て画面に出す写真（原稿フォルダの中のもの）。"""
    import mimetypes

    img = _find(project, rel)
    if img.suffix.lower() not in IMG_EXT:
        raise ValueError(f"{img.name} は写真ではありません。")
    return img.read_bytes(), mimetypes.guess_type(img.name)[0] or "image/jpeg"


def renumber(project, section_id: str) -> dict:
    """1つの区分の原稿に、いまの並び順で 01_ 02_ … を振り直す。

    載せる順番を決めるのに、いちばんよく使う操作。写真の名前も
    そろえて付け替えるので、結びつきは切れない。
    """
    folder = _folder_of(project, section_id)
    d = inbox_dir(project) / folder
    if not d.is_dir():
        raise ValueError(f"{folder} フォルダがありません。")
    docs = sorted([x for x in d.iterdir()
                   if x.is_file() and x.suffix.lower() in DOC_EXT], key=_sort_key)
    if not docs:
        return {"renamed": [], "message": f"{folder} に原稿がありません。"}

    # 写真の結びつきは、名前を変える前に調べておく
    # （変えたあとでは、どの原稿の写真だったか分からなくなる）
    plan = []
    for i, doc in enumerate(docs, 1):
        want = f"{i:02d}_{_strip_index(doc.stem)}{doc.suffix}"
        plan.append((doc, want, _photos_for(project, doc)))

    # いったん仮の名前へ逃がしてから付け直す。
    # 直接付けると「02→01」のときに、すでにある 01 とぶつかる
    done = []
    tmp: list[tuple[Path, str]] = []

    def stage_move(path: Path, want: str) -> None:
        if path.name == want:
            return
        stage = d / f"__なまえ変更中__{path.name}"
        path.rename(stage)
        tmp.append((stage, want))
        done.append({"from": f"{folder}/{path.name}", "to": f"{folder}/{want}"})

    for doc, want, imgs in plan:
        stage_move(doc, want)
        # 写真も同じ番号に合わせる
        for img, num in imgs:
            tail = str(num) if num else ""
            stage_move(img, f"{Path(want).stem}{tail}{img.suffix}")

    for stage, want in tmp:
        stage.rename(d / want)

    for row in done:
        _retag(project, row["from"], row["to"])
    project.save()
    return {"renamed": done,
            "message": (f"{len(done)} 件の名前を変えました。"
                        if done else "すでに番号順になっています。")}


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
