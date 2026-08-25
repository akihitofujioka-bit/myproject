"""ツール全体のテスト。

    python -m pytest tests -q          （pytest がある場合）
    python tests/test_all.py           （無くてもこれで動く）
"""

from __future__ import annotations

import json
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


# ====================================================== 旧形式 .doc

def test_doc97_reads_real_word97_file():
    """LibreOffice なしで .doc の文字を取り出せること。"""
    from gikai import doc97

    src = Path("/root/.claude/uploads/d73a01c8-6462-5062-90f7-c398f9a71e47")
    docs = list(src.glob("*.doc")) if src.exists() else []
    if not docs:
        print("  (見本の .doc が無いため省略)")
        return
    path = docs[0]
    assert doc97.is_doc(path)
    text = doc97.extract_text(path)
    assert len(text) > 5000, "本文が短すぎる"
    # テキストボックスの中身まで拾えていること
    assert "行政報告" in text
    assert "リョーマゴルフ" in text
    # 制御文字が残っていないこと
    assert "\r" not in text and "\x07" not in text and "\x13" not in text


def test_doc97_rejects_non_doc():
    from gikai import doc97

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "ただのテキスト.doc"
        f.write_text("これは Word ではありません", encoding="utf-8")
        assert not doc97.is_doc(f)
        try:
            doc97.extract_text(f)
            raise AssertionError("例外が出るべき")
        except doc97.DocError:
            pass


def test_read_any_handles_doc_without_libreoffice():
    """.doc の取り込みが、外部ソフト無しの経路を通ること。"""
    import gikai.importers as imp

    src = Path("/root/.claude/uploads/d73a01c8-6462-5062-90f7-c398f9a71e47")
    docs = list(src.glob("*.doc")) if src.exists() else []
    if not docs:
        return
    orig_so, orig_word = imp.convert_with_soffice, imp.convert_with_word
    imp.convert_with_soffice = lambda *a, **k: None   # 変換の道を塞ぐ
    imp.convert_with_word = lambda *a, **k: None
    try:
        doc = imp.read_any(docs[0])
        assert doc.kind == "doc"
        assert len(doc.text) > 5000
        assert not doc.warnings
    finally:
        imp.convert_with_soffice, imp.convert_with_word = orig_so, orig_word


# ====================================================== 写真の自動割り付け

def test_split_number_and_key():
    from gikai.autolayout import normalize_key, split_number

    assert split_number("森下けい子_原稿2") == ("森下けい子_原稿", 2)
    assert split_number("視察報告①") == ("視察報告", 1)
    assert split_number("原稿") == ("原稿", 0)
    assert normalize_key("森下 けい子（原稿）") == normalize_key("森下けい子原稿")


def test_match_photo_by_filename():
    from gikai.autolayout import match_photo
    from gikai.project import Article

    arts = [
        Article(id="a1", title="スーパー誘致", author="森下けい子",
                source_file="森下けい子_原稿.docx"),
        Article(id="a2", title="治水対策", author="大川内慎治",
                source_file="大川内慎治_視察報告.doc"),
    ]
    assert match_photo("森下けい子_原稿.jpg", arts).article_id == "a1"
    assert match_photo("森下けい子_原稿2.JPG", arts).order == 2
    assert match_photo("大川内慎治_視察報告①.png", arts).article_id == "a2"
    assert match_photo("大川内慎治.jpeg", arts).article_id == "a2"
    # 関係のない名前は結びつけない
    assert match_photo("IMG_2024.jpg", arts).article_id == ""


def _png(color=(80, 120, 90), size=(1600, 1200)) -> bytes:
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _make_docx_with_images(path: Path, pages: int = 3):
    """写真枠と説明文の枠を持つ、複数ページの様式を作る。"""
    body_parts = []
    rels = []
    media = {}
    for i in range(1, pages + 1):
        rid = f"rId{100 + i}"
        rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/image" Target="media/photo{i}.png"/>'
        )
        media[f"word/media/photo{i}.png"] = _png(size=(400, 300))
        body_parts.append(
            f'<w:p><w:r><w:t xml:space="preserve">見出し{i}</w:t></w:r></w:p>'
            f'<w:p/>'
            f'<w:p><w:r><w:t xml:space="preserve">{i}ページ目の本文です。'
            f'ここに記事が入ります。</w:t></w:r></w:p>'
            f'<w:p/>'
            # 写真
            f'<w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData>'
            f'<pic:pic><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
            # 説明文のテキストボックス
            f'<w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
            f'<w:p><w:r><w:t xml:space="preserve">前号の説明文{i}</w:t></w:r></w:p>'
            f'</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>'
            f'<w:p/>'
        )
        if i < pages:
            body_parts.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')

    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<w:body>{"".join(body_parts)}</w:body></w:document>'
    )
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.document.main+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                 '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join(rels) + "</Relationships>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        for name, blob in media.items():
            z.writestr(name, blob)


def test_image_anchors_have_page_and_order():
    with tempfile.TemporaryDirectory() as d:
        tpl = Path(d) / "様式.docx"
        _make_docx_with_images(tpl, pages=3)
        t = DocxTemplate(tpl)
        anchors = t.image_anchors()
        assert len(anchors) == 3
        assert [a["name"] for a in anchors] == ["photo1.png", "photo2.png", "photo3.png"]
        assert [a["page"] for a in anchors] == [1, 2, 3], f"ページが違う: {anchors}"


def test_auto_layout_places_photos_near_their_article():
    """写真の名前を原稿に合わせておくと、その記事のページの枠に入ること。"""
    from gikai.project import Project

    if not HAS_PIL:
        print("  (Pillow が無いため省略)")
        return

    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "第204号"
        p = Project.create(root, "第204号")
        tpl = Path(d) / "様式.docx"
        _make_docx_with_images(tpl, pages=3)
        p.set_template(tpl)

        slots = p.template_slots()["slots"]
        body_slots = [s for s in slots if s["kind"] == "body" and s["chars"] > 10]
        assert len(body_slots) >= 3

        # 3人ぶんの原稿を取り込み、それぞれ別のページの枠に割り当てる
        names = ["森下けい子_原稿", "大川内慎治_視察報告", "池田雄_一般質問"]
        for i, name in enumerate(names):
            f = Path(d) / f"{name}.txt"
            f.write_text(f"{name}の見出し\n本文です。" * 3, encoding="utf-8")
            art = p.import_manuscript(f)
            art.slot = body_slots[i]["id"]
            p.put_article(art)

        # 写真は原稿と同じ名前にしてある
        for i, name in enumerate(names):
            f = Path(d) / f"{name}.png"
            f.write_bytes(_png(color=(60 + i * 40, 100, 120)))
            p.import_photo(f)

        report = p.auto_layout()

        assert len(report["matched"]) == 3, f"名前の突き合わせが不足: {report}"
        assert not report["unmatched"]
        assert len(report["slots"]) == 3, f"写真枠の割り当てが不足: {report}"

        # 記事のページと写真枠のページが一致していること
        anchors = {a["name"]: a for a in p.template().image_anchors()}
        slots_by_id = {s["id"]: s for s in p.template_slots()["slots"]}
        for art in p.articles():
            page = slots_by_id[art.slot]["page_hint"]
            for pid in art.photos:
                photo = p.get_photo(pid)
                assert photo.slot, "写真枠が未割り当て"
                assert anchors[photo.slot]["page"] == page, (
                    f"{art.title} は {page} ページなのに写真は "
                    f"{anchors[photo.slot]['page']} ページの枠に入った"
                )
                assert photo.caption_slot, "説明文の枠が押さえられていない"


def test_auto_layout_keeps_photo_order():
    """同じ記事の写真は、連番の順に並ぶこと。"""
    from gikai.project import Project

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第205号", "第205号")
        f = Path(d) / "森下けい子_原稿.txt"
        f.write_text("見出し\n本文です。", encoding="utf-8")
        p.import_manuscript(f)
        for n in (3, 1, 2):
            g = Path(d) / f"森下けい子_原稿{n}.png"
            g.write_bytes(_png(size=(300, 200)))
            p.import_photo(g)

        p.auto_layout(assign_slots=False)
        art = p.articles()[0]
        names = [p.get_photo(pid).info["name"] for pid in art.photos]
        assert names == ["森下けい子_原稿1.png", "森下けい子_原稿2.png",
                         "森下けい子_原稿3.png"], names


def test_auto_layout_fills_caption_on_export():
    """割り当てた説明文が、書き出した Word に入ること。"""
    from gikai.project import Project

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第206号", "第206号")
        tpl = Path(d) / "様式.docx"
        _make_docx_with_images(tpl, pages=2)
        p.set_template(tpl)
        slots = [s for s in p.template_slots()["slots"]
                 if s["kind"] == "body" and s["chars"] > 10]

        f = Path(d) / "森下けい子_原稿.txt"
        f.write_text("見出し\n本文です。", encoding="utf-8")
        art = p.import_manuscript(f)
        art.slot = slots[0]["id"]
        p.put_article(art)

        g = Path(d) / "森下けい子_原稿.png"
        g.write_bytes(_png())
        photo = p.import_photo(g)
        photo.caption = "買い物環境の確保に向け協議を継続"
        p.put_photo(photo)

        p.auto_layout()
        out = p.export("確認.docx")
        assert Path(out["docx"]).exists()
        assert all(r["ok"] for r in out["photos"]), out["photos"]

        t = DocxTemplate(out["docx"])
        allsample = " ".join(s.sample for s in t.slots())
        assert "買い物環境の確保に向け協議を継続" in allsample, "説明文が入っていない"


# ====================================================== 自動組版

def _sample_project(d: Path, n_articles=4, n_photos=2, repeat=3):
    from gikai.project import Project

    p = Project.create(d / "第204号", "議会だより")
    p.data["issue_no"] = "第204号"
    p.save()
    body = ("質問　スーパー誘致の進捗状況について問う。\n"
            "答弁　松岡村長　現在も事業者との協議を継続している。"
            "小規模店舗を含めさまざまな可能性を検討し、村民の買い物環境の確保に努めていく。\n")
    names = ["森下けい子", "大川内慎治", "池田雄", "西村玲子", "藤原利彦", "横山泰昌"]
    for i in range(n_articles):
        a = names[i % len(names)] + f"{i}"
        f = d / f"{a}_原稿.txt"
        f.write_text(f"見出し{i}について問う\n" + body * repeat, encoding="utf-8")
        art = p.import_manuscript(f)
        art.author = a
        p.put_article(art)
    if HAS_PIL:
        for i in range(n_photos):
            g = d / f"{names[i % len(names)]}{i}_原稿.jpg"
            g.write_bytes(_png(size=(1800, 1300)))
            p.import_photo(g)
        if n_photos:
            p.auto_layout(assign_slots=False)
            for ph in p.photos():
                ph.caption = "現地を視察する委員"
                p.put_photo(ph)
    return p


def test_layout_spec_metrics():
    """1ページ5段・縦書きの寸法計算。"""
    from gikai.compose import LayoutSpec

    spec = LayoutSpec()
    assert spec.columns == 5
    m = spec.metrics()
    # A4・5段・10.5pt なら 1段13字前後になる
    assert 11 <= m["chars_per_line"] <= 15, m
    assert m["lines_per_column"] > 20
    assert m["chars_per_page"] == m["chars_per_column"] * 5

    # 段を増やせば1段は短くなる（＝1行の字数が減る）
    narrow = LayoutSpec(columns=8).metrics()
    assert narrow["chars_per_line"] < m["chars_per_line"]
    # 文字を大きくしても同じ
    big = LayoutSpec(body_pt=14).metrics()
    assert big["chars_per_line"] < m["chars_per_line"]


def test_compose_produces_vertical_five_columns():
    """組み上がった Word が、5段・縦書きの指定を持っていること。"""
    from gikai.compose import LayoutSpec, compose

    with tempfile.TemporaryDirectory() as d:
        p = _sample_project(Path(d))
        res = compose(p, LayoutSpec())
        assert res.path.exists()
        with zipfile.ZipFile(res.path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert '<w:cols w:num="5"' in xml, "5段の指定が無い"
        assert '<w:textDirection w:val="tbRl"/>' in xml, "縦書きの指定が無い"
        assert "見出し0について問う" in xml
        # A4 縦（twip）
        assert 'w:w="11906"' in xml and 'w:h="16838"' in xml


def test_compose_page_count_grows_with_content():
    """原稿が増えればページが増えること（分量に応じた自動調節）。"""
    from gikai.compose import compose

    with tempfile.TemporaryDirectory() as d:
        small = compose(_sample_project(Path(d) / "a", n_articles=2, n_photos=0))
        large = compose(_sample_project(Path(d) / "b", n_articles=16, n_photos=0, repeat=6))
        assert large.pages_estimated > small.pages_estimated, \
            f"原稿を増やしてもページが増えていない: {small.pages_estimated} → {large.pages_estimated}"


def test_compose_photos_take_space():
    """写真を入れると、その分だけ紙面を使うこと。"""
    if not HAS_PIL:
        return
    from gikai.compose import compose

    with tempfile.TemporaryDirectory() as d:
        without = compose(_sample_project(Path(d) / "a", n_articles=4, n_photos=0))
        with_photos = compose(_sample_project(Path(d) / "b", n_articles=4, n_photos=4))
        assert with_photos.photos == 4
        assert with_photos.lines_used > without.lines_used, "写真の場所が数えられていない"
        with zipfile.ZipFile(with_photos.path) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert len(media) == 4, media


def test_compose_layout_is_fixed_regardless_of_content():
    """中身が変わっても、段数・縦書き・判型は変わらないこと。"""
    from gikai.compose import compose

    xmls = []
    for n in (1, 12):
        with tempfile.TemporaryDirectory() as d:
            res = compose(_sample_project(Path(d), n_articles=n, n_photos=0))
            with zipfile.ZipFile(res.path) as z:
                xml = z.read("word/document.xml").decode("utf-8")
            xmls.append(xml[xml.index("<w:sectPr>"):])
    assert xmls[0] == xmls[1], "中身によって紙面の決まりごとが変わってしまっている"


def test_plan_and_fit_pages():
    """目標ページ数に合わせて詰められること。"""
    with tempfile.TemporaryDirectory() as d:
        p = _sample_project(Path(d), n_articles=8, n_photos=4, repeat=5)
        now = p.plan_pages(0)["pages_now"]
        assert now >= 2, f"見本が小さすぎる: {now}"

        # 目標が今より大きければ、詰める必要はない
        loose = p.plan_pages(now + 2)
        assert not loose["need_cut"]

        tight = p.plan_pages(now - 1)
        assert tight["need_cut"]
        assert sum(x["cut"] for x in tight["plan"]) > 0

        res = p.fit_to_pages(now - 1)
        assert res["applied"], "詰められていない"
        assert res["pages_after"] <= now - 1, res["message"]
        # 元の原稿は残っている（戻せる）
        for art in p.articles():
            assert art.raw, "取り込んだ原稿が失われている"


def test_fit_pages_reports_when_impossible():
    """どうやっても入らないときは、そう伝えること。"""
    with tempfile.TemporaryDirectory() as d:
        p = _sample_project(Path(d), n_articles=10, n_photos=8, repeat=5)
        res = p.fit_to_pages(1)
        assert "これ以上は縮まず" in res["message"] or res["pages_after"] <= 1


def test_compose_survives_without_articles():
    from gikai.compose import compose
    from gikai.project import Project

    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "空", "空の号")
        res = compose(p)
        assert res.path.exists()
        assert res.pages_estimated == 1
        assert any("記事がありません" in w for w in res.warnings)


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


# ====================================================== 画面（不具合の再発防止）

STATIC = Path(__file__).resolve().parents[1] / "gikai" / "static"


def _css() -> str:
    return (STATIC / "style.css").read_text(encoding="utf-8")


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _rule_body(css: str, selector: str) -> str:
    """CSS から指定セレクタの宣言部だけを取り出す。"""
    import re as _re

    m = _re.search(
        r"(?:^|\})\s*" + _re.escape(selector) + r"\s*\{([^}]*)\}", css, _re.MULTILINE
    )
    return m.group(1) if m else ""


def test_modal_is_hidden_by_default():
    """空のダイアログが出たまま操作できなくなる不具合の再発防止。

    .modal に無条件の display:flex を書くと、ブラウザ標準の
    [hidden]{display:none} を上書きしてしまい、中身が空のダイアログが
    起動直後から画面全体を覆ってしまう。
    """
    css = _css()
    base = _rule_body(css, ".modal").replace(" ", "")
    assert "display:none" in base, ".modal の既定は display:none でなければならない"
    assert "display:flex" not in base, ".modal に無条件の display:flex を書いてはいけない"
    assert ".modal:not([hidden])" in css, "開いたときだけ表示する指定が無い"

    # トースト（画面下の通知）も同じ理由で崩れないこと
    assert ".toast[hidden]" in css


def test_hidden_elements_are_really_hidden():
    """`hidden` を付けた要素が、CSS の display で見えてしまわないこと。

    ブラウザ標準の `[hidden]{display:none}` は詳細度が最低なので、
    `.steps{display:flex}` のような無条件の指定が勝ってしまう。
    実際にこれで、隠したはずの手順タブが出たままになった。
    """
    import re as _re

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = _css()

    # まとめて押さえる指定が1つあれば、この種の不具合は起きない
    assert _re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important",
                      css.replace("\n", "")), \
        "[hidden]{display:none !important} が消えている（隠した要素が出てしまう）"

    # hidden 付きで書かれている要素の id を集める
    ids = set(_re.findall(r'id="([\w-]+)"[^>]*\shidden', html))
    ids |= set(_re.findall(r'\shidden[^>]*\sid="([\w-]+)"', html))
    # その id が持つ class も見る（CSS は class で書かれていることが多い）
    names = set("#" + i for i in ids)
    for i in ids:
        m = _re.search(r'<[^>]*id="%s"[^>]*>' % _re.escape(i), html)
        for cls in _re.findall(r'class="([^"]+)"', m.group(0) if m else ""):
            names |= {"." + c for c in cls.split()}

    assert names, "hidden 付きの要素が1つも見つからない（この検査が働いていない）"
    for sel in sorted(names):
        body = _rule_body(css, sel).replace(" ", "")
        if not body:
            continue
        disp = _re.search(r"display:([\w-]+)", body)
        if disp and disp.group(1) != "none":
            # 上の一括指定で消えるので不具合にはならないが、
            # 書き方としては :not([hidden]) のほうが意図が伝わる
            assert f"{sel}:not([hidden])" in css or "[hidden]" in css, sel


def test_modal_html_starts_hidden():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="modal" hidden' in html, "ダイアログは hidden 付きで始めること"
    assert 'id="modalClose"' in html


def test_modal_can_be_closed_by_button_and_escape():
    js = _js()
    assert "function closeModal()" in js
    # 「閉じる」ボタン
    assert '$("#modalClose").addEventListener("click", closeModal)' in js
    # Esc キー
    assert '"Escape"' in js and "closeModal()" in js
    # 背景クリック
    assert 'e.target.id === "modal"' in js
    # 閉じる処理が1か所に集約されていること（閉じ忘れを防ぐ）
    assert js.count('$("#modal").hidden = true') == 1, \
        "閉じる処理は closeModal() に集約すること"


def test_empty_project_list_message():
    js = _js()
    assert "保存済みの号はありません" in js
    # 一覧の取得に失敗しても画面が空白のまま固まらないこと
    assert "保存済みの号を読み込めませんでした" in js


# ====================================================== 保存先フォルダ

def test_default_workspace_is_under_desktop():
    from gikai.workspace import WORKSPACE_NAME, default_workspace, desktop_dir

    ws = default_workspace()
    assert ws.name == WORKSPACE_NAME
    desktop = desktop_dir()
    if desktop is not None:
        assert ws.parent == desktop, "既定の保存先はデスクトップの下"
    else:
        # デスクトップが無い環境ではホームの下に置く
        assert ws.parent == Path.home()


def test_ensure_workspace_creates_missing_folder():
    from gikai.workspace import ensure_workspace

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "デスクトップ" / "議会だより"
        assert not target.exists()
        got, note = ensure_workspace(target)
        assert got == target
        assert got.is_dir(), "保存先フォルダが自動で作られていない"
        assert "作成しました" in note

        # 2回目は既にあるので、わざわざ知らせない
        got2, note2 = ensure_workspace(target)
        assert got2 == target and note2 == ""


def test_ensure_workspace_falls_back_when_uncreatable():
    """作れない場所を指定されても起動できること。"""
    from gikai.workspace import ensure_workspace

    with tempfile.TemporaryDirectory() as d:
        blocker = Path(d) / "ふさがっている"
        blocker.write_text("これはフォルダではなくファイル", encoding="utf-8")
        got, note = ensure_workspace(blocker / "議会だより")
        assert got.is_dir(), "代わりの保存先が用意されていない"
        assert got != blocker / "議会だより"
        assert note, "場所が変わったことを利用者に伝えていない"


def test_workspace_api_recreates_deleted_folder():
    """保存先を消されても一覧が失敗しないこと。"""
    import shutil as _shutil

    from gikai.server import AppState, handle_api

    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "議会だより"
        state = AppState(ws)
        assert ws.is_dir()
        _shutil.rmtree(ws)
        result = handle_api(state, "workspace", {}, {})
        assert result["projects"] == []
        assert ws.is_dir(), "消えた保存先が作り直されていない"


# ====================================================== 起動まわり

ROOT = Path(__file__).resolve().parents[1]


def test_runstate_roundtrip():
    from gikai import runstate

    original = runstate.STATE_FILE
    with tempfile.TemporaryDirectory() as d:
        runstate.STATE_FILE = Path(d) / "run.json"
        try:
            assert runstate.read() is None
            runstate.write("http://127.0.0.1:9999/", 9999, "/tmp/ws")
            got = runstate.read()
            assert got["app"] == "gikai_editor"
            assert got["port"] == 9999
            assert got["workspace"] == "/tmp/ws"
            # 応答が無いので、古い記録として片付けられる
            assert runstate.find_running() is None
            assert not runstate.STATE_FILE.exists()
        finally:
            runstate.STATE_FILE = original


def test_ping_and_quit_api():
    """画面の「終了」ボタンでサーバを止められること。"""
    import threading as _th
    import time as _time
    import urllib.request as _req

    from gikai import runstate
    from gikai.server import serve

    with tempfile.TemporaryDirectory() as d:
        httpd = serve(Path(d) / "議会だより")
        port = httpd.server_address[1]
        url = f"http://127.0.0.1:{port}/"
        _th.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            _time.sleep(0.3)
            with _req.urlopen(url + "api/ping", timeout=3) as r:
                info = json.loads(r.read())
            assert info["app"] == "gikai_editor"

            # 動いていると判定できること
            original = runstate.STATE_FILE
            runstate.STATE_FILE = Path(d) / "run.json"
            try:
                runstate.write(url, port, d)
                assert runstate.find_running() is not None
                assert runstate.request_quit(url) is True
            finally:
                runstate.STATE_FILE = original

            _time.sleep(1.2)
            try:
                _req.urlopen(url + "api/ping", timeout=1.5)
                raise AssertionError("終了したはずのサーバが応答している")
            except AssertionError:
                raise
            except Exception:
                pass  # 応答が無いのが正しい
        finally:
            httpd.server_close()


# ====================================================== アイコン・起動ファイル

def test_icon_files_exist():
    from PIL import Image

    for rel in ("icon.ico", "icon.png",
                "gikai/static/favicon.ico", "gikai/static/icon.png"):
        f = ROOT / rel
        assert f.exists(), f"{rel} がありません"
        with Image.open(f) as im:
            assert im.size[0] >= 16

    # ショートカット用は複数の大きさを含んでいること
    with Image.open(ROOT / "icon.ico") as im:
        sizes = {s for s in getattr(im, "info", {}).get("sizes", set())} or set(im.ico.sizes())
        assert (16, 16) in sizes and (256, 256) in sizes, f"大きさが足りない: {sizes}"


def test_favicon_is_linked():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'rel="icon"' in html and "favicon.ico" in html
    assert 'id="btnQuit"' in html, "「終了」ボタンが無い"


def test_quit_button_wired():
    js = _js()
    assert '$("#btnQuit")' in js
    assert 'api("quit"' in js
    assert "終了しました" in js


def _bat(name: str) -> str:
    """バッチファイルを CP932 として読む（Windows の cmd と同じ扱い）。"""
    return (ROOT / name).read_bytes().decode("cp932")


def test_batch_files_are_cp932():
    """バッチファイルの文字化け再発防止。

    日本語版 Windows の cmd.exe は .bat をシステムの ANSI コードページ
    (CP932) として読むため、UTF-8 で保存すると画面が文字化けする。
    """
    for name in ("起動.bat", "終了.bat", "デスクトップにアイコンを作る.bat",
                 "追加部品のインストール.bat", "_find_python.bat"):
        raw = (ROOT / name).read_bytes()
        text = raw.decode("cp932")           # 例外が出たら CP932 ではない
        # 日本語が読める形で入っていること（文字化けしていない）
        assert any(w in text for w in ("議会だより", "Python", "使える")), \
            f"{name} の日本語が壊れている"
        assert b"\r\n" in raw, f"{name} の改行が CRLF ではない"
        try:
            raw.decode("ascii")
            raise AssertionError(f"{name} に日本語が含まれていない")
        except UnicodeDecodeError:
            pass  # 日本語が入っているのが正しい


def test_python_detection_is_verified_not_assumed():
    """壊れた Python を掴んでしまう不具合の再発防止。

    ほかのソフトが PATH に置いた Python が壊れていると
    「Unable to create process」で止まる。コマンドの有無だけで
    判断せず、実際に動かして確かめていること。
    """
    s = _bat("_find_python.bat")
    # 実際に動かして確認する
    assert "_pycheck.py" in s, "動作確認をしていない"
    assert "if not exist" in s and "PYCHK" in s, "結果を確認していない"
    # 候補を複数試す
    for cand in ("py ", "python", "python3", "Python3*"):
        assert cand in s, f"{cand} を試していない"
    # 実際に動く行だけを見る（説明のための rem 行は除く）
    body = "\n".join(l for l in s.splitlines() if not l.strip().startswith("rem"))
    # 呼び出し元に値を返すため setlocal を使わない
    assert "setlocal" not in body, "setlocal があると呼び出し元に値が返らない"
    # 括弧を含む文字列を展開しない（for ブロックが途中で閉じるのを防ぐ）
    assert body.count("(") == body.count(")"), "括弧の対応が取れていない"

    # 動作確認用の小さな道具が同梱されていること
    probe = ROOT / "_pycheck.py"
    assert probe.exists()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "check.txt"
        import subprocess

        subprocess.run([sys.executable, str(probe), str(out)], check=True, timeout=30)
        assert out.read_text() == "ok"


def test_all_launchers_use_shared_detection():
    for name in ("起動.bat", "終了.bat", "追加部品のインストール.bat"):
        s = _bat(name)
        assert 'call "%~dp0_find_python.bat"' in s, f"{name} が検出処理を呼んでいない"
        assert "PYFOUND" in s, f"{name} が検出結果を確認していない"
        # 古い「あるかどうかだけ見る」やり方が残っていないこと
        assert "where py " not in s and "where python" not in s, \
            f"{name} に古い判定が残っている"


def test_installer_shows_python_location_on_error():
    """どの Python を使おうとしたかが分かること。"""
    s = _bat("追加部品のインストール.bat")
    assert "sys.executable" in s, "使った Python の場所を表示していない"
    assert "wheels フォルダに7個" in s or "7個のファイル" in s


def test_launcher_closes_after_start():
    """起動できたら黒い画面が残らないこと。"""
    text = _bat("起動.bat")
    # 画面なしの Python を使う（検出処理が PYW に入れる）
    assert "%PYW%" in text
    assert "start " in text, "別プロセスとして起動していない"
    # 起動できたときは pause せずに終わる
    ready = text.split(":ready", 1)[1]
    assert "pause" not in ready, "起動成功時に画面が残ってしまう"
    assert "exit /b 0" in ready
    # 失敗したときは、原因が見えるように画面を残す
    assert "pause" in text.split(":ready", 1)[0]


def test_bundled_wheels_cover_supported_pythons():
    """インターネットにつながらない環境でも導入できること。"""
    wheels = ROOT / "wheels"
    assert wheels.is_dir(), "wheels フォルダが無い"
    names = [p.name for p in wheels.glob("*.whl")]

    # Pillow は Python のバージョンごとに必要
    for tag in ("cp310", "cp311", "cp312", "cp313", "cp314"):
        assert any(n.startswith("pillow-") and tag in n for n in names), \
            f"Python {tag} 用の Pillow が入っていない"
    # PyMuPDF は abi3 なので 1 つで 3.10 以降に対応する
    assert any(n.startswith("pymupdf-") and "abi3" in n for n in names), \
        "PyMuPDF（abi3）が入っていない"
    # pypdf は純 Python なのでどこでも動く
    assert any(n.startswith("pypdf-") and "py3-none-any" in n for n in names), \
        "予備の pypdf が入っていない"
    assert (wheels / "README.txt").exists()


def test_installer_works_offline():
    """導入用バッチが外部に接続しない指定になっていること。"""
    s = _bat("追加部品のインストール.bat")
    assert "--no-index" in s, "--no-index が無いと外部に取りに行ってしまう"
    assert "--find-links" in s and "wheels" in s
    assert "インターネットには接続しません" in s
    # 以前あった pip 自体の更新（要インターネット）が残っていないこと
    assert "install --upgrade pip" not in s
    assert "Pillow pymupdf pypdf" in s


def test_pdf_falls_back_to_pypdf():
    """PyMuPDF が無くても PDF を読もうとすること。"""
    import gikai.importers as imp

    orig = imp._pdf_text_pymupdf
    imp._pdf_text_pymupdf = lambda p: None
    try:
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "空.pdf"
            f.write_bytes(b"%PDF-1.4\n%%EOF\n")
            doc = imp.read_pdf(f)
        # pypdf があれば「簡易的な方法」の注意書き、無ければ導入の案内
        assert doc.warnings
        joined = " ".join(doc.warnings)
        assert "簡易的な方法" in joined or "追加部品" in joined or "文字が取り出せません" in joined
    finally:
        imp._pdf_text_pymupdf = orig


def test_quit_batch_and_shortcut_batch():
    assert "--quit" in _bat("終了.bat")
    s = _bat("デスクトップにアイコンを作る.bat")
    assert "icon.ico" in s and "起動.bat" in s
    assert "CreateShortcut" in s


# ====================================================== 仕様書

def test_spec_document_is_generated_and_valid():
    """仕様書がコードから作れて、体裁が崩れていないこと。"""
    import subprocess

    gen = ROOT / "tools" / "make_docs.py"
    assert gen.exists()
    r = subprocess.run([sys.executable, str(gen)], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=120)
    assert r.returncode == 0, r.stderr

    doc = ROOT / "仕様書.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")

    # コードブロックの開き閉じが対応していること
    fences = [l for l in text.splitlines() if l.startswith("```")]
    assert len(fences) % 2 == 0, f"コードブロックが閉じていない: {len(fences)}"

    # 仕様と全ソースが入っていること
    assert "# 第1部　仕様" in text and "# 第2部　ソースコード" in text
    for name in ("app.py", "gikai/compose.py", "gikai/proofread.py",
                 "gikai/static/app.js", "起動.bat"):
        assert f"### `{name}`" in text, f"{name} が収録されていない"

    # 数字が実物から取られていること（書き置きになっていない）
    from gikai.compose import LayoutSpec

    m = LayoutSpec().metrics()
    assert f"1段 {m['chars_per_line']} 字" in text


def test_claude_md_references_are_real():
    """開発用の約束ごとが、実物とずれていないこと。

    CLAUDE.md には「この罠はこのテストが守っている」と書いてあるので、
    テスト名を変えたらここで気づけるようにする。
    """
    import re

    doc = ROOT / "CLAUDE.md"
    assert doc.exists(), "gikai_editor/CLAUDE.md が無い"
    text = doc.read_text(encoding="utf-8")
    tests_src = (ROOT / "tests" / "test_all.py").read_text(encoding="utf-8")

    named = set(re.findall(r"`(test_\w+)`", text))
    assert named, "守っているテストが1つも書かれていない"
    for name in sorted(named):
        assert f"def {name}(" in tests_src, \
            f"CLAUDE.md が参照している {name} が見つからない"

    # 参照しているファイルが実在すること
    for rel in sorted(set(re.findall(r"`((?:gikai|tools|tests)/[\w./\-]+)`", text))):
        assert (ROOT / rel).exists(), f"CLAUDE.md が参照している {rel} が無い"

    # 譲れない前提が書かれていること
    for must in ("オフライン", "CP932", "抽出型", "pytest"):
        assert must in text, f"{must} の記載が消えている"


# ====================================================== 構成（台割）

def test_sections_have_the_house_order():
    """紙面の並びは日高村議会だよりの構成そのままであること。"""
    from gikai import sections as sec

    names = [s.name for s in sec.default_sections()]
    assert names == ["表紙", "行政報告", "審議したこと・決まったこと",
                     "閉会中の委員会活動報告", "一般質問", "特集", "最終ページ"]
    # 「特集」は無い号があるので、空でも催促しない
    opt = [s.id for s in sec.default_sections() if s.optional]
    assert opt == ["tokushu"]


def test_guess_section_from_filename_and_title():
    from gikai import sections as sec

    secs = sec.default_sections()
    sid, why = sec.guess_section(secs, filename="03_一般質問_森下けい子.docx")
    assert sid == "ippan" and "ファイル名" in why

    sid, _ = sec.guess_section(secs, title="行政報告（令和8年6月定例会）")
    assert sid == "gyosei"

    sid, _ = sec.guess_section(secs, title="編集後記")
    assert sid == "saishu"

    # ファイル名は見出しより強い（届いた名前のほうが当てになる）
    sid, why = sec.guess_section(
        secs, filename="特集_治水の取り組み.docx", title="一般質問")
    assert sid == "tokushu", why

    # 手がかりが無ければ、当て推量せず未分類にする
    sid, why = sec.guess_section(secs, filename="20260601.txt", title="")
    assert sid == "" and why


def test_outline_lists_sections_in_order_with_unassigned_last():
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第207号", "第207号")
        for name, body in [
            ("行政報告.txt", "村長から令和8年度の行政報告がありました。"),
            ("一般質問_森下.txt", "一般質問で防災について問う。"),
            ("なぞの原稿.txt", "どこにも当てはまらない文章です。"),
        ]:
            f = Path(d) / name
            f.write_text(body, encoding="utf-8")
            p.import_manuscript(f)

        out = p.outline()
        names = [g["name"] for g in out["sections"]]
        # 構成の順どおりで、判定できなかったものは最後にまとまる
        assert names[:7] == ["表紙", "行政報告", "審議したこと・決まったこと",
                             "閉会中の委員会活動報告", "一般質問", "特集", "最終ページ"]
        assert names[-1] == "未分類"
        assert out["unassigned"] == 1

        by_id = {g["id"]: g for g in out["sections"]}
        assert by_id["gyosei"]["count"] == 1
        assert by_id["ippan"]["count"] == 1
        assert by_id["cover"]["count"] == 0     # 無い区分も並びを見せるため残す


def test_move_article_reorders_within_its_section():
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第208号", "第208号")
        ids = []
        for i in (1, 2, 3):
            f = Path(d) / f"一般質問_{i}.txt"
            f.write_text(f"一般質問その{i}について問う。", encoding="utf-8")
            ids.append(p.import_manuscript(f).id)

        order = lambda o: [a["id"] for g in o["sections"]
                           if g["id"] == "ippan" for a in g["articles"]]
        assert order(p.outline()) == ids

        out = p.move_article(ids[2], -1)         # 3番目を1つ上へ
        assert order(out) == [ids[0], ids[2], ids[1]]

        # 端では動かない（押しても壊れない）
        out = p.move_article(ids[0], -1)
        assert order(out) == [ids[0], ids[2], ids[1]]


def test_delete_articles_keeps_the_original_manuscripts():
    """一括削除しても、議員から預かった原本には手を付けないこと。"""
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第209号", "第209号")
        ids = []
        for i in (1, 2, 3):
            f = Path(d) / f"原稿{i}.txt"
            f.write_text(f"本文その{i}です。", encoding="utf-8")
            ids.append(p.import_manuscript(f).id)
        kept = sorted(x.name for x in (p.root / "manuscripts").iterdir())
        assert len(kept) == 3

        r = p.delete_articles(ids[:2])
        assert r["deleted"] == 2
        assert len(r["titles"]) == 2
        assert [a.id for a in p.articles()] == [ids[2]]

        # 原本はそのまま残っている＝取り込み直せる
        assert sorted(x.name for x in (p.root / "manuscripts").iterdir()) == kept

        # 保存し直しても消えたまま（画面を開き直しても戻らない）
        again = Project.open(p.root)
        assert [a.id for a in again.articles()] == [ids[2]]

        # 空で呼んでも何も起きない
        assert p.delete_articles([])["deleted"] == 0


def test_compose_headings_are_not_split_across_columns():
    """見出しが段の切れ目で割れないこと。

    行送りを本文の高さに固定してあるため、本文より大きい見出しが段の
    終わりに掛かると、隣の行に重なって印刷される（実機で確認済み）。
    keepLines で丸ごと次の段へ送ることで避けている。
    """
    from gikai.compose import compose

    with tempfile.TemporaryDirectory() as d:
        res = compose(_sample_project(Path(d), n_articles=6, n_photos=0))
        with zipfile.ZipFile(res.path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        # 見出しの段落には必ず keepLines が付いている
        heads = xml.count('<w:pBdr>')
        assert heads >= 6, heads
        assert xml.count("<w:keepNext/><w:keepLines/>") >= heads, \
            "見出しが段の切れ目で割れる（隣の行に重なって出る）"


def test_compose_lays_out_sections_in_order():
    """自動組版が、構成の順に区分見出しを立てて組むこと。"""
    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第210号", "第210号")
        for name, body in [
            ("最終ページ_編集後記.txt", "編集後記です。" + "あ" * 60),
            ("行政報告.txt", "行政報告です。" + "い" * 60),
            ("一般質問_森下.txt", "一般質問です。" + "う" * 60),
        ]:
            f = Path(d) / name
            f.write_text(body, encoding="utf-8")
            p.import_manuscript(f)

        res = p.compose()
        with zipfile.ZipFile(Path(res["docx"])) as z:
            text = z.read("word/document.xml").decode("utf-8")
        pos = [text.find(x) for x in ("行政報告", "一般質問", "編集後記")]
        assert all(i >= 0 for i in pos), "区分の見出しが紙面に入っていない"
        # 取り込んだ順ではなく、紙面の並びの順に組まれていること
        assert pos == sorted(pos), "構成の順に組まれていない"


# ====================================================== かんたん作成

def _easy_project(d: Path):
    """フォルダに原稿を入れた状態の号を用意する。"""
    from gikai import easy

    p = Project.create(d / "第204号", "第204号")
    inbox = Path(easy.ensure_folders(p)["inbox"])
    body = ("本文です。日高村議会の活動についてお伝えします。\n"
            "二つ目の段落です。じゅうぶんな長さを持たせています。\n"
            "三つ目の段落です。写真がこのあたりに入ります。\n")
    put = lambda f, n, t: (inbox / f / n).write_text(t, encoding="utf-8")
    put("02_行政報告", "01_村長報告.txt", "村長からの行政報告\n" + body * 3)
    put("05_一般質問", "01_森下けい子.txt", "消防の広域化について問う\n" + body * 4)
    put("05_一般質問", "02_山中太郎.txt", "子育て支援について問う\n" + body * 3)
    put("07_最終ページ", "編集後記.txt", "編集後記\n" + body)
    return p, inbox


def test_easy_folders_are_named_in_paper_order():
    """フォルダ名の番号が、そのまま紙面の並びであること。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第204号", "第204号")
        r = easy.ensure_folders(p)
        names = [f["folder"] for f in r["folders"]]
        assert names == ["01_表紙", "02_行政報告", "03_審議したこと・決まったこと",
                         "04_閉会中の委員会活動報告", "05_一般質問", "06_特集",
                         "07_最終ページ"], names
        for n in names:
            assert (Path(r["inbox"]) / n).is_dir(), n
        # 何を入れればよいか、フォルダを開いた人がその場で分かるように
        readme = Path(r["inbox"]) / easy.README_NAME
        assert readme.exists()
        text = readme.read_text(encoding="utf-8")
        assert "写真" in text and "順番" in text

        # 2回目は作り直さない（中身を消さない）
        (Path(r["inbox"]) / "05_一般質問" / "原稿.txt").write_text("あ", encoding="utf-8")
        again = easy.ensure_folders(p)
        assert again["made"] == []
        assert (Path(r["inbox"]) / "05_一般質問" / "原稿.txt").exists()


def test_easy_build_uses_the_folder_as_the_answer():
    """どのフォルダに入れたかが、そのまま区分になること。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, _ = _easy_project(Path(d))
        res = easy.build(p, max_pages=0)
        assert len(res["report"]["added"]) == 4
        got = {g["name"]: [a["title"] for a in g["articles"]]
               for g in res["outline"]["sections"] if g["count"]}
        assert got == {
            "行政報告": ["村長からの行政報告"],
            "一般質問": ["消防の広域化について問う", "子育て支援について問う"],
            "最終ページ": ["編集後記"],
        }, got
        # 判定の当てずっぽうではなく、フォルダが根拠であること
        art = [a for a in p.articles() if a.title == "編集後記"][0]
        assert "フォルダ" in art.section_why
        assert res["outline"]["unassigned"] == 0


def test_easy_build_is_repeatable():
    """同じフォルダからは同じ紙面ができること（何度押しても増えない）。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        first = easy.build(p)
        again = easy.build(p)
        assert again["report"]["added"] == []
        assert len(again["report"]["kept"]) == 4
        assert again["counts"]["articles"] == first["counts"]["articles"]
        assert again["compose"]["pages"] == first["compose"]["pages"]

        # フォルダから消したものは紙面からも消える
        (inbox / "05_一般質問" / "02_山中太郎.txt").unlink()
        third = easy.build(p)
        assert third["report"]["removed"] == ["05_一般質問/02_山中太郎.txt"]
        assert third["counts"]["articles"] == 3

        # 差し替えたものは読み直す
        f = inbox / "07_最終ページ" / "編集後記.txt"
        f.write_text("編集後記\n入れ替えた本文です。", encoding="utf-8")
        fourth = easy.build(p)
        assert fourth["report"]["updated"] == ["07_最終ページ/編集後記.txt"]
        body = [a.body for a in p.articles() if a.title == "編集後記"][0]
        assert "入れ替えた本文" in body


def test_easy_build_fits_the_page_limit():
    """最大ページ数を決めたら、そこに収まるまで詰めること。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第204号", "第204号")
        inbox = Path(easy.ensure_folders(p)["inbox"])
        body = "本文です。日高村議会の活動についてお伝えします。\n" * 40
        for i in range(6):
            (inbox / "05_一般質問" / f"{i:02d}_議員{i}.txt").write_text(
                f"見出し{i}について問う\n" + body, encoding="utf-8")

        loose = easy.build(p, max_pages=0)
        tight = easy.build(p, max_pages=2)
        assert loose["compose"]["pages"] > 2, loose["compose"]["pages"]
        assert tight["compose"]["pages"] <= 2, tight["compose"]["pages"]
        # 詰めた結果を隠さず返していること
        assert tight["fit"]["applied"], "何をどれだけ詰めたかが返っていない"


def test_easy_photos_go_with_their_manuscript():
    """写真が、名前の合う原稿に付くこと（番号付きのファイル名でも）。"""
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        for folder, name in [("05_一般質問", "森下けい子1.jpg"),
                             ("05_一般質問", "森下けい子2.jpg"),
                             ("05_一般質問", "山中太郎.jpg"),
                             ("02_行政報告", "はぐれ写真.jpg")]:
            (inbox / folder / name).write_bytes(_png(size=(1800, 1300)))

        easy.build(p)
        by_title = {a.title: a for a in p.articles()}
        # 原稿名に `01_` が付いていても、写真は名前で結びつく
        assert len(by_title["消防の広域化について問う"].photos) == 2
        assert len(by_title["子育て支援について問う"].photos) == 1
        # 名前の合わない写真は、その区分の先頭の記事へ（迷子にしない）
        assert len(by_title["村長からの行政報告"].photos) == 1


def test_easy_photos_are_placed_inside_their_article():
    """写真が記事のそばに入ること（末尾にまとめて積まない）。"""
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        (inbox / "05_一般質問" / "森下けい子.jpg").write_bytes(_png(size=(1800, 1300)))
        res = easy.build(p)
        with zipfile.ZipFile(Path(res["compose"]["docx"])) as z:
            xml = z.read("word/document.xml").decode("utf-8")

        img = xml.find("<w:drawing>")
        head_next = xml.find("子育て支援について問う")
        assert img > 0 and head_next > 0
        # 写真は、次の記事の見出しより前＝自分の記事の中にある
        assert img < head_next, "写真が別の記事まで流れている"
        # しかも本文の途中（見出しの直後でも末尾でもない）
        body_start = xml.find("消防の広域化について問う")
        assert body_start < img


def test_easy_keeps_the_manuscripts_folder_untouched():
    """フォルダから外しても、議員から預かった原稿は消さないこと。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        easy.build(p)
        kept = sorted(x.name for x in (p.root / "manuscripts").iterdir())
        assert kept

        (inbox / "05_一般質問" / "02_山中太郎.txt").unlink()
        easy.build(p)
        # 記事は消えるが、取り込んだ原本は残る
        assert "子育て支援について問う" not in [a.title for a in p.articles()]
        assert sorted(x.name for x in (p.root / "manuscripts").iterdir()) == kept


def test_rename_keeps_the_photo_link():
    """原稿の名前を変えても、写真との結びつきが切れないこと。

    写真は原稿と同じ名前で結びつくので、原稿だけ名前を変えると外れる。
    あわせてそろえる。
    """
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        for n in ("01_森下けい子.jpg", "01_森下けい子2.jpg"):
            (inbox / "05_一般質問" / n).write_bytes(_png(size=(1800, 1300)))
        easy.build(p)
        art = [a for a in p.articles() if a.title == "消防の広域化について問う"][0]
        assert len(art.photos) == 2

        r = easy.rename(p, "05_一般質問/01_森下けい子.txt", "01_森下けい子議員",
                        with_photos=True)
        moved = {x["to"] for x in r["renamed"]}
        assert moved == {"05_一般質問/01_森下けい子議員.txt",
                         "05_一般質問/01_森下けい子議員.jpg",
                         "05_一般質問/01_森下けい子議員2.jpg"}, moved

        # 作り直しても「そのまま」＝取り込み直しになっていない
        again = easy.build(p)
        assert again["report"]["added"] == [] and again["report"]["removed"] == []
        art = [a for a in p.articles() if a.title == "消防の広域化について問う"][0]
        assert len(art.photos) == 2, "名前を変えたら写真が外れた"


def _camera_photos(folder: Path, names):
    for n in names:
        (folder / n).write_bytes(_png(size=(1800, 1300)))


def test_photo_plan_flags_only_the_ones_that_need_a_person():
    """カメラの名前のままの写真だけを「選んでください」と出すこと。

    名前がすでに合っているものまで選ばせると、結局全部を人がさわることに
    なって手間が減らない。
    """
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        _camera_photos(inbox / "05_一般質問",
                       ["IMG_2451.jpg", "IMG_2452.jpg", "DSC00123.jpg"])
        _camera_photos(inbox / "02_行政報告", ["01_村長報告.jpg"])

        plan = easy.photo_plan(p)
        assert plan["photos"] == 4
        assert plan["unmatched"] == 3, plan

        rows = {r["name"]: r for s in plan["sections"] for r in s["photos"]}
        # 原稿と名前が合っているものは、初めから相手が入っている
        assert rows["01_村長報告.jpg"]["decided"]
        assert rows["01_村長報告.jpg"]["doc"] == "01_村長報告.txt"
        # カメラの名前のままのものは、人に選んでもらう
        assert not rows["IMG_2451.jpg"]["decided"]
        assert rows["IMG_2451.jpg"]["doc"] == ""


def test_assign_photos_renames_to_match_the_manuscript():
    """選んだとおりに名前がそろい、そのまま記事に付くこと。"""
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        ippan = inbox / "05_一般質問"
        _camera_photos(ippan, ["IMG_2451.jpg", "IMG_2452.jpg",
                               "DSC00123.jpg", "P1010099.jpg"])

        r = easy.assign_photos(p, {
            "05_一般質問/IMG_2451.jpg": "01_森下けい子.txt",
            "05_一般質問/IMG_2452.jpg": "01_森下けい子.txt",
            "05_一般質問/DSC00123.jpg": "02_山中太郎.txt",
            "05_一般質問/P1010099.jpg": easy.UNUSED,
        })
        assert len(r["renamed"]) == 4

        names = sorted(x.name for x in ippan.iterdir() if x.is_file())
        assert names == ["01_森下けい子.txt", "01_森下けい子1.jpg", "01_森下けい子2.jpg",
                         "02_山中太郎.jpg", "02_山中太郎.txt"], names
        # 1枚だけの記事には番号を付けない（README の書き方に合わせる）
        assert (ippan / "02_山中太郎.jpg").exists()
        # 使わない写真は消さずによけるだけ
        assert (ippan / easy.UNUSED / "P1010099.jpg").exists()

        res = easy.build(p)
        by = {a.title: a for a in p.articles()}
        assert len(by["消防の広域化について問う"].photos) == 2
        assert len(by["子育て支援について問う"].photos) == 1
        assert res["counts"]["photos"] == 3, "よけた写真まで取り込んでいる"

        # 一度そろえたら、もう選ぶものは残らない
        assert easy.photo_plan(p)["unmatched"] == 0


def test_assign_photos_survives_a_swap():
    """写真を入れ替えても、名前がぶつかって消えないこと。"""
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        ippan = inbox / "05_一般質問"
        _camera_photos(ippan, ["IMG_1.jpg", "IMG_2.jpg"])
        easy.assign_photos(p, {"05_一般質問/IMG_1.jpg": "01_森下けい子.txt",
                               "05_一般質問/IMG_2.jpg": "02_山中太郎.txt"})
        assert (ippan / "01_森下けい子.jpg").exists()
        assert (ippan / "02_山中太郎.jpg").exists()

        # 取り違えていたので入れ替える
        easy.assign_photos(p, {"05_一般質問/01_森下けい子.jpg": "02_山中太郎.txt",
                               "05_一般質問/02_山中太郎.jpg": "01_森下けい子.txt"})
        names = sorted(x.name for x in ippan.iterdir() if x.suffix == ".jpg")
        assert names == ["01_森下けい子.jpg", "02_山中太郎.jpg"], names


def test_assign_photos_refuses_bad_input():
    from gikai import easy

    if not HAS_PIL:
        return
    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        _camera_photos(inbox / "05_一般質問", ["IMG_1.jpg"])
        bad = [
            {"05_一般質問/IMG_1.jpg": "ありません.txt"},      # 無い原稿
            {"05_一般質問/01_森下けい子.txt": "02_山中太郎.txt"},  # 写真ではない
            {"../../project.json": "01_森下けい子.txt"},       # フォルダの外
        ]
        for m in bad:
            try:
                easy.assign_photos(p, m)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{m} が通ってしまった")
        assert (inbox / "05_一般質問" / "IMG_1.jpg").exists()


def test_rename_can_move_to_another_section():
    """名前を変える窓口で、別の区分へ移せること。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        easy.build(p)
        easy.rename(p, "07_最終ページ/編集後記.txt", "巻頭のことば", section_id="cover")
        assert (inbox / "01_表紙" / "巻頭のことば.txt").exists()
        assert not (inbox / "07_最終ページ" / "編集後記.txt").exists()

        res = easy.build(p)
        assert res["report"]["added"] == [] and res["report"]["removed"] == []
        got = {g["name"]: g["count"] for g in res["outline"]["sections"] if g["count"]}
        assert got.get("表紙") == 1 and "最終ページ" not in got, got


def test_rename_refuses_what_it_should():
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        bad = [
            ("05_一般質問/01_森下けい子.txt", "02_山中太郎"),   # すでにある名前
            ("05_一般質問/01_森下けい子.txt", "森下.docx"),      # 種類を変える
            ("05_一般質問/01_森下けい子.txt", "   "),            # 空
            ("../../../外.txt", "なにか"),                       # フォルダの外
            ("05_一般質問/../../project.json", "なにか"),        # 同上
        ]
        for rel, name in bad:
            try:
                easy.rename(p, rel, name)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{rel} → {name} が通ってしまった")
        # 元のファイルは無事
        assert (inbox / "05_一般質問" / "01_森下けい子.txt").exists()


def test_renumber_puts_files_in_order():
    """番号を振り直すと、いまの並びのまま 01_ 02_ … が付くこと。"""
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p, inbox = _easy_project(Path(d))
        folder = inbox / "05_一般質問"
        # 番号なしを足して、並びを崩す
        (folder / "あいさつ.txt").write_text("ごあいさつ\n本文です。", encoding="utf-8")

        r = easy.renumber(p, "ippan")
        names = sorted(x.name for x in folder.iterdir())
        assert names == ["01_森下けい子.txt", "02_山中太郎.txt", "03_あいさつ.txt"], names
        assert r["renamed"], "何を変えたかが返っていない"

        # 2回目は何も起きない（すでに番号順）
        assert easy.renumber(p, "ippan")["renamed"] == []


def test_renumber_does_not_collide_when_shifting():
    """番号がぶつかる並べ替えでも、ファイルを失わないこと。

    02→01 のように詰めると、すでにある 01 と衝突する。
    いったん仮の名前へ逃がしているのはそのため。
    """
    from gikai import easy

    with tempfile.TemporaryDirectory() as d:
        p = Project.create(Path(d) / "第204号", "第204号")
        folder = Path(easy.ensure_folders(p)["inbox"]) / "05_一般質問"
        for n in ("02_い.txt", "03_う.txt", "05_お.txt"):
            (folder / n).write_text(n + "\n本文です。", encoding="utf-8")

        easy.renumber(p, "ippan")
        names = sorted(x.name for x in folder.iterdir())
        assert names == ["01_い.txt", "02_う.txt", "03_お.txt"], names
        # 中身が入れ替わっていないこと
        assert "02_い" in (folder / "01_い.txt").read_text(encoding="utf-8")


def test_open_is_limited_to_the_issue_folder():
    """「開く」で、号のフォルダの外を開けないこと。"""
    from gikai.server import ApiError, _resolve_open

    with tempfile.TemporaryDirectory() as d:
        p, _ = _easy_project(Path(d))
        assert _resolve_open(p, "inbox").is_dir()
        assert _resolve_open(p, "output").is_dir()
        for bad in ("../../etc/passwd", "/etc/passwd", "..\\..\\windows"):
            try:
                _resolve_open(p, bad)
            except ApiError:
                pass
            else:
                raise AssertionError(f"{bad} を開けてしまう")


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
