"""書き込み式ページで使う共通設定を管理する。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


SETTINGS_PATH = Path(__file__).resolve().parent / "設定.json"


@dataclass
class Settings:
    """賛否表と最終ページで使う、号をまたぐ設定。"""

    members: List[str] = field(default_factory=list)
    chair: str = ""
    committee: str = "議会広報発行調査特別委員会"

    @property
    def vote_members(self) -> List[str]:
        """賛否表の列に並べる議員。議長が名簿に無いときは最後に加える（議長も賛否表に載るため）。"""
        def plain(value: str) -> str:
            return "".join(str(value).split()).replace("\u3000", "")
        names = [name for name in self.members if str(name).strip()]
        if self.chair.strip() and plain(self.chair) not in {plain(name) for name in names}:
            names.append(self.chair.strip())
        return names

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        """設定ファイルが無いときや空のときも、空の設定で動かす。"""
        target = Path(path) if path is not None else SETTINGS_PATH
        if not target.is_file():
            return cls()
        data = json.loads(target.read_text(encoding="utf-8"))
        known = {key: value for key, value in data.items()
                 if key in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Optional[Path] = None) -> Path:
        """設定をツールのフォルダへ保存する。"""
        target = Path(path) if path is not None else SETTINGS_PATH
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return target
