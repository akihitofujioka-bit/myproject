// PoC: 提出された Word(.docx) を取り込み、本文テキストと段落構造を抽出できるか検証する。
// mammoth でHTML/テキスト化し、スタイル名→項目（タイトル/氏名/本文）のマッピング方針を確認する。
import mammoth from 'mammoth';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { existsSync } from 'node:fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const input = path.join(__dirname, '..', 'fixtures', 'sample-submission.docx');

if (!existsSync(input)) {
  console.error('先に `npm run poc:make-sample` を実行してください。');
  process.exit(1);
}

// 推奨様式のスタイル名を、内部項目へマッピングする例。
// 様式に従っていない提出物は、この自動マッピングが外れた分だけ
// 正規化ワークベンチで担当者が項目に割り付ける（=ワンクッション）。
const styleMap = [
  "p[style-name='議会だより_タイトル'] => h1.title:fresh",
  "p[style-name='議会だより_氏名'] => p.author:fresh",
  "p[style-name='議会だより_本文'] => p.body:fresh",
];

const html = await mammoth.convertToHtml({ path: input }, { styleMap });
const text = await mammoth.extractRawText({ path: input });

console.log('=== スタイルマッピング後のHTML（項目判別の成否） ===');
console.log(html.value);
if (html.messages.length) {
  console.log('\n--- mammoth メッセージ ---');
  for (const m of html.messages) console.log(`[${m.type}] ${m.message}`);
}

console.log('\n=== 抽出した素のテキスト（手書き書き起こしの比較対象にも使える） ===');
console.log(text.value.trim());
