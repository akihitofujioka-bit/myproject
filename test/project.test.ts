// P1 完了条件の検証: 空プロジェクトを「作成 → 直列化 → 復元」できること。
// Electron に依存しない純粋ロジック（src/shared/project.ts）を Node 標準テストで確認する。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createEmptyProject,
  serializeProject,
  deserializeProject,
  duplicateProject,
  countArticleChars,
  ProjectLoadError,
} from '../src/shared/project.ts';
import { PROJECT_SCHEMA_VERSION } from '../src/shared/types.ts';

test('createEmptyProject: 既定テンプレート(縦書き/A4)を持つ空プロジェクトを作る', () => {
  const p = createEmptyProject({ id: 'prj_test', templateId: 'tpl_test', now: '2026-06-30T00:00:00.000Z' });
  assert.equal(p.schemaVersion, PROJECT_SCHEMA_VERSION);
  assert.equal(p.id, 'prj_test');
  assert.equal(p.activeTemplateId, 'tpl_test');
  assert.equal(p.templates.length, 1);
  assert.equal(p.templates[0].writingMode, 'vertical');
  assert.equal(p.templates[0].pageSize, 'A4');
  assert.deepEqual(p.articles, []);
  assert.equal(p.createdAt, '2026-06-30T00:00:00.000Z');
});

test('serialize → deserialize の往復で同一になる（保存→再オープン）', () => {
  const p = createEmptyProject({ id: 'prj_rt', templateId: 'tpl_rt', now: '2026-06-30T00:00:00.000Z' });
  const restored = deserializeProject(serializeProject(p));
  assert.deepEqual(restored, p);
});

test('deserialize: 不正なJSONはProjectLoadError', () => {
  assert.throws(() => deserializeProject('{ not json'), ProjectLoadError);
});

test('deserialize: 非対応スキーマバージョンはProjectLoadError', () => {
  const bad = JSON.stringify({ ...createEmptyProject(), schemaVersion: 999 });
  assert.throws(() => deserializeProject(bad), ProjectLoadError);
});

test('deserialize: 必須配列が欠けるとProjectLoadError', () => {
  const obj = createEmptyProject() as Record<string, unknown>;
  delete obj.articles;
  assert.throws(() => deserializeProject(JSON.stringify(obj)), ProjectLoadError);
});

test('duplicateProject: 新IDを採番し中身を引き継ぐ（次号のひな型）', () => {
  const src = createEmptyProject({ id: 'prj_src', now: '2026-06-30T00:00:00.000Z' });
  src.meta.municipality = '○○市';
  const dup = duplicateProject(src, { id: 'prj_dup', now: '2026-07-01T00:00:00.000Z' });
  assert.equal(dup.id, 'prj_dup');
  assert.notEqual(dup.id, src.id);
  assert.equal(dup.meta.municipality, '○○市');
  assert.equal(dup.createdAt, '2026-07-01T00:00:00.000Z');
});

test('countArticleChars: 空白・改行を除いて数える', () => {
  assert.equal(countArticleChars({ body: ['あいう', ' え お\n'] }), 5);
});
