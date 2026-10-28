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
    data["gyosei"] = {"title": items.GYOSEI_TITLE, "reports": [
        {"heading": "架空の防災事業について（見本地区）", "body": _long(8)},
        {"heading": "架空の交流センター", "body": _long(8)},
        {"heading": "架空の子育て支援", "body": _long(7)}]}
    data["budget"] = {"title": "令和８年度当初予算", "summary": _long(4),
                      "questions": [{"heading": "防災費", "question": "訓練の予定は。",
                                     "answer": _long(3)}]}
    # 当初予算の見開き（金額・事業はすべて架空）
    yosan = data["yosan"]
    yosan.update({"general_total": "５４億１，１３９万円", "headline": "見本村７２億円でスタート",
                  "previous_title": "令和７年度補正予算"})
    yosan["chart_items"] = [
        {"item": "総務費", "name": "架空の納税関連事業", "text": "返礼品の送付などに使います。"},
        {"item": "民生費", "name": "架空の子育て応援事業", "text": "子育て世帯へ見本の支援をします。"},
        {"item": "衛生費", "name": "架空の地域医療支援", "text": "見本診療所の運営を支えます。"},
        {"item": "土木費", "name": "架空の道路改良事業", "text": "見本線の改良を進めます。"}]
    for account, amount in zip(yosan["accounts"], ("※２億６，６６０万円", "６億９，７８３万円",
                                                   "７億　５１５万円", "１億１，８４５万円")):
        account["amount"] = amount
    yosan["accounts"][0]["note"] = "※は収益的支出と資本的支出の合計（架空）"
    yosan["focus"] = [
        {"name": "架空の住宅耐震対策事業", "amount": "７，２１７万円",
         "text": "住宅耐震改修補助金　前年度比１０件増、見本ブレーカーの購入費を補助"},
        {"name": "架空の公園整備事業", "amount": "５，１００万円", "text": "見本地区の公園を水害に強く整備します。"},
        {"name": "架空のスポーツ大会事業", "amount": "２億１０万円（寄付金活用）", "text": "見本大会を開きます。"},
        {"name": "架空の水道料金減免", "amount": "２，２２６万円",
         "text": "物価高騰支援策により、基本料金を令和８年４月検針分から令和９年３月検針分までを減免"}]
    yosan["previous"] = [{"name": "見本小学校の大規模改修", "amount": "１億２，２９７万円",
                          "text": "令和７年度の補正予算で行う架空の改修です。"}]
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
        {"committee": "架空総務常任委員会", "heading": "見本施設の整備を国・県にも要望",
         "body": "【見出し】調査日\n" + _long(4) + "\n【見出し】所感\n" + _long(4)},
        {"committee": "架空産業厚生常任委員会", "heading": "見本農園の取り組みを調査",
         "body": "【見出し】調査日\n" + _long(4) + "\n【見出し】所感\n" + _long(3)}]
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


def make_kessan() -> int:
    """10 月号（決算のページあり）の確かめ用の見本（架空の第997号）を作る。金額はすべて架空。"""
    root = Path(__file__).resolve().parent
    issue = layout.Issue(997, 10, "令和8年10月31日")
    work = edition.Edition.create(root / "試し出力" / "確かめ用_第997号", issue)
    work.settings = Settings(list(MEMBERS), CHAIR, "見本広報委員会")
    data = items.default_data(issue)
    amounts = [("７億　７３１万円", "７億　　８８万円"), ("７億　４１０万円", "６億９，１７８万円"),
               ("１億１，６１４万円", "１億１，２６０万円"), ("１億６，１７０万円", "１億４，３９３万円"),
               ("３，７１０万円", "１億　３４２万円")]
    for account, (revenue, expense) in zip(data["kessan"]["accounts"], amounts):
        account.update({"revenue": revenue, "expense": expense})
    data["kessan"]["questions"] = [
        {"heading": "一般会計", "question": "架空住宅の使用料の未納が増えているが、対応はどうか。",
         "answer": "令和７年度は１０人のうち４人が納付済みとなった。引き続き納付を呼びかけていく。"},
        {"heading": "簡易水道事業会計", "question": "施設の耐震化に向け、料金の見直しは考えているか。",
         "answer": "現在、経営計画を取りまとめており、早ければ１２月議会に提案できるよう調整している。"}]
    (work.folder / "写真" / "架空の決算審査.png").write_bytes(samples._png(1600, 900))
    data["kessan"]["photo"] = "架空の決算審査.png"
    work.save_items(data)
    for path in work.export():
        print("書き出しました: " + str(path))
    for line in work.check():
        print("確認: " + line)
    return 0


if __name__ == "__main__":
    main()
    raise SystemExit(make_kessan())
