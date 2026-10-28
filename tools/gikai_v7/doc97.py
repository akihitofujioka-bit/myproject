"""Word 97-2003 形式（.doc）から文字を取り出す。

Word の旧形式は、.docx のような ZIP ではなく「複合文書（OLE2）」という
古い入れ物の中に、独自の形式で文字が入っている。LibreOffice が無い
パソコンでも議員から届いた .doc を読めるよう、この形式を自分で
読み解く処理をここに置く。

外部ライブラリには依存しない（標準ライブラリだけで動く）。

参考にした仕様:
  * MS-CFB  複合文書ファイル
  * MS-DOC  Word のバイナリ形式（FIB → CLX → ピーステーブル）

読めるのは文字だけで、書式・画像・レイアウトは取り出さない。
様式（レイアウト）として使う場合は .docx が必要。
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF


class DocError(Exception):
    """.doc として読めなかった。"""


# ====================================================================== OLE2


class OleFile:
    """複合文書（OLE2）から、名前を指定してストリームを取り出す。

    .doc が必要とする範囲だけを実装した最小限の読み取り。
    """

    def __init__(self, data: bytes):
        if not data.startswith(OLE_SIGNATURE):
            raise DocError("複合文書ではありません")
        self.data = data

        (self.sector_shift,) = struct.unpack_from("<H", data, 30)
        (self.mini_sector_shift,) = struct.unpack_from("<H", data, 32)
        self.sector_size = 1 << self.sector_shift
        self.mini_sector_size = 1 << self.mini_sector_shift
        (self.num_fat_sectors,) = struct.unpack_from("<I", data, 44)
        (self.first_dir_sector,) = struct.unpack_from("<I", data, 48)
        (self.mini_cutoff,) = struct.unpack_from("<I", data, 56)
        (self.first_minifat_sector,) = struct.unpack_from("<I", data, 60)
        (self.num_minifat_sectors,) = struct.unpack_from("<I", data, 64)
        (self.first_difat_sector,) = struct.unpack_from("<I", data, 68)
        (self.num_difat_sectors,) = struct.unpack_from("<I", data, 72)

        self.fat = self._read_fat()
        self.minifat = self._read_minifat()
        self.entries = self._read_directory()
        self.mini_stream = self._read_mini_stream()

    # -------------------------------------------------------------- 低レベル

    def _sector(self, n: int) -> bytes:
        start = 512 + n * self.sector_size
        chunk = self.data[start : start + self.sector_size]
        if len(chunk) < self.sector_size:
            raise DocError("ファイルが途中で切れています")
        return chunk

    def _chain(self, start: int, fat: list[int]) -> list[int]:
        out: list[int] = []
        seen: set[int] = set()
        cur = start
        while cur not in (ENDOFCHAIN, FREESECT) and cur < len(fat):
            if cur in seen:  # 壊れたファイルで無限に回らないように
                break
            seen.add(cur)
            out.append(cur)
            cur = fat[cur]
        return out

    def _read_fat(self) -> list[int]:
        # DIFAT: 先頭 109 個はヘッダ内、それ以降は DIFAT セクタに続く
        difat = list(struct.unpack_from("<109I", self.data, 76))
        nxt, remaining = self.first_difat_sector, self.num_difat_sectors
        per = self.sector_size // 4 - 1
        while nxt not in (ENDOFCHAIN, FREESECT) and remaining > 0:
            sec = self._sector(nxt)
            difat.extend(struct.unpack_from(f"<{per}I", sec, 0))
            (nxt,) = struct.unpack_from("<I", sec, self.sector_size - 4)
            remaining -= 1

        fat: list[int] = []
        for sect in difat[: self.num_fat_sectors]:
            if sect in (ENDOFCHAIN, FREESECT):
                continue
            chunk = self._sector(sect)
            fat.extend(struct.unpack_from(f"<{self.sector_size // 4}I", chunk, 0))
        return fat

    def _read_minifat(self) -> list[int]:
        out: list[int] = []
        for sect in self._chain(self.first_minifat_sector, self.fat):
            chunk = self._sector(sect)
            out.extend(struct.unpack_from(f"<{self.sector_size // 4}I", chunk, 0))
        return out

    def _read_directory(self) -> dict[str, tuple[int, int]]:
        """名前 → (開始セクタ, 大きさ)。ルートは "" という名前で入れる。"""
        entries: dict[str, tuple[int, int]] = {}
        raw = b"".join(self._sector(s) for s in self._chain(self.first_dir_sector, self.fat))
        for off in range(0, len(raw), 128):
            e = raw[off : off + 128]
            if len(e) < 128:
                break
            (name_len,) = struct.unpack_from("<H", e, 64)
            obj_type = e[66]
            if obj_type not in (1, 2, 5) or name_len < 2:
                continue
            name = e[: name_len - 2].decode("utf-16-le", "replace")
            (start,) = struct.unpack_from("<I", e, 116)
            (size,) = struct.unpack_from("<Q", e, 120)
            if obj_type == 5:  # ルート（ミニストリームの入れ物を兼ねる）
                entries[""] = (start, size)
            elif obj_type == 2:
                entries[name] = (start, size)
        return entries

    def _read_mini_stream(self) -> bytes:
        if "" not in self.entries:
            return b""
        start, size = self.entries[""]
        data = b"".join(self._sector(s) for s in self._chain(start, self.fat))
        return data[:size]

    # -------------------------------------------------------------- 公開

    def names(self) -> list[str]:
        return [n for n in self.entries if n]

    def read(self, name: str) -> bytes:
        if name not in self.entries:
            raise DocError(f"{name} というデータがありません")
        start, size = self.entries[name]
        if size < self.mini_cutoff:
            out = bytearray()
            for s in self._chain(start, self.minifat):
                off = s * self.mini_sector_size
                out += self.mini_stream[off : off + self.mini_sector_size]
            return bytes(out[:size])
        out = bytearray()
        for s in self._chain(start, self.fat):
            out += self._sector(s)
        return bytes(out[:size])


# ====================================================================== Word

# FIB の中で使う位置（MS-DOC より）
_OFF_FLAGS = 0x000A       # fWhichTblStm などのフラグ
_OFF_CCP = 0x004C         # ここから 8 個の文字数が並ぶ
_OFF_FC_CLX = 0x01A2      # ピーステーブルの位置
_OFF_LCB_CLX = 0x01A6     # ピーステーブルの大きさ

# 本文の種類（FIB に並んでいる順）
_CCP_NAMES = ["本文", "脚注", "ヘッダ", "マクロ", "注釈", "文末脚注",
              "テキストボックス", "ヘッダのテキストボックス"]


def _parse_piece_table(table: bytes, fc_clx: int, lcb_clx: int) -> list[tuple[int, int, bool]]:
    """CLX からピーステーブルを取り出す。

    戻り値は (開始文字位置, ファイル内の位置, 1バイト文字か) の一覧に
    終端の文字位置を足したもの。
    """
    clx = table[fc_clx : fc_clx + lcb_clx]
    i = 0
    while i < len(clx):
        kind = clx[i]
        if kind == 0x01:  # 書式のかたまり → 読み飛ばす
            if i + 3 > len(clx):
                break
            (cb,) = struct.unpack_from("<H", clx, i + 1)
            i += 3 + cb
        elif kind == 0x02:  # ピーステーブル本体
            (lcb,) = struct.unpack_from("<I", clx, i + 1)
            body = clx[i + 5 : i + 5 + lcb]
            n = (len(body) - 4) // 12
            if n <= 0:
                raise DocError("ピーステーブルが空です")
            cps = list(struct.unpack_from(f"<{n + 1}I", body, 0))
            pieces: list[tuple[int, int, bool]] = []
            base = (n + 1) * 4
            for k in range(n):
                (fc,) = struct.unpack_from("<I", body, base + k * 8 + 2)
                compressed = bool(fc & 0x40000000)
                real_fc = (fc & 0x3FFFFFFF) // 2 if compressed else (fc & 0x3FFFFFFF)
                pieces.append((cps[k], real_fc, compressed))
            pieces.append((cps[n], 0, False))  # 終端
            return pieces
        else:
            break
    raise DocError("ピーステーブルが見つかりません")


# 制御文字の扱い
_FIELD_BEGIN, _FIELD_SEP, _FIELD_END = "\x13", "\x14", "\x15"


def _clean(text: str) -> str:
    """Word の制御文字を、ふつうの文字に直す。"""
    # フィールド（ページ番号や差し込みの指示）は、指示部分を捨てて結果だけ残す
    out: list[str] = []
    depth = 0
    showing = True
    for ch in text:
        if ch == _FIELD_BEGIN:
            depth += 1
            showing = False
            continue
        if ch == _FIELD_SEP:
            showing = True
            continue
        if ch == _FIELD_END:
            depth = max(0, depth - 1)
            showing = True
            continue
        if depth and not showing:
            continue
        out.append(ch)
    text = "".join(out)

    text = text.replace("\r", "\n")       # 段落の区切り
    text = text.replace("\x0b", "\n")     # 行区切り
    text = text.replace("\x0c", "\n")     # 改ページ
    text = text.replace("\x07", "\n")     # 表のセル・行の区切り
    text = text.replace("\x1e", "-")      # 分割しないハイフン
    text = text.replace("\x1f", "")       # 任意指定のハイフン
    text = text.replace("\xa0", "　")  # 分割しない空白
    text = text.replace("\x0e", "\n")     # 段の区切り
    # 画像・脚注参照などの目印は消す
    text = re.sub(r"[\x00-\x06\x08\x0f-\x12\x16-\x1d]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def extract_text(path: Path | str, *, include_textboxes: bool = True) -> str:
    """.doc から本文を取り出す。

    ``include_textboxes`` が真なら、テキストボックスの中の文字も続けて返す。
    議会だよりの様式のように、見出しや写真の説明がテキストボックスに
    入っている文書では、これを外すと大半が抜け落ちる。
    """
    data = Path(path).read_bytes()
    ole = OleFile(data)

    if "WordDocument" not in ole.entries:
        raise DocError("Word の文書ではありません")
    wd = ole.read("WordDocument")
    if len(wd) < _OFF_LCB_CLX + 4:
        raise DocError("ファイルが壊れているようです")
    if struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
        raise DocError("Word 97 以降の形式ではありません")

    (flags,) = struct.unpack_from("<H", wd, _OFF_FLAGS)
    table_name = "1Table" if flags & 0x0200 else "0Table"
    if table_name not in ole.entries:
        # 片方しか無い文書もあるので、あるほうを使う
        table_name = "1Table" if "1Table" in ole.entries else "0Table"
        if table_name not in ole.entries:
            raise DocError("Word 95 以前の形式は読み取れません")
    table = ole.read(table_name)

    (fc_clx,) = struct.unpack_from("<I", wd, _OFF_FC_CLX)
    (lcb_clx,) = struct.unpack_from("<I", wd, _OFF_LCB_CLX)
    pieces = _parse_piece_table(table, fc_clx, lcb_clx)

    ccps = list(struct.unpack_from("<8I", wd, _OFF_CCP))
    ccp_text = ccps[0]
    # 文字位置は 本文 → 脚注 → ヘッダ → … の順に続いている
    bounds: dict[str, tuple[int, int]] = {}
    pos = 0
    for name, n in zip(_CCP_NAMES, ccps):
        bounds[name] = (pos, pos + n)
        pos += n

    # ピースごとに文字を組み立てる
    chunks: list[tuple[int, str]] = []
    for k in range(len(pieces) - 1):
        cp_start, fc, compressed = pieces[k]
        cp_end = pieces[k + 1][0]
        n = cp_end - cp_start
        if n <= 0:
            continue
        if compressed:
            raw = wd[fc : fc + n]
            s = raw.decode("cp1252", "replace")
        else:
            raw = wd[fc : fc + n * 2]
            s = raw.decode("utf-16-le", "replace")
        chunks.append((cp_start, s))

    def slice_range(lo: int, hi: int) -> str:
        parts = []
        for cp_start, s in chunks:
            a, b = cp_start, cp_start + len(s)
            if b <= lo or a >= hi:
                continue
            parts.append(s[max(0, lo - a) : min(len(s), hi - a)])
        return "".join(parts)

    body = _clean(slice_range(0, ccp_text))
    if include_textboxes:
        lo, hi = bounds["テキストボックス"]
        tb = _clean(slice_range(lo, hi))
        if tb.strip():
            body = (body + "\n" + tb).strip("\n")
    return body


def is_doc(path: Path | str) -> bool:
    """中身を見て、Word 旧形式かどうかを判定する（拡張子は見ない）。"""
    try:
        with open(path, "rb") as f:
            if f.read(8) != OLE_SIGNATURE:
                return False
    except OSError:
        return False
    try:
        return "WordDocument" in OleFile(Path(path).read_bytes()).entries
    except (DocError, struct.error, ValueError):
        return False
