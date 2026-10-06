#!/usr/bin/env python3
"""複数台の録音から1本の逐語録を組み立てる。

決定的な処理だけを担当する:
  - segment.start_time（録音開始からの相対ミリ秒）を絶対時刻に直して整列する
  - 録音ごとのカバー範囲と、主録音に欠けている区間を検出する
  - 録音をまたいだ話者ラベルの対応候補を、発話時間の重なりから出す
  - 重なり区間で両録音の文字起こしが食い違う箇所に印を付ける

「どちらを主にするか」「欠落をどちらで埋めるか」「Speaker 1 が誰か」といった
判断はこのスクリプトでは決めない。references/verbatim.md を読んで人が決め、
build に引数で渡す。

使い方:
    merge_transcripts.py analyze rec_a.json rec_b.json [--json]
    merge_transcripts.py build  rec_a.json rec_b.json --primary A \\
        --fill-outside B --name "A/Speaker 1=委員長" -o out.md

入力JSON（録音1本につき1ファイル）:
    {
      "label": "A",                                # 短い識別子
      "file_id": "...",
      "name": "08-27 会議: ...",
      "start_at": "2026-08-27T04:25:23Z",          # UTC。list_files の値をそのまま
      "duration_ms": 4589000,
      "pages": [ <get_transcript の応答をそのまま>, ... ]
    }
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")

# 既定のしきい値。いずれもコマンドラインで変えられる。
DEFAULT_SILENCE_GAP_S = 20.0     # 主録音の無音がこれ以上続いたら欠落候補として見る
DEFAULT_MERGE_GAP_S = 5.0        # 発話区間をつなげて「カバー範囲」とみなす間隔
DEFAULT_PADDING_S = 20.0         # 照合相手を拾う前後の余裕
MIN_FLAG_CHARS = 12              # 短すぎる相槌は食い違い判定から外す

# 照合に使う語。発言の骨格になり、かつ音声認識が崩しやすいものだけを見る。
# 助詞や活用まで比べると、機器ごとの揺れで全発言が引っかかって使い物にならない。
KATAKANA_RE = re.compile(r"[ァ-ヶ][ァ-ヶー]{2,}")
LATIN_RE = re.compile(r"[A-Za-z]{2,}")
NUMBER_RE = re.compile(r"[0-9]{2,}")
# 漢字語は「相手にも似た語がある」ときだけ見る。崖崩れ→学級崩れのような聞き違いは
# 字面が近い別語として現れるので、同じ長さで部分一致でない相手を探して対にする。
KANJI_RE = re.compile(r"[一-龥]{2,}")
NEAR_MISS_MIN = 0.33


# --------------------------------------------------------------------------
# 読み込み
# --------------------------------------------------------------------------

def parse_start_at(value: str) -> datetime:
    """start_at を UTC の datetime にする。PLAUD の start_at は UTC。"""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Recording:
    def __init__(self, path: str, raw: dict):
        self.path = path
        self.label = str(raw.get("label") or raw.get("file_id") or path)
        self.file_id = raw.get("file_id", "")
        self.name = raw.get("name", "")
        self.serial_number = raw.get("serial_number", "")
        self.start_at = parse_start_at(raw["start_at"])
        self.start_ms = int(self.start_at.timestamp() * 1000)
        self.duration_ms = raw.get("duration_ms")
        self.warnings: list[str] = []

        pages = raw.get("pages") or []
        if isinstance(pages, dict):           # ページが1つだけ素で入っていても受ける
            pages = [pages]
        segments: list[dict] = []
        totals = set()
        blocks = set()
        for page in pages:
            if "total" in page:
                totals.add(page["total"])
            if page.get("block"):
                blocks.add(page["block"])
            for seg in page.get("segments", []):
                segments.append(
                    {
                        "rel_start": int(seg["start_time"]),
                        "rel_end": int(seg.get("end_time", seg["start_time"])),
                        "speaker": seg.get("speaker") or seg.get("original_speaker") or "不明",
                        "content": (seg.get("content") or "").strip(),
                        "rec": self,
                    }
                )
        segments.sort(key=lambda s: (s["rel_start"], s["rel_end"]))
        for seg in segments:
            seg["abs_start"] = self.start_ms + seg["rel_start"]
            seg["abs_end"] = self.start_ms + seg["rel_end"]
        self.segments = segments
        self.block = ", ".join(sorted(blocks)) if blocks else ""

        if len(totals) == 1:
            total = totals.pop()
            if total != len(segments):
                self.warnings.append(
                    f"total={total} に対し {len(segments)} セグメントしか読めていない。"
                    "next_cursor を最後までたどったか確認すること"
                )
        elif len(totals) > 1:
            self.warnings.append(f"ページ間で total が食い違っている: {sorted(totals)}")
        if blocks and blocks != {"transaction_polish"}:
            self.warnings.append(
                f"block が transaction_polish 以外を含む: {sorted(blocks)}。"
                "議事録の土台には transaction_polish を使う"
            )
        if not segments:
            self.warnings.append("セグメントが0件。文字起こし未実施の可能性がある")

    # -- 範囲まわり ---------------------------------------------------------

    @property
    def covered(self) -> tuple[int, int] | None:
        if not self.segments:
            return None
        return (
            min(s["abs_start"] for s in self.segments),
            max(s["abs_end"] for s in self.segments),
        )

    def speech_intervals(self, merge_gap_ms: int) -> list[list[int]]:
        """発話区間を merge_gap でつないだもの。"""
        merged: list[list[int]] = []
        for seg in sorted(self.segments, key=lambda s: s["abs_start"]):
            if merged and seg["abs_start"] - merged[-1][1] <= merge_gap_ms:
                merged[-1][1] = max(merged[-1][1], seg["abs_end"])
            else:
                merged.append([seg["abs_start"], seg["abs_end"]])
        return merged

    def speech_ms_in(self, start: int, end: int) -> int:
        return sum(
            max(0, min(end, iv[1]) - max(start, iv[0]))
            for iv in self.speech_intervals(0)
        )


def load_recordings(paths: list[str]) -> list[Recording]:
    recs = []
    seen = set()
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            rec = Recording(path, json.load(fh))
        if rec.label in seen:
            sys.exit(f"エラー: label が重複している: {rec.label}")
        seen.add(rec.label)
        recs.append(rec)
    if not recs:
        sys.exit("エラー: 録音ファイルが指定されていない")
    return sorted(recs, key=lambda r: r.start_ms)


# --------------------------------------------------------------------------
# 時刻表示
# --------------------------------------------------------------------------

def jst(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, JST)


def clock(ms: int) -> str:
    return jst(ms).strftime("%H:%M:%S")


def hms(delta_ms: int) -> str:
    total = int(round(abs(delta_ms) / 1000))
    sign = "-" if delta_ms < 0 else ""
    return f"{sign}{total // 3600:d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def dur(ms: int) -> str:
    total = int(round(ms / 1000))
    if total >= 60:
        return f"{total // 60}分{total % 60:02d}秒"
    return f"{total}秒"


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def find_gaps(primary: Recording, others: list[Recording],
              silence_gap_ms: int, merge_gap_ms: int) -> list[dict]:
    """主録音に無い/欠けている区間で、他録音が拾えているものを返す。"""
    gaps: list[dict] = []
    prim = primary.covered
    if prim is None:
        return gaps

    candidates: list[tuple[str, int, int]] = []
    union_start = min([prim[0]] + [o.covered[0] for o in others if o.covered])
    union_end = max([prim[1]] + [o.covered[1] for o in others if o.covered])
    if union_start < prim[0]:
        candidates.append(("head", union_start, prim[0]))
    if union_end > prim[1]:
        candidates.append(("tail", prim[1], union_end))

    intervals = primary.speech_intervals(merge_gap_ms)
    for left, right in zip(intervals, intervals[1:]):
        if right[0] - left[1] >= silence_gap_ms:
            candidates.append(("inside", left[1], right[0]))

    for kind, start, end in candidates:
        covers = []
        for other in others:
            speech = other.speech_ms_in(start, end)
            if speech > 0:
                covers.append({"label": other.label, "speech_ms": speech})
        covers.sort(key=lambda c: -c["speech_ms"])
        gaps.append(
            {
                "kind": kind,
                "start": start,
                "end": end,
                "length_ms": end - start,
                "covered_by": covers,
            }
        )
    return sorted(gaps, key=lambda g: g["start"])


def speaker_candidates(primary: Recording, other: Recording) -> list[dict]:
    """other の各話者が、時間的にどの primary 話者と重なるかを出す。"""
    prim_c, other_c = primary.covered, other.covered
    if not prim_c or not other_c:
        return []
    lo, hi = max(prim_c[0], other_c[0]), min(prim_c[1], other_c[1])
    if lo >= hi:
        return []

    prim_segs = [s for s in primary.segments if s["abs_end"] > lo and s["abs_start"] < hi]
    result = []
    for spk in sorted({s["speaker"] for s in other.segments}):
        own = [
            s for s in other.segments
            if s["speaker"] == spk and s["abs_end"] > lo and s["abs_start"] < hi
        ]
        total = sum(min(hi, s["abs_end"]) - max(lo, s["abs_start"]) for s in own)
        if total <= 0:
            continue
        overlaps: dict[str, int] = {}
        for a in own:
            for b in prim_segs:
                shared = min(a["abs_end"], b["abs_end"]) - max(a["abs_start"], b["abs_start"])
                if shared > 0:
                    overlaps[b["speaker"]] = overlaps.get(b["speaker"], 0) + shared
        ranked = sorted(overlaps.items(), key=lambda kv: -kv[1])
        result.append(
            {
                "speaker": spk,
                "speech_ms": total,
                "candidates": [
                    {"speaker": name, "overlap_ms": ms, "share": ms / total}
                    for name, ms in ranked
                ],
            }
        )
    return sorted(result, key=lambda r: -r["speech_ms"])


def analyze(recs: list[Recording], primary_label: str | None,
            silence_gap_ms: int, merge_gap_ms: int) -> dict:
    report: dict = {"recordings": [], "pairs": [], "warnings": []}

    for rec in recs:
        cov = rec.covered
        report["recordings"].append(
            {
                "label": rec.label,
                "file_id": rec.file_id,
                "name": rec.name,
                "serial_number": rec.serial_number,
                "start_at_utc": rec.start_at.isoformat().replace("+00:00", "Z"),
                "start_at_jst": jst(rec.start_ms).isoformat(),
                "duration_ms": rec.duration_ms,
                "segments": len(rec.segments),
                "block": rec.block,
                "covered_start": cov[0] if cov else None,
                "covered_end": cov[1] if cov else None,
                "covered_ms": (cov[1] - cov[0]) if cov else 0,
                "warnings": rec.warnings,
            }
        )
        for w in rec.warnings:
            report["warnings"].append(f"[{rec.label}] {w}")

    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            ca, cb = a.covered, b.covered
            overlap = 0
            if ca and cb:
                overlap = max(0, min(ca[1], cb[1]) - max(ca[0], cb[0]))
            report["pairs"].append(
                {
                    "a": a.label,
                    "b": b.label,
                    "start_gap_s": (b.start_ms - a.start_ms) / 1000,
                    "overlap_ms": overlap,
                    "same_meeting_by_overlap": overlap > 0,
                }
            )

    usable = [r for r in recs if r.covered]
    if usable:
        widest = max(usable, key=lambda r: r.covered[1] - r.covered[0])
        report["recommended_primary"] = widest.label
    else:
        report["recommended_primary"] = None

    chosen = primary_label or report["recommended_primary"]
    report["primary"] = chosen
    if chosen:
        primary = next((r for r in recs if r.label == chosen), None)
        if primary is None:
            sys.exit(f"エラー: --primary {chosen} に一致する録音がない")
        others = [r for r in recs if r is not primary]
        report["gaps"] = find_gaps(primary, others, silence_gap_ms, merge_gap_ms)
        report["speaker_candidates"] = {
            o.label: speaker_candidates(primary, o) for o in others
        }
    return report


# --------------------------------------------------------------------------
# 食い違いの検出
# --------------------------------------------------------------------------

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[\s、。,.「」『』（）()・]", "", text)


def tokens(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKC", text).replace(",", "")
    found = set()
    found |= {m.group() for m in KATAKANA_RE.finditer(norm)}
    found |= {m.group().upper() for m in LATIN_RE.finditer(norm)}
    found |= {m.group().lstrip("0") or "0" for m in NUMBER_RE.finditer(norm)}
    return found


def near_miss_pairs(mine_text: str, their_text: str) -> list[tuple[str, str, float]]:
    """こちらにあって相手に無い漢字語を、相手の似た語と対にする。

    完全に別の語どうしが対にならないよう、字数が同じで、かつ一方が他方の一部で
    ないものだけを候補にする（「事業所利用者」と「事業所」のような切れ方は
    誤認識ではなくセグメントの切れ目の差なので除く）。
    """
    mine = set(KANJI_RE.findall(mine_text))
    theirs = set(KANJI_RE.findall(their_text))
    found = []
    for token in sorted(mine - theirs):
        best, score = None, 0.0
        for other in sorted(theirs - mine):   # 実行ごとに結果が変わらないよう順序を固定
            if len(other) != len(token) or token in other or other in token:
                continue
            ratio = difflib.SequenceMatcher(None, token, other).ratio()
            if ratio > score:
                best, score = other, ratio
        if best and NEAR_MISS_MIN <= score < 1.0:
            found.append((token, best, score))
    return found


def cross_check(seg: dict, others: list[Recording], padding_ms: int,
                suspect_terms: list[str]) -> dict | None:
    """1セグメントを他録音の同時刻と突き合わせ、要確認なら所見を返す。

    録音ごとにセグメントの切れ目がずれるため、単に時間が重なる本文どうしを比べると
    隣へ押し出されただけの語が「相手に無い」と誤検出される。そこで
      - こちらだけにある語は、相手の前後 padding_ms まで広げた本文にも無いものだけ
      - 相手だけにある語は、相手セグメントの中点がこちらの区間に入るものだけ
    を採る。後者がないと、同じ食い違いが隣接する何発言にも重複して出る。
    """
    notes: dict = {"terms": [], "counterparts": []}

    for term in suspect_terms:
        if term in seg["content"]:
            notes["terms"].append(term)

    if len(normalize(seg["content"])) >= MIN_FLAG_CHARS:
        mine = tokens(seg["content"])
        lo, hi = seg["abs_start"] - padding_ms, seg["abs_end"] + padding_ms
        # 自分の前後の発言。相手にしか無いように見える語の多くはここに出ている。
        neighbours = tokens("".join(
            s["content"] for s in seg["rec"].segments
            if s is not seg and s["abs_end"] > lo and s["abs_start"] < hi
        ))

        for other in others:
            overlapping = [
                s for s in other.segments
                if s["abs_end"] > seg["abs_start"] and s["abs_start"] < seg["abs_end"]
            ]
            if not overlapping:
                continue
            wide = tokens("".join(
                s["content"] for s in other.segments
                if s["abs_end"] > lo and s["abs_start"] < hi
            ))
            owned = "".join(
                s["content"] for s in other.segments
                if seg["abs_start"] <= (s["abs_start"] + s["abs_end"]) // 2 < seg["abs_end"]
            )

            only_mine = sorted(mine - wide)
            only_theirs = sorted(tokens(owned) - mine - neighbours)
            pairs = near_miss_pairs(
                seg["content"],
                "".join(s["content"] for s in other.segments
                        if s["abs_end"] > lo and s["abs_start"] < hi),
            )
            if not only_mine and not only_theirs and not pairs:
                continue

            text = "".join(s["content"] for s in overlapping)
            notes["counterparts"].append(
                {
                    "label": other.label,
                    "ratio": difflib.SequenceMatcher(
                        None, normalize(seg["content"]), normalize(text)
                    ).ratio(),
                    "only_here": only_mine,
                    "only_there": only_theirs,
                    "pairs": pairs,
                    "text": text,
                }
            )

    if notes["terms"] or notes["counterparts"]:
        return notes
    return None


# --------------------------------------------------------------------------
# 組み立て
# --------------------------------------------------------------------------

def parse_range(text: str, recs: list[Recording]) -> tuple[Recording, int, int]:
    """--fill B:2026-08-27T13:41:52+09:00..2026-08-27T13:42:19+09:00"""
    try:
        label, span = text.split(":", 1)
        start_s, end_s = span.split("..", 1)
    except ValueError:
        sys.exit(f"エラー: --fill の書式は LABEL:開始..終了 : {text!r}")
    rec = next((r for r in recs if r.label == label), None)
    if rec is None:
        sys.exit(f"エラー: --fill が参照する録音がない: {label}")

    def to_ms(value: str) -> int:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return int(dt.timestamp() * 1000)

    return rec, to_ms(start_s), to_ms(end_s)


def resolve_speaker(seg: dict, names: dict[str, str], mapping: dict[str, str]) -> str:
    key = f"{seg['rec'].label}/{seg['speaker']}"
    key = mapping.get(key, key)
    if key in names:
        return names[key]
    label, _, spk = key.partition("/")
    return f"{spk}（{label}）"


def build(recs: list[Recording], args) -> str:
    primary = next((r for r in recs if r.label == args.primary), None)
    if primary is None:
        sys.exit(f"エラー: --primary {args.primary} に一致する録音がない")
    others = [r for r in recs if r is not primary]

    names = {}
    for item in args.name or []:
        key, _, value = item.partition("=")
        names[key.strip()] = value.strip()
    mapping = {}
    for item in args.speaker_map or []:
        key, _, value = item.partition("=")
        mapping[key.strip()] = value.strip()

    suspect_terms: list[str] = []
    if args.suspect_terms:
        with open(args.suspect_terms, encoding="utf-8") as fh:
            data = json.load(fh)
        # 素の配列でも {"terms": [...]} でも受ける。_ で始まるキーは注記。
        suspect_terms = data if isinstance(data, list) else data.get("terms", [])

    fills = [parse_range(f, recs) for f in args.fill or []]
    if args.fill_outside:
        for label in args.fill_outside:
            source = next((r for r in recs if r.label == label), None)
            if source is None:
                sys.exit(f"エラー: --fill-outside が参照する録音がない: {label}")
            for gap in find_gaps(primary, [source],
                                 int(args.silence_gap * 1000),
                                 int(args.merge_gap * 1000)):
                if gap["kind"] in ("head", "tail") and gap["covered_by"]:
                    fills.append((source, gap["start"], gap["end"]))

    # 本文に載せるセグメントを集める。主録音は全部、補完は指定区間だけ。
    picked: list[tuple[dict, str | None]] = [(s, None) for s in primary.segments]
    for source, start, end in fills:
        for seg in source.segments:
            if seg["abs_end"] > start and seg["abs_start"] < end:
                picked.append((seg, source.label))
    picked.sort(key=lambda item: (item[0]["abs_start"], item[0]["abs_end"]))

    origin = min(s["abs_start"] for s, _ in picked) if picked else primary.start_ms
    padding_ms = int(args.context_padding * 1000)

    # --- 見出し ---------------------------------------------------------
    out: list[str] = []
    title = args.title or primary.name or "会議"
    date_label = jst(origin).strftime("%Y-%m-%d")
    out.append(f"# {title}（逐語録）")
    out.append("")
    out.append(f"- 日付: {date_label}")
    out.append(f"- 収録時間帯: {clock(origin)} 〜 "
               f"{clock(max(s['abs_end'] for s, _ in picked))}（JST）")
    out.append(f"- 主録音: {primary.label}（{primary.file_id}）")
    if fills:
        for source, start, end in fills:
            out.append(f"- 補完: {source.label} の {clock(start)} 〜 {clock(end)}"
                       f"（{dur(end - start)}）")
    else:
        out.append("- 補完: なし")
    out.append("")
    out.append("使用した録音:")
    out.append("")
    out.append("| 記号 | file_id | 開始（JST） | 長さ | セグメント数 |")
    out.append("|---|---|---|---|---|")
    for rec in recs:
        length = dur(rec.duration_ms) if rec.duration_ms else "—"
        out.append(f"| {rec.label} | `{rec.file_id}` | {clock(rec.start_ms)} | "
                   f"{length} | {len(rec.segments)} |")
    out.append("")
    out.append("> この逐語録は PLAUD の音声認識（`transaction_polish`）をそのまま並べたもので、")
    out.append("> **校正済みの議事録ではありません。** 固有名詞・数字・団体名は誤認識が残ります。")
    out.append("> `⚠` の付いた発言は、別録音と食い違うか誤認識しやすい語を含む箇所です。")
    out.append("> 音声を聴いて確定してください。発言内容は書き換えていません。")
    out.append("")

    if len(recs) > 1:
        out.append("## 話者ラベルについて")
        out.append("")
        out.append("話者ラベルは録音ごとに独立して振られます。"
                   "同じ番号でも録音が違えば別人のことがあります。")
        out.append("")
        used = sorted({f"{s['rec'].label}/{s['speaker']}" for s, _ in picked})
        out.append("| 録音の話者 | 表示名 |")
        out.append("|---|---|")
        for key in used:
            mapped = mapping.get(key, key)
            display = names.get(mapped, f"（未同定）{mapped}")
            note = f"（{mapped} と同一人物として扱った）" if mapped != key else ""
            out.append(f"| {key} | {display}{note} |")
        out.append("")

    # --- 本文 -----------------------------------------------------------
    out.append("## 逐語録")
    out.append("")

    flags: list[dict] = []
    current_source: str | None = "__init__"
    for seg, fill_label in picked:
        source_label = fill_label or primary.label
        if source_label != current_source:
            if current_source != "__init__":
                out.append("")
            note = ("主録音" if fill_label is None
                    else f"補完区間（録音 {fill_label}）")
            out.append(f"<!-- {note} ここから -->")
            out.append("")
            current_source = source_label

        speaker = resolve_speaker(seg, names, mapping)
        rel = seg["abs_start"] - origin
        header = f"**[{clock(seg['abs_start'])} / {hms(rel)}] {speaker}**"

        check_against = [r for r in recs if r is not seg["rec"]]
        notes = cross_check(seg, check_against, padding_ms, suspect_terms)
        if notes:
            header += "　⚠"
            flags.append({"seg": seg, "speaker": speaker, "notes": notes})

        out.append(header)
        out.append("")
        out.append(seg["content"] or "（無音・聞き取り不能）")
        out.append("")
        if notes:
            for term in notes["terms"]:
                out.append(f"> ⚠ 誤認識しやすい語: 「{term}」")
            for cp in notes["counterparts"]:
                for mine_tok, their_tok, _ in cp["pairs"]:
                    out.append(f"> ⚠ 聞き違いの可能性: 「{mine_tok}」 / 録音 "
                               f"{cp['label']}は「{their_tok}」")
                bits = []
                if cp["only_here"]:
                    bits.append("この録音のみ: " + " / ".join(cp["only_here"]))
                if cp["only_there"]:
                    bits.append(f"録音 {cp['label']} のみ: " + " / ".join(cp["only_there"]))
                if bits:
                    out.append("> ⚠ " + "　".join(bits))
                out.append(f">   録音 {cp['label']}: {cp['text']}")
            out.append("")

    # --- 付録 -----------------------------------------------------------
    out.append("")
    out.append("## 要確認箇所の一覧")
    out.append("")
    if flags:
        out.append(f"{len(flags)} 件。時刻順。音声を聴いて直すときのチェックリストとして使う。")
        out.append("")
        out.append("| 時刻 | 話者 | 内容 |")
        out.append("|---|---|---|")
        for flag in flags:
            reasons = [f"「{t}」" for t in flag["notes"]["terms"]]
            for cp in flag["notes"]["counterparts"]:
                for mine_tok, their_tok, _ in cp["pairs"][:4]:
                    reasons.append(f"{mine_tok}↔{their_tok}")
                diff = sorted(set(cp["only_here"]) | set(cp["only_there"]))
                if diff:
                    reasons.append(f"{cp['label']}のみ: " + " / ".join(diff[:6]))
            head = flag["seg"]["content"][:28].replace("|", "／")
            out.append(f"| {clock(flag['seg']['abs_start'])} | {flag['speaker']} | "
                       f"{'；'.join(reasons)}　… {head}… |")
    else:
        out.append("なし。ただし照合相手のない区間は自動検出できないので、"
                   "下の「照合できていない区間」も見ること。")
    out.append("")

    # 同じ語の食い違いは会議中に何度も出る。語の対で束ねた方が直しやすい。
    out.append("## 録音間で食い違った語")
    out.append("")
    tally: dict[tuple[str, str, str], dict] = {}
    for flag in flags:
        for cp in flag["notes"]["counterparts"]:
            for mine_tok, their_tok, _ in cp["pairs"]:
                key = (mine_tok, their_tok, cp["label"])
                entry = tally.setdefault(key, {"count": 0,
                                               "first": flag["seg"]["abs_start"]})
                entry["count"] += 1
                entry["first"] = min(entry["first"], flag["seg"]["abs_start"])
    if tally:
        out.append("字面が近く、録音によって違う語として起こされた箇所。"
                   "どちらが正しいかは音声で確かめる（両方とも誤りのこともある）。")
        out.append("")
        out.append(f"| 主録音 {primary.label} | 別録音 | 回数 | 最初の時刻 |")
        out.append("|---|---|---|---|")
        for (mine_tok, their_tok, label), info in sorted(
            tally.items(), key=lambda kv: (-kv[1]["count"], kv[1]["first"])
        ):
            out.append(f"| {mine_tok} | {their_tok}（{label}） | {info['count']} | "
                       f"{clock(info['first'])} |")
    else:
        out.append("なし。")
    out.append("")

    out.append("## 照合できていない区間")
    out.append("")
    unchecked = []
    if others:
        prim_cov = primary.covered
        for rec in others:
            cov = rec.covered
            if not (cov and prim_cov):
                continue
            if prim_cov[0] < cov[0]:
                unchecked.append((prim_cov[0], min(cov[0], prim_cov[1])))
            if prim_cov[1] > cov[1]:
                unchecked.append((max(cov[1], prim_cov[0]), prim_cov[1]))
    else:
        cov = primary.covered
        if cov:
            unchecked.append(cov)
    if unchecked:
        for start, end in unchecked:
            if end > start:
                out.append(f"- {clock(start)} 〜 {clock(end)}（{dur(end - start)}）"
                           "— この時間帯を録れているのが1台だけのため、"
                           "録音間の突き合わせによる誤認識の検出ができていない")
    else:
        out.append("- なし（全区間を2台以上で録れている）")
    out.append("")

    for rec in recs:
        for w in rec.warnings:
            out.append(f"- ⚠ 収集時の警告 [{rec.label}]: {w}")

    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# 表示
# --------------------------------------------------------------------------

def print_analysis(report: dict) -> None:
    print("== 録音 ==")
    for rec in report["recordings"]:
        cov = ""
        if rec["covered_start"]:
            cov = (f"  発話範囲 {clock(rec['covered_start'])}〜{clock(rec['covered_end'])}"
                   f"（{dur(rec['covered_ms'])}）")
        print(f"[{rec['label']}] {rec['file_id']}  開始 {clock(int(datetime.fromisoformat(rec['start_at_jst']).timestamp() * 1000))} JST"
              f"  {rec['segments']}セグメント  block={rec['block']}")
        if cov:
            print(cov)
        print(f"  {rec['name']}")

    print()
    print("== 録音どうしの関係 ==")
    for pair in report["pairs"]:
        verdict = "時間帯が重なる → 同じ会議" if pair["same_meeting_by_overlap"] else "重なりなし → 別の会議"
        print(f"{pair['a']} ↔ {pair['b']}: 開始差 {pair['start_gap_s']:.0f}秒 / "
              f"重なり {dur(pair['overlap_ms'])} → {verdict}")

    print()
    print(f"== 主録音の推奨: {report['recommended_primary']}"
          f"（カバー範囲が最も広い）/ 今回の指定: {report['primary']} ==")

    if report.get("gaps") is not None:
        print()
        print("== 主録音に無い/欠けている区間 ==")
        if not report["gaps"]:
            print("なし")
        for gap in report["gaps"]:
            kind = {"head": "冒頭の録り逃し", "tail": "末尾の録り逃し",
                    "inside": "録音中の無音"}[gap["kind"]]
            covers = "、".join(
                f"{c['label']}が{dur(c['speech_ms'])}分の発話を保持" for c in gap["covered_by"]
            ) or "他録音も拾えていない（本当に無音の可能性）"
            print(f"- {kind} {clock(gap['start'])}〜{clock(gap['end'])}"
                  f"（{dur(gap['length_ms'])}）: {covers}")

    if report.get("speaker_candidates"):
        print()
        print("== 話者ラベルの対応候補（発話時間の重なり順・確定ではない）==")
        for label, rows in report["speaker_candidates"].items():
            print(f"-- 録音 {label} --")
            for row in rows:
                best = row["candidates"][:3]
                shown = "、".join(
                    f"{c['speaker']}({c['share'] * 100:.0f}%)" for c in best
                ) or "候補なし"
                print(f"  {row['speaker']}（発話 {dur(row['speech_ms'])}）→ {shown}")

    if report["warnings"]:
        print()
        print("== 警告 ==")
        for w in report["warnings"]:
            print(f"- {w}")


# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("recordings", nargs="+", help="録音JSON")
        p.add_argument("--silence-gap", type=float, default=DEFAULT_SILENCE_GAP_S,
                       help=f"欠落とみなす無音の秒数（既定 {DEFAULT_SILENCE_GAP_S}）")
        p.add_argument("--merge-gap", type=float, default=DEFAULT_MERGE_GAP_S,
                       help=f"発話区間をつなぐ間隔の秒数（既定 {DEFAULT_MERGE_GAP_S}）")

    p_an = sub.add_parser("analyze", help="整列・欠落・話者対応候補を出す")
    common(p_an)
    p_an.add_argument("--primary", help="主録音の指定（省略時は推奨値で解析）")
    p_an.add_argument("--json", action="store_true", help="JSONで出す")

    p_bu = sub.add_parser("build", help="逐語録Markdownを組み立てる")
    common(p_bu)
    p_bu.add_argument("--primary", required=True, help="主録音のlabel")
    p_bu.add_argument("--fill", action="append",
                      help="補完区間 LABEL:開始..終了（ISO8601。タイムゾーン省略時はJST）")
    p_bu.add_argument("--fill-outside", action="append",
                      help="主録音のカバー範囲外を、この録音で自動補完する")
    p_bu.add_argument("--name", action="append",
                      help='表示名 "A/Speaker 1=委員長"')
    p_bu.add_argument("--speaker-map", action="append",
                      help='録音間の話者対応 "B/Speaker 1=A/Speaker 3"')
    p_bu.add_argument("--suspect-terms", help="誤認識しやすい語のJSON配列ファイル")
    p_bu.add_argument("--context-padding", type=float, default=DEFAULT_PADDING_S,
                      help=f"照合相手を拾う前後の秒数（既定 {DEFAULT_PADDING_S}）。"
                           "小さくすると検出は増えるが誤検出も増える")
    p_bu.add_argument("--title", help="見出しに使う会議名")
    p_bu.add_argument("-o", "--output", help="出力先（省略時は標準出力）")

    args = parser.parse_args()
    recs = load_recordings(args.recordings)

    if args.command == "analyze":
        report = analyze(recs, args.primary,
                         int(args.silence_gap * 1000), int(args.merge_gap * 1000))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_analysis(report)
        return

    text = build(recs, args)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"書き出した: {args.output}（{len(text)}文字）")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
