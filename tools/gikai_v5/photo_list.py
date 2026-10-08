"""印刷所へ渡す写真配置一覧と、解像度の確認。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import docx_out as dx
from grid import Box, Geometry, mm2pt


@dataclass
class PhotoRecord:
    """紙面に置いた写真1枚の受け渡し情報。"""

    page_no: int
    section: str
    output_name: str
    original_name: str
    size: str
    width_mm: float
    height_mm: float
    position: str
    caption: str
    pixels: Optional[Tuple[int, int]] = None

    @property
    def dpi(self) -> Optional[int]:
        if not self.pixels or self.width_mm <= 0 or self.height_mm <= 0:
            return None
        x = self.pixels[0] / (self.width_mm / 25.4)
        y = self.pixels[1] / (self.height_mm / 25.4)
        return int(min(x, y) + 0.5)

    @property
    def warning(self) -> str:
        return dpi_warning(self.dpi)


def dpi_warning(dpi: Optional[int]) -> str:
    """印刷時の実効 dpi を2段階の注意文にする。"""
    if dpi is None:
        return "画素数を読み取れません"
    if dpi < 200:
        return f"画質が足りません（{dpi}dpi）"
    if dpi < 350:
        return f"画質が足りないおそれ（{dpi}dpi）"
    return ""


def write_photo_list(path: Path, records: List[PhotoRecord],
                     geometry: Optional[Geometry] = None) -> Path:
    """写真配置一覧を横書きの表にして Word へ書き出す。"""
    g = geometry or Geometry()
    headers = ["頁", "区分", "写真の名前", "元のファイル名", "大きさ",
               "幅mm", "高さmm", "紙面の位置", "写真の説明", "解像度"]
    widths_mm = [7, 18, 24, 24, 10, 10, 10, 20, 28, 29]
    widths = [mm2pt(value) for value in widths_mm]
    pages = []
    chunks = [records[n:n + 12] for n in range(0, len(records), 12)] or [[]]
    for page_no, chunk in enumerate(chunks):
        rows = [headers]
        for item in chunk:
            rows.append([
                str(item.page_no), item.section, item.output_name, item.original_name,
                item.size, f"{item.width_mm:.1f}", f"{item.height_mm:.1f}",
                item.position, item.caption, item.warning or f"{item.dpi}dpi",
            ])
        page = dx.Page()
        title = "写真配置一覧" + (f"（{page_no + 1}）" if len(chunks) > 1 else "")
        page.items.append(dx.TextBox(Box(mm2pt(15), mm2pt(12), mm2pt(180), mm2pt(10)),
                                     [title], dx.GOTHIC, 15, 17, False, False,
                                     "写真配置一覧", False, "中央", True))
        page.items.append(dx.Table(Box(mm2pt(15), mm2pt(25), mm2pt(180), mm2pt(255)),
                                   widths, rows, 6.0, dx.GOTHIC, True, "写真配置表"))
        pages.append(page)
    return dx.write_docx(path, g, pages)
