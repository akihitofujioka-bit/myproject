"""自動テスト（python -m unittest discover -s tests）。

様式の実物（前年の議会だより）には人の名前が入っているので、リポジトリに
入れない。ここでは実物と同じ作り（表紙は横書き 1 段・本文は縦書き 5 段・
VML の文字枠・1 升の表の見出し・空行での位置合わせ）の小さな見本を
その場で組み立てて使う。

実物でも確かめたいときは、環境変数 GIKAI_TEMPLATE_DIR に .docx の入った
フォルダを指定する（RealTemplateTest）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import core  # noqa: E402
import flow  # noqa: E402
import xlsx_vote  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

ROOT_OPEN = (
    '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:w10="urn:schemas-microsoft-com:office:word" '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
    'mc:Ignorable="w14 wp14">'
)


def para(text: str = "", sz: int = 22, extra: str = "", ppr: str = "") -> str:
    run = (f'<w:r><w:rPr><w:sz w:val="{sz}"/></w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
           if text else "")
    return (f'<w:p w14:paraId="1234ABCD"><w:pPr>{ppr}<w:rPr><w:sz w:val="{sz}"/></w:rPr></w:pPr>'
            f'{extra}{run}</w:p>')


def vml_box(text: str, *, vertical: bool = False, sid: int = 2001) -> str:
    flow = ' style="layout-flow:vertical;mso-layout-flow-alt:top-to-bottom"' if vertical else ""
    return (
        f'<w:r><w:pict w14:anchorId="0D619DA6"><v:shape id="_x0000_s{sid}" type="#_x0000_t202" '
        'style="position:absolute;margin-left:30pt;margin-top:40pt;width:200pt;height:40pt;'
        'mso-position-horizontal-relative:margin">'
        f'<v:textbox{flow}><w:txbxContent>'
        f'<w:p><w:r><w:rPr><w:rFonts w:ascii="ＭＳ ゴシック" w:eastAsia="ＭＳ ゴシック"/>'
        f'<w:sz w:val="22"/></w:rPr><w:t>{text}</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox><w10:wrap anchorx="margin"/></v:shape></w:pict></w:r>')


SECT_COVER = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="851" w:right="851" '
              'w:bottom="680" w:left="851" w:header="851" w:footer="992" w:gutter="0"/>'
              '<w:cols w:space="720"/><w:docGrid w:linePitch="360"/></w:sectPr>')
SECT_BODY = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="851" w:right="851" '
             'w:bottom="680" w:left="851" w:header="851" w:footer="992" w:gutter="0"/>'
             '<w:cols w:num="5" w:space="420"/><w:textDirection w:val="tbRl"/>'
             '<w:docGrid w:linePitch="360" w:charSpace="-3061"/></w:sectPr>')


def sample_document() -> str:
    body = [
        para("　　　　第２０１号", 40),
        para("　　　令和８年１月３１日", 32),
        para("ひだか議会だより", 72),
        para(),
        para("特集　新年の抱負を聞きました　…………14Ｐ", 24),
        para("発行　高知県日高村議会", 24, ppr=SECT_COVER),
        # 本文（縦書き 5 段）
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid><w:tr><w:tc><w:tcPr/>'
        + para("行政報告（要旨）", 48) + '</w:tc></w:tr></w:tbl>',
        para("　長"), para("　村"), para("郎"), para("　太"), para("　田"), para("　山"),
        para(),
        para("防災訓練", 28),
        para(),
        para("11月９日に防災訓練を行った。", 22, extra=vml_box("防災訓練の様子")),
        para("参加者は80人だった。"),
        para(), para(), para(), para(), para(),
        para("要望活動", 28),
        para(),
        para("質問　お米券配布はどうなるのか。"),
        '<w:p><w:pPr><w:rPr><w:sz w:val="22"/></w:rPr></w:pPr>'
        '<w:r><w:rPr><w:b/><w:sz w:val="22"/></w:rPr><w:t>答弁</w:t></w:r>'
        '<w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">　山田村長</w:t></w:r></w:p>',
        para("", extra=vml_box("別添１：第４回定例会議案・発議案と賛否", sid=2002)),
        para(), para(),
        para("おわり"),
        SECT_BODY,
    ]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ROOT_OPEN
            + "<w:body>" + "".join(body) + "</w:body></w:document>")


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>')


def make_template(folder: Path) -> Path:
    path = folder / "様式見本.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", sample_document())
    return path


def make_vote_xlsx(folder: Path) -> Path:
    """第204号の賛否表と同じ並び（見出しは 3 行目、議員は O 列から）の小さな Excel。"""
    cells = {
        "A1": "第３回定例会議案・発議案と賛否", "T2": "○：賛成　●：反対",
        "O3": "山田花子", "P3": "佐藤一郎", "Q3": "鈴木和子", "Y3": "議決結果",
        "J4": "議員名", "B6": "議　案・発議案",
        "A8": "認　定", "D8": "歳入歳出決算", "O8": "〇", "P8": "〇", "Q8": "議長", "Y8": "認定",
        "A9": "条例など", "D9": "村税条例の一部を改正する条例\n給水条例の一部を改正する条例",
        "O9": "〇", "P9": "●", "Q9": "議長", "Y9": "可決",
    }
    strings = list(dict.fromkeys(cells.values()))
    rows: dict[int, list[str]] = {}
    for ref, v in cells.items():
        r = int(re.sub(r"[A-Z]", "", ref))
        rows.setdefault(r, []).append(f'<c r="{ref}" t="s"><v>{strings.index(v)}</v></c>')
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.'
             'openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + "".join(f'<row r="{r}">{"".join(c)}</row>' for r, c in sorted(rows.items()))
             + '</sheetData></worksheet>')
    # ふりがな（rPh）を混ぜない確認のため、1 つ目の議員名に読みを付けておく
    sst = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main">' + "".join(
               f'<si><t xml:space="preserve">{s}</t>'
               + ('<rPh sb="0" eb="2"><t>ヤマダ</t></rPh>' if s == "山田花子" else "")
               + '</si>' for s in strings) + '</sst>')
    path = folder / "賛否.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
    return path


def document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = make_template(self.dir)
        self.tpl = core.Template(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def slot(self, text: str) -> core.Slot:
        return next(s for s in self.tpl.slots() if text in s.old_text)

    def test_finds_body_boxes_and_heading_cells_in_paper_order(self):
        kinds = [(s.kind, s.short) for s in self.tpl.slots()]
        self.assertEqual(kinds[0][0], "body")                      # 表紙
        self.assertIn(("cell", "行政報告（要旨）"), kinds)
        self.assertIn(("box", "防災訓練の様子"), kinds)
        # 枠は、つなぎ留めている段落の記事より前に並ぶ（紙面の順）
        order = [s.short for s in self.tpl.slots()]
        self.assertLess(order.index("防災訓練"), order.index("防災訓練の様子"))

    def test_groups_follow_big_headings_and_skip_name_lines(self):
        s = self.slot("11月９日")
        self.assertEqual(s.group, "行政報告（要旨）")
        name = self.slot("　長")
        self.assertEqual(name.kind_label, "名前（1字ずつ）")

    def test_vertical_body_has_12_chars_per_line_at_11pt(self):
        # 第201号の画面で数えた値（「村表彰式を行い、４人の方」＝ 12 字）
        geo = self.tpl.geometry(1)
        self.assertTrue(geo.vertical)
        self.assertEqual(geo.chars_per_line(11), 12)
        self.assertEqual(geo.base_pt, 11)

    def test_saved_file_keeps_namespace_declarations_for_word(self):
        # ElementTree は使っていない宣言を落とすが、mc:Ignorable の w14 が
        # 宣言されていないと Word が「壊れている」と判断する
        self.tpl.fill({})
        out = self.tpl.save(self.dir / "out.docx")
        xml = document_xml(out)
        self.assertIn('mc:Ignorable="w14 wp14"', xml)
        self.assertIn('xmlns:wp14=', xml)
        self.assertNotIn("ns0:", xml)
        ET.fromstring(xml.encode("utf-8"))

    def test_replacing_text_keeps_the_anchored_box_and_section_break(self):
        s = self.slot("11月９日")
        self.tpl.fill({s.id: core.Entry(core.NEW, "12月１日に訓練を行った。")})
        out = self.tpl.save(self.dir / "out.docx")
        xml = document_xml(out)
        self.assertIn("防災訓練の様子", xml)          # 枠は残る
        self.assertNotIn("参加者は80人", xml)
        self.assertEqual(xml.count("<w:sectPr"), 2)
        # 2 桁の数字は縦中横、1 桁は全角
        self.assertIn('w:vert="1"', xml)
        self.assertIn("１日", xml)

    def test_longer_article_eats_following_blank_lines(self):
        s = self.slot("11月９日")
        before = len(list(self.tpl.body))
        long_text = "あ" * 12 * 4          # 4 行ぶん
        rep = self.tpl.fill({s.id: core.Entry(core.NEW, long_text)})
        # 前年は 2 段落で 3 行（1 段落目が 14 字で 2 行）。1 段落 4 行になり 1 行長い
        # → 段落が 1 つ減り、空行も 1 つ減る
        self.assertEqual(len(list(self.tpl.body)), before - 1 - 1)
        self.assertEqual(rep.overflow_body, [])

    def test_article_too_long_is_reported(self):
        s = self.slot("11月９日")
        rep = self.tpl.fill({s.id: core.Entry(core.NEW, "あ" * 12 * 20)})
        self.assertEqual(len(rep.overflow_body), 1)
        self.assertGreater(rep.overflow_body[0][1], 10)

    def test_shorter_article_adds_blank_lines(self):
        s = self.slot("11月９日")
        before = len(list(self.tpl.body))
        rep = self.tpl.fill({s.id: core.Entry(core.NEW, "短い。")})
        # 3 行 → 1 行。2 段落が 1 段落になり、空行を 2 つ足す
        self.assertEqual(rep.added_blank, 2)
        self.assertEqual(len(list(self.tpl.body)), before - 1 + 2)

    def test_label_keeps_its_own_format(self):
        s = self.slot("答弁")
        self.tpl.fill({s.id: core.Entry(core.NEW, "質問　新しい質問。\n答弁　佐藤総務課長")})
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        m = re.search(r"<w:r><w:rPr><w:b\s*/><w:sz w:val=\"22\"\s*/></w:rPr><w:t>答弁</w:t>", xml)
        self.assertIsNotNone(m, "「答弁」の太字が引き継がれていない")

    def test_untouched_slots_are_highlighted_and_cover_number_is_updated(self):
        rep = self.tpl.fill({}, gou="205", hakkoubi="令和９年１月29日")
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertIn("第２０５号", xml)
        self.assertIn("令和９年１月２９日", xml)
        self.assertNotIn("第２０１号", xml)
        self.assertIn('w:highlight w:val="yellow"', xml)
        self.assertGreater(len(rep.kept), 3)

    def test_same_mode_is_not_highlighted(self):
        s = self.slot("発行")
        self.tpl.fill({s.id: core.Entry(core.SAME)}, mark_keep=True)
        p = self.tpl.refs[s.id].paras[0]
        self.assertNotIn("highlight", ET.tostring(p, encoding="unicode"))

    def test_name_lines_are_built_one_char_per_line_from_the_end(self):
        s = self.slot("　長")
        self.tpl.fill({s.id: core.Entry(core.NEW, "高橋次郎　議員")})
        lines = [core.para_text(p) for p in self.tpl.refs[s.id].paras]
        self.assertEqual([t.strip() for t in lines], list("員議郎次橋高"))

    def test_ruby_notation_becomes_word_ruby(self):
        s = self.slot("要望活動")
        self.tpl.fill({s.id: core.Entry(core.NEW, "｜山田《やまだ》さん")})
        p = self.tpl.refs[s.id].paras[0]
        self.assertEqual(core.para_text(p), "｜山田《やまだ》さん")
        self.assertIsNotNone(p.find(f".//{{{W_NS}}}ruby"))

    def test_vote_table_goes_into_the_box_in_excel_orientation(self):
        vote = xlsx_vote.read_vote_table(make_vote_xlsx(self.dir))
        s = self.slot("別添１")
        rep = self.tpl.fill({s.id: core.Entry(core.TABLE)}, vote=vote)
        self.assertEqual(len(rep.tables), 1)
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertIn("<w:tbl>", xml)
        self.assertIn('w:val="tbRlV"', xml)           # 議員名は縦書き
        self.assertIn("mso-position-vertical:bottom", xml)
        self.assertNotIn("ヤマダ", xml)
        # 升目の段落は行グリッドから外す（外さないと字が切れた: gikai_editor）
        tbl = xml[xml.find("<w:tbl>"):xml.find("</w:tbl>")]
        self.assertEqual(tbl.count("<w:p>"), tbl.count('<w:snapToGrid w:val="0"'))

    def test_duplicate_body_and_box(self):
        body = self.slot("要望活動")
        new = self.tpl.duplicate(body.id, body.id + "+1")
        self.assertEqual(new.copy_of, body.id)
        box = self.slot("防災訓練の様子")
        nb = self.tpl.duplicate(box.id, box.id + "+1")
        self.tpl.fill({nb.id: core.Entry(core.NEW, "新しい写真の説明")})
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertEqual(xml.count("防災訓練の様子"), 1)
        self.assertIn("新しい写真の説明", xml)
        self.assertEqual(len(re.findall(r'id="_x0000_s\d+"', xml)),
                         len(set(re.findall(r'id="(_x0000_s\d+)"', xml))))

    def test_emptying_a_body_keeps_positions_with_blank_lines(self):
        s = self.slot("11月９日")
        before = len(list(self.tpl.body))
        self.tpl.fill({s.id: core.Entry(core.EMPTY)})
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertNotIn("11月", xml)
        self.assertIn("防災訓練の様子", xml)   # 空にしても、つなぎ留めた枠は残る
        # 3 行の記事が、枠をつなぎ留めた空行 1 つ＋足した空行 2 つ（計 3 行）になる
        self.assertEqual(len(list(self.tpl.body)), before - 2 + 3)


class RegroupTest(unittest.TestCase):
    """読み取りを人が直す（分ける・つなげる・種類を変える）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tpl = core.Template(make_template(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def slot(self, text: str) -> core.Slot:
        return next(s for s in self.tpl.slots() if text in s.old_text)

    def test_split_keeps_format_of_each_part(self):
        s = self.slot("答弁")
        self.assertIn("質問", s.old_text)
        new = self.tpl.split(s.id, 1, s.id + "/1")
        self.assertEqual(self.tpl.refs[s.id].slot.old_text, "質問　お米券配布はどうなるのか。")
        self.assertTrue(new.old_text.startswith("答弁"))
        self.assertEqual(self.tpl.order.index(new.id), self.tpl.order.index(s.id) + 1)
        self.tpl.fill({s.id: core.Entry(core.NEW, "質問　新しい質問。"),
                       new.id: core.Entry(core.NEW, "答弁　佐藤総務課長")})
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertIn("新しい質問", xml)
        self.assertRegex(xml, r"<w:b\s*/><w:sz w:val=\"22\"\s*/></w:rPr><w:t>答弁</w:t>")

    def test_split_rejects_first_line(self):
        s = self.slot("答弁")
        with self.assertRaises(ValueError):
            self.tpl.split(s.id, 0, "x")

    def test_merge_joins_article_split_by_blank_lines(self):
        a = self.slot("11月９日")
        b = next(x for x in self.tpl.slots() if x.old_text == "要望活動")
        # 間に空行が 5 つある記事と見出しをつなげる（本文どうしなのでつなげられる）
        gone = self.tpl.merge(a.id)
        self.assertEqual(gone, b.id)
        self.assertNotIn(b.id, self.tpl.refs)
        self.assertIn("要望活動", self.tpl.refs[a.id].slot.old_text)
        before = len(list(self.tpl.body))
        self.tpl.fill({a.id: core.Entry(core.NEW, "つなげた記事。")})
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertNotIn("要望活動", xml)
        self.assertIn("防災訓練の様子", xml)          # 枠は残る
        self.assertLessEqual(abs(len(list(self.tpl.body)) - before), 12)

    def test_merge_refuses_across_other_content(self):
        cell = next(s for s in self.tpl.slots() if s.kind == "cell")
        with self.assertRaises(ValueError):
            self.tpl.merge(cell.id)             # 升目の後ろに同じ升目は無い

    def test_kind_override_changes_processing(self):
        s = self.slot("要望活動")
        self.tpl.set_kind(s.id, "名前（1字ずつ）")
        self.assertEqual(s.kind_label, "名前（1字ずつ）")
        self.tpl.fill({s.id: core.Entry(core.NEW, "高橋次郎")})
        lines = [core.para_text(p).strip() for p in self.tpl.refs[s.id].paras]
        self.assertEqual(lines, list("郎次橋高"))

    def test_heading_kind_uses_biggest_font(self):
        s = self.slot("11月９日")
        self.tpl.set_kind(s.id, "見出し")
        self.tpl.fill({s.id: core.Entry(core.NEW, "新しい見出し")})
        p = self.tpl.refs[s.id].paras[0]
        self.assertIn('w:val="22"', ET.tostring(p, encoding="unicode"))

    def test_box_kind_cannot_change(self):
        box = self.slot("防災訓練の様子")
        with self.assertRaises(ValueError):
            self.tpl.set_kind(box.id, "本文")

    def test_ops_are_replayed_in_order_and_undo_by_popping(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            issue = core.Issue.create(d, "205", "", "1月号", make_template(d))
            tpl = issue.load_template()
            s = next(x for x in tpl.slots() if "答弁" in x.old_text)
            issue.ops.append({"op": "split", "id": s.id, "at": 1, "new": s.id + "/1"})
            issue.ops.append({"op": "copy", "src": s.id + "/1", "id": s.id + "/1+1"})
            issue.kinds[s.id] = "見出し"
            issue.save()
            again = core.Issue.open(issue.folder)
            tpl = again.load_template()
            self.assertIn(s.id + "/1+1", tpl.refs)
            self.assertEqual(tpl.refs[s.id].slot.kind_label, "見出し")
            again.ops.pop()
            self.assertNotIn(s.id + "/1+1", again.load_template().refs)

    def test_old_copies_record_is_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            issue = core.Issue.create(d, "205", "", "1月号", make_template(d))
            sid = next(x.id for x in issue.load_template().slots() if "要望" in x.old_text)
            (issue.folder / core.DATA_NAME).write_text(
                '{"slots": {}, "copies": [{"src": "%s", "id": "%s+1"}], "removed": []}' % (sid, sid),
                encoding="utf-8")
            self.assertIn(sid + "+1", core.Issue.open(issue.folder).load_template().refs)


def make_manuscript(folder: Path) -> Path:
    """議員から届く原稿の見本。見出しの付け方を 3 通り混ぜてある。"""
    def p(text, rpr="", ppr=""):
        return (f'<w:p><w:pPr>{ppr}</w:pPr><w:r><w:rPr>{rpr}<w:sz w:val="21"/></w:rPr>'
                f'<w:t>{text}</w:t></w:r></w:p>')
    body = "".join([
        p("防災訓練", ppr='<w:pStyle w:val="1"/>'),                        # 見出しスタイル
        p("12月１日に防災訓練を行い、多くの住民が参加した。"),
        p("来年も続けて取り組んでいく。"),
        p("要望活動", rpr="<w:b/>"),                                        # 太字だけ
        p("国や県に対して、予算の確保を要望した。"),
        '<w:p><w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>表彰式</w:t></w:r></w:p>',  # 大きい字
        p("功労表彰を授与した。"),
    ])
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{W_NS}">'
              '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/>'
              '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>')
    path = folder / "原稿.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
    return path


class DistributeTest(unittest.TestCase):
    """原稿を見出しと本文に分けて、欄へ振り分ける。"""

    def test_docx_headings_by_style_bold_and_size(self):
        with tempfile.TemporaryDirectory() as d:
            blocks = core.split_manuscript(make_manuscript(Path(d)))
        self.assertEqual([(b.kind, b.text.split("\n")[0][:6]) for b in blocks], [
            ("見出し", "防災訓練"), ("本文", "12月１日に"),
            ("見出し", "要望活動"), ("本文", "国や県に対し"),
            ("見出し", "表彰式"), ("本文", "功労表彰を授")])
        self.assertEqual(blocks[1].text.count("\n"), 1)     # 本文の 2 段落は 1 まとまり

    def test_plain_text_headings_by_line_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "原稿.txt"
            path.write_text("防災訓練\n12月１日に防災訓練を行った。\n\n質問　どうするのか。\n"
                            "答弁　佐藤総務課長\n検討する。\n", encoding="cp932")
            blocks = core.split_manuscript(path)
        self.assertEqual(blocks[0].kind, "見出し")
        # 「質問」「答弁」で始まる行は見出しにしない
        self.assertFalse(any(b.kind == "見出し" and b.text.startswith(("質問", "答弁"))
                             for b in blocks))

    def test_assign_follows_paper_order_and_skips_captions(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tpl = core.Template(make_template(d))
            blocks = core.split_manuscript(make_manuscript(d))
        slots = tpl.slots()
        start = next(s.id for s in slots if s.old_text == "防災訓練")
        plan = core.assign_blocks(blocks, slots, start)
        got = [tpl.refs[i].slot.short if i else None for i in plan]
        self.assertEqual(got[0], "防災訓練")                 # 見出し → 見出し
        self.assertTrue(got[1].startswith("11月"))            # 本文 → 本文（写真の説明文の枠は飛ばす）
        self.assertEqual(got[2], "要望活動")
        self.assertTrue(got[3].startswith("質問"))
        self.assertNotIn("防災訓練の様子", got)

    def test_extra_body_paragraph_does_not_shift_later_articles(self):
        # 原稿の本文が様式より細かく分かれていても、後ろの見出しがずれないこと
        # （前から詰めるだけの作りでは、第201号で 26 のうち 8 しか合わなかった）
        with tempfile.TemporaryDirectory() as d:
            tpl = core.Template(make_template(Path(d)))
        slots = tpl.slots()
        start = next(s.id for s in slots if s.old_text == "防災訓練")
        H, B = core.HEADING, core.BODY
        blocks = [core.Block(H, "防災訓練"), core.Block(B, "一つ目。"), core.Block(B, "二つ目。"),
                  core.Block(H, "要望活動"), core.Block(B, "質問　三つ目。")]
        plan = core.assign_blocks(blocks, slots, start)
        short = [tpl.refs[i].slot.short if i else None for i in plan]
        self.assertEqual(short[0], "防災訓練")
        self.assertEqual(plan[1], plan[2])                   # 本文 2 つは同じ欄へつなげる
        self.assertEqual(short[3], "要望活動")
        self.assertTrue(short[4].startswith("質問"))

    def test_big_box_accepts_headings_but_caption_does_not(self):
        big = core.Slot("T1", "box", "簡易水道の有収率向上を", 1, False, 24)
        cap = core.Slot("T2", "box", "防災訓練の様子", 1, False, 11)
        self.assertTrue(core.accepts(big, core.HEADING))
        self.assertFalse(core.accepts(cap, core.HEADING))
        self.assertFalse(core.accepts(big, core.BODY))


class IssueTest(unittest.TestCase):
    def test_create_edit_reopen_and_build(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tpl = make_template(d)
            issue = core.Issue.create(d, "２０５", "令和９年１月29日", "1月号", tpl)
            self.assertEqual(issue.folder.name, "第205号")
            sid = next(s.id for s in issue.load_template().slots() if "要望" in s.old_text)
            issue.entries[sid] = core.Entry(core.NEW, "要望活動を行った")
            issue.ops.append({"op": "copy", "src": sid, "id": sid + "+1"})
            issue.save()
            again = core.Issue.open(issue.folder)
            self.assertEqual(again.entries[sid].text, "要望活動を行った")
            self.assertIn(sid + "+1", again.load_template().refs)
            rep = again.build()
            self.assertTrue(rep.out.exists())
            self.assertIn("要望活動を行った", document_xml(rep.out))

    def test_refuses_existing_folder(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tpl = make_template(d)
            core.Issue.create(d, "205", "", "1月号", tpl)
            with self.assertRaises(ValueError):
                core.Issue.create(d, "205", "", "1月号", tpl)


# ---------------------------------------------------------------- 一般質問の組み直し（flow.py）


def head_table(title: str) -> str:
    """議員ごとの題の 1 升の表。様式と同じく本文の外に浮かせ、前年の題の長さで寸法を決めてある。"""
    return ('<w:tbl><w:tblPr><w:tblpPr w:leftFromText="142" w:rightFromText="142" '
            'w:vertAnchor="page" w:tblpX="2475" w:tblpY="1394"/><w:tblOverlap w:val="never"/>'
            '<w:tblW w:w="1559" w:type="dxa"/></w:tblPr><w:tblGrid><w:gridCol w:w="1559"/></w:tblGrid>'
            '<w:tr><w:trPr><w:trHeight w:val="5968"/></w:trPr><w:tc><w:tcPr><w:tcW w:w="1559" w:type="dxa"/></w:tcPr>'
            + para(title, 36) + '</w:tc></w:tr></w:tbl>')


def ippan_document(trailing: str = "") -> str:
    """一般質問 2 人ぶん（前年）の見本。題の表・1 字ずつの名前・質問・答弁・2 問目の題。"""
    member = lambda title, name, sub: [  # noqa: E731
        head_table(title),
        *[para(ch) for ch in reversed(list(name + "議員"))],
        para(),
        para("質問　前年の質問の文である。"),
        '<w:p><w:pPr><w:rPr><w:sz w:val="22"/></w:rPr></w:pPr>'
        '<w:r><w:rPr><w:b/><w:sz w:val="22"/></w:rPr><w:t>答弁</w:t></w:r>'
        '<w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">　前年総務課長</w:t></w:r></w:p>',
        para("前年の答弁の本文で、十字より長い文である。"),
        para(),
        para(sub, 28),
        para(),
        para("質問　前年の二つ目の質問。"),
        para("答弁　前年村長"),
        para("前年の二つ目の答弁の本文である。"),
        *[para() for _ in range(6)],
    ]
    body = [
        para("第２０１号", 40, ppr=SECT_COVER),
        para("前の区分の記事である。"),
        para(), para(),
        para("", extra=vml_box("一般質問に２氏が立つ", vertical=True, sid=2101)),
        para(), para(),
        *member("前年の一つ目の題", "佐藤一郎", "前年の小見出し"),
        *member("前年の二つ目の題", "鈴木和子", "前年の別の小見出し"),
        trailing,
        para(), para(),
        para("", extra=vml_box("特集　新年の抱負", vertical=True, sid=2102).replace(
            'w:val="22"', 'w:val="48"')),
        para("特集の本文である。"),
        SECT_BODY,
    ]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ROOT_OPEN
            + "<w:body>" + "".join(body) + "</w:body></w:document>")


def make_ippan_template(folder: Path, trailing: str = "") -> Path:
    path = folder / "様式一般質問.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", ippan_document(trailing))
    return path


IPPAN_TEXT = """一般質問に３氏が立つ

防災対策について
山田太郎議員
【写真】yamada.jpg｜顔
質問　避難所の備蓄は十分か。
答弁　佐藤総務課長
　備蓄品は毎年見直しており、水と毛布を120人分増やす。
高齢者の見守り
質問　一人暮らしの高齢者の見守りは。
答弁　鈴木健康福祉課長
　民生委員と連携して訪問を続けている。

鈴木和子議員
公共交通の
今後について
質問　周遊バスの利用者を増やす考えは。
答弁　山田村長
　ダイヤを見直す。
【写真】bus.jpg｜中｜周遊バス

高橋次郎議員
空き家対策について
質問　空き家の活用はどうか。
答弁　佐藤企画課長
　空き家バンクに15件を登録した。
"""


class FlowParseTest(unittest.TestCase):
    def test_lines_are_classified(self):
        kinds = {ln.text: ln.kind for ln in flow.classify(IPPAN_TEXT)}
        self.assertEqual(kinds["一般質問に３氏が立つ"], flow.SKIP)
        self.assertEqual(kinds["山田太郎議員"], flow.MEMBER)
        self.assertEqual(kinds["防災対策について"], flow.TITLE)       # 名前より前に書いた題
        self.assertEqual(kinds["公共交通の"], flow.TITLE)            # 2 行に分けた題
        self.assertEqual(kinds["今後について"], flow.TITLE)
        self.assertEqual(kinds["【写真】yamada.jpg｜顔"], flow.PHOTO)
        self.assertEqual(kinds["答弁　佐藤総務課長"], flow.TEXT)
        self.assertEqual(kinds["ダイヤを見直す。"], flow.TEXT)

    def test_grouped_by_member_and_title(self):
        members, warns = flow.group(flow.classify(IPPAN_TEXT))
        self.assertEqual(warns, [])
        self.assertEqual([m.name for m in members], ["山田太郎", "鈴木和子", "高橋次郎"])
        self.assertEqual([t.title for t in members[0].topics],
                         [["防災対策について"], ["高齢者の見守り"]])
        self.assertEqual(members[0].head_photos, ["【写真】yamada.jpg｜顔"])
        self.assertEqual(members[1].topics[0].title, ["公共交通の", "今後について"])
        # 本文の行頭の字下げは残す
        self.assertIn("　備蓄品は毎年見直しており、水と毛布を120人分増やす。",
                      members[0].topics[0].lines)

    def test_override_by_line_text(self):
        lines = flow.classify(IPPAN_TEXT, {"高齢者の見守り": flow.TEXT})
        members, _ = flow.group(lines)
        self.assertEqual(len(members[0].topics), 1)
        self.assertEqual(next(ln for ln in lines if ln.text == "高齢者の見守り").auto, flow.TITLE)

    def test_question_before_any_name_is_warned(self):
        _, warns = flow.group(flow.classify("題の行\n質問　名前が無い。\n答弁　村長"))
        self.assertTrue(any("議員名" in w for w in warns))

    def test_kanji_number(self):
        self.assertEqual(flow._num("七"), 7)
        self.assertEqual(flow._num("十二"), 12)
        self.assertEqual(flow._num("１０"), 10)


class FlowBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.members, _ = flow.group(flow.classify(IPPAN_TEXT))

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, trailing: str = "") -> tuple[core.Template, flow.FlowResult, str]:
        tpl = core.Template(make_ippan_template(self.dir, trailing))
        res = flow.apply_ippan(tpl, self.members)
        xml = document_xml(tpl.save(self.dir / "out.docx"))
        return tpl, res, xml

    def test_parts_are_found_in_the_template(self):
        tpl = core.Template(make_ippan_template(self.dir))
        parts = flow.extract_parts(tpl)
        self.assertEqual(parts.old_count, 2)
        self.assertEqual(parts.head[0].tag, core.w("p"))           # 題の見本は囲みの段落
        self.assertIsNotNone(parts.head[0].find(f"{core.w('pPr')}/{core.w('pBdr')}"))
        self.assertIsNotNone(parts.name_at)
        self.assertIn("小見出し", core.para_text(parts.subtitle))
        # 終わりは最後の答弁の本文の次（後ろの空行と特集はそのまま残す）
        kids = list(tpl.body)
        self.assertEqual(core.para_text(kids[parts.end - 1]), "前年の二つ目の答弁の本文である。")

    def test_members_are_rebuilt_from_parts(self):
        _, res, xml = self.build()
        self.assertEqual((res.members, res.topics, res.old_count), (3, 4, 2))
        self.assertIn("一般質問に３氏が立つ", xml)
        for old in ("前年の一つ目の題", "佐藤一郎", "前年の小見出し", "前年の答弁"):
            self.assertNotIn(old, xml)
        self.assertNotIn("<w:tbl>", xml)                            # 題は表でなく囲みの段落
        self.assertEqual(xml.count("<w:pBdr>"), 4)                  # 3 人ぶん（1 人は 2 行の題）
        for title in ("防災対策について", "空き家対策について"):
            self.assertIn(title, xml)
        self.assertIn("高齢者の見守り", xml)                         # 2 問目の題
        # 名前は後ろの字から 1 字ずつの行
        body = ET.fromstring(xml.encode("utf-8")).find(core.w("body"))
        texts = [core.para_text(p) for p in body if p.tag == core.w("p")]
        i = texts.index("員")
        self.assertEqual(texts[i:i + 6], ["員", "議", "郎", "太", "田", "山"])
        self.assertIn("特集の本文である。", xml)                     # 後ろの区分はそのまま
        self.assertIn("前の区分の記事である。", xml)

    def test_title_is_a_boxed_paragraph_fitted_to_its_length(self):
        _, _, xml = self.build()
        self.assertNotIn("tblpPr", xml)                    # 浮かせない（重ならない・切れない）
        body = ET.fromstring(xml.encode("utf-8")).find(core.w("body"))
        heads = [p for p in body if p.find(f"{core.w('pPr')}/{core.w('pBdr')}") is not None]
        self.assertEqual([core.para_text(p) for p in heads],
                         ["防災対策について", "公共交通の", "今後について", "空き家対策について"])
        # 囲みは題の長さに縮める（段の残りを字下げ）。1 段（18pt で 7 字）を超える題は
        # 字下げせずに折り返す。2 行の題は同じ字下げで 1 つの囲みになる
        ind = [int(p.find(f"{core.w('pPr')}/{core.w('ind')}").get(core.w("right"))) for p in heads]
        self.assertEqual(ind[0], 0)
        self.assertGreater(ind[1], 0)
        self.assertEqual(ind[1], ind[2])

    def test_titles_keep_with_next_and_photo_is_marked(self):
        _, _, xml = self.build()
        self.assertIn("keepNext", xml)
        self.assertIn("【写真】bus.jpg（中・幅55mm）", xml)
        self.assertIn('w:val="FF0000"', xml)
        self.assertIn('<w:eastAsianLayout', xml)                 # 120 は縦中横

    def test_length_is_padded_to_keep_later_positions(self):
        tpl, res, _ = self.build()
        # 前年との差は、空行でページ単位（1 ページ = 5 段 × 36 行）にそろえる
        diff = res.new_lines + res.pad - res.old_lines
        self.assertAlmostEqual(diff, res.pages_added * flow.PAGE_LINES, delta=1)
        self.assertIn("一般質問を組み直しました", res.text())

    def test_content_after_last_answer_without_big_heading_is_kept(self):
        # 第199号のように、最後の議員のあとに大きな見出しの無い記事が続く
        _, _, xml = self.build(para("", extra=vml_box("写真の説明の枠", sid=2103)) + para("お知らせの本文"))
        self.assertIn("お知らせの本文", xml)
        self.assertIn("写真の説明の枠", xml)

    def test_slots_inside_are_left_out_of_fill(self):
        tpl, res, _ = self.build()
        self.assertTrue(res.skipped_slots)
        self.assertFalse(set(tpl.refs) & res.skipped_slots)
        tpl.fill({})                                    # 外した欄に触らずに差し込める
        self.assertTrue(any("前の区分" in s.old_text for s in tpl.slots()))

    def test_issue_build_uses_the_manuscript(self):
        issue = core.Issue.create(self.dir, "205", "", "1月号", make_ippan_template(self.dir))
        src = self.dir / "05_一般質問.txt"
        src.write_text(IPPAN_TEXT, encoding="utf-8")
        issue.set_flow_source(flow.IPPAN, str(src))
        issue.flow_kinds(flow.IPPAN)["高齢者の見守り"] = flow.TEXT
        issue.save()
        again = core.Issue.open(issue.folder)
        self.assertEqual(again.flow_kinds(flow.IPPAN), {"高齢者の見守り": flow.TEXT})
        rep = again.build()
        self.assertIn("議員 3 人・質問の題 3 件", rep.text())
        self.assertIn("空き家対策について", document_xml(rep.out))

    def test_broken_manuscript_leaves_template_as_is(self):
        issue = core.Issue.create(self.dir, "205", "", "1月号", make_ippan_template(self.dir))
        issue.set_flow_source(flow.IPPAN, str(self.dir / "無い.txt"))
        rep = issue.build()
        self.assertIn("組み直せませんでした", rep.text())
        self.assertIn("前年の一つ目の題", document_xml(rep.out))


# ---------------------------------------------------------------- 行政報告・委員会報告の組み直し


def big_box(text: str, sid: int, sz: int = 48) -> str:
    return vml_box(text, vertical=True, sid=sid).replace('w:val="22"', f'w:val="{sz}"')


def sections_document() -> str:
    """行政報告と委員会報告（前年）の見本。第198〜201号と同じ作り。"""
    body = [
        para("第２０１号", 40, ppr=SECT_COVER),
        # 行政報告: 区分の頭（表と村長の名前）は組み直さない
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid><w:tr><w:tc><w:tcPr/>'
        + para("行政報告（要旨）", 56) + '</w:tc></w:tr></w:tbl>',
        para("　長"), para("　村"), para("郎"), para("　太"), para("　田"), para("　山"),
        para(), para(),
        para("前年の表彰式", 28), para(),
        para("前年の表彰式の本文で、十字より長い文である。", extra=vml_box("前年の写真の説明", sid=2201)),
        para(), para(), para(),
        para("前年の要望活動", 28), para(),
        para("前年の要望活動の本文である。"),
        # 次の区分（決算）の見出しの一部が、最後の本文につなぎ留めてある（第200号）
        para("前年の最後の本文である。", extra=big_box("一般会計決算額", 2202, sz=32)),
        para(), para(),
        para("", extra=vml_box("１２月議会では、計10議案が決まった。", sid=2203)),
        para("◎前年の議案の行。"),
        para(), para(),
        # 委員会報告: 大見出しの枠が、最初の委員会の名前の行につなぎ留めてある（第201号）
        para("総務常任委員会", 28), para(), para(),
        para("　　　　　　郎"), para("太"),
        para("田", extra=big_box("閉会中の委員会活動報告", 2204, sz=40)),
        para("　　　　　　佐"),
        para(),
        para("　　　　　　長"), para("　　　　　　員"), para("　　　　　　委"),
        para(), para(),
        para("11月26日（水）午後２時より"), para(),
        para("前年総務課長"),
        para("　前年の総務常任委員会の本文である。", extra=vml_box("前年の委員会の写真", sid=2205)),
        para(), para(),
        para("経済建設厚生", 28), para("常任委員会", 28), para(), para(),
        para("花"), para("和"), para("中"), para("田"), para(), para("長"), para("員"), para("委"),
        para(), para("前年の経済建設厚生常任委員会の本文である。"),
        para(), para(),
        para("", extra=vml_box("一般質問に２氏が立つ", vertical=True, sid=2206)),
        para("質問　一般質問の本文。"),
        SECT_BODY,
    ]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ROOT_OPEN
            + "<w:body>" + "".join(body) + "</w:body></w:document>")


def make_sections_template(folder: Path) -> Path:
    path = folder / "様式行政委員会.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", sections_document())
    return path


GYOSEI_TEXT = """行政報告（要旨）
■防災訓練
11月９日に防災訓練を行い、村民120人が参加した。
【写真】kunren.jpg｜中｜段ボールベッドの組み立て
要望活動
10月に国と県へ、令和９年度の予算の確保を要望した。
村の表彰式
11月３日に表彰式を行い、３人の方に功労表彰を授与した。
"""

IINKAI_TEXT = """閉会中の委員会活動報告
総務常任委員会
委員長　山田太郎
11月26日（水）午後２時より
佐藤総務課長
　職員の採用試験では、一般職２人に合格を通知した。
経済建設厚生
常任委員会
鈴木和子委員長
11月26日（水）午前10時より
高橋建設課長
　村道の改良工事は、年度内に終わる見込みである。
"""


class SectionParseTest(unittest.TestCase):
    def test_gyosei_lines(self):
        lines, arts, warns, summ = flow.read_flow("行政報告", GYOSEI_TEXT)
        self.assertEqual(warns, [])
        self.assertEqual([a.title for a in arts], [["防災訓練"], ["要望活動"], ["村の表彰式"]])
        self.assertEqual(arts[0].lines[-1], "【写真】kunren.jpg｜中｜段ボールベッドの組み立て")
        self.assertEqual(summ, "記事 3 件")
        self.assertEqual(lines[0].kind, flow.SKIP)            # 区分の題は使わない

    def test_iinkai_lines(self):
        lines, arts, warns, _ = flow.read_flow("委員会報告", IINKAI_TEXT)
        self.assertEqual(warns, [])
        self.assertEqual([a.title for a in arts], [["総務常任委員会"], ["経済建設厚生", "常任委員会"]])
        self.assertEqual([a.chair for a in arts], [("山田太郎", "委員長"), ("鈴木和子", "委員長")])
        kinds = {ln.text: ln.kind for ln in lines}
        # 課長名・日時は短くても見出しにしない
        self.assertEqual(kinds["佐藤総務課長"], flow.TEXT)
        self.assertEqual(kinds["11月26日（水）午後２時より"], flow.TEXT)

    def test_kind_names_follow_the_section(self):
        self.assertEqual(flow.kind_name("行政報告", flow.TITLE), "見出し")
        self.assertEqual(flow.kind_name("委員会報告", flow.MEMBER), "委員長の名前")
        self.assertEqual(flow.kind_name(flow.IPPAN, flow.MEMBER), "議員名")


class SectionBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tpl = core.Template(make_sections_template(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, key: str, text: str) -> tuple[flow.FlowResult, str]:
        _, arts, _, _ = flow.read_flow(key, text)
        res = flow.apply_flow(self.tpl, key, arts)
        return res, document_xml(self.tpl.save(self.dir / "out.docx"))

    def test_ranges(self):
        kids = list(self.tpl.body)
        g = flow.extract_section(self.tpl, flow.SECTIONS["行政報告"])
        self.assertEqual(core.para_text(kids[g.start]), "前年の表彰式")
        self.assertIn("１２月議会では", flow._all_text(kids[g.end]))     # 次の区分の頭の枠
        i = flow.extract_section(self.tpl, flow.SECTIONS["委員会報告"])
        self.assertEqual(core.para_text(kids[i.start]), "総務常任委員会")  # 大見出しの枠より前から
        self.assertIn("一般質問に", flow._all_text(kids[i.end]))
        self.assertEqual(len(i.name), 4)                   # 佐田太郎（1 字ずつ）
        self.assertEqual(len(i.role), 3)                   # 委員長

    def test_gyosei_is_rebuilt_and_other_sections_kept(self):
        res, xml = self.apply("行政報告", GYOSEI_TEXT)
        self.assertEqual(res.label, "行政報告")
        self.assertIn("行政報告を組み直しました（記事 3 件）", res.text())
        for old in ("前年の表彰式", "前年の要望活動", "前年の写真の説明"):
            self.assertNotIn(old, xml)
        for new in ("防災訓練", "要望活動", "村の表彰式", "【写真】kunren.jpg（中・幅55mm）"):
            self.assertIn(new, xml)
        self.assertIn("行政報告（要旨）", xml)                  # 区分の頭は残す
        self.assertIn("一般会計決算額", xml)                    # 次の区分の見出しの一部は残す
        self.assertIn("１２月議会では", xml)
        self.assertIn("前年の総務常任委員会の本文", xml)        # 委員会報告には触らない

    def test_iinkai_chair_names_and_heading_box(self):
        res, xml = self.apply("委員会報告", IINKAI_TEXT)
        self.assertIn("閉会中の委員会活動報告", xml)            # 名前の行につないであった大見出し
        self.assertNotIn("前年の委員会の写真", xml)
        self.assertNotIn("前年総務課長", xml)
        body = ET.fromstring(xml.encode("utf-8")).find(core.w("body"))
        texts = [core.para_text(p).strip("　") for p in body if p.tag == core.w("p")]
        i = texts.index("総務常任委員会")
        # 見出し・空行・名前（後ろの字から）・空行・「委員長」（後ろの字から）
        self.assertEqual(texts[i + 2:i + 6], ["郎", "太", "田", "山"])
        self.assertEqual(texts[i + 7:i + 10], ["長", "員", "委"])
        self.assertIn("経済建設厚生", texts)
        self.assertEqual(texts[texts.index("経済建設厚生") + 1], "常任委員会")
        self.assertIn("一般質問に２氏が立つ", xml)
        self.assertEqual(sum(1 for s in self.tpl.slots() if "閉会中" in s.old_text), 1)

    def test_all_three_through_issue(self):
        issue = core.Issue.create(self.dir, "205", "", "1月号", make_sections_template(self.dir))
        for key, text in (("行政報告", GYOSEI_TEXT), ("委員会報告", IINKAI_TEXT)):
            src = self.dir / f"{key}.txt"
            src.write_text(text, encoding="utf-8")
            issue.set_flow_source(key, str(src))
        issue.save()
        again = core.Issue.open(issue.folder)
        rep = again.build()
        self.assertIn("行政報告を組み直しました", rep.text())
        self.assertIn("委員会報告を組み直しました", rep.text())
        xml = document_xml(rep.out)
        self.assertIn("村の表彰式", xml)
        self.assertIn("年度内に終わる見込み", xml)

    def test_old_ippan_record_is_still_read(self):
        issue = core.Issue.create(self.dir, "205", "", "1月号", make_sections_template(self.dir))
        data = json.loads((issue.folder / core.DATA_NAME).read_text(encoding="utf-8"))
        data["ippan"] = {"source": "05_一般質問.txt", "kinds": {"題": flow.TEXT}}
        (issue.folder / core.DATA_NAME).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        again = core.Issue.open(issue.folder)
        self.assertEqual(again.flow_source(flow.IPPAN), "05_一般質問.txt")
        self.assertEqual(again.flow_kinds(flow.IPPAN), {"題": flow.TEXT})


# ---------------------------------------------------------------- 審議したこと・特集


def category_box(text: str, sid: int) -> str:
    return vml_box(text, vertical=True, sid=sid).replace('w:val="22"', 'w:val="28"')


def card_box(name: str, org: str, body: str, sid: int) -> str:
    """特集の 1 人ぶんの縦書きの枠（名前・所属・ひとこと）。"""
    return (f'<w:r><w:pict><v:shape id="_x0000_s{sid}" type="#_x0000_t202" '
            'style="position:absolute;margin-left:-300pt;margin-top:6pt;width:220pt;height:280pt">'
            '<v:textbox style="layout-flow:vertical;mso-layout-flow-alt:top-to-bottom"><w:txbxContent>'
            + para() + para(name) + para(org) + para(body)
            + '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>')


def shingi_tokushu_document() -> str:
    body = [
        para("第２０１号", 40, ppr=SECT_COVER),
        para("", extra=vml_box("１２月議会では、計３議案が決まった。", sid=2301)),
        para(), para(),
        para("", extra=category_box("人　事", 2302)),
        para("◎前年の人事の議案に同意した。"),
        para("前年候補者氏"),
        para(),
        para("◎前年の条例の議案", extra=category_box("条　例", 2303)),
        para("質疑"),
        para("問　前年の問いである。"),
        para("答　前年の答えである。"),
        para(), para(),
        para("", extra=vml_box("別添１：第４回定例会議案・発議案と賛否", sid=2304)),
        para(), para(),
        para("", extra=vml_box("一般質問に１氏が立つ", vertical=True, sid=2305)),
        head_table("前年の題"),
        *[para(ch) for ch in reversed(list("前年一郎議員"))],
        para("質問　前年の質問。"), para("答弁　前年村長"), para("前年の答弁の本文である。"),
        para(), para(),
        para("", extra=big_box("特集　新年の抱負を聞きました", 2306, sz=56)),
        para("", extra=card_box("前年太郎さん・花子さん", "前年農園", "前年の抱負の文である。", 2307)
             + card_box("前年次郎さん", "前年食堂", "前年の二人目の抱負である。", 2308)),
        para(), para(),
        para("", extra=card_box("前年三郎さん", "前年会", "前年の三人目の抱負である。", 2309)),
        para(), para(),
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="800"/></w:tblGrid><w:tr><w:tc><w:tcPr/>'
        + para("編集後記", 36) + '</w:tc></w:tr></w:tbl>',
        para("編集後記の本文。"),
        SECT_BODY,
    ]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ROOT_OPEN
            + "<w:body>" + "".join(body) + "</w:body></w:document>")


def make_shingi_template(folder: Path) -> Path:
    path = folder / "様式審議特集.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", shingi_tokushu_document())
    return path


SHINGI_TEXT = """審議したこと　決まったこと
人事
◎教育委員の任命に同意した。
候補者
山田花子氏
議員提出議案
◎議会会議規則の一部を改正する規則
予算
◎令和９年度一般会計補正予算（第２号）
質疑
問　防災倉庫の整備費の内容は。
答　備蓄品を置く倉庫を２か所に建てる。
"""

TOKUSHU_TEXT = """特集　新年の抱負を聞きました
｜山田《やまだ》 太郎さん・花子さん
山田農園
新年あけましておめでとうございます。今年も元気に野菜を作ります。
鈴木和子さん
今年はお店を広げる予定です。
"""


class ShingiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tpl = core.Template(make_shingi_template(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def test_lines(self):
        lines, arts, warns, summ = flow.read_flow(flow.SHINGI, SHINGI_TEXT)
        self.assertEqual(warns, [])
        self.assertEqual([a.title for a in arts], [["人事"], ["議員提出議案"], ["予算"]])
        self.assertEqual(summ, "区分 3・議案 3 件")
        self.assertEqual(flow.kind_name(flow.SHINGI, flow.TITLE), "区分（人事・条例など）")

    def test_range_and_rebuild(self):
        kids = list(self.tpl.body)
        sp = flow.extract_shingi(self.tpl)
        self.assertIn("人", flow._all_text(kids[sp.start]))
        self.assertIn("別添１", flow._all_text(kids[sp.end]))          # 賛否表の枠の手前まで
        _, arts, _, _ = flow.read_flow(flow.SHINGI, SHINGI_TEXT)
        res = flow.apply_flow(self.tpl, flow.SHINGI, arts)
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertIn("審議したことを組み直しました（区分 3・議案 3 件）", res.text())
        for old in ("前年の人事の議案", "前年の問い", "条　例"):
            self.assertNotIn(old, xml)
        for new in ("教育委員の任命", "議員提出議案", "防災倉庫", "山田花子氏"):
            self.assertIn(new, xml)
        self.assertIn("１２月議会では", xml)                              # 区分の頭は残す
        self.assertIn("別添１：第４回定例会議案", xml)                    # 賛否表の枠も残す
        body = ET.fromstring(xml.encode("utf-8")).find(core.w("body"))
        boxed = [core.para_text(p) for p in body
                 if p.find(f"{core.w('pPr')}/{core.w('pBdr')}") is not None]
        self.assertEqual(boxed, ["人事", "議員提出議案", "予算"])          # 区分は囲みの段落


class TokushuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.tpl = core.Template(make_shingi_template(self.dir))

    def tearDown(self):
        self.tmp.cleanup()

    def test_lines(self):
        lines, cards, warns, summ = flow.read_flow(flow.TOKUSHU, TOKUSHU_TEXT)
        self.assertEqual(warns, [])
        self.assertEqual([c.name for c in cards], ["｜山田《やまだ》 太郎さん・花子さん", "鈴木和子さん"])
        self.assertEqual(cards[0].lines[0], "山田農園")
        self.assertEqual(lines[0].kind, flow.SKIP)

    def test_cards_are_found_in_paper_order(self):
        cards = flow.find_cards(self.tpl)
        self.assertEqual([c.slot.old_text.split("\n")[1] for c in cards],
                         ["前年太郎さん・花子さん", "前年次郎さん", "前年三郎さん"])

    def test_fill_and_remove_extra_cards(self):
        _, cards, _, _ = flow.read_flow(flow.TOKUSHU, TOKUSHU_TEXT)
        res = flow.apply_flow(self.tpl, flow.TOKUSHU, cards)
        xml = document_xml(self.tpl.save(self.dir / "out.docx"))
        self.assertIn("2 人（組）を、前年の 3 枠に入れた", res.text())
        self.assertIn("1 つ余ったので消しました", res.text())
        for old in ("前年太郎", "前年次郎", "前年三郎", "前年の抱負"):
            self.assertNotIn(old, xml)
        self.assertIn("<w:rubyBase>", xml)                             # ふりがな
        self.assertIn("山田農園", xml)
        self.assertIn("鈴木和子さん", xml)
        self.assertIn("特集　新年の抱負を聞きました", xml)            # 見出しの枠は前年の欄のまま
        self.assertIn("編集後記の本文。", xml)

    def test_too_many_people_are_reported(self):
        text = TOKUSHU_TEXT + "".join(f"佐藤{n}郎さん\nひとこと。\n" for n in "一二三")
        _, cards, _, _ = flow.read_flow(flow.TOKUSHU, text)
        res = flow.apply_flow(self.tpl, flow.TOKUSHU, cards)
        self.assertIn("枠が 2 つ足りません", res.text())
        self.assertIn("佐藤二郎さん、佐藤三郎さん", res.text())

    def test_template_without_cards_is_refused(self):
        tpl = core.Template(make_sections_template(self.dir))
        _, cards, _, _ = flow.read_flow(flow.TOKUSHU, TOKUSHU_TEXT)
        with self.assertRaises(ValueError):
            flow.apply_flow(tpl, flow.TOKUSHU, cards)


class TextTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(core.normalize_numbers("１２月3日　〒７８１－２１９４"),
                         "12月３日　〒７８１－２１９４")

    def test_width_counts_tatechuyoko_as_one(self):
        self.assertEqual(core.text_width("令和10年", True), 4)
        self.assertEqual(core.text_width("令和10年", False), 4)
        self.assertEqual(core.text_width("｜山田《やまだ》", True), 2)


class VoteTest(unittest.TestCase):
    def test_reads_members_rows_and_ignores_furigana(self):
        with tempfile.TemporaryDirectory() as d:
            t = xlsx_vote.read_vote_table(make_vote_xlsx(Path(d)))
        self.assertEqual(t.members, ["山田花子", "佐藤一郎", "鈴木和子"])
        self.assertEqual(t.title, "第３回定例会議案・発議案と賛否")
        self.assertEqual(len(t.rows), 2)
        self.assertEqual(t.rows[1].items, ["村税条例の一部を改正する条例", "給水条例の一部を改正する条例"])
        self.assertEqual(t.rows[1].votes, ["〇", "●", "議長"])
        self.assertEqual(t.rows[1].result, "可決")

    def test_old_xls_gets_a_clear_message(self):
        with self.assertRaises(ValueError) as cm:
            xlsx_vote.read_cells("古い.xls")
        self.assertIn(".xlsx", str(cm.exception))


class BatchFileTest(unittest.TestCase):
    def test_batch_files_are_cp932_crlf(self):
        # UTF-8 だと日本語版 Windows で文字化けする（gikai_editor で踏んだ）
        for bat in HERE.parent.glob("*.bat"):
            raw = bat.read_bytes()
            raw.decode("cp932")
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), bat.name)


@unittest.skipUnless(os.environ.get("GIKAI_TEMPLATE_DIR"), "実物の様式は指定したときだけ")
class RealTemplateTest(unittest.TestCase):
    def test_every_real_template_round_trips(self):
        folder = Path(os.environ["GIKAI_TEMPLATE_DIR"])
        for path in sorted(folder.glob("*.docx")):
            with self.subTest(path.name), tempfile.TemporaryDirectory() as d:
                tpl = core.Template(path)
                self.assertGreater(len(tpl.order), 100)
                tpl.fill({})
                out = tpl.save(Path(d) / "out.docx")
                ET.fromstring(document_xml(out).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
