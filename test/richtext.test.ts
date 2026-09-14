// P4: 本文リッチテキスト(HTML)ヘルパーの単体テスト。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  escapeHtml,
  paragraphsToHtml,
  htmlToPlainText,
  countCharsFromHtml,
} from '../src/shared/richtext.ts';

test('escapeHtml: 記号をエスケープ', () => {
  assert.equal(escapeHtml('a<b>&c'), 'a&lt;b&gt;&amp;c');
});

test('paragraphsToHtml ↔ htmlToPlainText の往復', () => {
  const html = paragraphsToHtml(['一行目', '二行目']);
  assert.equal(html, '<p>一行目</p><p>二行目</p>');
  assert.equal(htmlToPlainText(html), '一行目\n二行目');
});

test('htmlToPlainText: ルビの読み(rt)は落として親文字を残す', () => {
  const html = '<p>本日は<ruby>晴天<rt>せいてん</rt></ruby>なり</p>';
  assert.equal(htmlToPlainText(html), '本日は晴天なり');
});

test('htmlToPlainText: 見出し・箇条書き・br を改行に', () => {
  const html = '<h3>見出し</h3><ul><li>項目1</li><li>項目2</li></ul><p>本文<br>続き</p>';
  assert.equal(htmlToPlainText(html), '見出し\n項目1\n項目2\n本文\n続き');
});

test('countCharsFromHtml: 空白・改行・ルビの読みを除いて数える', () => {
  // 「本日は晴天なり」= 7文字（ルビ「せいてん」は数えない）
  assert.equal(countCharsFromHtml('<p>本日は<ruby>晴天<rt>せいてん</rt></ruby>なり</p>'), 7);
  assert.equal(countCharsFromHtml('<p>あ い　う</p>'), 3);
  assert.equal(countCharsFromHtml('<strong>太字</strong>'), 2);
});
