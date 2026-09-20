"""取り出した文字を分類して、日報・週報・月報の Markdown を組み立てる。

要約は LLM を使わない「語句の一致」による機械的な振り分け（config.json の classify）。
外部に何も送らない代わりに、文章の言い換えはしないので、出力は下書きとして人が手直しする前提。
書式は reports/daily/（/report スキル）の日報に合わせている。
"""

import re
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from extractors import KIND_LABEL

WEEKDAYS = "月火水木金土日"
DAILY_SECTIONS = ["会議・打ち合わせ", "その他の業務", "明日の予定", "課題・相談事項"]
SECTION_OF = {"meeting": "会議・打ち合わせ", "other": "その他の業務", "tomorrow": "明日の予定", "issue": "課題・相談事項"}
EMPTY_TEXT = {"会議・打ち合わせ": "記録なし", "その他の業務": "記録なし", "明日の予定": "特になし", "課題・相談事項": "特になし"}
NOTE_HEADER = "### 確認してほしい点（報告書には含めない）"
PLACEHOLDER_PREFIXES = ("記録なし", "特になし", "（")


def jp_date(d: date) -> str:
    return "%s（%s）" % (d.isoformat(), WEEKDAYS[d.weekday()])


def short_date(d: date) -> str:
    return "%d/%d（%s）" % (d.month, d.day, WEEKDAYS[d.weekday()])


# ---------------------------------------------------------------- 行の整形と分類

_BULLET = re.compile(r"^[\s\-\*・•●○◎□■☐☑✓✔▶►→⇒＞>]+|^[\(（]?\d{1,2}[\)）\.．、]\s*|^[①-⑳]\s*")
_DATE_ONLY = re.compile(r"^[\d\s/:\-年月日時分（）()曜]*$")


def normalize_line(s: str) -> str:
    s = s.replace("　", " ").strip()
    s = _BULLET.sub("", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s


def split_lines(text: str) -> List[str]:
    """本文を「1 項目 1 行」に分ける。長い行は文（。）で分ける。"""
    out: List[str] = []
    for raw in text.splitlines():
        line = normalize_line(raw)
        if not line or line.startswith("【シート:") or line.startswith("【見出し】"):
            continue
        pieces = [line]
        if len(line) > 60 and "。" in line:
            pieces = [p + "。" for p in line.split("。") if p.strip()]
            pieces[-1] = pieces[-1] if line.endswith("。") else pieces[-1][:-1]
        for p in pieces:
            p = p.strip()
            if len(p) < 2 or _DATE_ONLY.match(p):
                continue
            out.append(p)
    return out


def classify(line: str, cfg: Dict) -> str:
    for cat in ("issue", "tomorrow", "meeting"):
        if any(k and k in line for k in cfg.get(cat, [])):
            return cat
    return "other"


def is_excluded(line: str, topics: List[str]) -> bool:
    return any(t and t in line for t in topics)


# ---------------------------------------------------------------- 日報

class Material:
    """素材 1 件（ファイル、日時、取り出した文字）。"""

    def __init__(self, path: Path, dt: datetime, basis: str, info: Dict):
        self.path = path
        self.dt = dt
        self.basis = basis
        self.info = info

    @property
    def kind(self) -> str:
        return self.info.get("kind") or "?"

    def describe(self) -> str:
        """素材欄の見出し用: 「画像 → OCR、確度 0.50」など。"""
        k = KIND_LABEL.get(self.kind, self.kind)
        m = self.info.get("method", "")
        if self.info.get("error"):
            return "%s → 読み取り失敗" % k
        if self.kind in ("image", "pdf"):
            how = "文字層を利用" if m == "pdftext" else "OCR、確度 %.2f" % self.info.get("confidence", 0)
            pages = self.info.get("pages", 1)
            return "%s → %s%s" % (k, how, "、%d ページ" % pages if pages > 1 else "")
        if self.kind == "audio":
            sec = self.info.get("duration", 0)
            length = "%d分" % round(sec / 60) if sec >= 60 else "%d秒" % round(sec)
            return "%s %s → 文字起こし（%s）" % (k, length, m)
        return k


def build_daily(day: date, materials: List[Material], config: Dict) -> str:
    cls_cfg = config.get("classify", {})
    topics = config.get("privacy", {}).get("excludeTopics", [])
    long_lines = int(config.get("longSourceLines", 20))
    max_hits = int(config.get("maxHitsPerLongSource", 15))
    low_conf = float(config.get("ocr", {}).get("lowConfidence", 0.45))

    sections: "OrderedDict[str, List[str]]" = OrderedDict((s, []) for s in DAILY_SECTIONS)
    notes: List[str] = []
    seen = set()
    excluded_count = 0
    materials = sorted(materials, key=lambda m: (m.dt, m.path.name))

    for m in materials:
        if m.info.get("error"):
            notes.append("「%s」は読めませんでした: %s" % (m.path.name, m.info["error"]))
            continue
        lines = split_lines(m.info.get("text", ""))
        if not lines:
            notes.append("「%s」から文字を取り出せませんでした（白紙・無音・判読不能の可能性）" % m.path.name)
            continue
        if m.kind in ("image", "pdf") and m.info.get("method") == "ocr" and m.info.get("confidence", 1) < low_conf:
            notes.append("「%s」の OCR 確度が低め（%.2f）。誤読がないか原文と照合してください"
                         % (m.path.name, m.info.get("confidence", 0)))
        is_long = len(lines) > long_lines
        tag = "（%s）" % m.path.name if is_long else ""
        hits = 0
        for line in lines:
            if is_excluded(line, topics):
                excluded_count += 1
                continue
            key = re.sub(r"[\s。、.,]", "", line)
            if key in seen:
                continue
            cat = classify(line, cls_cfg)
            if is_long and cat == "other":
                continue
            if is_long:
                hits += 1
                if hits > max_hits:
                    break
            seen.add(key)
            sections[SECTION_OF[cat]].append(line + tag)
        if is_long:
            summary = "「%s」（%s）は内容が長いため、語句に一致した行だけ上に載せた。全文は下の素材欄" % (m.path.name, m.describe())
            if hits > max_hits:
                summary += "（該当行が多いため %d 件で打ち切り）" % max_hits
            sections["その他の業務"].append(summary)

    if excluded_count:
        sections["その他の業務"].append("非公開の議題あり（%d 行を省略）" % excluded_count)

    out = ["# 日報 %s" % jp_date(day), ""]
    for name, items in sections.items():
        out.append("## " + name)
        out.extend("- " + it for it in items) if items else out.append("- " + EMPTY_TEXT[name])
        out.append("")

    out += ["---", NOTE_HEADER]
    notes.append("各節への振り分けは語句の一致による機械的なもの（設定 classify）。取り違えがあれば直してください")
    out.extend("- " + n for n in notes)
    out.append("")

    out.append("### 素材（%d件）" % len(materials))
    if not materials:
        out.append("- この日の素材はありません")
    for i, m in enumerate(materials, 1):
        out.append("#### %d. %s %s（%s、日付の根拠: %s）"
                   % (i, m.dt.strftime("%H:%M"), m.path.name, m.describe(), m.basis))
        if m.info.get("error"):
            out.append("> 読み取り失敗: " + m.info["error"])
        else:
            body = m.info.get("text", "").strip() or "（文字なし）"
            for raw in body.splitlines():
                raw = raw.rstrip()
                if is_excluded(raw, topics):
                    raw = "（非公開の議題のため省略）"
                out.append("> " + raw)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- 日報の読み戻し（週報・月報の材料）

def parse_report(md: str) -> Dict[str, List[str]]:
    """日報の本文（--- より上）を節ごとの箇条書きに戻す。手で直した内容もそのまま拾う。"""
    sections: Dict[str, List[str]] = {}
    current = None
    for line in md.splitlines():
        if line.strip() == "---":
            break
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current and line.startswith("- "):
            item = line[2:].strip()
            if item and not item.startswith(PLACEHOLDER_PREFIXES):
                sections[current].append(item)
    return sections


def _uniq(items: List[str]) -> List[str]:
    seen, out = set(), []
    for it in items:
        key = re.sub(r"[\s。、.,（）()]", "", it)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _kind_summary(kinds: Counter) -> str:
    order = list(KIND_LABEL)  # テキスト・Word・Excel・画像・PDF・音声 の順
    return "、".join("%s %d" % (KIND_LABEL.get(k, k), n)
                     for k, n in sorted(kinds.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99))


# ---------------------------------------------------------------- 週報

def week_range(day: date) -> "tuple[date, date]":
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def build_weekly(day: date, dailies: "OrderedDict[date, Dict[str, List[str]]]",
                 kinds_by_day: Dict[date, Counter], config: Dict) -> str:
    monday, sunday = week_range(day)
    iso = day.isocalendar()
    out = ["# 週報 %s 〜 %s（%d年 第%d週）" % (jp_date(monday), jp_date(sunday), iso[0], iso[1]), ""]

    total_kinds: Counter = Counter()
    for c in kinds_by_day.values():
        total_kinds.update(c)
    days_with = [d for d in dailies if any(dailies[d].values())]
    out.append("## サマリ")
    out.append("- 日報のある日: %d 日（%s）" % (len(dailies), "、".join(short_date(d) for d in dailies)) if dailies
               else "- この週の日報はありません（素材フォルダに該当する日付のファイルがありません）")
    if total_kinds:
        out.append("- 素材: %d 件（%s）" % (sum(total_kinds.values()), _kind_summary(total_kinds)))
    meetings = sum(len(s.get("会議・打ち合わせ", [])) for s in dailies.values())
    issues = _uniq([it for s in dailies.values() for it in s.get("課題・相談事項", [])])
    out.append("- 会議・打ち合わせ %d 件、課題・相談事項 %d 件" % (meetings, len(issues)))
    out.append("")

    def per_day(section: str, title: str, empty: str):
        out.append("## " + title)
        any_item = False
        for d, s in dailies.items():
            items = s.get(section, [])
            if not items:
                continue
            any_item = True
            out.append("- **%s**" % short_date(d))
            out.extend("  - " + it for it in items)
        if not any_item:
            out.append("- " + empty)
        out.append("")

    per_day("会議・打ち合わせ", "主な会議と決定事項", "記録なし")
    per_day("その他の業務", "進行中の案件", "記録なし")

    out.append("## 来週の予定")
    plans: List[str] = []
    if days_with:
        plans += dailies[days_with[-1]].get("明日の予定", [])
    for s in dailies.values():
        for items in s.values():
            plans += [it for it in items if "来週" in it]
    plans = _uniq(plans)
    out.extend("- " + p for p in plans) if plans else out.append("- 特になし")
    out.append("")

    out.append("## リスク・課題")
    out.extend("- " + it for it in issues) if issues else out.append("- 特になし")
    out.append("")

    out += ["---", NOTE_HEADER,
            "- 各日の日報（%s）をそのまま束ねたもの。日報を直してから週報を作り直すと反映されます" % config.get("folders", {}).get("daily", "日報"),
            "- 「来週の予定」は最終日の「明日の予定」と、週内で「来週」と書かれた行を集めたもの", ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- 月報

def month_range(day: date) -> "tuple[date, date]":
    first = day.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, nxt - timedelta(days=1)


def month_weeks(first: date, last: date) -> List["tuple[date, date]"]:
    """月を月曜始まりの週に切る（月初・月末は途中で切れる）。"""
    weeks = []
    start = first
    while start <= last:
        end = min(start + timedelta(days=6 - start.weekday()), last)
        weeks.append((start, end))
        start = end + timedelta(days=1)
    return weeks


def build_monthly(day: date, dailies: "OrderedDict[date, Dict[str, List[str]]]",
                  kinds_by_day: Dict[date, Counter], config: Dict) -> str:
    first, last = month_range(day)
    out = ["# 月報 %d年%d月（%s 〜 %s）" % (first.year, first.month, first.isoformat(), last.isoformat()), ""]

    total_kinds: Counter = Counter()
    for c in kinds_by_day.values():
        total_kinds.update(c)
    meetings_all = [(d, it) for d, s in dailies.items() for it in s.get("会議・打ち合わせ", [])]
    issues = _uniq([it for s in dailies.values() for it in s.get("課題・相談事項", [])])

    out.append("## サマリ")
    out.append("- 日報のある日: %d 日" % len(dailies) if dailies
               else "- この月の日報はありません（素材フォルダに該当する日付のファイルがありません）")
    if total_kinds:
        out.append("- 素材: %d 件（%s）" % (sum(total_kinds.values()), _kind_summary(total_kinds)))
    out.append("- 会議・打ち合わせ %d 件、課題・相談事項 %d 件" % (len(meetings_all), len(issues)))
    out.append("")

    out.append("## 週ごとの主な動き")
    any_week = False
    for n, (ws, we) in enumerate(month_weeks(first, last), 1):
        items: List[str] = []
        for d, s in dailies.items():
            if ws <= d <= we:
                items += [("%s %s" % (short_date(d), it)) for it in s.get("会議・打ち合わせ", []) + s.get("その他の業務", [])]
        if not items:
            continue
        any_week = True
        out.append("### 第%d週（%d/%d〜%d/%d）" % (n, ws.month, ws.day, we.month, we.day))
        out.extend("- " + it for it in items)
        out.append("")
    if not any_week:
        out += ["- 記録なし", ""]

    out.append("## 会議・打ち合わせ一覧")
    out.extend("- %s %s" % (short_date(d), it) for d, it in meetings_all) if meetings_all else out.append("- 記録なし")
    out.append("")

    out.append("## 課題・相談事項")
    out.extend("- " + it for it in issues) if issues else out.append("- 特になし")
    out.append("")

    out.append("## 来月の予定")
    plans: List[str] = []
    days = list(dailies)
    if days:
        plans += dailies[days[-1]].get("明日の予定", [])
    for s in dailies.values():
        for items in s.values():
            plans += [it for it in items if "来月" in it]
    plans = _uniq(plans)
    out.extend("- " + p for p in plans) if plans else out.append("- 特になし")
    out.append("")

    out += ["---", NOTE_HEADER,
            "- 各日の日報をそのまま束ねたもの。日報を直してから月報を作り直すと反映されます",
            "- 「来月の予定」は最終日の「明日の予定」と、月内で「来月」と書かれた行を集めたもの", ""]
    return "\n".join(out).rstrip() + "\n"
