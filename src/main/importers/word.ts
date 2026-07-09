// Word(.docx) 取り込み。mammoth で HTML 化し、スタイル名で項目を判別する。
import mammoth from 'mammoth';
import path from 'node:path';
import { parseStyledHtml, splitTextToParagraphs, fieldsFromParagraphs } from './normalize.js';
import type { ArticleDraft } from '../../shared/types.js';

// 推奨様式（§15）のスタイル名 → 内部クラスへのマッピング
const STYLE_MAP = [
  "p[style-name='議会だより_タイトル'] => h1.gikai-title:fresh",
  "p[style-name='議会だより_氏名'] => p.gikai-author:fresh",
  "p[style-name='議会だより_小見出し'] => h2.gikai-sub:fresh",
  "p[style-name='議会だより_本文'] => p.gikai-body:fresh",
];

export async function extractWordDraft(filePath: string): Promise<ArticleDraft> {
  const { value: html } = await mammoth.convertToHtml({ path: filePath }, { styleMap: STYLE_MAP });
  let fields = parseStyledHtml(html);
  // スタイル無し等で何も取れない場合は素テキストで代替
  if (!fields.title && fields.body.length === 0) {
    const { value: raw } = await mammoth.extractRawText({ path: filePath });
    fields = fieldsFromParagraphs(splitTextToParagraphs(raw));
  }
  return {
    source: 'word',
    sourceFile: path.basename(filePath),
    title: fields.title,
    subtitle: fields.subtitle,
    authorName: fields.authorName,
    body: fields.body,
    sourceScanRelativePath: null,
  };
}
