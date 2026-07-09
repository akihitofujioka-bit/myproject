// Excel(.xlsx) 取り込み。先頭シートを行テキストにして本文にする。
// 主に「議決結果一覧」等の表データ用（§15.5）。
import * as xlsxNs from 'xlsx';
import path from 'node:path';
import type { ArticleDraft } from '../../shared/types.js';

// xlsx は環境により二形態: Vite は ESM(名前空間に関数)、tsx/CJS は default に実体。
// どちらでも動くよう、default があればそれを、無ければ名前空間を使う。
const XLSX = (xlsxNs as unknown as { default?: typeof xlsxNs }).default ?? xlsxNs;

export function extractExcelDraft(filePath: string): ArticleDraft {
  const wb = XLSX.readFile(filePath);
  const firstSheet = wb.SheetNames[0];
  const body: string[] = [];
  if (firstSheet) {
    const ws = wb.Sheets[firstSheet];
    const rows = XLSX.utils.sheet_to_json<(string | number)[]>(ws, { header: 1, blankrows: false });
    for (const row of rows) {
      const line = row.map((c) => (c == null ? '' : String(c))).join('\t').trim();
      if (line) body.push(line);
    }
  }
  return {
    source: 'excel',
    sourceFile: path.basename(filePath),
    title: firstSheet ? `${path.basename(filePath)}（${firstSheet}）` : path.basename(filePath),
    subtitle: '',
    authorName: '',
    body,
    sourceScanRelativePath: null,
  };
}
