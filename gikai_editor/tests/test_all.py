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
                 "追加部品のインストール.bat"):
        raw = (ROOT / name).read_bytes()
        text = raw.decode("cp932")           # 例外が出たら CP932 ではない
        assert "議会だより" in text, f"{name} の日本語が壊れている"
        assert b"\r\n" in raw, f"{name} の改行が CRLF ではない"
        try:
            raw.decode("ascii")
            raise AssertionError(f"{name} に日本語が含まれていない")
        except UnicodeDecodeError:
            pass  # 日本語が入っているのが正しい


def test_launcher_closes_after_start():
    """起動できたら黒い画面が残らないこと。"""
    text = _bat("起動.bat")
    # 画面なしの Python を使う
    assert "pythonw" in text and "pyw" in text
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
