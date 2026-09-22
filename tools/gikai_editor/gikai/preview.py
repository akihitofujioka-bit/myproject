"""紙面プレビュー（HTML）。

Word に差し込む前に、縦書きでどう見えるかを画面で確認するための簡易組版。
最終的な色や罫線は Word 側の様式が持っているので、ここで作るのは
「文字が枠に収まるか」「写真の入る位置」を確かめるための下見用。

ブラウザだけで表示するので、印刷用紙にそのまま出すこともできる。
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from .textutil import count_chars, estimate_lines

PAGE_CSS = """
:root {
  --ink: #1b1b1b; --rule: #c8ccd4; --accent: #1f6f4a; --accent2: #b23a48;
  --paper: #ffffff; --sub: #6b7280;
}
* { box-sizing: border-box; }
body { margin: 0; background: #eef0f4; color: var(--ink);
       font-family: "Yu Mincho", "YuMincho", "Hiragino Mincho ProN", "MS Mincho", serif; }
.sheet { width: 210mm; min-height: 297mm; margin: 12px auto; background: var(--paper);
         padding: 14mm 15mm; box-shadow: 0 2px 14px rgba(0,0,0,.14); page-break-after: always; }
.masthead { border-bottom: 3px solid var(--accent); padding-bottom: 6px; margin-bottom: 10px;
            display: flex; align-items: baseline; justify-content: space-between; }
.masthead h1 { font-size: 30pt; margin: 0; letter-spacing: .1em; color: var(--accent); }
.masthead .meta { font-size: 9pt; color: var(--sub); }
.article { border: 1px solid var(--rule); border-radius: 3px; margin-bottom: 8mm; padding: 6mm; }
.article > h2 { margin: 0 0 4mm; font-size: 15pt; color: var(--accent);
                border-right: none; border-bottom: 2px solid var(--accent); padding-bottom: 2mm; }
.byline { font-size: 9.5pt; color: var(--sub); margin-bottom: 3mm; }
.lead { font-weight: bold; margin-bottom: 3mm; }
.tate { writing-mode: vertical-rl; text-orientation: upright;
        height: 150mm; font-size: 10.5pt; line-height: 1.75; text-align: justify;
        border-top: 1px solid var(--rule); padding-top: 3mm; overflow-x: auto; }
.tate p { margin: 0 0 0 .4em; text-indent: 1em; }
.yoko { font-size: 10.5pt; line-height: 1.8; text-align: justify; }
.yoko p { margin: 0 0 .6em; text-indent: 1em; }
.photos { display: flex; flex-wrap: wrap; gap: 4mm; margin-top: 4mm; }
.photo { width: 52mm; }
.photo img { width: 100%; border: 1px solid var(--rule); display: block; }
.photo figcaption { font-size: 8.5pt; color: var(--sub); margin-top: 1mm; line-height: 1.4; }
.badge { display: inline-block; font-size: 8.5pt; padding: 1px 7px; border-radius: 999px;
         background: #eef4f0; color: var(--accent); margin-left: 6px;
         font-family: system-ui, sans-serif; }
.badge.over { background: #fdecee; color: var(--accent2); }
.empty { color: var(--sub); font-style: italic; }
@media print {
  body { background: #fff; }
  .sheet { margin: 0; box-shadow: none; width: auto; min-height: auto; }
}
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def _photo_tag(project, pid: str) -> str:
    ph = project.get_photo(pid)
    if not ph:
        return ""
    path = project.photos_dir / ph.file
    if not path.exists():
        return ""
    try:
        from . import photos as photos_mod

        thumb = photos_mod.to_thumbnail(path.read_bytes(), 420)
    except Exception:
        thumb = path.read_bytes()
    b64 = base64.b64encode(thumb).decode("ascii")
    cap = _esc(ph.caption) or '<span class="empty">説明文が未入力です</span>'
    credit = f'<br><small>{_esc(ph.credit)}</small>' if ph.credit else ""
    return (
        f'<figure class="photo"><img src="data:image/jpeg;base64,{b64}" alt="">'
        f"<figcaption>{cap}{credit}</figcaption></figure>"
    )


def build_preview(project, *, vertical: bool = True) -> str:
    """プロジェクト全体の紙面プレビュー HTML を組み立てる。"""
    parts: list[str] = [
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>",
        f"<title>{_esc(project.data.get('title', '議会だより'))} プレビュー</title>",
        f"<style>{PAGE_CSS}</style></head><body>",
        "<div class='sheet'>",
        "<div class='masthead'>",
        f"<h1>{_esc(project.data.get('title') or '議会だより')}</h1>",
        f"<div class='meta'>{_esc(project.data.get('issue_no'))} "
        f"{_esc(project.data.get('issue_date'))}</div>",
        "</div>",
    ]

    articles = project.articles()
    if not articles:
        parts.append("<p class='empty'>まだ記事がありません。原稿を取り込んでください。</p>")

    for art in articles:
        n = count_chars(art.body)
        over = art.limit_chars and n > art.limit_chars
        badge = ""
        if art.limit_chars:
            cls = "badge over" if over else "badge"
            badge = f'<span class="{cls}">{n} / {art.limit_chars} 字</span>'
        else:
            badge = f'<span class="badge">{n} 字</span>'
        if art.chars_per_line and art.lines:
            used = estimate_lines(art.body, art.chars_per_line)
            cls = "badge over" if used > art.lines else "badge"
            badge += f'<span class="{cls}">{used} / {art.lines} 行</span>'

        parts.append("<section class='article'>")
        title = _esc(art.title) or "<span class='empty'>見出し未設定</span>"
        parts.append(f"<h2>{title}{badge}</h2>")
        if art.author:
            parts.append(f"<div class='byline'>{_esc(art.author)}</div>")
        if art.lead:
            parts.append(f"<div class='lead'>{_esc(art.lead)}</div>")

        body_html = "".join(
            f"<p>{_esc(line)}</p>" for line in art.body.split("\n") if line.strip()
        ) or "<p class='empty'>本文が空です</p>"
        parts.append(f"<div class='{'tate' if vertical else 'yoko'}'>{body_html}</div>")

        pics = "".join(_photo_tag(project, pid) for pid in art.photos)
        if pics:
            parts.append(f"<div class='photos'>{pics}</div>")
        parts.append("</section>")

    # どの記事にも紐づいていない写真
    used = {pid for a in articles for pid in a.photos}
    spare = [p for p in project.photos() if p.id not in used]
    if spare:
        parts.append("<section class='article'><h2>未使用の写真</h2><div class='photos'>")
        parts.extend(_photo_tag(project, p.id) for p in spare)
        parts.append("</div></section>")

    parts.append("</div></body></html>")
    return "".join(parts)
