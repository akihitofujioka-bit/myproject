"""原稿の取り込みと部品分け（ingest.py）のテスト。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ingest as I  # noqa: E402
import samples  # noqa: E402
from grid import Geometry, layout_text  # noqa: E402


class DocxReadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = samples.make_ippan_docx(Path(self.temp.name) / "sample.docx")

    def tearDown(self):
        self.temp.cleanup()

    def test_style_inheritance_and_direct_run_format(self):
        source = I.read_docx(self.path)
        self.assertEqual(source.images, {})
        title = next(p for p in source.paragraphs if p.text == "暮らしを守る防災対策")
        heading = next(p for p in source.paragraphs if p.text == "避難所の備え")
        body = next(p for p in source.paragraphs if p.text.startswith("問　"))
        self.assertEqual((title.size, title.bold), (16, True))
        self.assertEqual((heading.size, heading.bold), (14, True))
        self.assertEqual(body.size, 10.5)

    def test_table_textbox_image_and_caption(self):
        # 通常の一般質問見本とは分け、画像取り込み専用の一時原稿で確かめる。
        image_path = samples.make_ingest_image_docx(Path(self.temp.name) / "image.docx")
        result = I.ingest(image_path)
        texts = [p.text for p in result.parts]
        self.assertIn("表の中の段落です。", texts)
        self.assertIn("テキストボックスの段落です。", texts)
        self.assertLess(texts.index("表の中の段落です。"),
                        texts.index("テキストボックスの段落です。"))
        photo = next(p for p in result.parts if p.kind == "写真")
        caption = result.parts[result.parts.index(photo) + 1]
        self.assertEqual(photo.image, "face.png")
        self.assertEqual(result.images["face.png"][:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((caption.kind, caption.sure), ("写真説明", True))

    def test_question_continuation_proposal_and_guesses(self):
        parts = I.ingest(self.path).parts
        continuation = next(p for p in parts if p.text.startswith("あわせて"))
        proposal = next(p for p in parts if p.text.startswith("◎"))
        guessed = [p for p in parts if p.kind in ("大見出し", "中見出し")]
        self.assertEqual((continuation.kind, continuation.sure, continuation.reason),
                         ("質問", True, "前の段落の続き"))
        self.assertEqual((proposal.kind, proposal.sure), ("議案", True))
        self.assertTrue(guessed)
        self.assertTrue(all(not p.sure for p in guessed))
        self.assertEqual(guessed[0].kind, "大見出し")

    def test_number_normalization(self):
        parts = I.ingest(self.path).parts
        joined = "\n".join(p.text for p in parts)
        self.assertIn("年２回", joined)
        self.assertIn("2026年度に３地区", joined)

    def test_doctype_is_rejected(self):
        bad = Path(self.temp.name) / "bad.docx"
        with zipfile.ZipFile(self.path) as src, zipfile.ZipFile(bad, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "word/document.xml":
                    data = data.replace(b"?>", b'?><!DOCTYPE x [<!ENTITY x "x">]>', 1)
                dst.writestr(name, data)
        with self.assertRaisesRegex(ValueError, "通常の Word"):
            I.read_docx(bad)


class TextReadTest(unittest.TestCase):
    def test_normalize_number_rules(self):
        self.assertEqual(I.normalize_numbers("1人・１２人・781－2194・0889-24-7777"),
                         "１人・12人・781－2194・0889-24-7777")

    def test_txt_marks_are_certain(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sample.txt"
            path.write_text(
                "【大見出し】見本の質問\n【写真】face.png｜顔｜▲見本　太郎議員\n"
                "【見出し】備え\n問　内容を伺います。\n答　確認します。\n",
                encoding="utf-8-sig")
            result = I.ingest(path)
        title = result.parts[0]
        photo = next(p for p in result.parts if p.kind == "写真")
        caption = result.parts[result.parts.index(photo) + 1]
        headings = [p for p in result.parts if p.kind == "中見出し"]
        self.assertEqual((title.kind, title.sure), ("大見出し", True))
        self.assertTrue(all(p.sure for p in headings))
        self.assertEqual((photo.image, photo.sure), ("face.png", True))
        self.assertEqual((caption.kind, caption.sure), ("写真説明", True))

    def test_encoding_order_includes_cp932(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sjis.txt"
            path.write_bytes("問　数字は12です。".encode("cp932"))
            self.assertEqual(I.ingest(path).parts[0].kind, "質問")

    def test_plain_text_heading_is_guess(self):
        ps = [I.Paragraph("短い見出し"), I.Paragraph("問　内容です。")]
        first = I.classify(ps, False)[0]
        self.assertEqual((first.kind, first.sure), ("中見出し", False))


class CheckAndFitTest(unittest.TestCase):
    def test_fifth_question_and_missing_photo_warnings(self):
        parts = []
        for n in range(5):
            parts.extend([I.Part("質問", f"問　質問{n}。"), I.Part("答弁", "答　答弁です。")])
        self.assertEqual(I.check_ippan(parts),
                         ["質問が 5 つあります（4 つまで）", "顔写真がありません"])

    def test_continuous_question_paragraphs_count_once(self):
        parts = [I.Part("質問", "問　一つ目。"), I.Part("質問", "続きです。"),
                 I.Part("答弁", "答　答え。"), I.Part("写真", image="face.png")]
        self.assertEqual(I.check_ippan(parts), [])

    def test_fit_report_counts_each_kind(self):
        g = Geometry(chars_per_line=12)
        parts = [I.Part("大見出し", "数えない"), I.Part("中見出し", "二行"),
                 I.Part("写真", image="x.png"), I.Part("本文", "あ" * 13),
                 I.Part("質問", "問　短い質問。"), I.Part("写真説明", "説明")]
        expected = 2 + sum(len(layout_text([p.text], 12)) for p in parts
                           if p.kind in ("本文", "質問", "答弁", "議案", "写真説明"))
        report = I.fit_report(parts, g, expected - 1)
        self.assertEqual(report.needed_lines, expected)
        self.assertEqual((report.overflow_lines, report.free_lines), (1, 0))

    def test_unsupported_extension(self):
        with self.assertRaisesRegex(ValueError, "この形式は取り込めません"):
            I.ingest(Path("sample.pdf"))


if __name__ == "__main__":
    unittest.main()
