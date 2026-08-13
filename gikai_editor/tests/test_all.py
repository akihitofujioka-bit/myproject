"""ツール全体のテスト。

    python -m pytest tests -q          （pytest がある場合）
    python tests/test_all.py           （無くてもこれで動く）
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gikai import textutil as T
from gikai.docxio import DocxTemplate, W, q
from gikai.importers import decode_bytes, read_any, read_docx
from gikai.photos import HAS_PIL, crop_to_ratio, inspect
from gikai.proofread import Dictionaries, apply_fixes, proofread
from gikai.project import Project
from gikai.summarize import fit_to_frame, headline_candidates, shorten, summarize


# ====================================================== textutil

def test_count_chars():
    assert T.count_chars("あいうえお") == 5
    assert T.count_chars("abcd") == 2          # 半角2文字で全角1文字ぶん
    assert T.count_chars("あ\nい") == 2         # 改行は数えない


def test_number_normalization():
    # 1桁は全角、2桁以上は半角（縦書きの慣行）
    assert T.normalize_numbers_tategaki("4月12日") == "４月12日"
    assert T.normalize_numbers_tategaki("５月１５日") == "５月15日"
    assert T.normalize_numbers_tategaki("59.60％") == "59･60％"


def test_normalize_manuscript():
    src = "ﾃｽﾄです｡  全角  ｽﾍﾟｰｽ,これ(かっこ)"
    out = T.normalize_manuscript(src)
    assert "ﾃ" not in out and "｡" not in out
    assert "（かっこ）" in out
    assert "、" in out


def test_split_sentences():
    s = T.split_sentences("これは一文目。「二文目。ここも中」と述べた。三文目！")
    assert len(s) == 3
    assert s[1].startswith("「二文目")   # 括弧の中の句点では切らない


def test_estimate_lines():
    assert T.estimate_lines("あ" * 40, 20) == 2
    assert T.estimate_lines("あ" * 21, 20) == 2
    assert T.estimate_lines("あ\nい", 20) == 2   # 段落ごとに改行


def test_levenshtein():
    assert T.levenshtein("山崎", "山﨑") == 1
    assert T.levenshtein("日高村", "日高村") == 0
    assert T.levenshtein("あいうえお", "かきくけこ", limit=2) == 3   # 打ち切り


# ====================================================== proofread

DIC = Dictionaries()


def _rule_ids(issues):
    return {i.rule_id for i in issues}


def test_house_rules():
    issues = proofread("さまざまな取り組み等について、ひとつの案を示した。", DIC)
    ids = _rule_ids(issues)
    assert "style.house.等" in ids
    assert "style.house.ひとつ" in ids


def test_house_rule_excludes_compounds():
    # 「平等」「等級」の「等」は指摘しない
    issues = proofread("平等な取り扱いと等級の見直し。", DIC)
    assert "style.house.等" not in _rule_ids(issues)


def test_typo_detected_as_error():
    issues = proofread("週知徹底を図る。", DIC)
    hit = [i for i in issues if i.rule_id == "typo.週知徹底を図る"] or \
          [i for i in issues if "週知" in i.text]
    assert hit and hit[0].severity == "error"


def test_ranuki():
    issues = proofread("会場では資料が見れる。", DIC)
    ra = [i for i in issues if i.category == "ら抜き言葉"]
    assert ra and ra[0].suggestion == "見られる"


def test_unbalanced_bracket():
    issues = proofread("村長は「検討する と述べた。", DIC)
    assert any(i.category == "括弧" for i in issues)


def test_hankaku_kana_flagged():
    issues = proofread("ﾃｽﾄ", DIC)
    assert any(i.rule_id == "punct.hankaku_kana" for i in issues)


def test_long_sentence():
    long = "あ" * 200 + "。"
    issues = proofread(long, DIC, enabled={"read"})
    assert any(i.rule_id == "read.long_sentence" for i in issues)


def test_proper_noun_confusable_kanji():
    # 辞書には「山﨑副村長」があるので「山崎副村長」は誤記として出る
    issues = proofread("山崎副村長が答弁した。", DIC, enabled={"noun"})
    hit = [i for i in issues if i.category == "固有名詞"]
    assert hit, "固有名詞の取り違えが検出されていない"
    assert "山﨑" in (hit[0].suggestion or "")


def test_ruby_suggestion():
    issues = proofread("河川の浚渫を進める。", DIC, enabled={"ruby"})
    assert any("しゅんせつ" in i.message for i in issues)


def test_apply_fixes_is_position_safe():
    text = "等について、ひとつの案。等の議論。"
    issues = proofread(text, DIC, enabled={"style"})
    fixed = apply_fixes(text, issues)
    assert "等" not in fixed
    assert fixed.count("など") == 2
    assert "一つ" in fixed


def test_issues_sorted_by_position():
    issues = proofread("出来る等のひとつ。", DIC)
    starts = [i.start for i in issues]
    assert starts == sorted(starts)


# ====================================================== summarize

BODY = (
    "５月12日に、第１回高知県消防広域化に関する実務協議会が開催された。"
    "会では市町村の意向調査結果や、県の統合に向けた推奨案、スケジュール、"
    "分賦金算定シミュレーション、各種論点などが示された。\n"
    "今後、方面別部会などでもしっかり内容を精査し、判断していかなくては"
    "ならないと考えている。村としても対応を進める必要がある。\n"
    "なお、次回の協議会は秋ごろに開催される予定であるということである。"
)


def test_shorten_keeps_meaning_markers():
    out = shorten("対応することができるということである。")
    assert "できる" in out
    assert len(out) < len("対応することができるということである。")


def test_summarize_respects_target():
    res = summarize(BODY, target_chars=60)
    assert res.chars <= 70          # 多少の端数は許容
    assert res.text.strip()


def test_summarize_without_loss_when_short():
    res = summarize("短い本文です。", target_chars=500)
    assert res.method == "圧縮のみ"
    assert "短い本文です。" in res.text


def test_fit_to_frame():
    res = fit_to_frame(BODY, chars_per_line=20, lines=5)
    assert res.chars <= 20 * 5


def test_headline_candidates_are_short():
    for h in headline_candidates(BODY, max_chars=13):
        assert T.count_chars(h) <= 13


# ====================================================== importers

def test_decode_cp932():
    text, enc = decode_bytes("日高村議会".encode("cp932"))
    assert text == "日高村議会"
    assert enc in ("cp932", "shift_jis")


def test_read_text_file(tmpdir=None):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "原稿.txt"
        f.write_bytes("一般質問について\n村長に問う。".encode("cp932"))
        doc = read_any(f)
        assert doc.kind == "text"
        assert doc.title == "一般質問について"
        # 見出しにした行は本文から取り除かれる（二重に出さないため）
        assert doc.text.strip() == "村長に問う。"


# ====================================================== docx

def _make_docx(path: Path, paragraphs: list[str], marker_para: str | None = None):
    """テスト用の最小 .docx を作る。"""
    ps = "".join(
        f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
        for t in paragraphs
    )
    tb = ""
    if marker_para:
        tb = (
            "<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>"
            f'<w:p><w:r><w:t xml:space="preserve">{marker_para}</w:t></w:r></w:p>'
            "</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>"
        )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f"<w:body>{ps}{tb}</w:body></w:document>"
    )
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


def test_docx_slot_detect_and_fill():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "様式.docx"
        _make_docx(src, ["見出し", "本文の一段落目。", "", "別の枠の文章。"],
                   marker_para="{{記事1_見出し}}")
        t = DocxTemplate(src)
        slots = t.slots()
        ids = {s.id for s in slots}
        assert "m:記事1_見出し" in ids, "マーカーが検出されていない"
        body_slots = [s for s in slots if s.kind == "body"]
        assert len(body_slots) == 2, "空段落で本文が分割されていない"

        t.fill({body_slots[0].id: "差し込んだ\n二行目",
                "m:記事1_見出し": "新しい見出し"})
        out = Path(d) / "out.docx"
        t.save(out)

        t2 = DocxTemplate(out)
        s2 = {s.id: s for s in t2.slots()}
        assert "差し込んだ" in s2["body:1"].sample
        assert "二行目" in s2["body:1"].sample
        # マーカーは消費されるので、次回は通常の枠として現れる
        assert any("新しい見出し" in s.sample for s in t2.slots())


def test_docx_fill_preserves_run_formatting():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "様式.docx"
        _make_docx(src, ["元の文字"])
        t = DocxTemplate(src)
        t.slots()
        t.fill({"body:1": "新しい文字"})
        out = Path(d) / "out.docx"
        t.save(out)
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert "新しい文字" in xml
        assert "元の文字" not in xml
        # 空要素は <w:b /> の形で書き出される
        assert "<w:b" in xml, "元の書式（太字）が失われている"


def test_docx_read_back():
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "原稿.docx"
        _make_docx(src, ["議員からの原稿です。", "二段落目。"])
        doc = read_docx(src)
        assert "議員からの原稿です。" in doc.text
        assert "二段落目。" in doc.text


# ====================================================== photos

def test_photo_inspect_and_crop():
    if not HAS_PIL:
        print("  (Pillow が無いため写真のテストは省略)")
        return
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (200, 120, 60)).save(buf, format="JPEG")
    data = buf.getvalue()

    info = inspect(data, "test.jpg")
    assert info.width == 1200 and info.orientation == "横"

    cropped = crop_to_ratio(data, 1.0)      # 正方形にする
    with Image.open(io.BytesIO(cropped)) as im:
        assert abs(im.width - im.height) <= 1


def test_photo_low_resolution_warning():
    if not HAS_PIL:
        return
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (320, 240)).save(buf, format="JPEG")
    info = inspect(buf.getvalue(), "small.jpg")
    assert not info.print_ok
    assert "解像度" in info.warning


# ====================================================== project 全体

def test_project_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "第204号"
        p = Project.create(root, "第204号")

        # 様式を読み込む
        tpl = Path(d) / "様式.docx"
        # 空段落で区切ると、別々の枠として認識される
        _make_docx(tpl, ["見出しの枠", "", "本文の枠です。ここに記事が入ります。"])
        p.set_template(tpl)
        assert p.data["template"] == "template.docx"

        # 原稿を取り込む
        manu = Path(d) / "森下議員_原稿.txt"
        manu.write_text(
            "消防の広域化について\n" + BODY, encoding="utf-8"
        )
        art = p.import_manuscript(manu)
        assert art.body
        assert art.title == "消防の広域化について"

        # 校正
        res = p.proofread_article(art.id)
        assert "issues" in res and res["chars"] > 0

        # 要約
        art.limit_chars = 80
        p.put_article(art)
        fit = p.fit_article(art.id)
        assert fit["chars"] <= 90

        # 割付して書き出し
        slots = p.template_slots()["slots"]
        body_slot = [s for s in slots if s["kind"] == "body"][-1]
        art.slot = body_slot["id"]
        art.title_slot = [s for s in slots if s["kind"] == "body"][0]["id"]
        p.put_article(art)

        out = p.export("テスト出力.docx")
        assert Path(out["docx"]).exists()
        assert out["filled"] == 2
        assert not out["unassigned"]

        # 書き出した Word に本文が入っているか
        t = DocxTemplate(out["docx"])
        allsample = " ".join(s.sample for s in t.slots())
        assert "消防の広域化について" in allsample
        assert "協議会" in allsample

        # 開き直しても内容が残っているか
        p2 = Project.open(root)
        assert len(p2.articles()) == 1
        assert p2.articles()[0].slot == body_slot["id"]


def test_project_preview_html():
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第205号", "第205号")
        manu = Path(d) / "原稿.txt"
        manu.write_text("見出しです\n本文です。", encoding="utf-8")
        p.import_manuscript(manu)
        from gikai.preview import build_preview

        html = build_preview(p)
        assert "<html" in html and "本文です。" in html
        assert "writing-mode: vertical-rl" in html


# ====================================================== 実行

def _run():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    ok = fail = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ok    {name}")
            ok += 1
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            fail += 1
    print(f"\n{ok} 件成功 / {fail} 件失敗")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(_run())
