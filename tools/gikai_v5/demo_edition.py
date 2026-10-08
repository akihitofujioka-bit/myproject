"""架空の見本で第999号を作り、一般質問 2 ページを書き出す。"""

from pathlib import Path

import edition
import layout
import samples
from settings import Settings


def main() -> int:
    root = Path(__file__).resolve().parent
    folder = root / "試し出力" / "第999号"
    sources = root / "試し出力" / "段階5見本原稿"
    first = samples.make_ippan_docx(sources / "一般質問_見本太郎.docx")
    second = samples.make_overflow_ippan_docx(sources / "一般質問_見本花子.docx")
    work = edition.Edition.create(
        folder, layout.Issue(999, 4, "令和8年4月30日", questioners=2))
    work.settings = Settings(samples.SAMPLE_MEMBERS, samples.SAMPLE_MEMBERS[0],
                             "議会広報発行調査特別委員会")
    forms = samples.sample_forms()
    for page in work.pages:
        if page["section"] in forms:
            work.set_form(page["no"], forms[page["section"]])
    pages = [page["no"] for page in work.pages if page["section"] == layout.IPPAN]
    work.assign(pages[0], first)
    work.assign(pages[1], second)
    paths = work.export()
    for path in paths:
        print(f"書き出しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
