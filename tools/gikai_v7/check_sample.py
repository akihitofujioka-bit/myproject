"""役場の Word で字が欠けないかを確かめる見本（架空の第998号）を作る。

どの段も字で埋まる長さの架空の文章を入れ、英数字・括弧・伸ばし棒・長い見出し・
一般質問の答弁（明朝）・特大の写真を含める。Word で開き、行の端の字が切れて
いないか、段の下端からはみ出していないかを見る。
"""

from pathlib import Path

import compose
import edition
import items
import layout
import samples
from grid import Rect
from settings import Settings

MEMBERS = ["見本 太郎", "見本 花子", "見本 次郎"]
CHAIR = "見本 次郎"

# 縦書きで向きが変わる字（伸ばし棒・括弧・英数字）を一通り含む架空の文。
SENTENCE = ("令和８年度は、見本地区のデジタル化（ＤＸ）を進め、窓口の待ち時間を"
            "約３０分短くする計画です。センターの開館は午前９時からとなります。"
            "２０２６年度の予算は１，５００万円、参加者は１２０人、問い合わせは０００－００－００００です。")


def _long(times: int) -> str:
    return SENTENCE * times


def main() -> int:
    root = Path(__file__).resolve().parent
    folder = root / "試し出力" / "確かめ用_第998号"
    issue = layout.Issue(998, 4, "令和8年4月30日")
    work = edition.Edition.create(folder, issue)
    work.settings = Settings(list(MEMBERS), CHAIR, "見本広報委員会")
    data = items.default_data(issue)
    data["cover"]["photo_caption"] = "架空の春まつりの様子"
    data["cover"]["feature_titles"] = "架空の防災特集"
    data["gyosei"] = {"title": "行政報告", "reports": [
        {"heading": "架空の防災事業について（見本地区）", "body": _long(8)},
        {"heading": "架空の交流センター", "body": _long(8)},
        {"heading": "架空の子育て支援", "body": _long(7)}]}
    data["budget"] = {"title": "令和８年度当初予算", "summary": _long(4),
                      "questions": [{"heading": "防災費", "question": "訓練の予定は。",
                                     "answer": _long(3)}]}
    bills = [("議案", "議案第１号", "架空の見本条例", "可決"),
             ("予算", "議案第２号", "架空の一般会計予算", "可決"),
             ("発議案", "発議案第１号", "架空の意見書", "可決")]
    data["shingi"].update({
        "period": "Ｒ８．３．４～３．１２",
        "counts": [{"kind": "議案", "count": 1}, {"kind": "予算", "count": 1},
                   {"kind": "発議案", "count": 1}],
        "bills": [{"kind": kind, "title": f"{number}　{title}", "description": _long(1),
                   "questions": [{"question": "開始時期は。", "answer": "４月からです。"}]}
                  for kind, number, title, _result in bills]})
    data["votes"] = items.build_votes(
        [{"kind": kind, "title": f"{number}　{title}", "result": result}
         for kind, number, title, result in bills], MEMBERS, CHAIR)
    data["committees"] = [
        {"committee": "架空総務委員会", "heading": "防災の調査", "body": _long(9)},
        {"committee": "架空産業委員会", "heading": "農業の調査", "body": _long(8)}]
    data["questions"] = [
        {"member": name, "title": f"暮らしを守る架空の施策（{n}）", "questions": [
            {"heading": f"質問の見出し{n}の{k}", "question": _long(1),
             "answer": _long(2), "answerer": "見本課長"} for k in range(1, 4)]}
        for n, name in enumerate(MEMBERS[:2], 1)]
    data["feature"] = {"title": "架空の防災特集", "body": _long(19)}
    data["last"].update({"editorial": _long(2), "free": _long(6),
                         "next_meeting": "次の定例会は６月４日（木）午前１０時に開会の予定です。"})
    work.save_items(data)

    photos = {"架空の表紙.png": (1200, 800), "架空の特大.png": (1500, 1000),
              "架空の一般質問.png": (900, 1200)}
    for name, size in photos.items():
        (work.folder / "写真" / name).write_bytes(samples._png(*size))
    cover = next(p["no"] for p in work.pages if p["section"] == layout.COVER)
    gyosei = next(p["no"] for p in work.pages if p["section"] == layout.GYOSEI)
    ippan = next(p["no"] for p in work.pages if p["section"] == layout.IPPAN)
    work.place_photo(cover, "架空の表紙.png", Rect(0, 0, 1, 1))
    # 特大の写真を置き、まわりの本文がよけて流れるかを見る。
    # 画面でクリックしたときと同じく、置けない所なら近くへ寄せる。
    for page_no, name, size, rect in ((gyosei, "架空の特大.png", "特大", Rect(1, 0, 1, 1)),
                                      (ippan, "架空の一般質問.png", "大", Rect(2, 0, 1, 1))):
        actual, moved = work.place_photo_near(page_no, name, rect, size)
        print(f"{page_no}ページに{size}の写真: {actual}" + ("（近くへ寄せた）" if moved else ""))

    paths = work.export()
    for path in paths:
        print("書き出しました: " + str(path))
    for line in work.check():
        print("確認: " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
