// PoC: 議員から提出される想定の「Word原稿」サンプルを生成する。
// 推奨様式（§15）のスタイル名を付与し、後段の取り込み(02)で項目判別できるか検証する材料にする。
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from 'docx';
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(__dirname, '..', 'fixtures');
mkdirSync(outDir, { recursive: true });

const doc = new Document({
  styles: {
    paragraphStyles: [
      { id: 'GikaiTitle', name: '議会だより_タイトル', basedOn: 'Heading1', next: 'Normal',
        run: { size: 32, bold: true } },
      { id: 'GikaiName', name: '議会だより_氏名', basedOn: 'Normal', next: 'Normal',
        run: { size: 24 } },
      { id: 'GikaiBody', name: '議会だより_本文', basedOn: 'Normal', next: 'GikaiBody',
        run: { size: 21 } },
    ],
  },
  sections: [
    {
      children: [
        new Paragraph({ style: 'GikaiTitle', text: '一般質問　防災対策について' }),
        new Paragraph({ style: 'GikaiName', text: '山田 太郎（市民クラブ・議席番号3）' }),
        new Paragraph({
          style: 'GikaiBody',
          children: [
            new TextRun(
              '私は今回の一般質問で、近年頻発する集中豪雨への備えについて市の見解を質しました。'
            ),
          ],
        }),
        new Paragraph({
          style: 'GikaiBody',
          children: [
            new TextRun(
              '特に高齢者世帯への避難情報の伝達手段について、防災無線に加え、戸別受信機の配布拡大を提案しました。'
            ),
          ],
        }),
        new Paragraph({
          style: 'GikaiBody',
          children: [
            new TextRun('市長は「来年度に向けて前向きに検討する」と答弁しました。'),
          ],
        }),
      ],
    },
  ],
});

const buf = await Packer.toBuffer(doc);
const outPath = path.join(outDir, 'sample-submission.docx');
writeFileSync(outPath, buf);
console.log('生成:', outPath, `(${buf.length} bytes)`);
