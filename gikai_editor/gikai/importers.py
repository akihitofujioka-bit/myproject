"""議員から届いた原稿を、様式を問わず取り込む。

対応形式:
  .docx  標準 (zipfile + XML、外部ライブラリ不要)
  .doc   Word 97-2003 形式。追加ソフト無しで読める（doc97）
  .txt / .md / .csv  文字コードを自動判定して読む
  .rtf   簡易パーサ
  .pdf   PyMuPDF があればそれで、無ければ pypdf でテキスト抽出
  画像   ファイル名だけを取り込み、写真として登録

すべてローカル処理。ネットワークには接続しない。
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from . import doc97
from .textutil import normalize_manuscript, normalize_space

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

TEXT_EXT = {".txt", ".md", ".csv", ".text", ".dat"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic"}


@dataclass
class ImportedDoc:
    """取り込んだ原稿1件。"""

    source: str
    kind: str  # docx / doc / text / rtf / pdf / image
    text: str = ""
    title: str = ""
    author: str = ""
    images: list[dict] = field(default_factory=list)  # {name, data(bytes)}
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "kind": self.kind,
            "text": self.text,
            "title": self.title,
            "author": self.author,
            "images": [{"name": i["name"], "size": len(i["data"])} for i in self.images],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------- 文字コード

_ENCODINGS = ["utf-8-sig", "utf-8", "cp932", "euc_jp", "shift_jis", "iso2022_jp"]


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """日本語のテキストファイルの文字コードを推定してデコードする。"""
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # 化けの典型（私用領域や置換文字が多い）を弾く
        bad = sum(1 for ch in text if ch == "\ufffd" or 0xE000 <= ord(ch) <= 0xF8FF)
        if bad > len(text) * 0.01:
            continue
        return text, enc
    return raw.decode("utf-8", errors="replace"), "utf-8(置換あり)"


# ---------------------------------------------------------------- docx

def _docx_paragraph_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == f"{{{W_NS}}}t":
            parts.append(node.text or "")
        elif tag == f"{{{W_NS}}}tab":
            parts.append("\t")
        elif tag in (f"{{{W_NS}}}br", f"{{{W_NS}}}cr"):
            parts.append("\n")
    return "".join(parts)


def read_docx(path: Path | str, *, include_textboxes: bool = True) -> ImportedDoc:
    """.docx から本文を取り出す。テキストボックス内・表内の文字も拾う。"""
    path = Path(path)
    doc = ImportedDoc(source=path.name, kind="docx")
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        xml_targets = ["word/document.xml"]
        xml_targets += sorted(
            n for n in names if re.match(r"word/(header|footer)\d*\.xml$", n)
        )
        seen_para: set[int] = set()
        chunks: list[str] = []
        for target in xml_targets:
            if target not in names:
                continue
            root = ET.fromstring(z.read(target))
            for p in root.iter(f"{{{W_NS}}}p"):
                if id(p) in seen_para:
                    continue
                seen_para.add(id(p))
                t = _docx_paragraph_text(p)
                if t.strip():
                    chunks.append(t)
        doc.text = normalize_space("\n".join(chunks))

        # 埋め込み画像
        for n in sorted(names):
            if n.startswith("word/media/") and Path(n).suffix.lower() in IMAGE_EXT:
                doc.images.append({"name": Path(n).name, "data": z.read(n)})

        # 文書プロパティから題名・作成者
        if "docProps/core.xml" in names:
            core = ET.fromstring(z.read("docProps/core.xml"))
            for tag, attr in (("title", "title"), ("creator", "author")):
                el = next(
                    (e for e in core.iter() if e.tag.endswith("}" + tag)), None
                )
                if el is not None and (el.text or "").strip():
                    setattr(doc, attr, el.text.strip())

    if not include_textboxes:
        pass
    if not doc.text:
        doc.warnings.append("本文が取り出せませんでした。ファイルが空か、画像だけの可能性があります。")
    return doc


# ---------------------------------------------------------------- .doc (旧形式)

def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if Path(p).exists():
            return p
    return None


def convert_with_soffice(path: Path | str, to: str = "docx") -> Path | None:
    """LibreOffice を使ってファイルを変換する。無ければ None。"""
    soffice = _find_soffice()
    if not soffice:
        return None
    path = Path(path)
    outdir = Path(tempfile.mkdtemp(prefix="gikai_conv_"))
    profile = outdir / "profile"
    try:
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--norestore",
                "--convert-to",
                to,
                "--outdir",
                str(outdir),
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    out = outdir / (path.stem + "." + to.split(":")[0])
    return out if out.exists() else None


def convert_with_word(path: Path | str) -> Path | None:
    """Windows の Word 本体を使って .doc を .docx に変換する。

    役場のパソコンには Word が入っているので、LibreOffice を
    入れなくても様式を読み込めるようにするための道。
    Windows 以外、または Word が無い場合は None。
    """
    if sys.platform != "win32":
        return None
    path = Path(path).resolve()
    outdir = Path(tempfile.mkdtemp(prefix="gikai_word_"))
    out = outdir / (path.stem + ".docx")
    script = (
        "$ErrorActionPreference='Stop';"
        "$w=New-Object -ComObject Word.Application;"
        "$w.Visible=$false;$w.DisplayAlerts=0;"
        f"$d=$w.Documents.Open('{path}',$false,$true);"
        f"$d.SaveAs2('{out}',16);"
        "$d.Close($false);$w.Quit()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True, capture_output=True, timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return out if out.exists() else None


def convert_to_pdf_with_word(path: Path | str) -> Path | None:
    """Word で PDF にする（Windows のみ）。

    役場のパソコンには Word が入っている（議会だよりを Word で作っている）。
    LibreOffice は入っていないことが多いので、こちらを先に試す。
    刷り上がりに近いのも Word のほうなので、プレビューにはこちらが向く。
    """
    if sys.platform != "win32":
        return None
    path = Path(path).resolve()
    outdir = Path(tempfile.mkdtemp(prefix="gikai_pdf_"))
    out = outdir / (path.stem + ".pdf")
    script = (
        "$ErrorActionPreference='Stop';"
        "$w=New-Object -ComObject Word.Application;"
        "$w.Visible=$false;$w.DisplayAlerts=0;"
        f"$d=$w.Documents.Open('{path}',$false,$true);"
        f"$d.SaveAs2('{out}',17);"   # 17 = wdFormatPDF
        "$d.Close($false);$w.Quit()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True, capture_output=True, timeout=300,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return out if out.exists() else None


def convert_doc_to_docx(path: Path | str) -> Path | None:
    """.doc を .docx にする。Word → LibreOffice の順に試す。

    Word のほうがレイアウトの再現が正確なうえ、役場のパソコンには
    たいてい入っているため、そちらを先に試す。
    """
    return convert_with_word(path) or convert_with_soffice(path, "docx")


def read_doc(path: Path | str) -> ImportedDoc:
    """旧 .doc 形式（Word 97-2003）。

    まず自前の読み取り（doc97）で文字を取り出す。これは追加の
    ソフトを何も必要としないので、どのパソコンでも動く。
    うまくいかなかったときだけ、Word や LibreOffice での変換を試す。
    """
    path = Path(path)
    doc = ImportedDoc(source=path.name, kind="doc")

    try:
        text = doc97.extract_text(path)
    except (doc97.DocError, OSError, struct.error, ValueError, IndexError):
        text = ""

    if text.strip():
        doc.text = normalize_space(text)
        return doc

    # 自前で読めなかった場合の予備
    converted = convert_doc_to_docx(path)
    if converted:
        got = read_docx(converted)
        got.source = path.name
        got.kind = "doc"
        return got

    doc.warnings.append(
        "この .doc から文字を取り出せませんでした。"
        "Word で開いて「名前を付けて保存」→「Word 文書（.docx）」に"
        "してから取り込んでください。"
    )
    return doc


# ---------------------------------------------------------------- テキスト

def read_text(path: Path | str) -> ImportedDoc:
    path = Path(path)
    raw = path.read_bytes()
    text, enc = decode_bytes(raw)
    doc = ImportedDoc(source=path.name, kind="text", text=normalize_space(text))
    if "置換あり" in enc:
        doc.warnings.append(f"文字コードを判定できませんでした（{enc}）。文字化けがないか確認してください。")
    return doc


# ---------------------------------------------------------------- RTF

_RTF_UNI = re.compile(r"\\u(-?\d+)\s?\??")
_RTF_CTRL = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")


def read_rtf(path: Path | str) -> ImportedDoc:
    """簡易 RTF パーサ。書式は捨てて文字だけを取り出す。"""
    path = Path(path)
    raw, _ = decode_bytes(path.read_bytes())

    def uni(m: re.Match) -> str:
        code = int(m.group(1))
        return chr(code + 65536 if code < 0 else code)

    text = _RTF_UNI.sub(uni, raw)
    text = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp932", "ignore"), text)
    text = text.replace("\\par", "\n").replace("\\line", "\n")
    text = _RTF_CTRL.sub("", text)
    text = re.sub(r"[{}]", "", text)
    return ImportedDoc(source=path.name, kind="rtf", text=normalize_space(text))


# ---------------------------------------------------------------- PDF

def _pdf_text_pymupdf(path: Path) -> str | None:
    """PyMuPDF で読む。無ければ None。段組みの解釈がいちばん正確。"""
    try:
        import pymupdf  # type: ignore
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError:
            return None
    with pymupdf.open(path) as pdf:
        return "\n".join(page.get_text() for page in pdf)


def _pdf_text_pypdf(path: Path) -> str | None:
    """pypdf で読む。無ければ None。

    pypdf は純 Python 製で、どの Python でもそのまま動くため
    オフライン導入用に同梱している。PyMuPDF より取り出しの精度は
    劣るが、文字の入った PDF なら十分読める。
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_pdf(path: Path | str) -> ImportedDoc:
    path = Path(path)
    doc = ImportedDoc(source=path.name, kind="pdf")

    text = _pdf_text_pymupdf(path)
    if text is None:
        text = _pdf_text_pypdf(path)
        if text is not None:
            doc.warnings.append(
                "簡易的な方法で読み取りました。段組みの原稿では文字の順序が"
                "入れ替わることがあるので、本文を確認してください。"
            )
    if text is None:
        doc.warnings.append(
            "PDF を読み取る部品が入っていません。"
            "「追加部品のインストール.bat」を実行するか、"
            "テキストをコピーして「直接貼り付ける」欄に貼ってください。"
        )
        return doc

    doc.text = normalize_space(text)
    if not doc.text.strip():
        doc.warnings.append(
            "文字が取り出せませんでした。画像として取り込まれた PDF（スキャン原稿）の可能性があります。"
        )
    return doc


# ---------------------------------------------------------------- 一括

def read_any(path: Path | str, *, normalize: bool = True) -> ImportedDoc:
    """拡張子を見て適切な取り込み処理を選ぶ。"""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        doc = read_docx(path)
    elif ext in (".doc", ".odt", ".ods", ".wpd"):
        doc = read_doc(path)
    elif ext == ".rtf":
        doc = read_rtf(path)
    elif ext == ".pdf":
        doc = read_pdf(path)
    elif ext in TEXT_EXT:
        doc = read_text(path)
    elif ext in IMAGE_EXT:
        doc = ImportedDoc(source=path.name, kind="image")
        doc.images.append({"name": path.name, "data": path.read_bytes()})
    else:
        doc = ImportedDoc(source=path.name, kind="unknown")
        doc.warnings.append(f"対応していない形式です（{ext}）。")
        return doc

    if normalize and doc.text:
        doc.text = normalize_manuscript(doc.text)
    if not doc.author:
        doc.author = guess_author(doc.text, path.stem)
    if not doc.title:
        # 1行目が見出しらしければ、それを見出しにして本文からは取り除く
        # （原本は ImportedDoc.raw 側に残るので、いつでも戻せる）
        title = guess_title(doc.text)
        if title:
            doc.title = title
            lines = doc.text.split("\n")
            for i, line in enumerate(lines):
                if line.strip().strip("　"):
                    del lines[i]
                    break
            doc.text = "\n".join(lines).lstrip("\n")
    return doc


# ---------------------------------------------------------------- 見出し・氏名の推定

_AUTHOR_PAT = re.compile(
    r"(?:議員|委員長|副委員長|文責|執筆|担当|氏名|作成者)\s*[:：]?\s*"
    r"([一-龥ぁ-んァ-ヶ﨑髙]{2,4}(?:\s|　)?[一-龥ぁ-んァ-ヶ]{0,4})"
)


def guess_title(text: str) -> str:
    """1行目が短ければ見出しとみなす。"""
    for line in text.split("\n"):
        line = line.strip().strip("　")
        if not line:
            continue
        if len(line) <= 30 and not line.endswith("。"):
            return line
        return ""
    return ""


def guess_author(text: str, fallback: str = "") -> str:
    """本文中の「〇〇議員」「文責 〇〇」などから執筆者を推定する。"""
    m = _AUTHOR_PAT.search(text)
    if m:
        return m.group(1).replace(" ", "").replace("　", "")
    # ファイル名に議員名が入っている運用は多い
    m = re.search(r"([一-龥﨑髙]{2,4}(?:けい子|[一-龥ぁ-んァ-ヶ]{1,4}))", fallback)
    if m:
        return m.group(1)
    return ""
