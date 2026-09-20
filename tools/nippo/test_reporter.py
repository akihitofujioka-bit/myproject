"""reporter.py の簡単な確認（OCR・Whisper を使わない部分だけ）。

    python3 tools/nippo/test_reporter.py
"""

import sys
from collections import Counter, OrderedDict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reporter  # noqa: E402
from reporter import Material  # noqa: E402

CFG = {
    "classify": {"meeting": ["打合せ", "会議"], "tomorrow": ["明日", "来週"], "issue": ["課題", "要確認"]},
    "privacy": {"excludeTopics": ["人事"]},
    "longSourceLines": 4, "maxHitsPerLongSource": 2, "ocr": {"lowConfidence": 0.45},
}


def test_split_and_classify():
    lines = reporter.split_lines("・午前 校正\n【シート: 進捗】\n【見出し】業務 | 期限\n2026/09/21\n① 明日 報告")
    assert lines == ["午前 校正", "明日 報告"], lines
    assert reporter.classify("総務課と打合せ", CFG["classify"]) == "meeting"
    assert reporter.classify("打合せの日程が課題", CFG["classify"]) == "issue"
    assert reporter.classify("校正した", CFG["classify"]) == "other"


def test_daily_and_parse():
    day = date(2026, 9, 21)
    memo = Material(Path("メモ.txt"), datetime(2026, 9, 21, 9), "ファイル名",
                    {"kind": "text", "text": "総務課と打合せ\n課題: 写真未了\n人事評価の話\n明日 議長へ報告"})
    ocr = Material(Path("手書き.jpg"), datetime(2026, 9, 21, 10), "撮影日時",
                   {"kind": "image", "method": "ocr", "confidence": 0.3, "text": "総務課と打合せ"})
    long = Material(Path("録音.m4a"), datetime(2026, 9, 21, 14), "録音日時",
                    {"kind": "audio", "method": "whisper-medium", "duration": 30,
                     "text": "雑談\n会議を始めます\n議題は課題の整理\n来週までに\nまた会議"})
    bad = Material(Path("古い.xls"), datetime(2026, 9, 21, 15), "ファイル名", {"kind": "excel", "error": "旧形式"})
    md = reporter.build_daily(day, [memo, ocr, long, bad], CFG)
    sections = reporter.parse_report(md)
    assert sections["会議・打ち合わせ"] == ["総務課と打合せ", "会議を始めます（録音.m4a）"], sections
    assert sections["課題・相談事項"] == ["課題: 写真未了", "議題は課題の整理（録音.m4a）"]
    assert sections["明日の予定"] == ["明日 議長へ報告"]  # 長い素材は上限 2 件で打ち切り
    assert any("非公開の議題あり（1 行を省略）" in s for s in sections["その他の業務"])
    assert "人事評価" not in md
    assert "OCR 確度が低め（0.30）" in md
    assert "「古い.xls」は読めませんでした: 旧形式" in md
    assert "音声 30秒" in md


def test_weekly_monthly():
    d1, d2 = date(2026, 9, 15), date(2026, 9, 19)
    dailies = OrderedDict([
        (d1, {"会議・打ち合わせ": ["A会議"], "その他の業務": [], "明日の予定": ["明日B"], "課題・相談事項": ["C課題"]}),
        (d2, {"会議・打ち合わせ": [], "その他の業務": ["来週D入稿"], "明日の予定": ["E報告"], "課題・相談事項": ["C課題"]}),
    ])
    kinds = {d1: Counter({"text": 1}), d2: Counter({"image": 2})}
    w = reporter.build_weekly(d1, dailies, kinds, CFG)
    assert "# 週報 2026-09-14（月） 〜 2026-09-20（日）" in w
    assert "- 素材: 3 件（テキスト 1、画像 2）" in w
    assert w.count("C課題") == 1, "課題は名寄せされる"
    assert "- E報告" in w and "- 来週D入稿" in w and "明日B" not in w.split("## 来週の予定")[1]
    m = reporter.build_monthly(d1, dailies, kinds, CFG)
    assert "### 第3週（9/14〜9/20）" in m and "9/15（火） A会議" in m
    assert reporter.month_range(date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert reporter.month_weeks(date(2026, 9, 1), date(2026, 9, 30))[0] == (date(2026, 9, 1), date(2026, 9, 6))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
    print("すべて通りました")
