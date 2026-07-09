// P2: 取り込みの正規化ロジック（純粋関数）の単体テスト。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseStyledHtml,
  splitTextToParagraphs,
  fieldsFromParagraphs,
  stripTags,
  decodeEntities,
} from '../src/main/importers/normalize.ts';
import { articleFromDraft } from '../src/shared/project.ts';
import type { ArticleDraft } from '../src/shared/types.ts';

test('parseStyledHtml: 推奨様式のクラスから項目を判別', () => {
  const html =
    '<h1 class="gikai-title">防災について</h1>' +
    '<p class="gikai-author">山田 太郎</p>' +
    '<p class="gikai-body">本文1</p>' +
    '<p class="gikai-body">本文2</p>';
  const f = parseStyledHtml(html);
  assert.equal(f.title, '防災について');
  assert.equal(f.authorName, '山田 太郎');
  assert.deepEqual(f.body, ['本文1', '本文2']);
});

test('parseStyledHtml: タイトルが無ければ先頭段落を繰り上げ', () => {
  const html = '<p>これはタイトル扱い</p><p>本文A</p>';
  const f = parseStyledHtml(html);
  assert.equal(f.title, 'これはタイトル扱い');
  assert.deepEqual(f.body, ['本文A']);
});

test('parseStyledHtml: 空要素は無視し、エンティティを復号', () => {
  const html = '<p class="gikai-body">A&amp;B</p><p></p><p class="gikai-body">   </p>';
  const f = parseStyledHtml(html);
  // タイトル未取得 → 先頭本文(A&B)が繰り上がる
  assert.equal(f.title, 'A&B');
  assert.deepEqual(f.body, []);
});

test('splitTextToParagraphs: 空行で段落分割し、段落内改行は結合', () => {
  const text = 'タイトル\n\n本文の1行目\n続き\n\n\n次の段落';
  assert.deepEqual(splitTextToParagraphs(text), ['タイトル', '本文の1行目続き', '次の段落']);
});

test('fieldsFromParagraphs: 先頭タイトル・残り本文', () => {
  const f = fieldsFromParagraphs(['T', 'b1', 'b2']);
  assert.equal(f.title, 'T');
  assert.deepEqual(f.body, ['b1', 'b2']);
});

test('stripTags / decodeEntities', () => {
  assert.equal(stripTags('<b>あ</b>&lt;い&gt;'), 'あ<い>');
  assert.equal(decodeEntities('&#12354;'), 'あ');
});

test('articleFromDraft: 下書きから記事を確定し文字数を計算', () => {
  const draft: ArticleDraft = {
    source: 'word',
    sourceFile: 'a.docx',
    title: '見出し',
    subtitle: '',
    authorName: '山田',
    body: ['あいう', 'えお'],
    sourceScanRelativePath: null,
  };
  const art = articleFromDraft(draft, { id: 'art_1' });
  assert.equal(art.id, 'art_1');
  assert.equal(art.source, 'word');
  assert.equal(art.charCount, 5);
  assert.equal(art.memberId, null);
});
