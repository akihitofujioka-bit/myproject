"""議会だより かんたん原稿ツール — 中核（画面なしで動く部分）

1号ぶんを「1つのフォルダ」で扱う。

    第204号/
      号情報.json                 号数・発行日
      01_表紙.txt                 区分ごとの原稿（この中に【写真】行を書く）
      02_行政報告.txt
      ...
      07_裏表紙.txt
      写真/                       写真の原本（印刷所にそのまま渡す）
      出力/                       作った Word

写真の配置は、原稿の中に次の 1 行を書くだけで表す。

    【写真】ファイル名.jpg｜中｜説明文

区切りは全角「｜」でも半角「|」でもよい。大きさは 大・中・小・顔 の 4 つ。
大きさと説明は省略できる。ツールは、この行を Word 原稿ではその場所に
縮小した写真として貼り、写真配置指示書では一覧にまとめる。

推測は一切しない。書いてあるとおりに並べるだけ。
"""

from __future__ import annotations

import datetime
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    from PIL import Image, ImageOps
    PIL_OK = True
except ImportError:  # 写真の縮小・向き補正ができないだけで、他は動く
    PIL_OK = False

try:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

import doc97

# ---------------------------------------------------------------- 決まりごと

# 区分（紙面の順）は号フォルダの中の「01_表紙.txt」のような番号付きファイルで表す。
# どの区分があるかは固定せず、フォルダにあるファイルがそのまま紙面の順になる。
# 号を作るときは、定例会ごとの雛形（第198〜201号の 1 年分から確認）で区分をそろえる。
COVER = "表紙"          # この名前の区分だけ横書き。数字の変換もしない
KUBUN_FILE = re.compile(r"^(\d{2})_(.+)\.txt$")

# 毎号あるもの
KUBUN_COMMON_HEAD = ["表紙", "行政報告", "審議したこと・決まったこと"]
KUBUN_COMMON_TAIL = ["閉会中の委員会活動報告", "一般質問", "特集", "裏表紙"]

# 号の種類 → 区分の並び。定例会ごとに加わるものを共通部分の間に入れる
TEMPLATES = {
    "3月号": KUBUN_COMMON_HEAD + ["当初予算の概要"] + KUBUN_COMMON_TAIL,
    "6月号": KUBUN_COMMON_HEAD + KUBUN_COMMON_TAIL + ["お知らせ"],
    "9月号": KUBUN_COMMON_HEAD + ["決算の概要"] + KUBUN_COMMON_TAIL + ["議員行政視察研修報告", "お知らせ"],
    "12月号": KUBUN_COMMON_HEAD + KUBUN_COMMON_TAIL + ["行政視察・研修報告", "お知らせ"],
}
DEFAULT_TEMPLATE = "6月号"

# 各区分に載せるものの目安（前年の号から）。画面のヒントに出す
HINTS = {
    "表紙": "号数・発行日・表紙写真の説明・特集の予告（例: 特集　新年の抱負を聞きました …………14Ｐ）・発行元",
    "行政報告": "村長の行政報告（要旨）。見出し＋本文を項目ごとに。村長の顔写真は【写真】行で",
    "審議したこと・決まったこと": "「○月議会では、報告○件、同意○件…合計○件が決まった」→ ◎議案名と質疑（問／答）。賛否一覧表は Excel を「別添」フォルダへ",
    "当初予算の概要": "（3月号）令和○年度各会計予算の額、注目する事業と金額、前年度からの繰越事業",
    "決算の概要": "（9月号）前年度決算の認定：歳入・歳出の額、主な事業の決算、質疑",
    "閉会中の委員会活動報告": "総務常任・経済建設厚生常任・治水対策特別・少子化対策特別 の順。開催日と協議内容",
    "一般質問": "「一般質問に○氏が立つ」→ 議員ごとに 見出し／質問／答弁 ○○課長。議員の顔写真は【写真】…｜顔",
    "特集": "その号の企画（3月: 新成人アンケート・入学おめでとう、6月: よさこい、9月: 金婚、12月: 新年の抱負 など）",
    "議員行政視察研修報告": "（9月号）視察先・日程・学んだこと",
    "行政視察・研修報告": "（12月号）受け入れた視察や参加した研修の報告",
    "お知らせ": "議会放送の視聴の仕方、視聴者の声、傍聴の案内など",
    "裏表紙": "編集後記（署名）、発行責任者、次の定例会の日程と傍聴の案内、再生紙の表示",
}

# 写真の大きさ → 幅（mm）。紙面は 5 段組で 1 段が約 30mm。
SIZES = {
    "大": 80,   # 3 段ぶん弱（段の見出し写真など）
    "中": 55,   # 2 段ぶん
    "小": 38,   # 1 段と少し
    "顔": 26,   # 議員・委員長の顔写真
}
DEFAULT_SIZE = "中"

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic"}
PRINT_DPI = 350   # 印刷所が求める解像度

INFO_NAME = "号情報.json"
PHOTO_DIR = "写真"
ATTACH_DIR = "別添"
OUT_DIR = "出力"

FONT_MINCHO = "ＭＳ 明朝"
FONT_GOTHIC = "ＭＳ ゴシック"

# 原稿 Word の紙面。印刷所に渡してきた従来の .doc に合わせる:
#   表紙は横書き 1 段、本文は縦書き 5 段（余白・段間は第203号の実測値）。
# 写真配置指示書（一覧表）は表なので、この設定に関係なく横書き。
TATEGAKI = True
DANSU = 5                      # 本文の段数
MARGIN_MM = (15, 12, 15, 15)   # 上・下・左・右
DAN_SPACE_MM = 6               # 段の間隔
LINE_SPACING = 1.45            # 本文の行送り（倍）
BODY_PT = 10.5                 # 本文の文字の大きさ
DAN_HEIGHT_MM = (297 - MARGIN_MM[0] - MARGIN_MM[1] - DAN_SPACE_MM * (DANSU - 1)) / DANSU   # 1 段の高さ
BODY_WIDTH_MM = 210 - MARGIN_MM[2] - MARGIN_MM[3]   # 本文が入る横幅（行が進む向き）

# 縦書きの慣行に合わせて数字の全角／半角をそろえるか（従来の .doc 4 号分から確認した規則）。
#   1 桁 → 全角（４人・３月）、2 桁以上 → 半角（第46回・国道33号）
#   「－」でつないだ郵便番号・電話番号・番地 → そのまま、表紙 → そのまま、【写真】行 → そのまま
NUMBERS_TATEGAKI = True
NUMBERS_SKIP_KUBUN = (COVER,)

# 【写真】ファイル名｜大きさ｜説明
PHOTO_LINE = re.compile(
    r"^\s*【写真】\s*(?P<file>[^｜|]+?)"
    r"(?:\s*[｜|]\s*(?P<size>[大中小顔])?)?"
    r"(?:\s*[｜|]\s*(?P<caption>.*?))?\s*$"
)

# 表紙の原稿に最初から入れておく文面
COVER_TEMPLATE = """第{gou}号
{hakkoubi}
ひだか議会だより

特集　（特集の題名）　…………（ページ）

発行　高知県日高村議会　編集　議会広報発行調査特別委員会
日高村本郷６１－１　〒７８１－２１９４　℡０８８９－２４－７７７７
"""

READ_ME = """このフォルダの使い方

・01_表紙.txt、02_行政報告.txt … に、区分ごとの原稿を書きます（番号の順が紙面の順です）
  区分を足す・順番を変えるのはツールの「区分を追加」「▲▼」でできます
・写真 フォルダに写真の原本を入れます（ファイル名はそのまま印刷所に伝わります）
・別添 フォルダには賛否一覧表（Excel）など、原稿以外で印刷所に渡すものを入れます
・写真を入れたい場所に、次の 1 行を書きます

    【写真】ファイル名.jpg｜中｜説明文

  大きさは 大・中・小・顔 のどれか（省略すると 中）。説明文は省略できます。
・ツールで「Word を作る」を押すと、出力 フォルダに
    原稿（写真入り）と 写真配置指示書 の 2 つの Word ができます
・印刷所には「出力の Word 2 つ」と「写真フォルダの中身」を渡します
"""


# ---------------------------------------------------------------- 原稿の解釈

@dataclass
class PhotoRef:
    """原稿の中の【写真】行 1 つ。"""
    file: str
    size: str = DEFAULT_SIZE
    caption: str = ""
    line_no: int = 0

    @property
    def width_mm(self) -> int:
        return SIZES.get(self.size, SIZES[DEFAULT_SIZE])

    def to_line(self) -> str:
        line = f"【写真】{self.file}｜{self.size}"
        if self.caption:
            line += f"｜{self.caption}"
        return line


def parse_photo_line(line: str, line_no: int = 0) -> PhotoRef | None:
    m = PHOTO_LINE.match(line)
    if not m:
        return None
    return PhotoRef(
        file=m.group("file").strip(),
        size=(m.group("size") or DEFAULT_SIZE),
        caption=(m.group("caption") or "").strip(),
        line_no=line_no,
    )


def parse_blocks(text: str) -> list[tuple[str, object]]:
    """原稿を、("text", 文字列) と ("photo", PhotoRef) の並びに分ける。

    連続する本文行は 1 つの "text" にまとめる。空行はそのまま残す。
    """
    blocks: list[tuple[str, object]] = []
    buf: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        ref = parse_photo_line(line, i)
        if ref:
            if buf:
                blocks.append(("text", "\n".join(buf)))
                buf = []
            blocks.append(("photo", ref))
        else:
            buf.append(line)
    if buf:
        blocks.append(("text", "\n".join(buf)))
    return blocks


def photo_refs(text: str) -> list[PhotoRef]:
    return [b for kind, b in parse_blocks(text) if kind == "photo"]


def count_chars(text: str) -> int:
    """本文の字数（【写真】行と空白を除く）。画面の「○字」に出す素の字数。"""
    n = 0
    for line in text.splitlines():
        if parse_photo_line(line):
            continue
        n += len(re.sub(r"\s", "", line))
    return n


# ------------------------------------------------------------ 紙面に入る量

MM_PER_PT = 25.4 / 72


def count_width(text: str) -> int:
    """組版で何文字ぶんの幅になるか（半角は 0.5 文字として数え、切り上げ）。

    枠に収まるかを見るときは、こちらを使う。「12日」は 2 文字ぶん、
    「１２日」は 3 文字ぶんで、紙面の占める幅が実際に違うため。
    """
    n = 0.0
    for line in text.splitlines():
        if parse_photo_line(line):
            continue
        for ch in line:
            if ch.isspace():
                continue
            n += 1.0 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 0.5
    return int(n + 0.999)


def page_capacity() -> dict:
    """いまの紙面の設定で、1 ページに何字入るかを計算する。

    縦書き 5 段では、文字は段の高さの向きに並び、行は紙の横幅の向きに進む。
      1 行の字数 = 段の高さ ÷ 文字の大きさ
      1 段の行数 = 本文の横幅 ÷ 行送り
    既定値（5 段・10.5pt・行送り1.45）では 13 字 × 33 行 × 5 段 = 2145 字。
    """
    char_mm = BODY_PT * MM_PER_PT
    line_mm = BODY_PT * LINE_SPACING * MM_PER_PT
    per_line = int(DAN_HEIGHT_MM / char_mm)
    per_dan = int(BODY_WIDTH_MM / line_mm)
    return {
        "chars_per_line": per_line,
        "lines_per_dan": per_dan,
        "chars_per_dan": per_line * per_dan,
        "chars_per_page": per_line * per_dan * DANSU,
        "char_area_mm2": char_mm * line_mm,
    }


def photo_chars(ref: "PhotoRef", info: "PhotoInfo | None" = None) -> int:
    """写真が本文を何字ぶん押しのけるかの目安。

    写真の面積を 1 文字の面積で割る。高さは元の写真の縦横比から出し、
    1 段に収まらないときは Word に貼るときと同じように縮める。
    """
    cap = page_capacity()
    w = ref.width_mm
    h = w * 3 / 4   # 縦横比がわからないときは 4:3 とみなす
    if info and info.width_px and info.height_px:
        h = w * info.height_px / info.width_px
    max_h = DAN_HEIGHT_MM - 4
    if h > max_h:
        w, h = max_h * w / h, max_h
    caption = 2 if ref.caption else 1     # 赤字の指示文とキャプションのぶん
    return int(w * h / cap["char_area_mm2"]) + caption * cap["chars_per_line"]


# ---------------------------------------------------------------- 数字の表記

_Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
_H2Z = str.maketrans("0123456789", "０１２３４５６７８９")
# 「７８１－２１９４」「0889-24-7777」のような区切り付きの番号はひとまとまりで拾う
_NUM_GROUP = re.compile(r"[0-9０-９]+(?:[－\-‐][0-9０-９]+)+|[0-9０-９]+")


def to_zenkaku_digits(s: str) -> str:
    return s.translate(_H2Z)


def normalize_numbers(text: str) -> str:
    """縦書きの慣行に合わせて数字の全角／半角をそろえる。

    1 桁は全角、2 桁以上は半角。「－」でつないだ郵便番号・電話番号・番地は
    書いてあるとおり残す。【写真】行はファイル名なので触らない。
    """

    def repl(m: re.Match) -> str:
        s = m.group(0)
        if any(ch in s for ch in "－-‐"):
            return s
        h = s.translate(_Z2H)
        return h.translate(_H2Z) if len(h) == 1 else h

    out = []
    for line in text.split("\n"):
        out.append(line if parse_photo_line(line) else _NUM_GROUP.sub(repl, line))
    return "\n".join(out)


# ---------------------------------------------------------------- 号フォルダ

@dataclass
class Issue:
    """1 号ぶんのフォルダ。"""
    folder: Path
    gou: str = ""
    hakkoubi: str = ""
    template: str = ""

    # ---- 作る・開く

    @classmethod
    def create(cls, root: Path | str, gou: str, hakkoubi: str,
               template: str = DEFAULT_TEMPLATE) -> "Issue":
        """root の下に「第○号」フォルダを作り、号の種類に合った区分ファイルをそろえる。"""
        gou = str(gou).strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if template not in TEMPLATES:
            raise KeyError(f"号の種類が不明です: {template}")
        folder = Path(root) / f"第{gou}号"
        if folder.exists():
            raise FileExistsError(f"{folder} は既にあります")
        folder.mkdir(parents=True)
        (folder / PHOTO_DIR).mkdir()
        (folder / ATTACH_DIR).mkdir()
        (folder / OUT_DIR).mkdir()
        issue = cls(folder=folder, gou=gou, hakkoubi=hakkoubi, template=template)
        issue.save_info()
        for i, name in enumerate(TEMPLATES[template], 1):
            body = COVER_TEMPLATE.format(gou=to_zenkaku_digits(gou), hakkoubi=hakkoubi) if name == COVER else ""
            (folder / f"{i:02d}_{name}.txt").write_text(body, encoding="utf-8-sig")
        (folder / "はじめにお読みください.txt").write_text(READ_ME, encoding="utf-8-sig")
        return issue

    @classmethod
    def open(cls, folder: Path | str) -> "Issue":
        folder = Path(folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"{folder} が見つかりません")
        issue = cls(folder=folder)
        p = folder / INFO_NAME
        if p.exists():
            info = json.loads(p.read_text(encoding="utf-8-sig"))
            issue.gou = str(info.get("gou", ""))
            issue.hakkoubi = str(info.get("hakkoubi", ""))
            issue.template = str(info.get("template", ""))
        else:
            m = re.search(r"(\d+)", folder.name)
            issue.gou = m.group(1) if m else ""
        (folder / PHOTO_DIR).mkdir(exist_ok=True)
        (folder / ATTACH_DIR).mkdir(exist_ok=True)
        (folder / OUT_DIR).mkdir(exist_ok=True)
        return issue

    def save_info(self) -> None:
        (self.folder / INFO_NAME).write_text(
            json.dumps({"gou": self.gou, "hakkoubi": self.hakkoubi, "template": self.template},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 原稿

    def _kubun_files(self) -> list[tuple[int, str, Path]]:
        """フォルダにある区分ファイルを (番号, 区分名, パス) で番号順に返す。"""
        found = []
        for p in self.folder.iterdir():
            m = KUBUN_FILE.match(p.name)
            if m and p.is_file():
                found.append((int(m.group(1)), m.group(2), p))
        return sorted(found, key=lambda t: (t[0], t[1]))

    def kubun_list(self) -> list[str]:
        """区分名を紙面の順に返す。"""
        return [name for _, name, _ in self._kubun_files()]

    def text_path(self, kubun: str) -> Path:
        for _, name, p in self._kubun_files():
            if name == kubun:
                return p
        raise KeyError(f"区分がありません: {kubun}")

    def _renumber(self, names: list[str]) -> None:
        """区分ファイルを names の順に 01_, 02_ … と付け直す（中身は触らない）。"""
        paths = {name: p for _, name, p in self._kubun_files()}
        tmp = []
        for i, name in enumerate(names, 1):
            src = paths[name]
            t = src.with_name(f"~{i:02d}_{name}.txt")   # いったん退避して番号の衝突を避ける
            src.rename(t)
            tmp.append((t, src.with_name(f"{i:02d}_{name}.txt")))
        for t, dst in tmp:
            t.rename(dst)

    def add_kubun(self, name: str, after: str | None = None) -> None:
        """区分を足す。after を指定するとその次に入る。省略すると末尾。"""
        name = name.strip().replace("/", "／").replace("\\", "＼")
        if not name:
            raise ValueError("区分の名前を入れてください")
        names = self.kubun_list()
        if name in names:
            raise FileExistsError(f"区分「{name}」は既にあります")
        n = len(names) + 1
        (self.folder / f"{n:02d}_{name}.txt").write_text("", encoding="utf-8-sig")
        names.append(name)
        if after in names:
            names.remove(name)
            names.insert(names.index(after) + 1, name)
        self._renumber(names)

    def move_kubun(self, name: str, delta: int) -> None:
        """区分の順番を delta（-1 で上、+1 で下）だけ動かす。"""
        names = self.kubun_list()
        i = names.index(name)
        j = max(0, min(len(names) - 1, i + delta))
        if i != j:
            names.insert(j, names.pop(i))
            self._renumber(names)

    def remove_kubun(self, name: str) -> None:
        """空の区分だけ外せる（原稿が入っているものは消さない）。ファイルは削除する。"""
        p = self.text_path(name)
        if read_text_file(p).strip():
            raise ValueError(f"「{name}」には原稿が入っているので外せません。中身を空にしてからにしてください")
        p.unlink()
        self._renumber(self.kubun_list())

    def read_text(self, kubun: str) -> str:
        p = self.text_path(kubun)
        return read_text_file(p) if p.exists() else ""

    def write_text(self, kubun: str, text: str) -> None:
        # BOM 付き UTF-8 にしておくと、Windows のメモ帳でも文字化けしない
        self.text_path(kubun).write_text(text.replace("\r\n", "\n"), encoding="utf-8-sig")

    def all_texts(self) -> list[tuple[str, str]]:
        return [(name, read_text_file(p)) for _, name, p in self._kubun_files()]

    # ---- 写真

    @property
    def photo_dir(self) -> Path:
        return self.folder / PHOTO_DIR

    @property
    def attach_dir(self) -> Path:
        return self.folder / ATTACH_DIR

    @property
    def out_dir(self) -> Path:
        return self.folder / OUT_DIR

    def attach_files(self) -> list[Path]:
        """別添フォルダの中身（賛否一覧表の Excel など）。"""
        if not self.attach_dir.is_dir():
            return []
        return sorted((p for p in self.attach_dir.iterdir() if p.is_file() and not p.name.startswith(".")),
                      key=lambda p: natural_key(p.name))

    def photo_files(self) -> list[Path]:
        if not self.photo_dir.is_dir():
            return []
        files = [p for p in self.photo_dir.iterdir()
                 if p.is_file() and p.suffix.lower() in PHOTO_EXT and not p.name.startswith(".")]
        return sorted(files, key=lambda p: natural_key(p.name))

    def photo_usage(self) -> dict[str, list[str]]:
        """写真ファイル名 → 使われている区分の一覧。"""
        used: dict[str, list[str]] = {}
        for name, text in self.all_texts():
            for ref in photo_refs(text):
                used.setdefault(ref.file, []).append(name)
        return used

    def all_refs(self) -> list[tuple[str, PhotoRef]]:
        """紙面の順に (区分, PhotoRef) を並べる。"""
        out = []
        for name, text in self.all_texts():
            for ref in photo_refs(text):
                out.append((name, ref))
        return out

    def estimate(self) -> dict:
        """区分ごとの分量と、全体で何ページになるかの目安を出す。

        表紙は横書き 1 段で組み方が違うので、ページ数の計算からは外して
        1 ページとして数える。写真は本文を押しのけるぶんを字数に足す。
        """
        cap = page_capacity()
        rows = []
        body_chars = 0
        for kubun, text in self.all_texts():
            chars = count_width(text)
            pchars = 0
            for ref in photo_refs(text):
                pchars += photo_chars(ref, photo_info(self.photo_dir / ref.file))
            total = chars + pchars
            rows.append({
                "kubun": kubun,
                "chars": chars,
                "photo_chars": pchars,
                "total": total,
                "photos": len(photo_refs(text)),
                "pages": total / cap["chars_per_page"],
                "cover": kubun == COVER,
            })
            if kubun != COVER:
                body_chars += total
        body_pages = -(-body_chars // cap["chars_per_page"]) if body_chars else 0
        has_cover = any(r["cover"] for r in rows)
        pages = int(body_pages) + (1 if has_cover else 0)
        return {
            "capacity": cap,
            "rows": rows,
            "body_chars": body_chars,
            "pages": pages,
            "odd": pages % 2 == 1,
        }

    def title(self) -> str:
        return f"第{self.gou}号" if self.gou else self.folder.name


def natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ---------------------------------------------------------------- 取り込み

def read_text_file(path: Path | str) -> str:
    """文字コードを自動判別してテキストを読む（UTF-8 → CP932 → EUC-JP）。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp932", "euc_jp"):
        try:
            return raw.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def import_manuscript(path: Path | str) -> str:
    """議員から届いた原稿ファイルから文字だけを取り出す。

    .docx（本文・表・テキストボックス）、.doc（旧形式）、.txt に対応。
    書式は捨てる。段落の区切りだけ改行として残す。
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        text = docx_to_text(path)
    elif ext == ".doc":
        text = doc97.extract_text(path)
    elif ext in (".txt", ".text", ".md"):
        text = read_text_file(path)
    else:
        raise ValueError(f"この形式は取り込めません: {path.name}（.docx / .doc / .txt に対応）")
    return normalize_numbers(text) if NUMBERS_TATEGAKI else text


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(path: Path | str) -> str:
    """python-docx を使わず、document.xml から段落ごとの文字を取り出す。

    テキストボックス（txbxContent）の中も本文と同じ順に拾う。
    """
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    # Word が作る XML に DOCTYPE や実体定義は含まれない。含まれていたら
    # 細工されたファイルなので読まない（XML 爆弾・外部実体参照の対策）
    head = xml[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in xml.lower():
        raise ValueError(f"通常の Word ファイルではありません: {Path(path).name}")
    root = ET.fromstring(xml)
    lines: list[str] = []
    for p in root.iter(_W + "p"):
        parts: list[str] = []
        has_nested = False

        def walk(node):
            nonlocal has_nested
            for ch in node:
                if ch.tag == _W + "p":      # テキストボックス内の段落は別に拾う
                    has_nested = True
                    continue
                if ch.tag == _W + "t":
                    parts.append(ch.text or "")
                elif ch.tag in (_W + "br", _W + "cr"):
                    parts.append("\n")
                elif ch.tag == _W + "tab":
                    parts.append("\t")
                else:
                    walk(ch)

        walk(p)
        line = "".join(parts)
        if not line and has_nested:   # 枠だけの段落は空行にしない
            continue
        lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


# ---------------------------------------------------------------- 写真の情報

@dataclass
class PhotoInfo:
    path: Path
    width_px: int = 0
    height_px: int = 0
    error: str = ""

    def max_print_mm(self) -> float:
        """350dpi で刷ったとき、何 mm 幅まで使えるか。"""
        return self.width_px / PRINT_DPI * 25.4 if self.width_px else 0.0

    def warning_for(self, width_mm: int) -> str:
        if self.error:
            return self.error
        limit = self.max_print_mm()
        if limit and limit < width_mm:
            return f"解像度不足（{width_mm}mm には {limit:.0f}mm 相当までしか使えません。元データをもらってください）"
        return ""


def photo_info(path: Path | str) -> PhotoInfo:
    path = Path(path)
    if not path.exists():
        return PhotoInfo(path=path, error="写真フォルダにありません")
    if not PIL_OK:
        return PhotoInfo(path=path)
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            return PhotoInfo(path=path, width_px=im.width, height_px=im.height)
    except Exception as e:  # 壊れた画像など
        return PhotoInfo(path=path, error=f"読み込めません（{e}）")


def reduced_jpeg(path: Path | str, max_px: int = 1200) -> io.BytesIO | None:
    """Word に貼る用に、向きを直して縮小した JPEG をメモリ上に作る。

    原本は触らない。Word のファイルが重くならないようにするため。
    """
    if not PIL_OK:
        return None
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_px, max_px))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            buf.seek(0)
            return buf
    except Exception:
        return None


# ---------------------------------------------------------------- Word 生成

def _set_font(run, name=FONT_MINCHO, size=BODY_PT, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)


# 縦書きで立てて入れる（縦中横）半角数字: 2〜3 桁。1 桁は全角にしてあり、4 桁以上はそのまま
_TATECHUYOKO = re.compile(r"(?<![0-9])[0-9]{2,3}(?![0-9])")


def _para(doc, text="", *, name=FONT_MINCHO, size=BODY_PT, bold=False,
          color=None, align=None, after=4, tatechuyoko=False, line=None):
    p = doc.add_paragraph()
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(after)
    if line:
        p.paragraph_format.line_spacing = line
    if not text:
        return p
    if not tatechuyoko:
        _set_font(p.add_run(text), name, size, bold, color)
        return p
    # 2〜3 桁の半角数字だけ別の run にして「縦中横」を掛ける
    pos = 0
    for m in _TATECHUYOKO.finditer(text):
        if m.start() > pos:
            _set_font(p.add_run(text[pos:m.start()]), name, size, bold, color)
        run = p.add_run(m.group(0))
        _set_font(run, name, size, bold, color)
        layout = OxmlElement("w:eastAsianLayout")
        layout.set(qn("w:combine"), "1")
        run._element.get_or_add_rPr().append(layout)
        pos = m.end()
    if pos < len(text):
        _set_font(p.add_run(text[pos:]), name, size, bold, color)
    return p


def _setup_page(doc):
    """A4 縦・余白 20mm・横書き（表紙と指示書用）。既定フォントも決める。"""
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.top_margin = sec.bottom_margin = Mm(20)
    sec.left_margin = sec.right_margin = Mm(20)
    style = doc.styles["Normal"]
    style.font.name = FONT_MINCHO
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_MINCHO)


def _add_body_section(doc):
    """本文用のセクションを足す: 縦書き（右から左）5 段、余白と段間は従来の紙面に合わせる。"""
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.top_margin, sec.bottom_margin = Mm(MARGIN_MM[0]), Mm(MARGIN_MM[1])
    sec.left_margin, sec.right_margin = Mm(MARGIN_MM[2]), Mm(MARGIN_MM[3])
    sect = sec._sectPr
    # 段組: <w:cols w:num="5" w:space="340"/>（space は twip。1mm = 56.7twip）
    cols = sect.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect.append(cols)
    cols.set(qn("w:num"), str(DANSU))
    cols.set(qn("w:space"), str(round(DAN_SPACE_MM * 56.7)))
    if TATEGAKI:
        # <w:textDirection w:val="tbRl"/> で縦書き。要素の順番に決まりがあり docGrid の前に置く
        td = OxmlElement("w:textDirection")
        td.set(qn("w:val"), "tbRl")
        grid = sect.find(qn("w:docGrid"))
        if grid is not None:
            grid.addprevious(td)
        else:
            sect.append(td)
    return sec


def _add_photo(doc, issue: Issue, number: int, kubun: str, ref: PhotoRef,
               warnings: list[str]) -> None:
    """原稿 Word の中に、写真（縮小版）と赤い指示文を入れる。"""
    src = issue.photo_dir / ref.file
    info = photo_info(src)
    label = f"【写真{number}】{ref.file}（{ref.size}・幅{ref.width_mm}mm）"
    if ref.caption:
        label += f"　説明: {ref.caption}"
    _para(doc, label, name=FONT_GOTHIC, size=9, bold=True, color=(0xC0, 0x00, 0x00), after=1)

    if info.error:
        warnings.append(f"{kubun}: {ref.file} — {info.error}")
        _para(doc, f"（{info.error}）", name=FONT_GOTHIC, size=9, color=(0xC0, 0x00, 0x00))
        return
    warn = info.warning_for(ref.width_mm)
    if warn:
        warnings.append(f"{kubun}: {ref.file} — {warn}")

    buf = reduced_jpeg(src)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    # 縦書き 5 段の中では、写真の高さが 1 段の高さを超えると段からはみ出すので、
    # 貼るときは高さを 1 段に収まるまで縮める（印刷所への大きさの指示は赤字のとおり）
    width_mm = ref.width_mm
    max_h = DAN_HEIGHT_MM - 4
    if TATEGAKI and info.width_px and info.height_px:
        h = width_mm * info.height_px / info.width_px
        if h > max_h:
            width_mm = max_h * info.width_px / info.height_px
    try:
        p.add_run().add_picture(buf if buf else str(src), width=Mm(width_mm))
    except Exception as e:
        warnings.append(f"{kubun}: {ref.file} — Word に貼れませんでした（{e}）")
        _set_font(p.add_run("（写真を貼れませんでした）"), FONT_GOTHIC, 9, color=(0xC0, 0, 0))
    if warn:
        _para(doc, f"※ {warn}", name=FONT_GOTHIC, size=8, color=(0xC0, 0x00, 0x00))


def build_manuscript(issue: Issue, out: Path | str | None = None) -> tuple[Path, list[str]]:
    """原稿 Word（写真入り）を作る。戻り値は (保存先, 注意事項)。"""
    if not DOCX_OK:
        raise RuntimeError("python-docx が入っていません（pip install python-docx）")
    out = Path(out) if out else issue.out_dir / f"{issue.title()}_原稿.docx"
    doc = Document()
    _setup_page(doc)   # 1 つ目のセクション = 表紙（横書き 1 段）
    warnings: list[str] = []

    _para(doc, f"ひだか議会だより {issue.title()}　原稿", name=FONT_GOTHIC, size=16, bold=True, align="center")
    _para(doc, f"発行日 {issue.hakkoubi}　／　作成 {datetime.date.today():%Y-%m-%d}",
          name=FONT_GOTHIC, size=9, align="center", after=12)
    _para(doc, "赤い【写真○】は写真を入れる場所と大きさの指示です。写真の原本は「写真」フォルダにあります。",
          name=FONT_GOTHIC, size=9, color=(0xC0, 0, 0), after=12)

    number = 0
    body_started = False
    for kubun, text in issue.all_texts():
        is_cover = kubun == COVER
        if not is_cover and not body_started:
            _add_body_section(doc)   # 表紙のあと、ここから縦書き 5 段
            body_started = True
        elif body_started:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        _para(doc, f"■ {kubun}", name=FONT_GOTHIC, size=14, bold=True, after=8)
        if NUMBERS_TATEGAKI and kubun not in NUMBERS_SKIP_KUBUN:
            text = normalize_numbers(text)
        if not text.strip():
            _para(doc, "（原稿なし）", name=FONT_GOTHIC, size=9, color=(0x80, 0x80, 0x80))
            warnings.append(f"{kubun}: 原稿が空です")
        for kind, block in parse_blocks(text):
            if kind == "photo":
                number += 1
                _add_photo(doc, issue, number, kubun, block, warnings)
            else:
                for line in block.split("\n"):
                    _para(doc, line, after=0,
                          tatechuyoko=TATEGAKI and not is_cover,
                          line=None if is_cover else LINE_SPACING)
    doc.save(out)
    return out, warnings


def build_photo_sheet(issue: Issue, out: Path | str | None = None) -> tuple[Path, list[str]]:
    """写真配置指示書（一覧表）を作る。印刷所が写真を照合するための紙。"""
    if not DOCX_OK:
        raise RuntimeError("python-docx が入っていません（pip install python-docx）")
    out = Path(out) if out else issue.out_dir / f"{issue.title()}_写真配置指示.docx"
    doc = Document()
    _setup_page(doc)
    warnings: list[str] = []

    _para(doc, f"ひだか議会だより {issue.title()}　写真配置指示書", name=FONT_GOTHIC, size=16, bold=True, align="center")
    _para(doc, f"作成 {datetime.date.today():%Y-%m-%d}　写真の原本は「写真」フォルダ内。番号は原稿 Word の【写真○】と同じ。",
          name=FONT_GOTHIC, size=9, align="center", after=10)

    refs = issue.all_refs()
    if not refs:
        _para(doc, "写真の指定がありません。", name=FONT_GOTHIC)
    else:
        table = doc.add_table(rows=1, cols=6)
        table.style = "Table Grid"
        heads = ["番号", "写真", "ファイル名", "区分", "大きさ", "説明"]
        for cell, h in zip(table.rows[0].cells, heads):
            cell.text = ""
            _set_font(cell.paragraphs[0].add_run(h), FONT_GOTHIC, 9, True)
        for n, (kubun, ref) in enumerate(refs, 1):
            row = table.add_row().cells
            _set_font(row[0].paragraphs[0].add_run(str(n)), FONT_GOTHIC, 10, True)
            src = issue.photo_dir / ref.file
            info = photo_info(src)
            if info.error:
                _set_font(row[1].paragraphs[0].add_run(info.error), FONT_GOTHIC, 8, color=(0xC0, 0, 0))
                warnings.append(f"{kubun}: {ref.file} — {info.error}")
            else:
                buf = reduced_jpeg(src, 600)
                try:
                    row[1].paragraphs[0].add_run().add_picture(buf if buf else str(src), width=Mm(35))
                except Exception:
                    _set_font(row[1].paragraphs[0].add_run("（表示不可）"), FONT_GOTHIC, 8)
            _set_font(row[2].paragraphs[0].add_run(ref.file), FONT_GOTHIC, 9)
            if info.width_px:
                _set_font(row[2].add_paragraph().add_run(f"{info.width_px}×{info.height_px}px"), FONT_GOTHIC, 8)
            _set_font(row[3].paragraphs[0].add_run(kubun), FONT_GOTHIC, 9)
            _set_font(row[4].paragraphs[0].add_run(f"{ref.size}（幅{ref.width_mm}mm）"), FONT_GOTHIC, 9)
            _set_font(row[5].paragraphs[0].add_run(ref.caption or "（説明なし）"), FONT_MINCHO, 9)
            warn = info.warning_for(ref.width_mm)
            if warn:
                _set_font(row[5].add_paragraph().add_run("※ " + warn), FONT_GOTHIC, 8, color=(0xC0, 0, 0))
                warnings.append(f"{kubun}: {ref.file} — {warn}")
        widths = [12, 40, 40, 30, 22, 26]
        for row in table.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = Mm(w)

    # 使っていない写真も知らせる（入れ忘れの確認用）
    used = issue.photo_usage()
    unused = [p.name for p in issue.photo_files() if p.name not in used]
    if unused:
        _para(doc, "", after=8)
        _para(doc, "写真フォルダにあるが、原稿で使っていない写真:", name=FONT_GOTHIC, size=9, bold=True)
        for name in unused:
            _para(doc, "・" + name, name=FONT_GOTHIC, size=9, after=0)
    # 別添（賛否一覧表の Excel など）
    attach = issue.attach_files()
    if attach:
        _para(doc, "", after=8)
        _para(doc, "別添（「別添」フォルダにあるファイル。原稿とは別に印刷所へ渡すもの）:", name=FONT_GOTHIC, size=9, bold=True)
        for p in attach:
            _para(doc, "・" + p.name, name=FONT_GOTHIC, size=9, after=0)
    doc.save(out)
    return out, warnings


def build_all(issue: Issue) -> tuple[list[Path], list[str]]:
    """原稿 Word と写真配置指示書をまとめて作る。"""
    outs: list[Path] = []
    warnings: list[str] = []
    for fn in (build_manuscript, build_photo_sheet):
        path, w = fn(issue)
        outs.append(path)
        for item in w:
            if item not in warnings:
                warnings.append(item)
    return outs, warnings
