"""V7 の架空入力で「試し出力/第999号」を作り、Wordまで書き出す。"""

from pathlib import Path

import compose
import edition
import items
import layout
import samples
from grid import Rect
from settings import Settings


def main() -> int:
    root = Path(__file__).resolve().parent
    folder = root / "試し出力" / "第999号"
    issue = layout.Issue(999, 4, "令和8年4月30日")
    work = edition.Edition.create(folder, issue)
    work.settings = Settings(["見本 太郎", "見本 花子", "見本 次郎"], "見本 次郎",
                             "見本広報委員会")
    data = items.default_data(issue)
    data["cover"]["photo_caption"] = "架空の春まつりの様子"
    data["cover"]["feature_titles"] = "架空の防災特集"
    data["gyosei"] = {"title": "行政報告", "reports": [
        {"heading": "架空の防災事業", "body": "見本地区で架空の訓練を実施しました。"},
        {"heading": "架空の交流事業", "body": "見本会館で交流会を開きました。"}]}
    data["budget"] = {"title": "令和8年度当初予算", "summary": "架空の新年度予算の概要です。",
                      "questions": [{"heading": "防災費", "question": "訓練の予定は。",
                                     "answer": "見本地区で秋に行います。"}]}
    data["shingi"].update({
        "period": "R8.3.4～3.12",
        "counts": [{"kind": "条例", "count": 1}, {"kind": "予算", "count": 1}],
        "bills": [{"kind": "条例", "title": "架空の見本条例",
                   "description": "架空制度を整える条例です。",
                   "questions": [{"question": "開始時期は。", "answer": "4月からです。"}]}]})
    data["votes"] = items.build_votes(
        [{"kind": "議案", "title": "架空の見本条例", "result": "原案可決"}],
        work.settings.members, work.settings.chair)
    data["committees"] = [
        {"committee": "架空総務委員会", "heading": "防災の調査", "body": "見本施設を調査しました。"},
        {"committee": "架空産業委員会", "heading": "農業の調査", "body": "見本農園を調査しました。"}]
    data["questions"] = [
        {"member": "見本 太郎", "title": "暮らしを守る架空の防災", "questions": [
            {"heading": "避難所の備え", "question": "備蓄の状況は。",
             "answer": "架空倉庫に備えています。", "answerer": "見本課長"}]},
        {"member": "見本 花子", "title": "架空の子育て支援", "questions": [
            {"heading": "相談窓口", "question": "新しい窓口は。",
             "answer": "見本庁舎に設けます。", "answerer": "見本室長"}]}]
    data["feature"] = {"title": "架空の防災特集", "body": "住民参加の架空訓練を紹介します。"}
    data["last"].update({"editorial": "架空の編集後記です。",
                         "free": "架空の催しをお知らせします。",
                         "next_meeting": "次の定例会は6月4日午前10時に開会の予定です。"})
    work.save_items(data)

    photos = {"架空の表紙.png": (1200, 800), "架空の行政報告.png": (1000, 750)}
    for name, size in photos.items():
        (work.folder / "写真" / name).write_bytes(samples._png(*size))
    cover = next(p["no"] for p in work.pages if p["section"] == layout.COVER)
    gyosei = next(p["no"] for p in work.pages if p["section"] == layout.GYOSEI)
    work.place_photo(cover, "架空の表紙.png", Rect(0, 0, 1, 1))
    part = next(i for i, value in enumerate(work.parts(cover)) if value.kind == "写真")
    work.set_photo_caption(cover, part, "架空の春まつりの様子")
    sample = compose.photo_rect(work.geometry, "中", 0, 0)
    work.place_photo(gyosei, "架空の行政報告.png",
                     Rect(0, work.geometry.lines_per_dan - sample.line_span, 1, 1))

    paths = work.export()
    for path in paths:
        print("書き出しました: " + str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
