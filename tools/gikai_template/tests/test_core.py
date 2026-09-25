"""自動テスト（python -m unittest discover -s tests）。

様式の実物（前年の議会だより）には人の名前が入っているので、リポジトリに
入れない。ここでは実物と同じ作り（表紙は横書き 1 段・本文は縦書き 5 段・
VML の文字枠・1 升の表の見出し・空行での位置合わせ）の小さな見本を
その場で組み立てて使う。

実物でも確かめたいときは、環境変数 GIKAI_TEMPLATE_DIR に .docx の入った
フォルダを指定する（RealTemplateTest）。
"""

from __future__ import annotations

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


class IssueTest(unittest.TestCase):
    def test_create_edit_reopen_and_build(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tpl = make_template(d)
            issue = core.Issue.create(d, "２０５", "令和９年１月29日", "1月号", tpl)
            self.assertEqual(issue.folder.name, "第205号")
            sid = next(s.id for s in issue.load_template().slots() if "要望" in s.old_text)
            issue.entries[sid] = core.Entry(core.NEW, "要望活動を行った")
            issue.copies.append({"src": sid, "id": sid + "+1"})
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
