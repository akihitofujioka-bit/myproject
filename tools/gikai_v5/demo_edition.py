"""架空の見本で第999号を作り、事務局原稿を含めて書き出す。"""

from pathlib import Path

import edition
import layout
import samples
import compose
from settings import Settings
from grid import Rect


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
    office_page = next(page["no"] for page in work.pages
                       if page["section"] == layout.GYOSEI)
    work.save_writer(office_page,
                     "【大見出し】架空の行政報告\n"
                     "【見出し】見本事業の進み具合\n"
                     "本文として、架空の取り組みを報告します。")
    work.assign(pages[0], first)
    work.assign(pages[1], second)
    # 利用者と同じく、写真フォルダへ入れてから紙面をクリックする流れを通す。
    photos = {
        "架空の表紙.png": (1200, 800),
        "架空の顔写真一.png": (600, 800),
        "架空の顔写真二.png": (600, 800),
        "架空の行政報告.png": (1000, 750),
    }
    for name, (width, height) in photos.items():
        (work.folder / "写真" / name).write_bytes(samples._png(width, height))
    cover_page = next(page["no"] for page in work.pages if page["section"] == layout.COVER)
    work.place_photo(cover_page, "架空の表紙.png", Rect(1, 2, 1, 1))
    cover_photo = next(i for i, part in enumerate(work.parts(cover_page))
                       if part.kind == "写真")
    work.set_photo_caption(cover_page, cover_photo, "見本行事の様子")

    face_rect = compose.photo_rect(work.geometry, "顔", 0, 4)
    for page_no, filename, caption in (
            (pages[0], "架空の顔写真一.png", "見本　太郎議員"),
            (pages[1], "架空の顔写真二.png", "見本　花子議員")):
        work.place_photo(page_no, filename, face_rect)
        face = next(i for i, part in enumerate(work.parts(page_no))
                    if part.kind == "写真")
        work.set_photo_caption(page_no, face, caption)

    office_sample = compose.photo_rect(work.geometry, "中", 0, 0)
    office_rect = Rect(0, work.geometry.lines_per_dan - office_sample.line_span,
                       office_sample.dan_span, office_sample.line_span)
    work.place_photo(office_page, "架空の行政報告.png", office_rect)
    paths = work.export()
    for path in paths:
        print(f"書き出しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
