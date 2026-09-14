// PoC (最重要): 縦書きの議会だより紙面を .docx で出力できるか検証する。
// docx ライブラリの TextDirection.TOP_TO_BOTTOM_RIGHT_TO_LEFT ("tbRl") を
// セクションに適用し、本文・見出し・写真を縦書きで配置する。
import {
  Document, Packer, Paragraph, TextRun, ImageRun,
  PageTextDirectionType, AlignmentType, PageOrientation,
} from 'docx';
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { makeSolidPng } from './_helpers.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, '..', 'out');
mkdirSync(outDir, { recursive: true });

// 写真の代わりの単色プレースホルダ（埋め込み検証用）
const photo = makeSolidPng(320, 240, [120, 160, 200]);

const body = [
  '私は今回の一般質問で、近年頻発する集中豪雨への備えについて市の見解を質しました。',
  '特に高齢者世帯への避難情報の伝達手段について、防災無線に加え、戸別受信機の配布拡大を提案しました。',
  '市長は「来年度に向けて前向きに検討する」と答弁し、来年度予算での対応に期待が持てる内容となりました。',
];

const doc = new Document({
  sections: [
    {
      properties: {
        page: {
          // ★ ここが縦書きの肝。セクション(ページ)の文字方向を「上→下、行は右→左」に設定。
          textDirection: PageTextDirectionType.TOP_TO_BOTTOM_RIGHT_TO_LEFT,
          size: { orientation: PageOrientation.PORTRAIT },
          margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 },
        },
      },
      children: [
        new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: '一般質問　防災対策について', bold: true, size: 32 })],
        }),
        new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: '山田 太郎（市民クラブ）', size: 24 })],
        }),
        new Paragraph({
          children: [
            new ImageRun({
              data: photo,
              transformation: { width: 240, height: 180 },
            }),
          ],
        }),
        ...body.map(
          (t) => new Paragraph({ children: [new TextRun({ text: t, size: 21 })] })
        ),
      ],
    },
  ],
});

const buf = await Packer.toBuffer(doc);
const outPath = path.join(outDir, 'vertical-newsletter.docx');
writeFileSync(outPath, buf);
console.log('生成:', outPath, `(${buf.length} bytes)`);
console.log('検証: unzip -p out/vertical-newsletter.docx word/document.xml | grep textDirection');
