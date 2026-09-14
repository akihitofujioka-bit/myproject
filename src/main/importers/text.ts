// プレーンテキスト(.txt)取り込み。空行で段落分割し、先頭をタイトルにする。
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { splitTextToParagraphs, fieldsFromParagraphs } from './normalize.js';
import type { ArticleDraft } from '../../shared/types.js';

export async function extractTextDraft(filePath: string): Promise<ArticleDraft> {
  const raw = await fs.readFile(filePath, 'utf8');
  const fields = fieldsFromParagraphs(splitTextToParagraphs(raw));
  return {
    source: 'text',
    sourceFile: path.basename(filePath),
    title: fields.title,
    subtitle: fields.subtitle,
    authorName: fields.authorName,
    body: fields.body,
    sourceScanRelativePath: null,
  };
}
