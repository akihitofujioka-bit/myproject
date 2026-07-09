// P2 完了条件の実証（Electron非依存）:
// 提出物を取り込み → 正規化して記事化 → 保存 → 再オープンで残る、をファイルI/O込みで確認。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { extractWordDraft } from '../src/main/importers/word.ts';
import { extractTextDraft } from '../src/main/importers/text.ts';
import { extractExcelDraft } from '../src/main/importers/excel.ts';
import { saveProjectToDir, loadProjectFromDir } from '../src/main/projectStore.ts';
import { copyIntoAssets, readAssetDataUrl } from '../src/main/assetStore.ts';
import { createEmptyProject, articleFromDraft, createImageAsset } from '../src/shared/project.ts';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORD_FIXTURE = path.join(__dirname, '..', 'poc', 'fixtures', 'sample-submission.docx');

async function tmpDir(): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), 'gikai-p2-'));
}

test('Word取り込み: 推奨様式のスタイルから項目を正規化', async () => {
  const draft = await extractWordDraft(WORD_FIXTURE);
  assert.equal(draft.source, 'word');
  assert.equal(draft.title, '一般質問　防災対策について');
  assert.match(draft.authorName, /山田/);
  assert.ok(draft.body.length >= 1);
});

test('テキスト取り込み: 先頭行タイトル・残り本文', async () => {
  const dir = await tmpDir();
  const txt = path.join(dir, 'kiji.txt');
  await fs.writeFile(txt, '見出しです\n\n本文の段落1\n\n本文の段落2', 'utf8');
  const draft = await extractTextDraft(txt);
  assert.equal(draft.title, '見出しです');
  assert.deepEqual(draft.body, ['本文の段落1', '本文の段落2']);
});

test('取り込み→記事化→保存→再オープンで記事が残る（完了条件）', async () => {
  const dir = await tmpDir();
  const draft = await extractWordDraft(WORD_FIXTURE);
  const project = createEmptyProject({ id: 'prj_p2', now: '2026-06-30T00:00:00.000Z' });
  project.articles.push(articleFromDraft(draft, { id: 'art_p2' }));

  await saveProjectToDir(dir, project);
  const reopened = await loadProjectFromDir(dir);

  assert.equal(reopened.articles.length, 1);
  assert.equal(reopened.articles[0].id, 'art_p2');
  assert.equal(reopened.articles[0].title, '一般質問　防災対策について');
  assert.equal(reopened.articles[0].source, 'word');
  assert.ok(reopened.articles[0].charCount > 0);
});

test('手書きスキャン: assetsへ複製→ImageAsset化→data URLで読み戻せる', async () => {
  const dir = await tmpDir();
  const project = createEmptyProject({ now: '2026-06-30T00:00:00.000Z' });
  await saveProjectToDir(dir, project); // assets/ を用意

  // ダミーのスキャン画像（PNGヘッダ）を用意して取り込む
  const scanSrc = path.join(dir, 'scan.png');
  await fs.writeFile(scanSrc, Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  const rel = await copyIntoAssets(dir, scanSrc);
  assert.match(rel, /^assets\/scan\.png$/);

  const image = createImageAsset(rel);
  const article = articleFromDraft(
    {
      source: 'handwritten',
      sourceFile: 'scan.png',
      title: '',
      subtitle: '',
      authorName: '',
      body: [],
      sourceScanRelativePath: rel,
    },
    { sourceScanImageId: image.id }
  );
  project.images.push(image);
  project.articles.push(article);
  await saveProjectToDir(dir, project);

  const reopened = await loadProjectFromDir(dir);
  assert.equal(reopened.images.length, 1);
  assert.equal(reopened.articles[0].sourceScanImageId, image.id);
  const dataUrl = await readAssetDataUrl(dir, reopened.images[0].relativePath);
  assert.match(dataUrl, /^data:image\/png;base64,/);
});

test('Excel取り込み: 表を本文行に正規化', async () => {
  // xlsx で最小のブックを生成して取り込む
  const XLSX = (await import('xlsx')).default;
  const dir = await tmpDir();
  const xlsxPath = path.join(dir, 'giketsu.xlsx');
  const ws = XLSX.utils.aoa_to_sheet([
    ['議案', '結果'],
    ['第1号', '可決'],
  ]);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  XLSX.writeFile(wb, xlsxPath);

  const draft = extractExcelDraft(xlsxPath);
  assert.equal(draft.source, 'excel');
  assert.ok(draft.body.some((l) => l.includes('第1号') && l.includes('可決')));
});
